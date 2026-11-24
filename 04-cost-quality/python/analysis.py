"""
The results, from data/runs.json, the labels, and data/prices.json. No model calls.

  v4             assembled from b0 and v3: v3's reply when 01's draft check passes it, otherwise b0's reply, which
                 counts as an escalation (v3's calls plus b0's draft call). Valid only because both runs drafted
                 from the same extraction and chunks: checked by hash for every escalated email, or it raises.
  outcome        per reply, from its per-question label with 02's rule (compare.blind_outcome): correct, or wrong;
                 an email with no reply is 'no reply' and counts as a failure
  spend          hypothetical: each call's local token counts at the rates of the hosted model that stands in for
                 its local model (prices.json), plus query embeddings; per scenario
  per success    spend / labelled-correct emails; with a downstream cost E per failed email, (spend + E x failures) /
                 correct; and the break-even E against b0 (cost.break_even)
  expectations   E1-E8 of PROTOCOL.md, evaluated mechanically where they can be
"""
from collections import Counter

import cost
from shared import labels as load_labels
from shared import source_module

LABELLED = ("b0", "v1", "v2", "v3")
VARIANTS = ("b0", "v1", "v2", "v3", "v4")
NO_REPLY = "no reply"


# ------------------------------------------------------------------------------------------- v4


def compose_v4(b0: dict[str, dict], v3: dict[str, dict]) -> dict[str, dict]:
    """The cascade: v3 first, escalated to b0's draft when 01's draft check doesn't pass v3's draft."""
    if set(b0) != set(v3):
        raise ValueError("b0 and v3 cover different emails")
    result = {}
    for eid in sorted(v3):
        small, large = v3[eid], b0[eid]
        passed = small["draft_check"] == []
        if passed:
            result[eid] = {**small, "escalated": False, "from": "v3"}
            continue
        if small["draft_inputs_sha256"] is None and large["draft_inputs_sha256"] is None:
            # neither run reached drafting (the extraction was unusable in both): nothing to escalate to
            result[eid] = {**small, "escalated": False, "from": "v3"}
            continue
        if small["draft_inputs_sha256"] != large["draft_inputs_sha256"]:
            raise ValueError(f"{eid}: b0 and v3 drafted from different inputs; v4 can't reuse b0's draft")
        large_draft = [c for c in large["calls"] if c["step"] == "draft"]
        result[eid] = {**large, "calls": small["calls"] + large_draft, "escalated": True, "from": "b0",
                       "v3_check": small["draft_check"]}
    return result


# ------------------------------------------------------------------------------------------- outcomes


def outcome(eid: str, record: dict, label_for: dict, questions: dict) -> dict:
    compare = source_module("compare")
    if record["reply"] is None:
        return {"outcome": NO_REPLY, "false_answers": 0, "false_statement": False, "labelled": True}
    label = label_for.get(record["key"])
    if label is None:
        return {"outcome": None, "false_answers": None, "false_statement": None, "labelled": False}
    result = compare.blind_outcome(questions[eid]["questions"], label)
    return {"outcome": result["outcome"], "false_answers": result["false_answers"],
            "false_statement": label["false_statement"], "labelled": True}


def fact_check(eid: str, reply: str | None) -> str:
    """02's grader: 01's mechanical fact check (pass, fail, not gradeable, no reply)."""
    return source_module("grade").grade(source_module("score").Scorer(), eid, reply)["verdict"]


# ------------------------------------------------------------------------------------------- spend


def spend(records: dict[str, dict], prices: dict, scenario: str) -> dict:
    s = prices["scenarios"][scenario]
    inference = sum(cost.call_cost(c, s) for r in records.values() for c in r["calls"])
    tokens = sum(r["query_embedding_tokens"] for r in records.values())
    other = cost.embedding_cost(tokens, prices["embedding"])
    return cost.breakdown(inference, other)


def summarize(records: dict[str, dict], outcomes: dict[str, dict], prices: dict) -> dict:
    calls = [c for r in records.values() for c in r["calls"]]
    by = Counter()
    for c in calls:
        by[f"{c['step']}_prompt"] += c["prompt_tokens"]
        by[f"{c['step']}_output"] += c["output_tokens"]
    labelled = all(o["labelled"] for o in outcomes.values())
    correct = sum(o["outcome"] == "correct" for o in outcomes.values()) if labelled else None
    failures = len(records) - correct if labelled else None
    result = {
        "emails": len(records),
        "calls": len(calls),
        "calls_by_model": dict(Counter(c["model"] for c in calls)),
        "tokens": dict(by),
        "truncated": sum(c["done_reason"] == "length" for c in calls),
        "no_reply": sum(r["reply"] is None for r in records.values()),
        "draft_check_pass": sum(r["draft_check"] == [] for r in records.values()),
        "fact_check": dict(Counter(fact_check(eid, r["reply"]) for eid, r in records.items())),
        "labelled": labelled,
        "correct": correct,
        "failures": failures,
        "false_answers": sum(o["false_answers"] for o in outcomes.values()) if labelled else None,
        "false_statements": sum(bool(o["false_statement"]) for o in outcomes.values()) if labelled else None,
        "escalated": sum(r.get("escalated", False) for r in records.values()),
        "spend": {},
    }
    for scenario in prices["scenarios"]:
        costs = spend(records, prices, scenario)
        total = cost.subtotal(costs, ["inference", "other_metered"])
        result["spend"][scenario] = {"inference": costs["inference"]["usd"],
                                     "other_metered": costs["other_metered"]["usd"], "total": total,
                                     "per_email": total / len(records),
                                     "per_success": cost.cost_per_success(total, correct, failures) if labelled else None}
    return result


# ------------------------------------------------------------------------------------------- comparisons


def per_email(outcomes: dict[str, dict[str, dict]]) -> dict[str, dict[str, str]]:
    """variant -> email -> outcome, with 'no reply' kept (it is a failure, and a different one)."""
    return {v: {eid: o["outcome"] for eid, o in by_email.items()} for v, by_email in outcomes.items()}


def paired(base: dict[str, str], candidate: dict[str, str]) -> dict:
    """02's paired comparison, with 'no reply' counted as wrong. The sign test is not reported (20 emails)."""
    as_binary = {eid: ("correct" if o == "correct" else "wrong") for eid, o in base.items()}
    cand = {eid: ("correct" if o == "correct" else "wrong") for eid, o in candidate.items()}
    result = source_module("compare").paired(as_binary, cand)
    result.pop("p_two_sided", None)
    return result


def decision(base: dict, candidate: dict, pairs: dict) -> dict:
    """PROTOCOL.md's adoption rule: no broken email, no more false answers, no more emails without a reply."""
    reasons = []
    if pairs["broken"]:
        reasons.append(f"broke {len(pairs['broken'])} email(s) b0 answered correctly: {', '.join(pairs['broken'])}")
    if candidate["false_answers"] > base["false_answers"]:
        reasons.append(f"false answers {base['false_answers']} -> {candidate['false_answers']}")
    if candidate["no_reply"] > base["no_reply"]:
        reasons.append(f"emails without a reply {base['no_reply']} -> {candidate['no_reply']}")
    return {"adopt": not reasons, "reasons": reasons}


def text_comparison(before: dict[str, dict], after: dict[str, dict]) -> dict:
    if set(before) != set(after):
        raise ValueError("the two runs cover different emails")
    same = {k: sum(before[e][k] == after[e][k] for e in before) for k in ("extraction", "chunks", "reply")}
    return {"emails": len(before), **{f"same_{k}": v for k, v in same.items()},
            "different_reply": [e for e in sorted(before) if before[e]["reply"] != after[e]["reply"]]}


# ------------------------------------------------------------------------------------------- expectations


def draft_call(record: dict) -> dict | None:
    calls = [c for c in record["calls"] if c["step"] == "draft"]
    return calls[0] if calls else None


def expectations(runs: dict[str, dict], cap: int, v3a: dict[str, dict] | None) -> dict[str, dict]:
    """E1-E6 of PROTOCOL.md (mechanics). E7 and E8 need labels and are evaluated in report.py."""
    b0, v1, v2, v3, v3r = (runs[n] for n in ("b0", "v1", "v2", "v3", "v3r"))
    result = {}
    if v3a is None:
        result["E1"] = {"held": None, "detail": "02's v3a is not available"}
    else:
        c = text_comparison(v3a, b0)
        held = c["same_extraction"] == c["same_chunks"] == c["same_reply"] == c["emails"]
        result["E1"] = {"held": held, "detail": c}

    same_extraction = sum(b0[e]["extraction"] == v1[e]["extraction"] for e in b0)
    fewer = [e for e in b0 if draft_call(b0[e]) and draft_call(v1[e])
             and draft_call(v1[e])["prompt_tokens"] > draft_call(b0[e])["prompt_tokens"]]
    total_b0 = sum(draft_call(r)["prompt_tokens"] for r in b0.values() if draft_call(r))
    total_v1 = sum(draft_call(r)["prompt_tokens"] for r in v1.values() if draft_call(r))
    result["E2"] = {"held": same_extraction == len(b0) and not fewer and total_v1 < total_b0,
                    "detail": {"same_extraction": same_extraction, "emails_with_more_draft_input": fewer,
                               "draft_prompt_tokens": {"b0": total_b0, "v1": total_v1}}}

    problems, expected_output, actual_output = [], 0, 0
    for e in b0:
        d0, d2 = draft_call(b0[e]), draft_call(v2[e])
        if d0 is None or d2 is None:
            if (d0 is None) != (d2 is None):
                problems.append(f"{e}: drafted in only one run")
            continue
        expected_output += min(d0["output_tokens"], cap)
        actual_output += d2["output_tokens"]
        if d0["output_tokens"] <= cap and v2[e]["reply"] != b0[e]["reply"]:
            problems.append(f"{e}: under the cap but the reply changed")
        if d0["output_tokens"] > cap and (d2["done_reason"] != "length" or v2[e]["reply"] is not None):
            problems.append(f"{e}: over the cap but not cut off without a reply")
    result["E3"] = {"held": not problems and expected_output == actual_output,
                    "detail": {"cap": cap, "problems": problems, "draft_output_tokens": {
                        "expected": expected_output, "actual": actual_output},
                        "cut_off": [e for e in b0 if draft_call(b0[e]) and draft_call(b0[e])["output_tokens"] > cap]}}

    same_inputs = sum(b0[e]["draft_inputs_sha256"] == v3[e]["draft_inputs_sha256"] for e in b0)
    result["E4"] = {"held": same_inputs == len(b0), "detail": {"same_draft_inputs": same_inputs}}

    c = text_comparison(v3, v3r)
    result["E5"] = {"held": c["same_reply"] == c["emails"], "detail": c}

    differ = [e for e in b0 if draft_call(b0[e]) and draft_call(v3[e])
              and draft_call(b0[e])["prompt_tokens"] != draft_call(v3[e])["prompt_tokens"]]
    result["E6"] = {"held": not differ, "detail": {"emails_with_different_draft_prompt_tokens": differ}}
    return result


def questions() -> dict:
    return load_labels()
