"""
Human verification of the blind labels. The blind labeller is a model, not ground truth: a person reviews every
label, settles each flagged case, and only then do the labels count as verified.

  python verify.py sheet                      worksheet/verify.md (to read) and worksheet/verify.csv (to fill in)
  python verify.py import --verifier "..."    worksheet/verify.csv -> data/final_labels.json

verify.csv has one row per question of each reply, with the blind value in 'blind_value' and the same value in
'final_value', plus one 'reviewed' row per reply. The verifier changes 'final_value' where they disagree, and
writes 'yes' in the 'reviewed' row of every reply they have read. The import refuses unless every reply is
reviewed, records every change from the blind label, and never overwrites data/final_labels.json.

verify.md lists the replies that most need a person first. A reply is flagged when:
  - 02's blind labeller (#33) labelled the same reply text and its outcome differs;
  - 01's draft check or 02's fact check disagrees with the label (a check passes a reply labelled wrong, or
    the fact check fails a reply labelled correct);
  - the labeller's note says it was unsure;
  - the email's labelled outcome differs between versions (these replies decide the fixed and broken lists).
It doesn't say which version wrote a reply.
"""
import argparse
import csv
import io
import json
import re
import sys

import analysis
from labels import collect
from shared import BLIND, EVALUATION, EXPORT, FINAL, WORKSHEET, labels, rel, source_module

UNSURE = re.compile(r"\b(unsure|unclear|uncertain|borderline|arguabl\w*|ambiguous|debatable|could be read)\b|\?", re.I)


def flags(items: dict, blind: dict, previous: dict) -> dict[str, list[str]]:
    runs = json.loads(EXPORT.read_text())["runs"]
    qs = labels()
    compare = source_module("compare")
    result = {key: [] for key in items}
    outcome = {k: compare.blind_outcome(qs[items[k]["email"]]["questions"], blind[k])["outcome"] for k in items}
    for key, item in items.items():
        eid = item["email"]
        if key in previous:
            before = compare.blind_outcome(qs[eid]["questions"], previous[key])["outcome"]
            if before != outcome[key]:
                result[key].append(f"#33's blind labeller judged this same text {before}")
        check_passed = any(runs[s]["emails"][eid]["draft_check"] == [] for s in item["sources"])
        if check_passed and outcome[key] == "wrong":
            result[key].append("01's draft check passed it, labelled wrong")
        verdict = analysis.fact_check(eid, item["reply"])
        if verdict == "pass" and outcome[key] == "wrong":
            result[key].append("the fact check passed it, labelled wrong")
        if verdict == "fail" and outcome[key] == "correct":
            result[key].append("the fact check failed it, labelled correct")
        if UNSURE.search(blind[key].get("note", "")):
            result[key].append("the labeller's note sounds unsure")
    by_email: dict[str, set] = {}
    for name in ("b0", "v1", "v2", "v3"):
        for eid, record in runs[name]["emails"].items():
            by_email.setdefault(eid, set()).add(outcome.get(record["key"], "no reply") if record["key"] else "no reply")
    for key, item in items.items():
        if len(by_email[item["email"]]) > 1:
            result[key].append("this email's outcome differs between versions")
    return result


def sheet() -> None:
    for name in ("verify.md", "verify.csv"):
        if (WORKSHEET / name).exists():
            sys.exit(f"{rel(WORKSHEET / name)} already exists and is never overwritten")
    blind = json.loads(BLIND.read_text())["labels"]
    previous_path = EVALUATION / "data" / "blind_labels.json"
    previous = json.loads(previous_path.read_text())["labels"] if previous_path.exists() else {}
    items = collect()
    found = flags(items, blind, previous)
    qs = labels()
    order = sorted(items, key=lambda k: (not found[k], items[k]["email"], k))
    md = [f"# Verification sheet\n\n{len(items)} replies; {sum(bool(found[k]) for k in items)} flagged, listed first.\n",
          "For each reply: read the email's questions and facts in worksheet/worksheet.md, read the reply, check the "
          "blind label below, and in worksheet/verify.csv change `final_value` where you disagree and write `yes` in "
          "the reply's `reviewed` row.\n"]
    rows = io.StringIO()
    writer = csv.writer(rows)
    writer.writerow(["reply_id", "email", "item", "blind_value", "final_value", "note"])
    for key in order:
        rid, eid, label = key[:8], items[key]["email"], blind[key]
        md.append(f"\n---\n\n## Reply {rid} ({eid})" + (" FLAGGED" if found[key] else ""))
        for f in found[key]:
            md.append(f"- {f}")
        quoted = "\n".join("> " + line if line else ">" for line in items[key]["reply"].split("\n"))
        md.append(f"\n{quoted}\n")
        for q in qs[eid]["questions"]:
            md.append(f"- `{q['id']}` {q['asks']}: **{label['questions'][q['id']]}**")
            writer.writerow([rid, eid, q["id"], label["questions"][q["id"]], label["questions"][q["id"]], ""])
        flag = "yes" if label["false_statement"] else "no"
        md.append(f"- false statement: **{flag}**")
        if label.get("note"):
            md.append(f"- labeller's note: {label['note']}")
        writer.writerow([rid, eid, "false_statement", flag, flag, ""])
        writer.writerow([rid, eid, "reviewed", "", "", ""])
    WORKSHEET.mkdir(exist_ok=True)
    (WORKSHEET / "verify.md").write_text("\n".join(md) + "\n")
    (WORKSHEET / "verify.csv").write_text(rows.getvalue())
    print(f"wrote {rel(WORKSHEET / 'verify.md')} and {rel(WORKSHEET / 'verify.csv')}: {len(items)} replies, "
          f"{sum(bool(found[k]) for k in items)} flagged")


def import_verified(verifier: str) -> None:
    if FINAL.exists():
        sys.exit(f"{rel(FINAL)} already exists and is never overwritten")
    blind_doc = json.loads(BLIND.read_text())
    blind = blind_doc["labels"]
    items = collect()
    by_id = {k[:8]: k for k in items}
    qs = labels()
    compare = source_module("compare")
    given: dict[str, dict[str, tuple[str, str]]] = {}
    problems = []
    for n, row in enumerate(csv.DictReader(io.StringIO((WORKSHEET / "verify.csv").read_text())), 2):
        rid = row["reply_id"].strip()
        if rid not in by_id:
            problems.append(f"line {n}: unknown reply id {rid!r}")
            continue
        given.setdefault(rid, {})[row["item"].strip()] = (row["final_value"].strip().lower(), row["note"].strip())
    final, changes = {}, []
    for rid, key in sorted(by_id.items()):
        eid, rows = items[key]["email"], given.get(rid, {})
        if rows.get("reviewed", ("", ""))[0] != "yes":
            problems.append(f"{rid} ({eid}): not marked reviewed")
            continue
        label = {"email": eid, "questions": {q["id"]: rows.get(q["id"], ("", ""))[0] for q in qs[eid]["questions"]},
                 "false_statement": rows.get("false_statement", ("", ""))[0] == "yes",
                 "note": blind[key].get("note", "")}
        if rows.get("false_statement", ("", ""))[0] not in ("yes", "no"):
            problems.append(f"{rid}: false_statement must be yes or no")
            continue
        try:
            compare.blind_outcome(qs[eid]["questions"], label)
        except ValueError as error:
            problems.append(f"{rid}: {error}")
            continue
        notes = " | ".join(f"{item}: {note}" for item, (_, note) in rows.items() if note)
        for item, before in [*blind[key]["questions"].items(), ("false_statement", blind[key]["false_statement"])]:
            after = label["questions"].get(item) if item != "false_statement" else label["false_statement"]
            if after != before:
                changes.append({"reply": key, "email": eid, "item": item, "blind": before, "final": after,
                                "note": notes})
        if notes:
            label["verifier_note"] = notes
        final[key] = label
    if problems:
        sys.exit("NOT WRITTEN:\n  " + "\n  ".join(problems))
    FINAL.write_text(json.dumps({"labeller": blind_doc["labeller"], "verifier": verifier, "changes": changes,
                                 "labels": final}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {rel(FINAL)}: {len(final)} replies, {len(changes)} values changed from the blind labels")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sheet")
    imp = sub.add_parser("import")
    imp.add_argument("--verifier", required=True)
    args = parser.parse_args()
    if args.command == "sheet":
        sheet()
    else:
        import_verified(args.verifier)


if __name__ == "__main__":
    main()
