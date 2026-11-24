"""Check a run against the expectations in PROTOCOL.md.

    python report.py [runs/<run>]           the latest non-dev run by default; exit 1 if anything fails
    python report.py --negative-control     two expectations changed on purpose (E5b, E6): must exit 1
"""

import json
import sys
from pathlib import Path

from common import CRASH_POINTS
from freeze import verify
from validate import human_date, money
from workflow import template

DEMO = Path(__file__).resolve().parent.parent
ONE_EACH = {"credits": 1, "emails": 1, "scheduled": "Basic", "ticket": "waiting_on_customer"}


class Checks:
    def __init__(self):
        self.rows = []

    def expect(self, eid, what, actual, expected):
        self.rows.append((eid, what, actual == expected, actual, expected))


def effects(o):
    return {"credits": len(o["credits"]), "emails": len(o["emails"]), "scheduled": o["plan"]["scheduled_plan"],
            "ticket": o["ticket"]}


NONE = {"credits": 0, "emails": 0, "scheduled": None, "ticket": "open"}


def status(o):
    return o["workflows"][-1]["status"]


def reason(o, *keys):
    r = o["workflows"][-1]["reason"] or {}
    return tuple(r.get(k) for k in keys)


def before(events, a, b):
    return a in events and b in events and events.index(a) < events.index(b)


def check_all(r, negative=False):
    c = Checks()

    e = r["E1"]
    o = e["e02"]
    ev = o["events"]
    c.expect("E1", "e02: syntactic failure recorded on attempt 1", ev.count(["understand", "validation_failed"]), 1)
    c.expect("E1", "e02: 2 model calls for step 1", o["model_calls"]["understand"], 2)
    c.expect("E1", "e02: completed with one of each effect", (status(o), effects(o)), ("completed", ONE_EACH))
    c.expect("E1", "e02: the first billing write comes after the repaired output is accepted",
             before(ev, ["understand", "validation_failed"], ["understand", "done"])
             and before(ev, ["understand", "done"], ["change_plan", "started"]), True)
    o = e["e03"]
    c.expect("E1", "e03: handed over at step 1, syntactic", (status(o), reason(o, "step", "level")),
             ("handed_over", ("understand", "syntactic")))
    c.expect("E1", "e03: 0 effects, 0 calls to any receiving system", (effects(o), sum(o["calls"].values())),
             (NONE, 0))

    for eid, cases in (("E2", {"e04": ("business_rule", None), "e05": ("business_rule", None),
                               "e06": ("approval", "needs_approval")}),
                       ("E3", {"e07": ("evidence", None), "e08": ("evidence", None), "e09": ("evidence", None)})):
        for email, (level, why) in cases.items():
            o = r[eid][email]
            c.expect(eid, f"{email}: handed over at step 2, level {level}", (status(o), reason(o, "step", "level")),
                     ("handed_over", ("check", level)))
            c.expect(eid, f"{email}: 0 effects", effects(o), NONE)
            c.expect(eid, f"{email}: step 1 passed syntactic and schema", o["steps"]["understand"], "done")
            if why:
                c.expect(eid, f"{email}: reason {why}", reason(o, "why")[0], why)
            if eid == "E3":
                c.expect(eid, f"{email}: 0 billing writes, 0 credit-service calls",
                         (o["calls"]["set_plan"], o["calls"]["apply_credit"]), (0, 0))

    e = r["E4"]
    o = e["4a"]
    body = template({"amount": money(2000), "date": human_date("2026-12-01"), "invoice": "INV-1043"})["body"]
    c.expect("E4", "4a: draft degraded, workflow completed_degraded", (o["steps"]["draft"], status(o)),
             ("degraded", "completed_degraded"))
    c.expect("E4", "4a: the email is the template, with $20.00 and 1 December 2026",
             (o["emails"] == [body], "$20.00" in body, "1 December 2026" in body), (True, True, True))
    c.expect("E4", "4a: one of each effect, record matches", (effects(o), o["outcome"]["matches"]), (ONE_EACH, True))
    o = e["4b_first"]
    c.expect("E4", "4b: held, 0 effects", (status(o), effects(o)), ("held", NONE))
    o = e["4b_second"]
    c.expect("E4", "4b: second run completed, one of each, 2 step-1 calls",
             (status(o), effects(o), o["model_calls"]["understand"]), ("completed", ONE_EACH, 2))
    o = e["4c"]
    c.expect("E4", "4c: step 5 degraded, ticket unchanged, completed_degraded",
             (o["steps"]["update_ticket"], o["ticket"], status(o)), ("degraded", "open", "completed_degraded"))
    c.expect("E4", "4c: plan, credit, email one each; matches",
             (o["plan"]["scheduled_plan"], len(o["credits"]), len(o["emails"]), o["outcome"]["matches"]),
             ("Basic", 1, 1, True))

    e = r["E5"]
    o = e["5a"]
    c.expect("E5", "5a: one claim succeeds, the other is refused", o["statuses"], ["claim_refused", "completed"])
    c.expect("E5", "5a: one of each effect", effects(o), ONE_EACH)
    c.expect("E5", "5b: check-then-insert, 8 credits in every trial", e["5b_check_then_insert"]["credits_per_trial"],
             [8] * 20)
    want = 8 if negative else 1
    c.expect("E5", f"5b: key under a unique constraint, {want} credit in every trial",
             e["5b_keys"]["credits_per_trial"], [want] * 20)
    c.expect("E5", "5b: the other 7 calls return the first result, replayed", e["5b_keys"]["replayed_per_trial"],
             [7] * 20)
    a, b = e["5c_before"], e["5c_after"]
    c.expect("E5", "5c: redelivery after completion: no new workflow, effects or model calls",
             (len(b["workflows"]), effects(b), b["model_calls"], b["calls"]),
             (1, effects(a), a["model_calls"], a["calls"]))

    for design, points in r["E6"].items():
        for p, o in points.items():
            n = int(p[1:])
            credits, emails = 1, 1
            if design == "B":
                credits, emails = (2 if p == "P08" else 1), (2 if p == "P12" else 1)
            if design == "A":
                credits, emails = (2 if n >= 8 else 1), (2 if n >= 12 else 1)
            if negative and design == "C" and p == "P08":
                credits = 2
            c.expect("E6", f"{design} {p}: credits, emails", (len(o["credits"]), len(o["emails"])), (credits, emails))
            c.expect("E6", f"{design} {p}: plan scheduled Basic, ticket set",
                     (o["plan"]["scheduled_plan"], o["ticket"]), ("Basic", "waiting_on_customer"))
            c.expect("E6", f"{design} {p}: record matches receivers", o["outcome"]["matches"],
                     credits == 1 and emails == 1)
            if design == "C":
                c.expect("E6", f"C {p}: completed, model calls", (status(o), sum(o["model_calls"].values())),
                         ("completed", 3 if p == "P01" else 2))
    c.expect("E6", "every crash run exited at its crash point, every recovery ended normally",
             sorted({tuple(o["exits"]) for pts in r["E6"].values() for o in pts.values()}), [(70, 0)])
    c.expect("E6", "13 crash points per design", sorted(len(p) for p in r["E6"].values()), [len(CRASH_POINTS)] * 3)

    e = r["E7"]
    o = e["7a"]
    c.expect("E7", "7a: 2 model calls in total, resume calls only step 6, completed, one of each",
             (o["model_calls"], status(o), effects(o)), ({"understand": 1, "draft": 1}, "completed", ONE_EACH))
    o = e["7b"]
    c.expect("E7", "7b: revalidation fails at approval, handed over, 0 effects",
             (reason(o, "step", "level", "revalidation"), status(o), effects(o)),
             (("check", "approval", True), "handed_over", NONE))
    o = e["7c"]
    c.expect("E7", "7c: step 3 stays done, handed over listing change_plan",
             (o["steps"]["change_plan"], status(o), reason(o, "level", "committed")),
             ("done", "handed_over", ("approval", ["change_plan"])))
    c.expect("E7", "7c: plan scheduled Basic, 0 credits, 0 emails, no compensation",
             (o["plan"]["scheduled_plan"], len(o["credits"]), len(o["emails"]), o["calls"]["set_plan"],
              "compensate_change_plan" in o["steps"]), ("Basic", 0, 0, 1, False))
    a, o = e["7d_before_resume"], e["7d"]
    c.expect("E7", "7d: resume refuses (exit 3), no further calls, status unchanged",
             (o["exits"], o["calls"], o["model_calls"], status(o)), ([70, 3], a["calls"], a["model_calls"], status(a)))
    o = e["7e_unsaved"]
    c.expect("E7", "7e: regenerated reading fails at business rule, handed over listing both effects",
             (status(o), reason(o, "level", "committed")),
             ("handed_over", ("business_rule", ["change_plan", "apply_credit"])))
    c.expect("E7", "7e: 1 plan change, 1 credit, 0 emails",
             (o["plan"]["scheduled_plan"], len(o["credits"]), len(o["emails"])), ("Basic", 1, 0))
    o = e["7e_saved"]
    c.expect("E7", "7e under C: completed, no new step 1 call", (status(o), o["model_calls"]["understand"]),
             ("completed", 1))

    e = r["E8"]
    o = e["8a"]
    c.expect("E8", "8a: unknown recorded, then the same key again",
             (["apply_credit", "unknown"] in o["events"], ["apply_credit", "retry_same_key"] in o["events"]),
             (True, True))
    c.expect("E8", "8a: replayed first result; 1 credit, 2 calls; completed, matches",
             (o["credit_record"]["replayed"], len(o["credits"]), o["calls"]["apply_credit"], status(o),
              o["outcome"]["matches"]), (True, 1, 2, "completed", True))
    o = e["8b"]
    c.expect("E8", "8b: unknown, then a lookup finds it; 1 credit, 1 write; completed, matches",
             (["apply_credit", "unknown"] in o["events"], ["apply_credit", "lookup"] in o["events"], len(o["credits"]),
              o["calls"]["apply_credit"], status(o), o["outcome"]["matches"]),
             (True, True, 1, 1, "completed", True))
    o = e["8c"]
    c.expect("E8", "8c: handed over with step 4 unknown; 1 credit in the service",
             (status(o), o["steps"]["apply_credit"], len(o["credits"])), ("handed_over", "unknown", 1))
    o = e["8d_naive"]
    c.expect("E8", "8d naive: the pruned key makes a second credit; the record doesn't match",
             (len(o["credits"]), o["outcome"]["matches"]), (2, False))
    o = e["8d_aware"]
    c.expect("E8", "8d retention-aware: no write, a lookup finds the credit; 1 credit, completed, matches",
             (o["calls"]["apply_credit"], o["calls"]["lookup"], len(o["credits"]), status(o), o["outcome"]["matches"]),
             (1, 1, 1, "completed", True))

    e = r["E9"]
    o = e["9a"]
    c.expect("E9", "9a: plan scheduled Basic, 0 credits, 0 compensations, 0 emails, handed over listing change_plan",
             (o["plan"]["scheduled_plan"], len(o["credits"]), "compensate_change_plan" in o["steps"],
              len(o["emails"]), status(o), reason(o, "committed")[0]),
             ("Basic", 0, False, 0, "handed_over", ["change_plan"]))
    o = e["9b"]
    c.expect("E9", "9b: 2 compensation calls; plan stays Pro at $25.00 (was $20.00); 0 credits; handed over",
             (o["compensation_attempts"], o["plan"]["plan"], o["plan"]["scheduled_plan"], o["plan"]["price_cents"],
              len(o["credits"]), status(o), reason(o, "compensated")[0]),
             (2, "Pro", None, 2500, 0, "handed_over", ["change_plan"]))
    o = e["9c"]
    c.expect("E9", "9c: handed over at step 2, evidence; 0 effects, 0 compensations",
             (reason(o, "step", "level"), effects(o), o["calls"]["set_plan"]), (("check", "evidence"), NONE, 0))

    e = r["E10"]
    c.expect("E10", "10a: 2 send calls, 1 email", (e["10a"]["calls"]["send"], len(e["10a"]["emails"])), (2, 1))
    c.expect("E10", "10b: no deduplication, 2 emails", len(e["10b"]["emails"]), 2)
    o = e["10c_no_outbox"]
    c.expect("E10", "10c without outbox: 0 emails, the record says step 6 done",
             (len(o["emails"]), o["steps"]["draft"]), (0, "done"))
    c.expect("E10", "10c with outbox: 1 email", len(e["10c_outbox"]["emails"]), 1)
    return c.rows


def latest_run():
    runs = sorted(p for p in (DEMO / "runs").glob("*") if p.is_dir() and not p.name.endswith("-dev"))
    if not runs:
        sys.exit("no runs: python run.py")
    return runs[-1]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    negative = "--negative-control" in sys.argv
    run = Path(args[0]) if args else latest_run()
    data = json.loads((run / "results.json").read_text())
    problems = verify()
    print(f"run: {run.name}   python {data['environment']['python']}, sqlite {data['environment']['sqlite']}")
    print("freeze: " + ("ok" if not problems else "; ".join(problems)))
    if negative:
        print("NEGATIVE CONTROL: E5b expects 8 credits per trial, E6 C P08 expects 2 credits")
    rows = check_all(data["results"], negative)
    failed = [row for row in rows if not row[2]]
    for eid, what, ok, actual, expected in rows:
        if not ok or eid not in ("E6",):
            print(f"{'PASS' if ok else 'FAIL'}  {eid:4} {what}")
        if not ok:
            print(f"      expected {json.dumps(expected)}\n      actual   {json.dumps(actual)}")
    e6 = [row for row in rows if row[0] == "E6"]
    print(f"E6: {sum(1 for row in e6 if row[2])} of {len(e6)} checks pass (failures listed above)")
    print(f"\n{len(rows) - len(failed)} of {len(rows)} checks pass")
    sys.exit(1 if failed or problems else 0)


if __name__ == "__main__":
    main()
