"""
Scoring against the labels in data/labels.json, with the rules in data/README.md, and the hand labels in
data/hand_labels.json.

A hand label records whether a reply is correct: every fact the labels list for its answerable questions
is stated correctly, every unanswerable question is said to be not covered, and nothing false is stated.
Hand labels are keyed by a hash of the email id and the reply text, so a reply that changes needs reading
again.
"""
import hashlib
import json
from pathlib import Path

from steps import contains, normalize

DATA = Path(__file__).resolve().parent.parent / "data"


class Scorer:
    def __init__(self):
        self.labels = json.loads((DATA / "labels.json").read_text())["emails"]
        path = DATA / "hand_labels.json"
        self.hand = json.loads(path.read_text())["replies"] if path.exists() else {}

    def questions(self, eid: str) -> list[dict]:
        return self.labels[eid]["questions"]

    def extraction(self, eid: str, extracted: list[str]) -> dict:
        """Pair extracted questions with labelled ones by their match terms (data/README.md)."""
        labelled = self.questions(eid)
        covered = {q["id"]: False for q in labelled}
        unpaired = []
        for text in extracted:
            hits = [q for q in labelled if any(t in text.lower() for t in q["match"])]
            for q in hits:
                covered[q["id"]] = True
            if not hits:
                unpaired.append(text)
        missed = [qid for qid, ok in covered.items() if not ok]
        return {"ok": not missed and not unpaired, "missed": missed, "unpaired": unpaired}

    def identifiers(self, eid: str, found: list[str]) -> bool:
        return {normalize(i).strip() for i in found} == {normalize(i).strip() for i in self.labels[eid]["identifiers"]}

    @staticmethod
    def supported(fact: dict, texts: list[str]) -> bool:
        return any(e["text"] in t for e in fact["evidence"] for t in texts)

    def retrieval(self, eid: str, texts: list[str]) -> dict:
        """Every fact of every answerable question has an evidence passage whole inside a retrieved chunk."""
        missing = [f["id"] for q in self.questions(eid) for f in q["facts"] if not self.supported(f, texts)]
        return {"ok": not missing, "missing": missing}

    def mechanical(self, eid: str, reply: str) -> dict[str, bool]:
        return {f["id"]: any(contains(reply, a) for a in f["any_of"])
                for q in self.questions(eid) for f in q["facts"] if f["check"] == "mechanical"}

    @staticmethod
    def key(eid: str, reply: str) -> str:
        return hashlib.sha256(f"{eid}\n{reply}".encode()).hexdigest()[:16]

    def verdict(self, eid: str, reply: str) -> str | None:
        """'correct', 'wrong', or None if the reply hasn't been read yet."""
        label = self.hand.get(self.key(eid, reply))
        return label["verdict"] if label else None
