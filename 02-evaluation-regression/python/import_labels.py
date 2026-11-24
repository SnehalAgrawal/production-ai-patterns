"""
Turns the filled-in worksheet/labels.csv into data/blind_labels.json, keyed by each reply's label key.

  python import_labels.py --labeller "who labelled"

Every reply on the worksheet must have every row filled with an allowed value; anything else is an error, listed,
and nothing is written. Each label is also checked with the same rules the reports use (compare.blind_outcome).
It never overwrites data/blind_labels.json.
"""
import argparse
import csv
import io
import json
import sys

import compare
from common import DATA, SOURCE_DATA, rel
from worksheet import OUT, collect, reply_id

BLIND = DATA / "blind_labels.json"


def parse(csv_text: str, items: dict[str, dict], labels: dict) -> tuple[dict, list[str]]:
    """(blind labels keyed by label key, problems)."""
    by_id = {reply_id(k): k for k in items}
    rows: dict[str, dict[str, tuple[str, str]]] = {}
    problems = []
    for n, row in enumerate(csv.DictReader(io.StringIO(csv_text)), 2):
        rid, item, value = row["reply_id"].strip(), row["item"].strip(), row["value"].strip().lower()
        if rid not in by_id:
            problems.append(f"line {n}: unknown reply id {rid!r}")
            continue
        if item in rows.setdefault(rid, {}):
            problems.append(f"line {n}: {rid} {item} appears twice")
        rows[rid][item] = (value, row.get("note", "").strip())
    result = {}
    for rid, key in sorted(by_id.items()):
        eid = items[key]["email"]
        questions = labels[eid]["questions"]
        given = rows.get(rid, {})
        expected = [q["id"] for q in questions] + ["false_statement"]
        missing = [i for i in expected if not given.get(i, ("", ""))[0]]
        extra = [i for i in given if i not in expected]
        if missing or extra:
            problems.append(f"{rid} ({eid}): missing {missing or 'nothing'}, unexpected {extra or 'nothing'}")
            continue
        flag = given["false_statement"][0]
        if flag not in ("yes", "no"):
            problems.append(f"{rid}: false_statement {flag!r} is not yes or no")
            continue
        label = {"email": eid, "questions": {q["id"]: given[q["id"]][0] for q in questions},
                 "false_statement": flag == "yes",
                 "note": " | ".join(f"{i}: {note}" for i, (_, note) in given.items() if note)}
        try:
            compare.blind_outcome(questions, label)
        except ValueError as error:
            problems.append(f"{rid}: {error}")
            continue
        result[key] = label
    return result, problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labeller", required=True)
    args = parser.parse_args()
    if BLIND.exists():
        sys.exit(f"{rel(BLIND)} already exists and is never overwritten")
    items = collect()
    labels = json.loads((SOURCE_DATA / "labels.json").read_text())["emails"]
    result, problems = parse((OUT / "labels.csv").read_text(), items, labels)
    if problems:
        sys.exit("NOT WRITTEN:\n  " + "\n  ".join(problems))
    BLIND.write_text(json.dumps({"labeller": args.labeller, "labels": result}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {rel(BLIND)}: {len(result)} replies")


if __name__ == "__main__":
    main()
