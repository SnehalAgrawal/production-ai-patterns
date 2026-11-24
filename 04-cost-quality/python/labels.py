"""
The blind labelling worksheet, and its import. The rubric, the worksheet format and the validation are 02's
(worksheet.render, import_labels.parse), imported unchanged, so a label here means what it means in #33.

  python labels.py worksheet                     worksheet/worksheet.md and worksheet/labels.csv
  python labels.py import --labeller "..."       the filled-in labels.csv -> data/blind_labels.json

The worksheet holds every distinct reply of the labelled runs (b0, v1, v2, v3; v4 reuses their replies),
deduplicated by 01's label key, under neutral ids, with emails and replies shuffled (seed 36). It never says which
run wrote a reply, what the checks said, or how any earlier labeller judged it. Neither file is ever overwritten.
"""
import argparse
import json
import sys

from shared import BLIND, EXPORT, SOURCE_DATA, WORKSHEET, labels, rel, source_module

LABELLED_RUNS = ("b0", "v1", "v2", "v3")
SEED = 36


def collect() -> dict[str, dict]:
    """label key -> {email, reply, sources}. 'sources' stays in this process; it is never written to the worksheet."""
    runs = json.loads(EXPORT.read_text())["runs"]
    items: dict[str, dict] = {}
    for name in LABELLED_RUNS:
        for eid, record in runs[name]["emails"].items():
            if record["reply"] is None:
                continue
            item = items.setdefault(record["key"], {"email": eid, "reply": record["reply"], "sources": []})
            if item["reply"] != record["reply"] or item["email"] != eid:
                raise ValueError(f"key {record['key']} maps to two different replies")
            item["sources"].append(name)
    return items


def worksheet() -> None:
    for name in ("worksheet.md", "labels.csv"):
        if (WORKSHEET / name).exists():
            sys.exit(f"{rel(WORKSHEET / name)} already exists and is never overwritten (it may hold labels)")
    render_module = source_module("worksheet")
    items = collect()
    texts = {eid: (SOURCE_DATA / "emails" / f"{eid}.txt").read_text() for eid in {i["email"] for i in items.values()}}
    original = render_module.ordered
    render_module.ordered = lambda found, seed=SEED: original(found, seed)  # this demo's own shuffle
    try:
        md, rows = render_module.render(items, labels(), texts)
    finally:
        render_module.ordered = original
    WORKSHEET.mkdir(exist_ok=True)
    (WORKSHEET / "worksheet.md").write_text(md)
    (WORKSHEET / "labels.csv").write_text(rows)
    print(f"wrote {rel(WORKSHEET / 'worksheet.md')} and {rel(WORKSHEET / 'labels.csv')}: {len(items)} replies")


def import_labels(labeller: str) -> None:
    if BLIND.exists():
        sys.exit(f"{rel(BLIND)} already exists and is never overwritten")
    parse = source_module("import_labels").parse
    result, problems = parse((WORKSHEET / "labels.csv").read_text(), collect(), labels())
    if problems:
        sys.exit("NOT WRITTEN:\n  " + "\n  ".join(problems))
    BLIND.write_text(json.dumps({"labeller": labeller, "labels": result}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {rel(BLIND)}: {len(result)} replies")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("worksheet")
    imp = sub.add_parser("import")
    imp.add_argument("--labeller", required=True)
    args = parser.parse_args()
    if args.command == "worksheet":
        worksheet()
    else:
        import_labels(args.labeller)


if __name__ == "__main__":
    main()
