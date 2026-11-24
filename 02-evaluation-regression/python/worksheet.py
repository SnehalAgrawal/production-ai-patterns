"""
The blind labelling worksheet: every distinct test reply to label, from Part A and Part B, with nothing that
says where it came from.

  python worksheet.py      writes worksheet/worksheet.md (to read) and worksheet/labels.csv (to fill in)

Replies are deduplicated by their 01-style label key (email id and exact reply text). Which arm or run produced
each reply stays in data/replies.json and data/replies-b.json and is never written here. The worksheet shows
the email, each question with its labelled fact sentences and evidence passages, and the replies under neutral
ids (the first 8 characters of the label key). It shows no arm, run, prompt version, grader verdict, original
label or note, and not the grader's accepted wordings. Emails, and the replies within each email, are shuffled
with a fixed seed.
"""
import csv
import io
import json
import random
import sys

from common import DEMO, SOURCE_DATA, load_replies, rel
from common_b import LABELLED_RUNS, REPLIES_B, WORKSHEET_SEED

OUT = DEMO / "worksheet"
ANSWERABLE = "correct | wrong | omitted | declined"
UNCOVERED = "declined | answered"
RULES = """\
## How to label

Label each reply on its own, against its email's questions and facts only.

For each **answerable** question, one of:
- `correct`: every fact listed for it is stated correctly;
- `wrong`: it is addressed, but a fact is missing or wrong;
- `omitted`: it isn't addressed;
- `declined`: the reply says it can't be answered.

For each question **not covered by the documentation**, one of:
- `declined`: the reply says it isn't covered, and states nothing about it as fact;
- `answered`: the reply states anything about it as fact.

For each reply, `false_statement`: `yes` if the reply states anything false anywhere (including things not asked), otherwise `no`.

Fill in the `value` column of `labels.csv` (one row per question, plus one `false_statement` row per reply); `note` is optional. While labelling, don't open `data/`, `runs/`, or any report: they say which version wrote each reply.
"""


def collect(entries_a: list[dict] | None = None, runs_b: dict | None = None) -> dict[str, dict]:
    """
    label key -> {email, reply, sources}, from Part A's replies and Part B's labelled runs (by default, the data
    files). 'sources' (arm or run) is kept for the data, never for the worksheet.
    """
    entries_a = load_replies() if entries_a is None else entries_a
    runs_b = json.loads(REPLIES_B.read_text())["runs"] if runs_b is None else runs_b
    items: dict[str, dict] = {}

    def add(e: dict, source: str) -> None:
        if e["reply"] is None:
            return
        item = items.setdefault(e["key"], {"email": e["email"], "reply": e["reply"], "sources": []})
        if item["reply"] != e["reply"] or item["email"] != e["email"]:
            raise ValueError(f"key {e['key']} maps to two different replies")
        item["sources"].append(source)

    for e in entries_a:
        add(e, f"part A {e['arm']}")
    for name in LABELLED_RUNS:
        for eid, record in runs_b[name]["emails"].items():
            add({**record, "email": eid}, f"part B {name}")
    return items


def reply_id(key: str) -> str:
    return key[:8]


def ordered(items: dict[str, dict], seed: int = WORKSHEET_SEED) -> list[tuple[str, list[str]]]:
    """[(email, [keys])], emails and the replies within each shuffled with a fixed seed."""
    rng = random.Random(seed)
    by_email: dict[str, list[str]] = {}
    for key in sorted(items):
        by_email.setdefault(items[key]["email"], []).append(key)
    emails = sorted(by_email)
    rng.shuffle(emails)
    order = []
    for eid in emails:
        keys = sorted(by_email[eid])
        rng.shuffle(keys)
        order.append((eid, keys))
    return order


def render(items: dict[str, dict], labels: dict, email_texts: dict[str, str]) -> tuple[str, str]:
    """(worksheet.md, labels.csv)."""
    ids = [reply_id(k) for k in items]
    if len(set(ids)) != len(ids):
        raise ValueError("two replies share a neutral id")
    order = ordered(items)
    md = [f"# Labelling worksheet\n\n{len(items)} replies to {len(order)} emails.\n", RULES]
    rows = io.StringIO()
    writer = csv.writer(rows)
    writer.writerow(["reply_id", "email", "item", "allowed", "value", "note"])
    for number, (eid, keys) in enumerate(order, 1):
        questions = labels[eid]["questions"]
        md.append(f"\n---\n\n## Email {number} of {len(order)}: {eid}\n\n```text\n{email_texts[eid].strip()}\n```\n")
        md.append("**Questions, and what a correct reply must contain**\n")
        for q in questions:
            if not q["answerable"]:
                md.append(f"- `{q['id']}` {q['asks']}  \n  *Not covered by the documentation:* a correct reply says so "
                          "and states nothing about it as fact.")
                continue
            md.append(f"- `{q['id']}` {q['asks']}")
            for f in q["facts"]:
                evidence = "; ".join(f"{e['doc']}: \"{e['text']}\"" for e in f["evidence"])
                md.append(f"  - {f['fact']}  \n    *Evidence:* {evidence}")
        for key in keys:
            rid = reply_id(key)
            quoted = "\n".join("> " + line if line else ">" for line in items[key]["reply"].split("\n"))
            md.append(f"\n### Reply {rid}\n\n{quoted}\n")
            for q in questions:
                writer.writerow([rid, eid, q["id"], ANSWERABLE if q["answerable"] else UNCOVERED, "", ""])
            writer.writerow([rid, eid, "false_statement", "yes | no", "", ""])
    return "\n".join(md) + "\n", rows.getvalue()


def main() -> None:
    for name in ("worksheet.md", "labels.csv"):
        if (OUT / name).exists():
            sys.exit(f"{rel(OUT / name)} already exists and is never overwritten (it may hold labels)")
    items = collect()
    labels = json.loads((SOURCE_DATA / "labels.json").read_text())["emails"]
    texts = {eid: (SOURCE_DATA / "emails" / f"{eid}.txt").read_text() for eid in {i["email"] for i in items.values()}}
    md, rows = render(items, labels, texts)
    OUT.mkdir(exist_ok=True)
    (OUT / "worksheet.md").write_text(md)
    (OUT / "labels.csv").write_text(rows)
    print(f"wrote {rel(OUT / 'worksheet.md')} and {rel(OUT / 'labels.csv')}: {len(items)} replies")


if __name__ == "__main__":
    main()
