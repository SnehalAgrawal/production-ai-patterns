"""Answer the lender's nine questions about one decision from the records alone.

Sources: the audit log, the content store (with each subject's key), the release manifests
written at activation, the policy store, the evaluation records, the ledger, the purge log.
Content is shown only if its keyed digest matches the one in the audit log.

Statuses: answered | content erased | content deleted by retention | not answerable.
"""

import json
from pathlib import Path

from common import canon, keyed, load, manifest_sha, sha
from evidence import AuditLog, ContentStore, chain_start, check_anchor, read_jsonl, verify_chain

ANSWERED, ERASED, RETAINED, NOT = "answered", "content erased", "content deleted by retention", "not answerable"


def _content(root: Path, store: ContentStore, events: list[dict], subject: str, ref: str, digest: str,
             created_at: str | None = None) -> dict:
    item = store.get(ref)
    if item is not None:
        key = store.key(subject)
        if key is None:
            return {"status": NOT, "why": "content present but its key is gone; can't verify"}
        if keyed(key, item["text"].encode("utf-8")) != digest:
            return {"status": NOT, "why": "content doesn't match the digest in the audit log"}
        return {"status": ANSWERED, "value": item["text"]}
    erased = [e for e in events if e["kind"] == "erased" and e["data"]["subject_id"] == subject]
    if erased:
        e = erased[-1]
        return {"status": ERASED, "when": e["at"], "request": e["data"]["request_id"]}
    # Blame retention only if a purge record covers when this content was created (deviation D3).
    purges = [p for p in read_jsonl(root / "purge_log.jsonl") if p["store"] == "content"
              and created_at is not None and p["from"] <= created_at <= p["to"]]
    if purges:
        return {"status": RETAINED, "when": purges[-1]["at"], "rule": purges[-1]["rule"]}
    return {"status": NOT, "why": "content missing, and no erasure or retention record explains it"}


def reconstruct(root: Path, decision_id: str) -> dict:
    root = Path(root)
    events = AuditLog(root / "audit.jsonl").events()
    evs = [e for e in events if e["decision_id"] == decision_id]
    questions = [f"Q{i}" for i in range(1, 10)]
    if not evs:
        purges = [p for p in read_jsonl(root / "purge_log.jsonl") if p["store"] == "audit"]
        why = "no events for this decision"
        if purges:
            p = purges[-1]
            why += (f"; purge log: rule {p['rule']} deleted {p['count']} audit events dated {p['from']} to {p['to']}"
                    f" on {p['at']}")
        return {q: {"status": NOT, "why": why} for q in questions}

    store = ContentStore(root)
    first = {}
    for e in evs:
        first.setdefault(e["kind"], e)
    received, context = first.get("received"), first.get("context")
    subject = received["data"]["subject_id"] if received else None
    out = {}

    # Q1: what the customer asked.
    if received:
        letter = _content(root, store, events, subject, received["data"]["letter_ref"], received["data"]["letter_hmac"],
                          received["at"])
        income = _content(root, store, events, subject, received["data"]["income_ref"], received["data"]["income_hmac"],
                          received["at"])
        out["Q1"] = {"status": letter["status"], "letter": letter, "income_statement": income, "received_at": received["at"]}
    else:
        out["Q1"] = {"status": NOT, "why": "no received event"}

    # Q2: what the system used: the policy at its version, and the account as of the decision.
    if context:
        p = context["data"]["policy"]
        policies = load("policies.json")["versions"]
        doc = policies.get(p["version"])
        policy = ({"status": ANSWERED, "value": f"{p['doc_id']} {p['version']}"} if doc and sha(canon(doc)) == p["sha256"]
                  else {"status": NOT, "why": "policy version missing or changed"})
        snap = context["data"]["account_snapshot"]
        snapshot = _content(root, store, events, subject, snap["ref"], snap["hmac"], context["at"])
        out["Q2"] = {"policy": policy, "account_snapshot": snapshot}
    else:
        out["Q2"] = {"policy": {"status": NOT}, "account_snapshot": {"status": NOT}}

    # Q3: release, model identifiers, instructions.
    calls = [e for e in evs if e["kind"] == "model_call"]
    if calls:
        release = calls[0]["data"]["release"]
        path = root / "releases" / f"{release}.json"
        activated = [e for e in events if e["kind"] == "release_activated" and e["data"]["release"] == release]
        m = json.loads(path.read_text()) if path.exists() else None
        ok = m is not None and activated and manifest_sha(m) == activated[-1]["data"]["manifest_sha256"]
        out["Q3"] = {"status": ANSWERED if ok else NOT, "release": release,
                     "manifest_sha256": activated[-1]["data"]["manifest_sha256"] if activated else None,
                     "calls": [{"step": c["data"]["step"], "prompt_template": c["data"]["prompt_template"],
                                "model_requested": c["data"]["model_requested"],
                                "model_returned": c["data"]["model_returned"],
                                "version_metadata": c["data"]["version_metadata"] or "no version metadata returned"}
                               for c in calls]}
    else:
        out["Q3"] = {"status": NOT, "why": "no model calls recorded"}

    # Q4, Q5: the recommendation and the checks (structured, in the log itself).
    rec = first.get("recommended")
    out["Q4"] = {"status": ANSWERED, "action": rec["data"]["action"]} if rec else {"status": NOT}
    chk = first.get("checked")
    out["Q5"] = {"status": ANSWERED, "checks": chk["data"]["checks"]} if chk else {"status": NOT}

    # Q6: the decision.
    decided = [e for e in evs if e["kind"] == "decided"]
    if decided:
        d = decided[-1]
        out["Q6"] = {"status": ANSWERED, "at": d["at"], **{k: d["data"][k] for k in
                     ("reviewer", "role", "decision", "reason_code", "approved_action", "release", "policy_version",
                      "evidence_view")}}
    else:
        out["Q6"] = {"status": NOT, "why": "no decision recorded"}

    # Q7: what was executed, against the approval, the recommendation and the ledger.
    executed = [e for e in evs if e["kind"] == "executed"]
    no_action = [e for e in evs if e["kind"] == "no_action"]
    if executed:
        ex = executed[-1]["data"]
        ledger = {r["ledger_id"]: r for r in read_jsonl(root / "ledger.jsonl")}
        approved_sha = decided[-1]["data"]["approved_action_sha256"] if decided else None
        out["Q7"] = {"status": ANSWERED, "executed": ex["action"], "ledger_entry": ex["ledger_id"] in ledger,
                     "matches_approval": ex["action_sha256"] == approved_sha,
                     "matches_recommendation": rec is not None and ex["action_sha256"] == rec["data"]["action_sha256"],
                     "modification_recorded": bool(decided) and decided[-1]["data"]["decision"] == "modify"}
    elif no_action:
        out["Q7"] = {"status": ANSWERED, "executed": None, "reason": no_action[-1]["data"]["reason"]}
    else:
        out["Q7"] = {"status": NOT, "why": "neither an execution nor a no-action record"}

    # Q8: integrity of the whole log, and agreement with the external anchor.
    broken = verify_chain(events, chain_start(root))
    anchor = check_anchor(root)
    out["Q8"] = {"status": ANSWERED, "chain_verifies": broken is None, "broken_at": broken,
                 "anchor": "agrees" if anchor is None else anchor}

    # Q9: was the release evaluated before use?
    if calls:
        release = calls[0]["data"]["release"]
        activated = [e for e in events if e["kind"] == "release_activated" and e["data"]["release"] == release]
        evaluation = next((e for e in load("evaluations.json")["evaluations"] if e["release"] == release), None)
        if activated and evaluation:
            a = activated[-1]
            out["Q9"] = {"status": ANSWERED, "evaluation_id": evaluation["evaluation_id"],
                         "evaluated_at": evaluation["evaluated_at"], "activated_at": a["at"],
                         "same_manifest": evaluation["manifest_sha256"] == a["data"]["manifest_sha256"],
                         "evaluated_before_use": evaluation["evaluated_at"] < a["at"],
                         "returned_model_matches": all(c["data"]["model_returned"] == evaluation["returned_model_observed"]
                                                       for c in calls)}
        else:
            out["Q9"] = {"status": NOT, "why": "no activation or evaluation record"}
    else:
        out["Q9"] = {"status": NOT}
    return out
