"""Run the baseline and scenarios E1-E12 from PROTOCOL.md; save what was observed.

    python run.py            # writes runs/<UTC timestamp>/ (not committed) with observations.json

Each scenario works in its own directory: a copy of the baseline, or a fresh run. Nothing is
called over the network. report.py checks observations.json against the protocol.
"""

import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path

from checker import check
from common import DATA, DEMO, action_sha, load, plus
from evidence import AuditLog, ContentStore, append_jsonl, event_hash, read_jsonl, write_jsonl
from hashes import experiment
from lifecycle import erase, purge, scan, subject_counts
from reconstruct import reconstruct
from workflow import Refused, Workflow, run_baseline

CANARY = "CANARY-7Q4K-2291"


def check_freezes() -> dict:
    status = {}
    for name in ("freeze-inputs.json", "freeze.json"):
        path = DEMO / "results" / name
        if not path.exists():
            status[name] = "missing"
            continue
        frozen = json.loads(path.read_text())["files"]
        changed = [f for f, h in frozen.items() if hashlib.sha256((DEMO / f).read_bytes()).hexdigest() != h]
        status[name] = "ok" if not changed else f"changed: {changed}"
    return status


def copy(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


def statuses(answers: dict) -> dict:
    out = {}
    for q, a in answers.items():
        if q == "Q2" and "policy" in a:
            out["Q2.policy"] = a["policy"]["status"]
            out["Q2.account_snapshot"] = a["account_snapshot"]["status"]
        else:
            out[q] = a["status"]
    return out


def forced_decided(root: Path, at: str, decision_id: str, reviewer: str, role: str, action: dict,
                   release: str = "assistant-2026.11.1", policy_version: str = "v14") -> None:
    """A decision record written straight into the log, not through the decision gate."""
    AuditLog(root / "audit.jsonl").append(at, "decided", reviewer, {
        "reviewer": reviewer, "role": role, "decision": "approve", "reason_code": "forced",
        "approved_action": action, "approved_action_sha256": action_sha(action),
        "release": release, "policy_version": policy_version,
        "evidence_view": {"version": "card-v3", "shown_sha256": None}}, decision_id)


def forced_executed(root: Path, at: str, decision_id: str, action: dict, ledger_id: str, audit: bool = True) -> None:
    """An execution written straight into the ledger (and the log), not through the executor."""
    append_jsonl(root / "ledger.jsonl", {"ledger_id": ledger_id, "decision_id": decision_id, "loan_id": "forced",
                                         "action": action, "at": at})
    if audit:
        AuditLog(root / "audit.jsonl").append(at, "executed", "forced",
                                             {"action": action, "action_sha256": action_sha(action),
                                              "ledger_id": ledger_id}, decision_id)


def refused(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
        return None
    except Refused as e:
        return str(e)


def findings_for(findings: list[dict]) -> list[list]:
    return [[f["check"], f["decision_id"], f["finding"]] for f in findings]


def main() -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = DEMO / "runs" / stamp
    out_dir.mkdir(parents=True)
    obs = {"run": stamp, "freezes": check_freezes(),
           "setup": {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
                     "load_average_1m": round(os.getloadavg()[0], 2)}}

    # Baseline -------------------------------------------------------------------------------
    base = out_dir / "base"
    run_baseline(base)
    events = AuditLog(base / "audit.jsonl").events()
    by = {}
    for e in events:
        by.setdefault(e["decision_id"], []).append(e)
    obs["B"] = {
        "activated": [e["data"] for e in events if e["kind"] == "release_activated"],
        "decisions": sorted(k for k in by if k),
        "executed": sorted(e["decision_id"] for e in events if e["kind"] == "executed"),
        "no_action": sorted(e["decision_id"] for e in events if e["kind"] == "no_action"),
        "ledger_entries": len(read_jsonl(base / "ledger.jsonl")),
        "routed": {e["decision_id"]: e["data"]["required_role"] for e in events if e["kind"] == "routed"},
        "failed_checks": {e["decision_id"]: [c["name"] for c in e["data"]["checks"] if not c["passed"]]
                          for e in events if e["kind"] == "checked" and not all(c["passed"] for c in e["data"]["checks"])},
        "findings": findings_for(check(base)),
    }

    # E1 ---------------------------------------------------------------------------------------
    obs["E1"] = {}
    for d in ("D-C01", "D-C04"):
        a = reconstruct(base, d)
        obs["E1"][d] = {"statuses": statuses(a), "Q3_calls": a["Q3"]["calls"], "Q4": a["Q4"]["action"],
                        "Q6": {k: a["Q6"][k] for k in ("reviewer", "role", "decision", "approved_action")},
                        "Q7": a["Q7"], "Q8": a["Q8"], "Q9": a["Q9"]}

    # E2a: one character appended to the recommendation prompt --------------------------------
    e2a = out_dir / "e2a"
    data_mod = e2a / "data"
    shutil.copytree(DATA, data_mod)
    p = data_mod / "recommendation_prompt.txt"
    p.write_text(p.read_text(encoding="utf-8") + ".", encoding="utf-8")
    wf = Workflow(e2a / "run", data_dir=data_mod)
    why = refused(wf.activate, "assistant-2026.11.1", "2026-11-03T08:00:00Z")
    ev = AuditLog(e2a / "run" / "audit.jsonl").events()
    obs["E2a"] = {"refused": why, "refusal_events": [e["data"] for e in ev if e["kind"] == "release_refused"],
                  "process_refused": refused(wf.process, "C01"),
                  "decisions": len([e for e in AuditLog(e2a / "run" / "audit.jsonl").events() if e["decision_id"]])}

    # E2b: the provider changes the model behind the same name ----------------------------------
    e2b = copy(base, out_dir / "e2b")
    wf = Workflow(e2b, returned_model="lender-recommender-2026-11-20")
    for decision_id, case_id, at in (("D-E2-1", "C02", "2026-11-03T14:00:00Z"), ("D-E2-2", "C09", "2026-11-03T14:20:00Z")):
        wf.process(case_id, decision_id, at)
        wf.decide(decision_id, "S-101", "approve", plus(at, minutes=12), "policy-4.2")
        wf.execute(decision_id, plus(at, minutes=13))
    f = check(e2b)
    obs["E2b"] = {"executed": sorted(e["decision_id"] for e in AuditLog(e2b / "audit.jsonl").events()
                                     if e["kind"] == "executed" and e["decision_id"].startswith("D-E2")),
                  "K6_decisions": sorted({x["decision_id"] for x in f if x["check"] == "K6"}),
                  "findings": findings_for(f)}

    # E3: approval bound to the action ---------------------------------------------------------
    e3 = copy(base, out_dir / "e3")
    wf = Workflow(e3)
    wf.process("C01", "D-E3", "2026-11-03T14:00:00Z")
    wf.decide("D-E3", "S-101", "approve", "2026-11-03T14:12:00Z", "policy-4.2")
    ledger_before = len(read_jsonl(e3 / "ledger.jsonl"))
    why = refused(wf.execute, "D-E3", "2026-11-03T14:13:00Z", {"action": "fee_waiver", "amount": 50.00})
    ledger_after = len(read_jsonl(e3 / "ledger.jsonl"))
    refusal = [e["data"]["reason"] for e in AuditLog(e3 / "audit.jsonl").events()
               if e["kind"] == "execution_refused" and e["decision_id"] == "D-E3"]
    forced_executed(e3, "2026-11-03T14:14:00Z", "D-E3", {"action": "fee_waiver", "amount": 50.00}, "ADJ-F03")
    f3 = check(e3)
    e3c = copy(base, out_dir / "e3c")
    wf = Workflow(e3c)
    wf.process("C02", "D-E3c", "2026-11-03T14:00:00Z")
    wf.decide("D-E3c", "S-101", "approve", "2026-11-03T14:12:00Z", "policy-4.2")
    forced_executed(e3c, "2026-11-03T14:13:00Z", "D-E3c", {"action": "fee_waiver", "amount": 20.00}, "ADJ-F3C")
    f3c = check(e3c)
    obs["E3"] = {"a_refused": why, "a_refusal_logged": refusal, "a_ledger_before": ledger_before,
                 "a_ledger_after": ledger_after, "b_findings": findings_for([x for x in f3 if x["decision_id"] == "D-E3"]),
                 "c_baseline_K7": [x for x in obs["B"]["findings"] if x[0] == "K7"],
                 "c_forced_findings": findings_for([x for x in f3c if x["decision_id"] == "D-E3c"])}

    # E4: stale approval -----------------------------------------------------------------------
    e4 = copy(base, out_dir / "e4")
    wf = Workflow(e4)
    wf.process("C08", "D-E4", "2026-11-03T14:00:00Z")
    wf.decide("D-E4", "S-103", "approve", "2026-11-03T14:12:00Z", "policy-4.2")
    activated = wf.activate("assistant-2026.11.2", "2026-11-03T14:15:00Z")
    stale = refused(wf.execute, "D-E4", "2026-11-03T14:20:00Z")
    # The case goes through again under the new release; S-103 tries to approve it.
    wf.process("C08", "D-E4-r", "2026-11-03T14:25:00Z")
    reapproval = refused(wf.decide, "D-E4-r", "S-103", "approve", "2026-11-03T14:37:00Z", "policy-4.2")
    routed_r = [e["data"]["required_role"] for e in AuditLog(e4 / "audit.jsonl").events()
                if e["kind"] == "routed" and e["decision_id"] == "D-E4-r"]
    forced_executed(e4, "2026-11-03T14:40:00Z", "D-E4", {"action": "fee_waiver", "amount": 45.00}, "ADJ-F04")
    f4 = check(e4)
    obs["E4"] = {"activated": activated, "stale_refused": stale, "reapproval_refused": reapproval,
                 "reprocessed_routed_to": routed_r,
                 "forced_findings": findings_for([x for x in f4 if x["decision_id"] == "D-E4"])}

    # E5: authority and separation of duties --------------------------------------------------
    e5 = copy(base, out_dir / "e5")
    wf = Workflow(e5)
    wf.process("C10", "D-E5a", "2026-11-03T14:00:00Z")
    sod = refused(wf.decide, "D-E5a", "S-104", "approve", "2026-11-03T14:12:00Z", "policy-4.2")
    wf.process("C05", "D-E5b", "2026-11-03T14:20:00Z")
    limit = refused(wf.decide, "D-E5b", "S-101", "approve", "2026-11-03T14:32:00Z", "policy-4.2")
    forced_decided(e5, "2026-11-03T14:40:00Z", "D-E5a", "S-104", "hardship-lead", {"action": "fee_waiver", "amount": 150.00})
    forced_executed(e5, "2026-11-03T14:41:00Z", "D-E5a", {"action": "fee_waiver", "amount": 150.00}, "ADJ-F5A")
    forced_decided(e5, "2026-11-03T14:42:00Z", "D-E5b", "S-101", "hardship-agent", {"action": "fee_waiver", "amount": 120.00})
    forced_executed(e5, "2026-11-03T14:43:00Z", "D-E5b", {"action": "fee_waiver", "amount": 120.00}, "ADJ-F5B")
    f5 = check(e5)
    obs["E5"] = {"a_refused": sod, "b_refused": limit,
                 "forced_findings": findings_for([x for x in f5 if x["decision_id"] in ("D-E5a", "D-E5b")])}

    # E6: bypass ---------------------------------------------------------------------------------
    e6 = copy(base, out_dir / "e6")
    wf = Workflow(e6)
    wf.process("C12", "D-E6a", "2026-11-03T14:00:00Z")
    forced_executed(e6, "2026-11-03T14:05:00Z", "D-E6a", {"action": "fee_waiver", "amount": 30.00}, "ADJ-F6A")
    forced_executed(e6, "2026-11-03T14:06:00Z", "D-E6b", {"action": "fee_waiver", "amount": 25.00}, "ADJ-F6B",
                    audit=False)
    f6, f6_no_k5 = check(e6), check(e6, k5=False)
    obs["E6"] = {"a_findings": findings_for([x for x in f6 if x["decision_id"] == "D-E6a" and x["check"] == "K3"]),
                 "b_findings": findings_for([x for x in f6 if x["decision_id"] == "D-E6b"]),
                 "b_findings_without_K5": findings_for([x for x in f6_no_k5 if x["decision_id"] == "D-E6b"])}

    # E7: edit, delete, truncate ---------------------------------------------------------------
    def edit_events(root: Path, fn) -> None:
        path = root / "audit.jsonl"
        write_jsonl(path, fn(read_jsonl(path)))

    def set_reviewer(evs):
        for e in evs:
            if e["decision_id"] == "D-C01" and e["kind"] == "decided":
                e["data"]["reviewer"] = "S-103"
        return evs

    e7a = copy(base, out_dir / "e7a")
    edit_events(e7a, set_reviewer)
    edited_seq = next(e["seq"] for e in read_jsonl(e7a / "audit.jsonl") if e["decision_id"] == "D-C01" and e["kind"] == "decided")
    e7b = copy(base, out_dir / "e7b")
    deleted_seq = next(e["seq"] for e in read_jsonl(e7b / "audit.jsonl") if e["decision_id"] == "D-C02" and e["kind"] == "routed")
    edit_events(e7b, lambda evs: [e for e in evs if e["seq"] != deleted_seq])
    e7c = copy(base, out_dir / "e7c")
    removed = [[e["decision_id"], e["kind"]] for e in read_jsonl(e7c / "audit.jsonl")[-3:]]
    edit_events(e7c, lambda evs: evs[:-3])
    obs["E7"] = {"a_edited_seq": edited_seq, "a_findings": findings_for([x for x in check(e7a) if x["check"] == "K1"]),
                 "b_deleted_seq": deleted_seq, "b_findings": findings_for([x for x in check(e7b) if x["check"] == "K1"]),
                 "c_removed": removed,
                 "c_findings": findings_for([x for x in check(e7c) if x["check"] in ("K1", "K2", "K8")])}

    # E8: full rewrite ------------------------------------------------------------------------
    e8 = copy(base, out_dir / "e8")

    def rewrite(evs):
        evs = set_reviewer(evs)
        prev = "0" * 64
        for e in evs:
            body = {k: v for k, v in e.items() if k not in ("prev", "hash")}
            e["prev"], e["hash"] = prev, event_hash(prev, body)
            prev = e["hash"]
        return evs

    edit_events(e8, rewrite)
    obs["E8"] = {"findings": findings_for(check(e8)), "findings_without_K2": findings_for(check(e8, k2=False))}

    # E9: where the canary and the names ended up -------------------------------------------------
    canary = scan(base, CANARY)
    names = [c["borrower_name"] for c in load("cases.json")["cases"]]
    rec_prompts = [p.name for p in (base / "content").rglob("*recommendation-prompt.json")
                   if CANARY in p.read_text(encoding="utf-8")]
    e9n = copy(base, out_dir / "e9n")
    Workflow(e9n, log_prompts=True).process("C07", "D-E9n", "2026-11-03T14:00:00Z")
    obs["E9"] = {"canary_stores": sorted(canary), "canary_content_items": canary.get("content", []),
                 "canary_in_recommendation_prompts": rec_prompts,
                 "names_found": {n: sorted(scan(base, n)) for n in names if scan(base, n)},
                 "negative_control_stores": sorted(scan(e9n, CANARY))}

    # E10: plain hash vs keyed hash -------------------------------------------------------------
    key = ContentStore(base).key("B-1007")
    obs["E10"] = experiment("L-398841", key)

    # E11: erasure ----------------------------------------------------------------------------
    e11 = out_dir / "e11"
    run_baseline(e11, cache=True)
    before = subject_counts(e11, "B-1003")
    erased = erase(e11, "B-1003", "ER-0001", "2026-11-20T10:00:00Z")
    after = subject_counts(e11, "B-1003")
    a = reconstruct(e11, "D-C03")
    obs["E11"] = {"before": before, "deleted": erased, "after": after,
                  "erased_events": [e["data"] for e in AuditLog(e11 / "audit.jsonl").events() if e["kind"] == "erased"],
                  "K1": findings_for([x for x in check(e11) if x["check"] == "K1"]),
                  "statuses": statuses(a), "Q1": a["Q1"]["letter"], "Q2_snapshot": a["Q2"]["account_snapshot"],
                  "negative_control_stores": sorted(scan(e11, "reduced hours until January"))}

    # E12: retention on the fake clock ----------------------------------------------------------
    e12 = copy(base, out_dir / "e12")
    obs["E12"] = {}
    for label, now in (("day0", "2026-11-03T13:00:00Z"), ("day31", "2026-12-04T00:00:00Z"),
                       ("day366", "2027-11-04T00:00:00Z"), ("day731", "2028-11-03T00:00:00Z")):
        purged = purge(e12, now)
        a = reconstruct(e12, "D-C01")
        obs["E12"][label] = {"purged": [{k: r[k] for k in ("store", "rule", "count")} for r in purged],
                             "keys_left": len(json.loads((e12 / "keys.json").read_text())),
                             "traces_left": len(read_jsonl(e12 / "traces.jsonl")),
                             "outbound_left": len(read_jsonl(e12 / "outbound.jsonl")),
                             "statuses": statuses(a), "Q1": a["Q1"].get("letter", a["Q1"]),
                             "K1": findings_for([x for x in check(e12) if x["check"] == "K1"]),
                             "why": a["Q1"].get("why")}

    (out_dir / "observations.json").write_text(json.dumps(obs, indent=1, ensure_ascii=False))
    print(f"wrote {out_dir / 'observations.json'}")
    print(f"freezes: {obs['freezes']}")


if __name__ == "__main__":
    main()
