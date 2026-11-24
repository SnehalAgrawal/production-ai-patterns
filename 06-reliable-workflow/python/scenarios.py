"""The scenarios in PROTOCOL.md (E1-E10). Each runs in a fresh directory with fresh databases.

Every workflow run is a separate process (worker.py), so a crash point ends it for real. What a scenario
returns is read back from the receiving systems' databases, the workflow record, and the model call log.
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from common import CRASH_EXIT, CRASH_POINTS, Clock, load_fixtures, write_json
from model import ScriptedModel
from record import Record
from services import Billing, Credits, Email, Helpdesk, seed_all
from workflow import DESIGNS, LEASE_SECONDS, Run

HERE = Path(__file__).resolve().parent
FX = load_fixtures()


class Scenario:
    def __init__(self, root, name, config=None):
        self.dir = Path(root) / name
        self.dir.mkdir(parents=True)
        write_json(self.dir / "scenario.json", config or {})
        Clock(self.dir).start(FX["start_time"])
        seed_all(self.dir, FX)
        self.exits = []

    def configure(self, **changes):
        path = self.dir / "scenario.json"
        config = json.loads(path.read_text())
        config.update(changes)
        write_json(path, config)

    def worker(self, email, design="C", crash=None, run_id=1):
        env = {k: x for k, x in os.environ.items() if k != "CRASH_AT"}
        if crash:
            env["CRASH_AT"] = CRASH_POINTS.get(crash, crash)
        r = subprocess.run([sys.executable, str(HERE / "worker.py"), str(self.dir), email, "--design", design,
                            "--run-id", str(run_id)], env=env, capture_output=True, text=True, cwd=HERE)
        if r.returncode not in (0, 3, CRASH_EXIT):
            raise RuntimeError(f"{self.dir.name}: worker failed\n{r.stderr}")
        self.exits.append(r.returncode)
        return r.returncode

    def crash_and_recover(self, email, design, point, between=None, resume_after=LEASE_SECONDS + 1):
        """Run until the crash point; optionally change something; then a new process recovers."""
        first = self.worker(email, design, crash=point)
        if between:
            between()
        Clock(self.dir).advance(resume_after)  # the crashed worker's lease has expired
        second = self.worker(email, design, run_id=2 if design == "A" else 1)
        return first, second

    def observe(self, email):
        return observe(self.dir, email, self.exits)


def observe(directory, email, exits=()):
    org = FX["emails"][email]["org"]
    billing, credits, helpdesk, mail = Billing(directory), Credits(directory), Helpdesk(directory), Email(directory)
    sub = _row(billing, "SELECT * FROM subscriptions WHERE org = ?", org)  # observing doesn't log a call
    record = Record(directory, Clock(directory))
    db = record.db()
    wfs = [dict(r) for r in db.execute("SELECT id, status, reason FROM workflows WHERE email = ? ORDER BY rowid",
                                       (email,))]
    db.close()
    final = wfs[-1]["id"] if wfs else None
    steps = record.steps(final) if final else {}
    credit_rows = credits.rows(org)
    email_rows = mail.rows(org)
    model = ScriptedModel(directory, FX)
    out = {
        "exits": list(exits),
        "workflows": [{"status": w["status"], "reason": json.loads(w["reason"]) if w["reason"] else None}
                      for w in wfs],
        "steps": {n: s["status"] for n, s in steps.items()},
        "attempts": {n: s["attempts"] for n, s in steps.items() if s["attempts"]},
        "credit_record": steps["apply_credit"]["result"] if steps else None,
        "events": [[st, kind] for st, kind, _ in record.events(final)] if final else [],
        "plan": {"plan": sub["plan"], "price_cents": sub["price_cents"], "scheduled_plan": sub["scheduled_plan"],
                 "scheduled_effective": sub["scheduled_effective"]},
        "credits": [r["amount_cents"] for r in credit_rows],
        "ticket": helpdesk.status(sub["ticket"]),
        "emails": [r["body"] for r in email_rows],
        "calls": {"set_plan": billing.calls("set_plan"), "billing_reads": billing.calls("get_subscription")
                  + billing.calls("get_invoice"), "apply_credit": credits.calls("apply_credit"),
                  "lookup": credits.calls("lookup"), "set_status": helpdesk.calls("set_status"),
                  "send": mail.calls("send")},
        "model_calls": {"understand": model.calls(email, "understand"), "draft": model.calls(email, "draft")},
    }
    out["outcome"] = outcome_check(steps, sub, credit_rows, email_rows, out["ticket"])
    return out


def _row(service, sql, *args):
    db = service.db()
    try:
        return dict(db.execute(sql, args).fetchone())
    finally:
        db.close()


def outcome_check(steps, sub, credit_rows, email_rows, ticket):
    """The outcome level: does the record agree with what the receiving systems hold?

    A step the record calls `unknown` isn't a mismatch: the record admits it doesn't know. It's listed as
    unresolved instead.
    """
    if not steps:
        return {"matches": None, "mismatches": [], "unresolved": []}
    mismatches, unresolved = [], []
    s = steps["change_plan"]["status"]
    want = "Basic" if s == "done" else None
    if sub["scheduled_plan"] != want:
        mismatches.append(f"change_plan: record {s}, billing scheduled {sub['scheduled_plan']}")
    s = steps["apply_credit"]
    if s["status"] == "unknown":
        unresolved.append("apply_credit")
    else:
        want = [s["result"]["credit_id"]] if s["status"] == "done" else []
        have = [r["id"] for r in credit_rows]
        if have != want:
            mismatches.append(f"apply_credit: record {s['status']} {want}, credit service {have}")
    s = steps["update_ticket"]["status"]
    want = "waiting_on_customer" if s == "done" else "open"
    if ticket != want:
        mismatches.append(f"update_ticket: record {s}, helpdesk {ticket}")
    s = steps["send"]
    want = len(s["result"]["sent"]) if s["status"] == "done" else 0
    if len(email_rows) != want:
        mismatches.append(f"send: record {want} email(s), email service {len(email_rows)}")
    return {"matches": not mismatches and not unresolved, "mismatches": mismatches, "unresolved": unresolved}


def single(root, name, email, design="C", config=None):
    sc = Scenario(root, name, config)
    sc.worker(email, design)
    return sc.observe(email)


def crashed(root, name, email, design, point, config=None, between=None, resume_after=LEASE_SECONDS + 1):
    sc = Scenario(root, name, config)
    sc.crash_and_recover(email, design, point, (lambda: between(sc)) if between else None, resume_after)
    return sc.observe(email)


# --- E1-E10 ------------------------------------------------------------------------------------------------

def e1(root):
    return {"e02": single(root, "e1-e02", "e02"), "e03": single(root, "e1-e03", "e03")}


def e2(root):
    return {e: single(root, f"e2-{e}", e) for e in ("e04", "e05", "e06")}


def e3(root):
    return {e: single(root, f"e3-{e}", e) for e in ("e07", "e08", "e09")}


def e4(root):
    held = Scenario(root, "e4-4b", None)
    held.worker("e12")
    first = held.observe("e12")
    held.worker("e12")
    return {"4a": single(root, "e4-4a", "e11"),
            "4b_first": first, "4b_second": held.observe("e12"),
            "4c": single(root, "e4-4c", "e01", config={"helpdesk": {"down": True}})}


def claim_race(root):
    sc = Scenario(root, "e5-5a")
    before, after = threading.Barrier(2), threading.Barrier(2)
    statuses = []

    def go(owner):
        statuses.append(Run(sc.dir, "e01", DESIGNS["C"], owner=owner).run(before.wait, after.wait))

    threads = [threading.Thread(target=go, args=(f"worker-{i}",)) for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {"statuses": sorted(statuses), **sc.observe("e01")}


def receiver_race(root, mode, threads=8, trials=20):
    per_trial, replayed = [], []
    for trial in range(trials):
        sc = Scenario(root, f"e5-5b-{mode}-{trial:02d}", {"credits": {"mode": mode}})
        barrier, results = threading.Barrier(threads), []

        def go(directory=sc.dir, barrier=barrier, results=results):
            results.append(Credits(directory).apply_credit("org-acme", "INV-1043", 2000, key="wf-race:apply_credit",
                                                           reference="wf-race:apply_credit", between=barrier.wait))

        workers = [threading.Thread(target=go) for _ in range(threads)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        per_trial.append(len(Credits(sc.dir).rows()))
        replayed.append(sum(1 for r in results if r["replayed"]))
    return {"credits_per_trial": per_trial, "replayed_per_trial": replayed}


def e5(root):
    redelivered = Scenario(root, "e5-5c")
    redelivered.worker("e01")
    before = redelivered.observe("e01")
    redelivered.worker("e01")
    return {"5a": claim_race(root),
            "5b_check_then_insert": receiver_race(root, "check_then_insert"),
            "5b_keys": receiver_race(root, "keys"),
            "5c_before": before, "5c_after": redelivered.observe("e01")}


def e6(root):
    return {design: {p: crashed(root, f"e6-{design}-{p}", "e01", design, p) for p in CRASH_POINTS}
            for design in ("A", "B", "C")}


def e7(root):
    def policy_v2(sc):
        sc.configure(policy_version=2)

    def old_schema(sc):
        sc.before_resume = sc.observe("e01")
        Record(sc.dir, Clock(sc.dir)).set_schema_version("wf-e01", 0)

    sc = Scenario(root, "e7-7d")
    sc.crash_and_recover("e01", "C", "P03", lambda: old_schema(sc))
    return {"7a": crashed(root, "e7-7a", "e01", "C", "P03"),
            "7b": crashed(root, "e7-7b", "e01", "C", "P03", between=policy_v2),
            "7c": crashed(root, "e7-7c", "e01", "C", "P06", between=policy_v2),
            "7d_before_resume": sc.before_resume, "7d": sc.observe("e01"),
            "7e_unsaved": crashed(root, "e7-7e-unsaved", "e10", "C-unsaved", "P09"),
            "7e_saved": crashed(root, "e7-7e-saved", "e10", "C", "P09")}


def e8(root):
    lost = {"lose_response_on_calls": [1]}
    retention = {"credits": {"mode": "keys", "lookup": True, "retention_hours": 24}}
    return {"8a": single(root, "e8-8a", "e01", config={"credits": {"mode": "keys", **lost}}),
            "8b": single(root, "e8-8b", "e01", config={"credits": {"mode": "no_keys", "lookup": True, **lost}}),
            "8c": single(root, "e8-8c", "e01", config={"credits": {"mode": "no_keys", "lookup": False, **lost}}),
            "8d_naive": crashed(root, "e8-8d-naive", "e01", "C-naive-retention", "P08", retention,
                                resume_after=30 * 3600),
            "8d_aware": crashed(root, "e8-8d-aware", "e01", "C", "P08", retention, resume_after=30 * 3600)}


def e9(root):
    disputed = {"billing": {"disputed": ["INV-1043"]},
                "credits": {"reject_invoices": {"INV-1043": "invoice_disputed"}}}
    compensate = {**disputed, "billing": {"disputed": ["INV-1043"], "fail_set_plan_calls": [2]}}
    out = {"9a": single(root, "e9-9a", "e01", config=disputed),
           "9b": single(root, "e9-9b", "e01", "C-compensate", config=compensate),
           "9c": single(root, "e9-9c", "e01", "C-dispute-check", config=disputed)}
    rec = Record(Path(root) / "e9-9b", Clock(Path(root) / "e9-9b"))
    out["9b"]["compensation_attempts"] = rec.step("wf-e01", "compensate_change_plan")["attempts"]
    return out


def e10(root):
    return {"10a": crashed(root, "e10-10a", "e01", "C", "P12"),
            "10b": crashed(root, "e10-10b", "e01", "C", "P12", {"email": {"dedupe": False}}),
            "10c_no_outbox": crashed(root, "e10-10c-no-outbox", "e01", "C-no-outbox", "P11"),
            "10c_outbox": crashed(root, "e10-10c-outbox", "e01", "C", "P11")}


ALL = {"E1": e1, "E2": e2, "E3": e3, "E4": e4, "E5": e5, "E6": e6, "E7": e7, "E8": e8, "E9": e9, "E10": e10}
