"""The evidence stores: a hash-chained audit log, a content store keyed by subject, an external anchor.

The audit log holds references and keyed digests, never letter text, names or account values.
Content lives in the content store, one directory per subject, so it can be deleted (erasure,
retention) without rewriting the log.
"""

import json
import secrets
import shutil
from pathlib import Path

from common import ZERO, canon, keyed, sha


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# --- audit log -----------------------------------------------------------------------------

def event_hash(prev: str, body: dict) -> str:
    return sha(prev.encode() + canon(body))


def body_of(event: dict) -> dict:
    return {k: v for k, v in event.items() if k not in ("prev", "hash")}


class AuditLog:
    def __init__(self, path: Path):
        self.path = path

    def events(self) -> list[dict]:
        return read_jsonl(self.path)

    def append(self, at: str, kind: str, actor: str, data: dict, decision_id: str | None = None) -> dict:
        events = self.events()
        prev = events[-1]["hash"] if events else chain_start(self.path.parent)
        seq = events[-1]["seq"] + 1 if events else first_seq(self.path.parent)
        body = {"seq": seq, "at": at, "decision_id": decision_id, "kind": kind, "actor": actor, "data": data}
        event = {**body, "prev": prev, "hash": event_hash(prev, body)}
        append_jsonl(self.path, event)
        return event


def chain_start(root: Path) -> str:
    """Where the chain starts: zeros, or the hash of the last event retention deleted."""
    purges = [p for p in read_jsonl(root / "purge_log.jsonl") if p["store"] == "audit"]
    return purges[-1]["last_purged_hash"] if purges else ZERO


def first_seq(root: Path) -> int:
    purges = [p for p in read_jsonl(root / "purge_log.jsonl") if p["store"] == "audit"]
    return purges[-1]["last_purged_seq"] + 1 if purges else 1


def verify_chain(events: list[dict], start: str = ZERO) -> int | None:
    """None if the chain verifies, else the sequence number of the first event that doesn't."""
    prev = start
    for event in events:
        if event["prev"] != prev or event["hash"] != event_hash(prev, body_of(event)):
            return event["seq"]
        prev = event["hash"]
    return None


# --- external anchor -----------------------------------------------------------------------

def write_anchor(root: Path, at: str) -> dict:
    events = AuditLog(root / "audit.jsonl").events()
    anchor = {"at": at, "count": len(events), "last_seq": events[-1]["seq"] if events else 0,
              "head": events[-1]["hash"] if events else None}
    append_jsonl(root / "anchor" / "anchors.jsonl", anchor)
    return anchor


def check_anchor(root: Path) -> str | None:
    """None if the log agrees with the latest anchor, else what disagrees."""
    anchors = read_jsonl(root / "anchor" / "anchors.jsonl")
    if not anchors:
        return "no anchor"
    anchor = anchors[-1]
    by_seq = {e["seq"]: e for e in AuditLog(root / "audit.jsonl").events()}
    if anchor["last_seq"] not in by_seq:
        return f"log ends before the anchored event {anchor['last_seq']}"
    if by_seq[anchor["last_seq"]]["hash"] != anchor["head"]:
        return f"hash of event {anchor['last_seq']} differs from the anchored head"
    return None


# --- content store -------------------------------------------------------------------------

class ContentStore:
    """One directory per subject; one random HMAC key per subject in keys.json."""

    def __init__(self, root: Path):
        self.root = root
        self.dir = root / "content"
        self.keys_path = root / "keys.json"

    def _keys(self) -> dict:
        return json.loads(self.keys_path.read_text()) if self.keys_path.exists() else {}

    def key(self, subject: str, create: bool = False) -> bytes | None:
        keys = self._keys()
        if subject not in keys and create:
            keys[subject] = secrets.token_hex(32)
            self.keys_path.write_text(json.dumps(keys, indent=1))
        return bytes.fromhex(keys[subject]) if subject in keys else None

    def put(self, subject: str, name: str, text: str, created_at: str) -> tuple[str, str]:
        """Store text; return (reference, keyed digest)."""
        path = self.dir / subject / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"created_at": created_at, "text": text}, ensure_ascii=False), encoding="utf-8")
        return f"content://{subject}/{name}", keyed(self.key(subject, create=True), text.encode("utf-8"))

    def get(self, ref: str) -> dict | None:
        subject, name = ref.removeprefix("content://").split("/", 1)
        path = self.dir / subject / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def subjects(self) -> list[str]:
        return sorted(p.name for p in self.dir.iterdir()) if self.dir.exists() else []

    def items(self, subject: str) -> list[Path]:
        d = self.dir / subject
        return sorted(d.iterdir()) if d.exists() else []

    def erase_subject(self, subject: str) -> dict:
        counts = {"content": len(self.items(subject)), "keys": 1 if self.key(subject) else 0}
        shutil.rmtree(self.dir / subject, ignore_errors=True)
        keys = self._keys()
        keys.pop(subject, None)
        self.keys_path.write_text(json.dumps(keys, indent=1))
        return counts
