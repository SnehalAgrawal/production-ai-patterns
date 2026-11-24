"""The downgrade-and-credit workflow: seven steps, each with a contract, and a runner that reads the record.

The two rules the code follows:
- The record decides what to do next; the receiving system decides what happened.
- Every step ends by writing one of a few outcomes into the record (done, failed, unknown, degraded), and
  recovery is reading that record, not rerunning the code.
"""

import json
from dataclasses import dataclass

import validate as v
from common import Clock, connect, crash_point, load_fixtures, scenario_config
from model import ModelUnavailable, ScriptedModel
from record import SCHEMA_VERSION, TERMINAL, Record
from services import Billing, Credits, Email, Helpdesk, KeyReused, Rejected, ResponseLost, Unavailable

STEPS = ("understand", "check", "change_plan", "apply_credit", "update_ticket", "draft", "send")
SIDE_EFFECTS = ("change_plan", "apply_credit", "update_ticket", "send")
LEASE_SECONDS = 60
RETENTION_MARGIN_SECONDS = 3600

# The step contracts (PROTOCOL.md). Printed by report.py; the code below implements them.
CONTRACTS = [
    ("understand", "model", "none", "reuse the saved output; one repair call on a syntactic or schema failure; "
                                    "model unavailable: hold"),
    ("check", "code", "none", "re-run on every resume under the current policy; never reset a committed step"),
    ("change_plan", "billing", "compensable (state-based set)", "call again: a repeat leaves the same state"),
    ("apply_credit", "credit service", "pivot", "unknown: same key within retention, else lookup, else hand over"),
    ("update_ticket", "helpdesk", "optional (state-based set)", "helpdesk down: degraded, continue"),
    ("draft", "model", "none (writes the outbox row)", "reuse the saved draft; model unavailable: template"),
    ("send", "outbox relay", "forward only", "send unsent rows with the row id as the message id"),
]


@dataclass(frozen=True)
class Design:
    name: str
    use_record: bool = True  # False: ignore the saved record and start again (design A)
    keys: bool = True  # idempotency keys, and outbox ids as message ids
    save_model_outputs: bool = True  # save step 1's reading before anything uses it
    retention_aware: bool = True  # don't retry a key older than the service keeps keys
    on_reject: str = "hand_over"  # or "compensate"
    outbox: bool = True  # False: step 6 and the send request go to two different stores
    check_dispute: bool = False  # check the invoice's dispute status in step 2, before the pivot


DESIGNS = {d.name: d for d in (
    Design("A", use_record=False, keys=False),
    Design("B", keys=False),
    Design("C"),
    Design("C-unsaved", save_model_outputs=False),
    Design("C-naive-retention", retention_aware=False),
    Design("C-compensate", on_reject="compensate"),
    Design("C-dispute-check", check_dispute=True),
    Design("C-no-outbox", outbox=False),
)}


class Stop(Exception):
    """End this run with a workflow status (held, handed_over) and a reason."""

    def __init__(self, status, reason):
        super().__init__(status)
        self.status = status
        self.reason = reason


class MailQueue:
    """For the no-outbox design only: a separate store the send request is written to after step 6."""

    def __init__(self, directory):
        self.path = f"{directory}/mailqueue.db"
        db = connect(self.path)
        db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, wf TEXT, payload TEXT, sent INTEGER)")
        db.close()

    def put(self, request_id, wf, payload):
        db = connect(self.path)
        db.execute("INSERT OR IGNORE INTO requests VALUES (?, ?, ?, 0)", (request_id, wf, json.dumps(payload)))
        db.close()

    def unsent(self, wf):
        db = connect(self.path)
        rows = [(r["id"], "email", json.loads(r["payload"]))
                for r in db.execute("SELECT * FROM requests WHERE wf = ? AND sent = 0 ORDER BY id", (wf,))]
        db.close()
        return rows

    def mark_sent(self, request_id):
        db = connect(self.path)
        db.execute("UPDATE requests SET sent = 1 WHERE id = ?", (request_id,))
        db.close()


def template(facts):
    """The degraded draft: fixed text the team wrote, filled from the record. No model involved."""
    return {"subject": "Your plan change and credit",
            "body": (f"Hello,\n\nYour organization will move to Basic on {facts['date']}, at the start of your next "
                     f"billing period. We've applied a credit of {facts['amount']} for invoice {facts['invoice']}; "
                     "it will appear on your next invoice.\n\nBest regards,\nSupport")}


class Run:
    def __init__(self, directory, email_id, design, owner="worker", run_id=1):
        self.fx = load_fixtures()
        self.config = scenario_config(directory)
        self.clock = Clock(directory)
        self.record = Record(directory, self.clock)
        self.model = ScriptedModel(directory, self.fx)
        self.billing, self.credits = Billing(directory), Credits(directory)
        self.helpdesk, self.email = Helpdesk(directory), Email(directory)
        self.queue = MailQueue(directory)
        self.email_id, self.mail = email_id, self.fx["emails"][email_id]
        self.org = self.mail["org"]
        self.design, self.owner = design, owner
        self.wf = f"wf-{email_id}" if design.use_record else f"wf-{email_id}-run{run_id}"
        self.policy = self.fx["policies"][str(self.config.get("policy_version", 1))]
        self.version = self.reading = self.decision = self.subscription = None

    # --- the runner -------------------------------------------------------------------------------------

    def run(self, before_claim=None, after_claim=None):
        self.record.create(self.wf, self.email_id, self.org, self.policy["version"], STEPS)
        wf = self.record.workflow(self.wf)
        if wf["schema_version"] != SCHEMA_VERSION:
            return "refused"  # written by an incompatible version: don't guess what its fields mean
        if wf["status"] in TERMINAL:
            return wf["status"]  # a redelivered request for a finished workflow: nothing to do
        if before_claim:
            before_claim()
        self.version = self.record.claim(self.wf, self.owner, LEASE_SECONDS)
        if after_claim:
            after_claim()  # the race test holds both workers here until both have tried to claim
        if self.version is None:
            return "claim_refused"
        try:
            for name in STEPS:
                getattr(self, name)()
        except Stop as stop:
            self.record.finish(self.wf, self.version, stop.status, stop.reason)
            return stop.status
        degraded = [n for n, s in self.record.steps(self.wf).items() if s["status"] == "degraded"]
        status = "completed_degraded" if degraded else "completed"
        self.record.finish(self.wf, self.version, status, {"degraded": degraded} if degraded else None)
        crash_point("workflow.after_complete")
        return status

    def step(self, name):
        return self.record.step(self.wf, name)

    def update(self, name, event, detail=None, outbox=None, **fields):
        self.record.update_step(self.wf, self.version, name, event, detail, outbox, **fields)

    def committed(self):
        steps = self.record.steps(self.wf)
        return [n for n in SIDE_EFFECTS if steps[n]["status"] in ("done", "compensated")]

    def hand_over(self, step, why, **extra):
        raise Stop("handed_over", {"step": step, "why": why, "committed": self.committed(), **extra})

    # --- 1. understand (model) ---------------------------------------------------------------------------

    def understand(self):
        s = self.step("understand")
        if s["status"] == "done" and s["output"] is not None:
            self.reading = s["output"]  # a saved answer is reused, never asked for again
            return
        problems = None
        for attempt in (1, 2):
            try:
                text = self.model.call(self.email_id, "understand", problems)
            except ModelUnavailable:
                self.update("understand", "model_unavailable", error="model unavailable")
                raise Stop("held", {"step": "understand", "why": "model unavailable"}) from None
            crash_point("understand.after_model")
            reading, checks = v.parse_reading(text)
            if reading is not None:
                output = reading if self.design.save_model_outputs else None
                self.update("understand", "done", {"attempt": attempt}, status="done", attempts=attempt,
                            output=output, validation=checks, error=None)
                crash_point("understand.after_save")
                self.reading = reading
                return
            self.update("understand", "validation_failed", {"attempt": attempt, "checks": checks},
                        attempts=attempt, validation=checks)
            problems = [c.get("detail") or c["rule"] for c in checks if not c["ok"]]
        failed = next(c for c in checks if not c["ok"])
        self.update("understand", "failed", status="failed")
        self.hand_over("understand", "the output failed validation", level=failed["level"], rule=failed["rule"])

    # --- 2. check (code) ---------------------------------------------------------------------------------

    def check(self):
        prev = self.step("check")
        self.subscription = self.billing.get_subscription(self.org)
        invoice = self.billing.get_invoice(self.reading["invoice"])
        decision, checks = v.decide(self.reading, self.mail["text"], self.org, self.subscription, invoice,
                                    self.policy, self.fx["basic_member_limit"], self.design.check_dispute)
        if decision is None:
            failed = checks[-1]
            self.update("check", "validation_failed", {"failed": failed}, status="failed", validation=checks,
                        policy_version=self.policy["version"])
            why = "needs_approval" if failed["level"] == "approval" else "the decision failed validation"
            self.hand_over("check", why, level=failed["level"], rule=failed["rule"], detail=failed.get("detail"),
                           revalidation=prev["status"] == "done")
        decision["from_plan"] = (prev["output"] or {}).get("from_plan", self.subscription["plan"])

        def same(a, b):
            return {k: x for k, x in a.items() if k != "policy_version"} == \
                   {k: x for k, x in b.items() if k != "policy_version"}

        if prev["status"] == "done" and not same(prev["output"], decision) and self.committed():
            self.hand_over("check", "the decision changed after effects were committed")
        self.update("check", "done", {"revalidation": prev["status"] == "done"}, status="done", output=decision,
                    validation=checks, policy_version=self.policy["version"])
        crash_point("check.after_save")
        self.decision = decision

    # --- 3. change plan (billing; compensable) ------------------------------------------------------------

    def change_plan(self):
        s = self.step("change_plan")
        if s["status"] in ("done", "compensated"):
            return
        key = f"{self.wf}:change_plan" if self.design.keys else None
        self.update("change_plan", "started", status="started", key=key, attempts=s["attempts"] + 1,
                    first_attempt_at=s["first_attempt_at"] or self.clock.now())
        crash_point("change_plan.before_call")
        result = self.billing.set_plan(self.org, self.decision["plan"], self.decision["effective"],
                                       self.fx["list_prices"], key=key)
        self.update("change_plan", "done", status="done", result=result)
        crash_point("change_plan.after_record")

    # --- 4. apply credit (credit service; the pivot) ------------------------------------------------------

    def apply_credit(self):
        s = self.step("apply_credit")
        if s["status"] == "done":
            return
        if s["status"] in ("started", "unknown") and self.design.keys:
            if s["status"] == "started":  # a call may have been in flight when the last worker stopped
                self.update("apply_credit", "unknown", {"why": "started, no result recorded"}, status="unknown")
            return self.resolve_unknown()
        return self.attempt_credit(f"{self.wf}:apply_credit" if self.design.keys else None)

    def attempt_credit(self, key):
        s = self.step("apply_credit")
        amount = self.decision["amount_cents"]  # step 2's saved decision, never the model's reading
        cross = v.check("cross_step", True, "the credit carries the amount step 2 computed and recorded")
        self.update("apply_credit", "started", {"key": key}, status="started", key=key, attempts=s["attempts"] + 1,
                    first_attempt_at=s["first_attempt_at"] or self.clock.now(), validation=[cross])
        crash_point("apply_credit.before_call")
        try:
            result = self.credits.apply_credit(self.org, self.decision["invoice"], amount, key=key,
                                               reference=f"{self.wf}:apply_credit")
        except ResponseLost:
            self.update("apply_credit", "unknown", {"why": "response lost after the request was sent"},
                        status="unknown", error="response lost")
            return self.resolve_unknown()
        except Rejected as r:
            self.update("apply_credit", "rejected", {"reason": r.reason}, status="failed", error=r.reason)
            return self.on_reject(r.reason)
        except KeyReused:
            self.update("apply_credit", "key_reused", status="failed", error="key reused with a different request")
            self.hand_over("apply_credit", "key reused with a different request")
        self.credit_done(result, via="call")

    def credit_done(self, result, via):
        self.update("apply_credit", "done", {"via": via, "replayed": result.get("replayed", False)},
                    status="done", result=result, error=None)
        crash_point("apply_credit.after_record")

    def resolve_unknown(self):
        """The credit may or may not exist. Ask the receiving system; never guess."""
        s = self.step("apply_credit")
        caps = self.credits.capabilities()
        age = self.clock.now() - s["first_attempt_at"]
        retention = caps["retention_hours"]
        key_alive = retention is None or age < retention * 3600 - RETENTION_MARGIN_SECONDS
        if caps["keys"] and s["key"] and (key_alive or not self.design.retention_aware):
            self.record.event(self.wf, self.version, "apply_credit", "retry_same_key", {"age_seconds": age})
            return self.attempt_credit(s["key"])
        if caps["lookup"]:
            found = self.credits.find_by_reference(f"{self.wf}:apply_credit")
            self.record.event(self.wf, self.version, "apply_credit", "lookup", {"found": found is not None,
                                                                                "age_seconds": age})
            if found:
                return self.credit_done(found, via="lookup")
        self.hand_over("apply_credit", "outcome unknown", unknown=["apply_credit"])

    def on_reject(self, reason):
        if self.design.on_reject == "compensate" and "change_plan" in self.committed():
            self.compensate_plan()
            self.hand_over("apply_credit", reason, compensated=["change_plan"])
        self.hand_over("apply_credit", reason)

    def compensate_plan(self):
        """A new action, with its own key and its own retries; not an undo."""
        name, key = "compensate_change_plan", f"{self.wf}:compensate_change_plan"
        for attempt in (1, 2, 3):
            self.update(name, "started", status="started", key=key, attempts=attempt)
            try:
                result = self.billing.set_plan(self.org, self.decision["from_plan"], None, self.fx["list_prices"],
                                               key=key)
            except Unavailable as e:
                self.update(name, "attempt_failed", {"error": str(e)}, status="failed", error=str(e))
                continue
            self.update(name, "done", status="done", result=result, error=None)
            self.update("change_plan", "compensated", status="compensated")
            return
        self.hand_over(name, "compensation failed")

    # --- 5. update ticket (helpdesk; optional) -------------------------------------------------------------

    def update_ticket(self):
        s = self.step("update_ticket")
        if s["status"] in ("done", "degraded"):
            return
        key = f"{self.wf}:update_ticket" if self.design.keys else None
        try:
            result = self.helpdesk.set_status(self.subscription["ticket"], "waiting_on_customer", key=key)
        except Unavailable as e:
            self.update("update_ticket", "degraded", {"why": str(e)}, status="degraded", error=str(e))
            return
        self.update("update_ticket", "done", status="done", result=result)

    # --- 6. draft (model) and 7. send (outbox relay) -------------------------------------------------------

    def draft(self):
        s = self.step("draft")
        if s["status"] in ("done", "degraded"):
            return
        facts = {"amount": v.money(self.decision["amount_cents"]), "date": v.human_date(self.decision["effective"]),
                 "invoice": self.decision["invoice"]}
        why, checks = None, []
        try:
            draft, checks = v.parse_draft(self.model.call(self.email_id, "draft"), facts)
            if draft is None:
                why = "the draft failed its check"
        except ModelUnavailable:
            draft, why = None, "model unavailable"
        if draft is None:
            draft = template(facts)
        status = "degraded" if why else "done"
        payload = {"to": self.org, "subject": draft["subject"], "body": draft["body"]}
        outbox = (f"{self.wf}:send", "email", payload) if self.design.outbox else None
        self.update("draft", status, {"why": why} if why else None, outbox=outbox, status=status, output=draft,
                    validation=checks, error=why)
        crash_point("draft.after_save")
        if not self.design.outbox:
            self.queue.put(f"{self.wf}:send", self.wf, payload)  # a second store, a second transaction

    def send(self):
        """The relay. It may send a message twice (a crash before marking it), so the message id goes along."""
        store = self.record if self.design.outbox else self.queue
        sent = []
        for message_id, _kind, payload in store.unsent(self.wf):
            result = self.email.send(payload["to"], payload["subject"], payload["body"],
                                     message_id=message_id if self.design.keys else None)
            store.mark_sent(message_id)
            sent.append(result["email_id"])
        self.update("send", "done", {"sent": sent}, status="done", result={"sent": sent})
