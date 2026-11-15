"""
Checks the frozen test material (data/README.md) for consistency, with no model calls:

  - every email has labels and is in exactly one split
  - every labelled identifier appears in its email, as written
  - every evidence passage appears in its document, and whole inside one chunk of the pipeline's chunking
  - every mechanical fact has an accepted wording that appears in its own evidence
  - every question's reference wording matches its own match terms, and no other question's in the same email
  - a question is unanswerable exactly when it has no facts
"""
import json
from collections import Counter
from pathlib import Path

import chunkers
from steps import contains
from tokens import Tokenizer

DATA = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    documents = {p.name: p.read_text() for p in sorted((DATA / "documents").glob("*.md"))}
    emails = {p.stem: p.read_text() for p in sorted((DATA / "emails").glob("*.txt"))}
    labels = json.loads((DATA / "labels.json").read_text())["emails"]
    splits = json.loads((DATA / "splits.json").read_text())
    settings = json.loads((DATA / "settings.json").read_text())
    chunks = [c.text for c in chunkers.chunk(settings["chunking"], documents, Tokenizer())]
    problems = []
    if sorted(emails) != sorted(labels) or sorted(emails) != sorted(splits["dev"] + splits["test"]):
        problems.append("emails, labels, and splits don't list the same emails exactly once")
    ids = Counter()
    for eid in sorted(labels):
        lab = labels[eid]
        for identifier in lab["identifiers"]:
            if identifier not in emails[eid]:
                problems.append(f"{eid}: identifier {identifier} isn't in the email")
        for q in lab["questions"]:
            ids[q["id"]] += 1
            if not any(t in q["asks"].lower() for t in q["match"]):
                problems.append(f"{q['id']}: the reference wording doesn't match its own terms")
            for other in lab["questions"]:
                if other is not q and any(t in q["asks"].lower() for t in other["match"]):
                    problems.append(f"{q['id']}: the reference wording also matches {other['id']}'s terms")
            if q["answerable"] != bool(q["facts"]):
                problems.append(f"{q['id']}: answerable doesn't agree with its facts")
            for f in q["facts"]:
                ids[f["id"]] += 1
                for e in f["evidence"]:
                    if e["text"] not in documents[e["doc"]]:
                        problems.append(f"{f['id']}: evidence isn't in {e['doc']}")
                    elif not any(e["text"] in c for c in chunks):
                        problems.append(f"{f['id']}: evidence isn't whole inside any chunk")
                if f["check"] == "mechanical" and not any(contains(e["text"], a) for e in f["evidence"] for a in f["any_of"]):
                    problems.append(f"{f['id']}: no accepted wording appears in its evidence")
    problems += [f"{i}: id used {n} times" for i, n in ids.items() if n > 1]

    print(f"{len(emails)} emails, {len(chunks)} chunks")
    print(f"{'':<34}{'dev':>6}{'test':>6}")
    rows = []
    for name in ("dev", "test"):
        qs = [q for e in splits[name] for q in labels[e]["questions"]]
        facts = [f for q in qs for f in q["facts"]]
        rows.append([len(splits[name])]
                    + [sum(len(labels[e]["questions"]) == k for e in splits[name]) for k in (1, 2, 3)]
                    + [len(qs), sum(not q["answerable"] for q in qs), len(facts),
                       sum(f["check"] == "mechanical" for f in facts), sum(f["check"] == "human" for f in facts),
                       sum(len(labels[e]["identifiers"]) for e in splits[name])])
    names = ["emails", "  with 1 question", "  with 2 questions", "  with 3 questions", "questions",
             "  unanswerable", "facts", "  mechanical", "  human", "identifiers"]
    for k, name in enumerate(names):
        print(f"{name:<34}{rows[0][k]:>6}{rows[1][k]:>6}")
    print("no problems" if not problems else "\n".join(["PROBLEMS:"] + problems))


if __name__ == "__main__":
    main()
