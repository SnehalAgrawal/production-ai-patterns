"""The workflow record: one SQLite file the workflow owns.

workflows  one row per workflow: status, owner and lease, version, schema and policy version, reason
steps      one row per step: status, attempts, key, the model's output, the validation result, the result a
           receiving system returned, when the first attempt started
events     append-only: what happened, in order
outbox     messages to send, written in the same transaction as the step that produces them

The record says what the workflow decided and what it was told. It is not proof of what a receiving
system did: that lives in the receiving system.
"""

import json

from common import connect

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, email TEXT, org TEXT, status TEXT, owner TEXT,
    lease_until INTEGER, version INTEGER, schema_version INTEGER, policy_version INTEGER, reason TEXT);
CREATE TABLE IF NOT EXISTS steps (wf TEXT, name TEXT, status TEXT, attempts INTEGER DEFAULT 0, key TEXT,
    output TEXT, validation TEXT, result TEXT, policy_version INTEGER, first_attempt_at INTEGER, error TEXT,
    PRIMARY KEY (wf, name));
CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, wf TEXT, step TEXT, kind TEXT,
    detail TEXT, at INTEGER);
CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, wf TEXT, kind TEXT, payload TEXT, sent INTEGER);
"""

STEP_FIELDS = ("status", "attempts", "key", "output", "validation", "result", "policy_version",
               "first_attempt_at", "error")
TERMINAL = ("completed", "completed_degraded", "handed_over")


class LostOwnership(Exception):
    """Another worker claimed the workflow since this one did."""


class Record:
    def __init__(self, directory, clock):
        self.path = f"{directory}/workflow.db"
        self.clock = clock
        db = connect(self.path)
        db.executescript(SCHEMA)
        db.close()

    def db(self):
        return connect(self.path)

    def create(self, wf, email, org, policy_version, steps):
        """Create the workflow if it doesn't exist. Returns False if it already existed."""
        db = self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            cur = db.execute("INSERT OR IGNORE INTO workflows VALUES (?, ?, ?, 'running', NULL, 0, 0, ?, ?, NULL)",
                             (wf, email, org, SCHEMA_VERSION, policy_version))
            created = cur.rowcount == 1
            if created:
                for name in steps:
                    db.execute("INSERT INTO steps (wf, name, status) VALUES (?, ?, 'pending')", (wf, name))
                self._event(db, wf, None, "created", {})
            db.execute("COMMIT")
            return created
        finally:
            db.close()

    def workflow(self, wf):
        db = self.db()
        try:
            row = db.execute("SELECT * FROM workflows WHERE id = ?", (wf,)).fetchone()
            return dict(row) if row else None
        finally:
            db.close()

    def claim(self, wf, owner, lease_seconds):
        """Take the workflow if nobody holds an unexpired lease. Returns the new version, or None."""
        now = self.clock.now()
        db = self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            cur = db.execute("UPDATE workflows SET owner = ?, lease_until = ?, version = version + 1 "
                             "WHERE id = ? AND (owner IS NULL OR owner = ? OR lease_until < ?)",
                             (owner, now + lease_seconds, wf, owner, now))
            if cur.rowcount != 1:
                db.execute("ROLLBACK")
                return None
            version = db.execute("SELECT version FROM workflows WHERE id = ?", (wf,)).fetchone()[0]
            self._event(db, wf, None, "claimed", {"version": version})
            db.execute("COMMIT")
            return version
        finally:
            db.close()

    def step(self, wf, name):
        db = self.db()
        try:
            row = db.execute("SELECT * FROM steps WHERE wf = ? AND name = ?", (wf, name)).fetchone()
            if row is None:
                return None
            out = dict(row)
            for field in ("output", "validation", "result"):
                if out[field] is not None:
                    out[field] = json.loads(out[field])
            return out
        finally:
            db.close()

    def steps(self, wf):
        db = self.db()
        try:
            names = [r[0] for r in db.execute("SELECT name FROM steps WHERE wf = ? ORDER BY rowid", (wf,))]
        finally:
            db.close()
        return {n: self.step(wf, n) for n in names}

    def update_step(self, wf, version, name, event, detail=None, outbox=None, **fields):
        """Write a step's fields and an event in one transaction, only while this worker still owns the run.

        `outbox` (id, kind, payload) is written in the same transaction: the step's result and the message
        about it are committed together, or neither is.
        """
        db = self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._check_version(db, wf, version)
            db.execute("INSERT OR IGNORE INTO steps (wf, name, status) VALUES (?, ?, 'pending')", (wf, name))
            for field, value in fields.items():
                assert field in STEP_FIELDS, field
                if field in ("output", "validation", "result") and value is not None:
                    value = json.dumps(value, sort_keys=True)
                db.execute(f"UPDATE steps SET {field} = ? WHERE wf = ? AND name = ?", (value, wf, name))
            if outbox is not None:
                db.execute("INSERT OR IGNORE INTO outbox VALUES (?, ?, ?, ?, 0)",
                           (outbox[0], wf, outbox[1], json.dumps(outbox[2], sort_keys=True)))
            self._event(db, wf, name, event, detail or {})
            db.execute("COMMIT")
        finally:
            db.close()

    def event(self, wf, version, step, kind, detail=None):
        db = self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._check_version(db, wf, version)
            self._event(db, wf, step, kind, detail or {})
            db.execute("COMMIT")
        finally:
            db.close()

    def finish(self, wf, version, status, reason=None):
        db = self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._check_version(db, wf, version)
            db.execute("UPDATE workflows SET status = ?, reason = ?, owner = NULL, lease_until = NULL "
                       "WHERE id = ?", (status, json.dumps(reason, sort_keys=True) if reason else None, wf))
            self._event(db, wf, None, status, reason or {})
            db.execute("COMMIT")
        finally:
            db.close()

    def unsent(self, wf):
        db = self.db()
        try:
            rows = db.execute("SELECT id, kind, payload FROM outbox WHERE wf = ? AND sent = 0 ORDER BY id", (wf,))
            return [(r["id"], r["kind"], json.loads(r["payload"])) for r in rows]
        finally:
            db.close()

    def mark_sent(self, outbox_id):
        db = self.db()
        try:
            db.execute("UPDATE outbox SET sent = 1 WHERE id = ?", (outbox_id,))
        finally:
            db.close()

    def events(self, wf):
        db = self.db()
        try:
            return [(r["step"], r["kind"], json.loads(r["detail"]))
                    for r in db.execute("SELECT step, kind, detail FROM events WHERE wf = ? ORDER BY seq", (wf,))]
        finally:
            db.close()

    def set_schema_version(self, wf, value):
        """For the incompatible-record case only (PROTOCOL.md, 7d)."""
        db = self.db()
        try:
            db.execute("UPDATE workflows SET schema_version = ? WHERE id = ?", (value, wf))
        finally:
            db.close()

    def _check_version(self, db, wf, version):
        current = db.execute("SELECT version FROM workflows WHERE id = ?", (wf,)).fetchone()[0]
        if current != version:
            db.execute("ROLLBACK")
            raise LostOwnership(f"{wf}: version {current}, expected {version}")

    def _event(self, db, wf, step, kind, detail):
        db.execute("INSERT INTO events (wf, step, kind, detail, at) VALUES (?, ?, ?, ?, ?)",
                   (wf, step, kind, json.dumps(detail, sort_keys=True), self.clock.now()))
