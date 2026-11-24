"""
Comparing two arms on the same emails, case by case, and the outcome of each email from a person's labels.

Outcome per email (the email outcome rule of 01 and Article #32): correct when every labelled fact of the
answerable questions is stated correctly, every question the documentation doesn't cover is said to be not
covered, and nothing false is stated. An arm that produced no reply has a wrong outcome.

Two label sources:
  original  01's data/hand_labels.json: one verdict per reply ('correct' or 'wrong')
  blind     data/blind_labels.json: per question, written without knowing the arm (schema in PROTOCOL.md)
"""
import math
from collections import defaultdict

CORRECT, WRONG = "correct", "wrong"
ANSWERABLE_VALUES = {"correct", "wrong", "omitted", "declined"}
UNCOVERED_VALUES = {"declined", "answered"}


# ------------------------------------------------------------------------------------------- blind labels


def blind_outcome(questions: list[dict], label: dict) -> dict:
    """
    The outcome and the two gates for one reply, from its per-question blind label.

    Raises ValueError if a question is missing, extra, or has a value its kind doesn't allow, so a label
    that doesn't follow the schema is an error, never a guess.
    """
    given = label.get("questions", {})
    expected = {q["id"]: q for q in questions}
    if set(given) != set(expected):
        raise ValueError(f"questions {sorted(given)} don't match the email's {sorted(expected)}")
    if not isinstance(label.get("false_statement"), bool):
        raise ValueError("false_statement must be true or false")
    for qid, value in given.items():
        allowed = ANSWERABLE_VALUES if expected[qid]["answerable"] else UNCOVERED_VALUES
        if value not in allowed:
            raise ValueError(f"{qid}: {value!r} is not one of {sorted(allowed)}")
    answerable = [qid for qid, q in expected.items() if q["answerable"]]
    uncovered = [qid for qid, q in expected.items() if not q["answerable"]]
    correct = (all(given[q] == "correct" for q in answerable) and all(given[q] == "declined" for q in uncovered)
               and not label["false_statement"])
    return {
        "outcome": CORRECT if correct else WRONG,
        "false_refusals": sum(given[q] == "declined" for q in answerable),
        "answerable": len(answerable),
        "false_answers": sum(given[q] == "answered" for q in uncovered),
        "uncovered": len(uncovered),
    }


# ------------------------------------------------------------------------------------------- paired comparison


def sign_test(fixed: int, broken: int) -> float:
    """
    Exact two-sided sign test on the emails whose outcome changed.

    Emails with the same outcome in both arms say nothing about the difference. If the change made no
    difference, each changed email would be a coin flip; this is the chance of a split at least this
    lopsided, in either direction.
    """
    n = fixed + broken
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(fixed, broken) + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired(baseline: dict[str, str], candidate: dict[str, str]) -> dict:
    """Outcomes per email for two arms over the same emails: what stayed, what was fixed, what broke."""
    if set(baseline) != set(candidate):
        raise ValueError("the two arms must cover the same emails")
    groups = defaultdict(list)
    for eid in sorted(baseline):
        before, after = baseline[eid], candidate[eid]
        if before == after:
            groups["both_" + before].append(eid)
        else:
            groups["fixed" if after == CORRECT else "broken"].append(eid)
    result = {name: groups[name] for name in ("both_correct", "both_wrong", "fixed", "broken")}
    result["baseline_correct"] = sum(v == CORRECT for v in baseline.values())
    result["candidate_correct"] = sum(v == CORRECT for v in candidate.values())
    result["emails"] = len(baseline)
    result["p_two_sided"] = sign_test(len(result["fixed"]), len(result["broken"]))
    return result


# ------------------------------------------------------------------------------------------- slices


def slices(questions: list[dict]) -> dict[str, str]:
    """The slices an email belongs to, from its labels alone (never from a reply)."""
    facts = [f["check"] for q in questions for f in q["facts"]]
    if not facts:
        mix = "no facts"
    elif all(c == "mechanical" for c in facts):
        mix = "all mechanical"
    elif all(c == "human" for c in facts):
        mix = "all human"
    else:
        mix = "mixed"
    return {
        "questions": str(len(questions)),
        "uncovered question": "yes" if any(not q["answerable"] for q in questions) else "no",
        "facts": mix,
    }


def by_slice(emails: list[str], slice_of: dict[str, dict[str, str]], baseline: dict[str, str],
             candidate: dict[str, str]) -> dict[str, dict[str, tuple[int, int, int]]]:
    """Per slice value: (emails, baseline correct, candidate correct)."""
    table: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for eid in emails:
        for name, value in slice_of[eid].items():
            cell = table[name][value]
            cell[0] += 1
            cell[1] += baseline[eid] == CORRECT
            cell[2] += candidate[eid] == CORRECT
    return {name: {value: tuple(cell) for value, cell in sorted(values.items())} for name, values in table.items()}
