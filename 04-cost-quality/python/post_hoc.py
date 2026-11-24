"""
Post-hoc records, written after the runs and outside the freeze (README deviation D2). Nothing here changes a
result in report.py; it keeps evidence that runs.json doesn't hold, so the README's and the article's descriptions
can be checked from committed files.

  python post_hoc.py      writes data/post_hoc.json (never overwrites it)

  cut_off_drafts   every draft call that stopped at its output limit (done_reason 'length') in b0, v2 and v3: the
                   raw output, its token count, and where it stopped (inside "reply" or after it, in "sources"); and
                   the highest number in the sources list when there is one. runs.json keeps reply None for these,
                   since the output isn't valid JSON, so the raw text exists only in the git-ignored runs/ folder.
  agreement        the blind labels against #33's blind labels, on the replies both labelled: outcomes, per-question
                   values, and false-statement flags, counted separately.
"""
import json
import re
import sys

from shared import BLIND, DATA, EVALUATION, RUNS, labels, rel, source_module

OUT = DATA / "post_hoc.json"


def cut_off_drafts() -> list[dict]:
    found = []
    for name in ("b0", "v2", "v3"):
        for path in sorted((RUNS / name / "state").glob("*.json")):
            draft = json.loads(path.read_text())["steps"].get("draft")
            if not draft:
                continue
            for attempt in draft["attempts"]:
                if attempt["done_reason"] != "length":
                    continue
                content = attempt["content"]
                in_sources = '"sources"' in content
                sources = re.findall(r"\d+", content.split('"sources"', 1)[1]) if in_sources else []
                found.append({"run": name, "email": path.stem, "model": attempt["model"],
                              "output_tokens": attempt["output_tokens"],
                              "stopped_in": "sources" if in_sources else "reply",
                              "highest_source": max(map(int, sources)) if sources else None,
                              "content": content})
    return found


def agreement() -> dict:
    compare = source_module("compare")
    qs = labels()
    ours = json.loads(BLIND.read_text())["labels"]
    theirs = json.loads((EVALUATION / "data" / "blind_labels.json").read_text())["labels"]
    shared = sorted(k for k in ours if k in theirs)
    outcome = question = flags = questions = 0
    for key in shared:
        a, b = ours[key], theirs[key]
        q = qs[a["email"]]["questions"]
        outcome += compare.blind_outcome(q, a)["outcome"] == compare.blind_outcome(q, b)["outcome"]
        for qid in a["questions"]:
            questions += 1
            question += a["questions"][qid] == b["questions"][qid]
        flags += a["false_statement"] == b["false_statement"]
    return {"replies": len(shared), "same_outcome": outcome, "question_values": questions,
            "same_question_values": question, "same_false_statement_flags": flags}


def main() -> None:
    if OUT.exists():
        sys.exit(f"{rel(OUT)} already exists and is never overwritten")
    document = {"_comment": __doc__.strip().splitlines()[0], "cut_off_drafts": cut_off_drafts(),
                "agreement_with_33": agreement()}
    OUT.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n")
    for d in document["cut_off_drafts"]:
        print(f"{d['run']:3} {d['email']} {d['model']:12} {d['output_tokens']:>4} stopped in {d['stopped_in']:7} "
              f"highest source {d['highest_source']}")
    print(json.dumps(document["agreement_with_33"]))


if __name__ == "__main__":
    main()
