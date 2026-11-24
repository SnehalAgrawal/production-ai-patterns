"""Retention, erasure, and a scan of every store for a planted value.

Retention deletes by age with the configured periods in data/retention.json (illustrative,
not legal periods) and writes what it deleted to purge_log.jsonl. Erasure deletes everything
keyed by one subject and appends one event to the audit log; the audit log itself holds no
personal content, so it isn't rewritten.
"""

import json
from pathlib import Path

from common import load, parse, plus
from evidence import AuditLog, ContentStore, append_jsonl, read_jsonl, write_jsonl

SUBJECT_STORES = ("outbound.jsonl", "eval_cases.jsonl")


def erase(root: Path, subject: str, request_id: str, at: str) -> dict:
    root = Path(root)
    counts = ContentStore(root).erase_subject(subject)
    for name in SUBJECT_STORES:
        rows = read_jsonl(root / name)
        keep = [r for r in rows if r.get("subject_id") != subject]
        counts[name.removesuffix(".jsonl")] = len(rows) - len(keep)
        write_jsonl(root / name, keep)
    AuditLog(root / "audit.jsonl").append(at, "erased", "privacy-ops",
                                         {"subject_id": subject, "request_id": request_id, "deleted": counts})
    return counts


def subject_counts(root: Path, subject: str) -> dict:
    root = Path(root)
    store = ContentStore(root)
    counts = {"content": len(store.items(subject)), "keys": 1 if store.key(subject) else 0}
    for name in SUBJECT_STORES:
        counts[name.removesuffix(".jsonl")] = sum(1 for r in read_jsonl(root / name) if r.get("subject_id") == subject)
    return counts


def _due(created: str, days: int, now: str) -> bool:
    return parse(plus(created, days=days)) <= parse(now)


def purge(root: Path, now: str) -> list[dict]:
    """Delete what the schedule says is due at `now`; record each deletion in the purge log."""
    root = Path(root)
    days = load("retention.json")["days"]
    records = []

    def record(store, rule, deleted_times, extra=None):
        if deleted_times:
            r = {"at": now, "store": store, "rule": rule, "count": len(deleted_times),
                 "from": min(deleted_times), "to": max(deleted_times), **(extra or {})}
            append_jsonl(root / "purge_log.jsonl", r)
            records.append(r)

    for name, period in (("traces.jsonl", "debug_traces"), ("outbound.jsonl", "outbound_requests"),
                         ("eval_cases.jsonl", "eval_cases")):
        rows = read_jsonl(root / name)
        gone = [r for r in rows if _due(r["at"], days[period], now)]
        write_jsonl(root / name, [r for r in rows if r not in gone])
        record(name.removesuffix(".jsonl"), f"{period}-{days[period]}d", [r["at"] for r in gone])

    store = ContentStore(root)
    gone_times = []
    for subject in store.subjects():
        for item in store.items(subject):
            created = json.loads(item.read_text(encoding="utf-8"))["created_at"]
            if _due(created, days["content"], now):
                gone_times.append(created)
                item.unlink()
        if not store.items(subject):
            store.erase_subject(subject)      # the key goes with the last item
    record("content", f"content-{days['content']}d", gone_times)

    log = AuditLog(root / "audit.jsonl")
    events = log.events()
    # Only a prefix can go, so the rest of the chain still verifies from the last deleted hash.
    n = 0
    while n < len(events) and _due(events[n]["at"], days["audit"], now):
        n += 1
    gone = events[:n]
    if gone:
        write_jsonl(root / "audit.jsonl", events[len(gone):])
        record("audit", f"audit-{days['audit']}d", [e["at"] for e in gone],
               {"last_purged_seq": gone[-1]["seq"], "last_purged_hash": gone[-1]["hash"]})
    return records


def scan(root: Path, needle: str) -> dict:
    """Which stores contain `needle`? Content items are listed by name."""
    root = Path(root)
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and needle in path.read_text(encoding="utf-8", errors="replace"):
            rel = path.relative_to(root).as_posix()
            store = "content" if rel.startswith("content/") else rel
            found.setdefault(store, []).append(rel)
    return found
