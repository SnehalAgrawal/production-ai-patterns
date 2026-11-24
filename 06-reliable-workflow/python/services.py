"""The four receiving systems: billing, credits, helpdesk, email.

Each owns its own SQLite file, opens its own connections, and commits its own transactions. Nothing the
workflow writes can share a transaction with them, and they can't share one with each other: that's the
property the demo needs from "separate systems". They are called in-process so runs are deterministic;
there is no network here, only separate transaction boundaries.

Every call is logged in the service's own `calls` table, in its own transaction, before the work starts.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

from common import Clock, connect, crash_point, scenario_config


class ServiceError(Exception):
    pass


class ResponseLost(ServiceError):
    """The service committed, but the caller never received its answer (a timeout, a dropped connection)."""


class Unavailable(ServiceError):
    """Nothing happened: the service refused or couldn't be reached."""


class Rejected(ServiceError):
    """A permanent refusal. Retrying won't change it."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class KeyReused(ServiceError):
    """The same idempotency key arrived with a different request."""


class NotSupported(ServiceError):
    pass


CALLS = "CREATE TABLE IF NOT EXISTS calls (seq INTEGER PRIMARY KEY AUTOINCREMENT, op TEXT, args TEXT, at INTEGER);"


class Service:
    name = ""
    schema = ""

    def __init__(self, directory, config=None):
        self.directory = Path(directory)
        self.path = self.directory / f"{self.name}.db"
        self.config = (scenario_config(directory) if config is None else config).get(self.name, {})
        self.clock = Clock(directory)

    def db(self):
        return connect(self.path)

    def create(self):
        db = self.db()
        db.executescript(CALLS + self.schema)
        db.close()

    def log_call(self, op, **args):
        """Record the call (its own transaction) and return its number among calls of this op."""
        db = self.db()
        try:
            db.execute("INSERT INTO calls (op, args, at) VALUES (?, ?, ?)",
                       (op, json.dumps(args, sort_keys=True), self.clock.now()))
            return db.execute("SELECT COUNT(*) FROM calls WHERE op = ?", (op,)).fetchone()[0]
        finally:
            db.close()

    def calls(self, op=None):
        db = self.db()
        try:
            if op is None:
                return db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
            return db.execute("SELECT COUNT(*) FROM calls WHERE op = ?", (op,)).fetchone()[0]
        finally:
            db.close()


class Billing(Service):
    """Plans and invoices. "Set the plan" is state-based: repeating it leaves the same state.

    The stand-in's own rule, for the compensation case: setting the plan an organization is already on
    cancels any scheduled change and re-prices the subscription at today's list price. A legacy price
    doesn't come back.
    """

    name = "billing"
    schema = """
    CREATE TABLE subscriptions (org TEXT PRIMARY KEY, plan TEXT, price_cents INTEGER, members INTEGER,
        next_period_start TEXT, ticket TEXT, scheduled_plan TEXT, scheduled_price_cents INTEGER,
        scheduled_effective TEXT);
    CREATE TABLE invoices (id TEXT PRIMARY KEY, org TEXT, period TEXT, amount_cents INTEGER, disputed INTEGER);
    CREATE TABLE charges (id TEXT PRIMARY KEY, invoice TEXT, status TEXT);
    """

    def seed(self, fixtures):
        self.create()
        disputed = set(self.config.get("disputed", []))
        db = self.db()
        db.execute("BEGIN")
        for s in fixtures["subscriptions"]:
            db.execute("INSERT INTO subscriptions (org, plan, price_cents, members, next_period_start, ticket) "
                       "VALUES (?, ?, ?, ?, ?, ?)",
                       (s["org"], s["plan"], s["price_cents"], s["members"], s["next_period_start"], s["ticket"]))
        for inv in fixtures["invoices"]:
            db.execute("INSERT INTO invoices VALUES (?, ?, ?, ?, ?)",
                       (inv["id"], inv["org"], inv["period"], inv["amount_cents"], int(inv["id"] in disputed)))
            for ch in inv["charges"]:
                db.execute("INSERT INTO charges VALUES (?, ?, ?)", (ch["id"], inv["id"], ch["status"]))
        db.execute("COMMIT")
        db.close()
        self.list_prices = fixtures["list_prices"]

    def get_subscription(self, org):
        self.log_call("get_subscription", org=org)
        db = self.db()
        try:
            row = db.execute("SELECT * FROM subscriptions WHERE org = ?", (org,)).fetchone()
            return dict(row) if row else None
        finally:
            db.close()

    def get_invoice(self, invoice):
        self.log_call("get_invoice", invoice=invoice)
        db = self.db()
        try:
            row = db.execute("SELECT * FROM invoices WHERE id = ?", (invoice,)).fetchone()
            if row is None:
                return None
            charges = db.execute("SELECT id, status FROM charges WHERE invoice = ? ORDER BY id", (invoice,))
            return {**dict(row), "charges": [dict(c) for c in charges]}
        finally:
            db.close()

    def set_plan(self, org, plan, effective, list_prices, key=None):
        n = self.log_call("set_plan", org=org, plan=plan, effective=effective, key=key)
        if n in self.config.get("fail_set_plan_calls", []):
            raise Unavailable("billing unavailable")
        db = self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT plan FROM subscriptions WHERE org = ?", (org,)).fetchone()["plan"]
            if plan == current:
                db.execute("UPDATE subscriptions SET scheduled_plan = NULL, scheduled_price_cents = NULL, "
                           "scheduled_effective = NULL, price_cents = ? WHERE org = ?", (list_prices[plan], org))
            else:
                db.execute("UPDATE subscriptions SET scheduled_plan = ?, scheduled_price_cents = ?, "
                           "scheduled_effective = ? WHERE org = ?", (plan, list_prices[plan], effective, org))
            db.execute("COMMIT")
        finally:
            db.close()
        crash_point("billing.after_commit")
        return {"org": org, "plan": plan, "effective": effective}


def fingerprint(**request):
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


class Credits(Service):
    """Account credits. Modes (scenario.json):

    keys               the key is recorded in the same transaction as the credit, under a unique constraint
    check_then_insert  look the key up, then write the credit and the key in separate transactions
    no_keys            keys are ignored

    `lookup` says whether a credit can be found by the caller's reference; `retention_hours` how long keys
    are kept (None: forever).
    """

    name = "credits"
    schema = """
    CREATE TABLE credits (id INTEGER PRIMARY KEY AUTOINCREMENT, org TEXT, invoice TEXT, amount_cents INTEGER,
        reference TEXT, created_at INTEGER);
    CREATE TABLE idempotency (key TEXT PRIMARY KEY, fingerprint TEXT, result TEXT, created_at INTEGER);
    """

    def capabilities(self):
        """What the service documents about itself: what a caller may rely on."""
        mode = self.config.get("mode", "keys")
        return {"keys": mode != "no_keys", "lookup": self.config.get("lookup", True),
                "retention_hours": self.config.get("retention_hours")}

    def apply_credit(self, org, invoice, amount_cents, key=None, reference=None, between=None):
        n = self.log_call("apply_credit", org=org, invoice=invoice, amount_cents=amount_cents, key=key)
        reason = self.config.get("reject_invoices", {}).get(invoice)
        if reason:
            raise Rejected(reason)
        mode = self.config.get("mode", "keys")
        retention = self.config.get("retention_hours")
        now = self.clock.now()
        db = self.db()
        try:
            if retention is not None:
                db.execute("DELETE FROM idempotency WHERE created_at <= ?", (now - retention * 3600,))
            fp = fingerprint(org=org, invoice=invoice, amount_cents=amount_cents)
            if key and mode == "keys":
                result = self._keyed(db, key, fp, org, invoice, amount_cents, reference, now, between)
            elif key and mode == "check_then_insert":
                result = self._check_then_insert(db, key, fp, org, invoice, amount_cents, reference, now, between)
            else:
                result = self._insert(db, org, invoice, amount_cents, reference, now)
        finally:
            db.close()
        crash_point("credits.after_commit")
        if n in self.config.get("lose_response_on_calls", []):
            raise ResponseLost("no response")
        return result

    @staticmethod
    def _saved(db, key, fp):
        row = db.execute("SELECT fingerprint, result FROM idempotency WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fp:
            raise KeyReused(key)
        return {**json.loads(row["result"]), "replayed": True}

    @staticmethod
    def _write_credit(db, org, invoice, amount_cents, reference, now):
        cur = db.execute("INSERT INTO credits (org, invoice, amount_cents, reference, created_at) "
                         "VALUES (?, ?, ?, ?, ?)", (org, invoice, amount_cents, reference, now))
        return {"credit_id": cur.lastrowid, "amount_cents": amount_cents}

    def _keyed(self, db, key, fp, org, invoice, amount_cents, reference, now, between):
        earlier = self._saved(db, key, fp)
        if earlier is not None:
            return earlier
        if between:
            between()
        try:
            db.execute("BEGIN IMMEDIATE")  # the credit and its key commit together, or neither does
            result = self._write_credit(db, org, invoice, amount_cents, reference, now)
            db.execute("INSERT INTO idempotency (key, fingerprint, result, created_at) VALUES (?, ?, ?, ?)",
                       (key, fp, json.dumps(result), now))
            db.execute("COMMIT")
            return {**result, "replayed": False}
        except sqlite3.IntegrityError:
            db.execute("ROLLBACK")  # a concurrent request with this key committed first; ours is undone
            return self._saved(db, key, fp)

    def _check_then_insert(self, db, key, fp, org, invoice, amount_cents, reference, now, between):
        earlier = self._saved(db, key, fp)
        if earlier is not None:
            return earlier
        if between:
            between()
        result = self._insert(db, org, invoice, amount_cents, reference, now)
        db.execute("INSERT OR IGNORE INTO idempotency (key, fingerprint, result, created_at) VALUES (?, ?, ?, ?)",
                   (key, fp, json.dumps({k: result[k] for k in ("credit_id", "amount_cents")}), now))
        return result

    def _insert(self, db, org, invoice, amount_cents, reference, now):
        db.execute("BEGIN IMMEDIATE")
        result = self._write_credit(db, org, invoice, amount_cents, reference, now)
        db.execute("COMMIT")
        return {**result, "replayed": False}

    def find_by_reference(self, reference):
        self.log_call("lookup", reference=reference)
        if not self.capabilities()["lookup"]:
            raise NotSupported("no lookup")
        db = self.db()
        try:
            row = db.execute("SELECT id, amount_cents FROM credits WHERE reference = ? ORDER BY id",
                             (reference,)).fetchone()
            return {"credit_id": row["id"], "amount_cents": row["amount_cents"]} if row else None
        finally:
            db.close()

    def rows(self, org=None):
        db = self.db()
        try:
            q = "SELECT id, org, invoice, amount_cents, reference FROM credits"
            rows = db.execute(q + (" WHERE org = ?" if org else "") + " ORDER BY id", (org,) if org else ())
            return [dict(r) for r in rows]
        finally:
            db.close()


class Helpdesk(Service):
    """Tickets. "Set the status" is state-based."""

    name = "helpdesk"
    schema = "CREATE TABLE tickets (id TEXT PRIMARY KEY, org TEXT, status TEXT);"

    def seed(self, fixtures):
        self.create()
        db = self.db()
        for s in fixtures["subscriptions"]:
            db.execute("INSERT INTO tickets VALUES (?, ?, 'open')", (s["ticket"], s["org"]))
        db.close()

    def set_status(self, ticket, status, key=None):
        self.log_call("set_status", ticket=ticket, status=status, key=key)
        if self.config.get("down"):
            raise Unavailable("helpdesk down")
        db = self.db()
        try:
            db.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket))
        finally:
            db.close()
        crash_point("helpdesk.after_commit")
        return {"ticket": ticket, "status": status}

    def status(self, ticket):
        db = self.db()
        try:
            return db.execute("SELECT status FROM tickets WHERE id = ?", (ticket,)).fetchone()["status"]
        finally:
            db.close()


class Email(Service):
    """Outgoing email. With `dedupe` (the default), a message id seen before returns the first email."""

    name = "email"
    schema = ("CREATE TABLE emails (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT, to_org TEXT, "
              "subject TEXT, body TEXT, created_at INTEGER);")

    def send(self, to_org, subject, body, message_id=None):
        self.log_call("send", to_org=to_org, message_id=message_id)
        db = self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            if message_id and self.config.get("dedupe", True):
                row = db.execute("SELECT id FROM emails WHERE message_id = ?", (message_id,)).fetchone()
                if row:
                    db.execute("COMMIT")
                    return {"email_id": row["id"], "replayed": True}
            cur = db.execute("INSERT INTO emails (message_id, to_org, subject, body, created_at) "
                             "VALUES (?, ?, ?, ?, ?)", (message_id, to_org, subject, body, self.clock.now()))
            db.execute("COMMIT")
        finally:
            db.close()
        crash_point("email.after_commit")
        return {"email_id": cur.lastrowid, "replayed": False}

    def rows(self, org=None):
        db = self.db()
        try:
            rows = db.execute("SELECT id, message_id, to_org, subject, body FROM emails"
                              + (" WHERE to_org = ?" if org else "") + " ORDER BY id", (org,) if org else ())
            return [dict(r) for r in rows]
        finally:
            db.close()


def seed_all(directory, fixtures):
    Billing(directory).seed(fixtures)
    Credits(directory).create()
    Helpdesk(directory).seed(fixtures)
    Email(directory).create()
