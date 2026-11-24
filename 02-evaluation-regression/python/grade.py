"""
The deterministic grader, and how its verdicts compare with a person's labels.

The grader is 01's mechanical fact check (score.py, rules in 01's data/README.md), applied per email:

  pass            every mechanical fact of the email's answerable questions is present in the reply
  fail            at least one is missing
  not gradeable   the email has no mechanical fact, so the grader has nothing to look for
  no reply        the arm produced no reply (01's e14 in the chain arm)

It only looks for expected wordings. Human facts and questions the documentation doesn't cover are listed
per email as not checked, and never count as passes. The fact list itself (01's labels.json) is reused as
committed before any reply existed; this demo does not test whether that list is complete or correct.
"""
from collections import Counter

PASS, FAIL, NOT_GRADEABLE, NO_REPLY = "pass", "fail", "not gradeable", "no reply"


def grade(scorer, eid: str, reply: str | None) -> dict:
    questions = scorer.questions(eid)
    record = {
        "email": eid,
        "not_checked": {
            "human_facts": [f["id"] for q in questions for f in q["facts"] if f["check"] == "human"],
            "uncovered_questions": [q["id"] for q in questions if not q["answerable"]],
        },
    }
    if reply is None:
        return {**record, "verdict": NO_REPLY, "checked": [], "missing": []}
    found = scorer.mechanical(eid, reply)
    missing = [fid for fid, present in found.items() if not present]
    if not found:
        verdict = NOT_GRADEABLE
    else:
        verdict = FAIL if missing else PASS
    return {**record, "verdict": verdict, "checked": list(found), "missing": missing}


def calibration(rows: list[tuple[str, str | None]]) -> dict:
    """
    Grader verdicts against a person's labels, one (verdict, label) pair per reply.

    The positive class is a reply the person labelled wrong, the thing the grader exists to catch:
      caught        fail, labelled wrong
      missed        pass, labelled wrong      (a missed error)
      false_alarms  fail, labelled correct    (a correct reply flagged)
      passed        pass, labelled correct
    Replies with no reply, or that the grader can't grade, are counted apart and are outside both rates.
    """
    counts = Counter()
    for verdict, label in rows:
        if verdict in (NO_REPLY, NOT_GRADEABLE):
            counts[verdict] += 1
        elif label is None:
            counts["unlabelled"] += 1
        else:
            counts[(verdict, label)] += 1
    return {
        "caught": counts[(FAIL, "wrong")],
        "missed": counts[(PASS, "wrong")],
        "false_alarms": counts[(FAIL, "correct")],
        "passed": counts[(PASS, "correct")],
        "not_gradeable": counts[NOT_GRADEABLE],
        "no_reply": counts[NO_REPLY],
        "unlabelled": counts["unlabelled"],
    }
