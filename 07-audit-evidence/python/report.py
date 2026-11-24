"""Check a run against PROTOCOL.md's expectations.

    python report.py                      # the latest run in runs/
    python report.py runs/<stamp>         # a given run
    python report.py --negative-control   # two expectations changed on purpose: must report them and exit 1

Prints one line per check (PASS or FAIL), then E10's timings. The stable section (everything
but timings) ends with its SHA-256, which compare.py uses across repeat runs. Exit 1 if any
check fails.
"""

import hashlib
import json
import sys
from pathlib import Path

from common import DEMO

ALL = ["Q1", "Q2.policy", "Q2.account_snapshot", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9"]
EXECUTED = [f"D-C{i:02d}" for i in (1, 2, 3, 4, 5, 7, 8, 9, 10, 11)]
M1 = "f83e1fdc45e070e2f7d56a4d772645e46cbdc83cc7e8d83c61d6ce2fd26d9d6a"
M2 = "9cc4c56ed883fe014c02c807d9223a6bb579facb9518980ff640ca0e6a437de0"


def checks(o: dict, negative: bool) -> list[tuple[str, str, bool, object]]:
    out = []

    def c(cid, text, ok, seen=""):
        out.append((cid, text, bool(ok), seen))

    def kinds(findings, check, decision=None):
        return [f for f in findings if f[0] == check and (decision is None or f[1] == decision)]

    c("F", "inputs and code unchanged since the freezes", all(v == "ok" for v in o["freezes"].values()), o["freezes"])

    b = o["B"]
    c("B.1", "deploy gate admits assistant-2026.11.1 with manifest f83e1fdc...",
      [a["manifest_sha256"] for a in b["activated"]] == [M1], [a["manifest_sha256"][:8] for a in b["activated"]])
    c("B.2", "12 decisions", len(b["decisions"]) == 12, len(b["decisions"]))
    c("B.3", "10 executed: C01-C05, C07-C11", b["executed"] == EXECUTED, b["executed"])
    c("B.4", "no action for C06 and C12", b["no_action"] == ["D-C06", "D-C12"], b["no_action"])
    c("B.5", "10 ledger entries", b["ledger_entries"] == 10, b["ledger_entries"])
    leads = sorted(d for d, r in b["routed"].items() if r == "hardship-lead")
    c("B.6", "C05 and C10 routed to a lead, the other 10 to an agent",
      leads == ["D-C05", "D-C10"] and len(b["routed"]) == 12, leads)
    c("B.7", "only C12's surplus_below_threshold check fails",
      b["failed_checks"] == {"D-C12": ["surplus_below_threshold"]}, b["failed_checks"])
    c("B.8", "the checker reports 0 findings on the baseline", b["findings"] == [], b["findings"])

    e1 = o["E1"]
    for d in ("D-C01", "D-C04"):
        c(f"E1.{d}", f"{d}: all nine questions answered from the records",
          all(e1[d]["statuses"].get(q) == "answered" for q in ALL), e1[d]["statuses"])
    c("E1.Q3", "Q3 shows requested and returned model strings and 'no version metadata returned'",
      all(call["model_requested"] == "lender-recommender" and call["model_returned"] == "lender-recommender-2026-10-01"
          and call["version_metadata"] == "no version metadata returned" for d in e1 for call in e1[d]["Q3_calls"]))
    d4 = e1["D-C04"]
    c("E1.C04", "D-C04: recommended 35.00, decided modify to 20.00, executed 20.00",
      d4["Q4"] == {"action": "fee_waiver", "amount": 35.0} and d4["Q6"]["decision"] == "modify"
      and d4["Q6"]["approved_action"] == {"action": "fee_waiver", "amount": 20.0}
      and d4["Q7"]["executed"] == {"action": "fee_waiver", "amount": 20.0},
      [d4["Q4"], d4["Q6"]["decision"], d4["Q6"]["approved_action"], d4["Q7"]["executed"]])
    c("E1.C04.Q7", "D-C04 Q7: matches the approval, differs from the recommendation by a recorded modification",
      d4["Q7"]["matches_approval"] and not d4["Q7"]["matches_recommendation"] and d4["Q7"]["modification_recorded"],
      {k: d4["Q7"][k] for k in ("matches_approval", "matches_recommendation", "modification_recorded")})

    e = o["E2a"]
    c("E2a.1", "deploy gate refuses the edited prompt", e["refused"] is not None, e["refused"])
    c("E2a.2", "the diff names exactly recommendation_prompt",
      [r["changed_components"] for r in e["refusal_events"]] == [["recommendation_prompt"]],
      [r["changed_components"] for r in e["refusal_events"]])
    c("E2a.3", "no decision made under it", e["decisions"] == 0 and e["process_refused"] is not None, e["decisions"])

    e = o["E2b"]
    c("E2b.1", "both new decisions execute normally", e["executed"] == ["D-E2-1", "D-E2-2"], e["executed"])
    k6 = sorted({f[1] for f in e["findings"] if f[0] == "K6"})
    c("E2b.2", "K6 flags exactly D-E2-1 and D-E2-2, none of the baseline",
      k6 == ["D-E2-1", "D-E2-2"] and all(f[0] == "K6" for f in e["findings"]), k6)

    e = o["E3"]
    c("E3a.1", "executor refuses 50.00 against an approval of 35.00", e["a_refused"] is not None, e["a_refused"])
    c("E3a.2", "ledger unchanged", e["a_ledger_before"] == e["a_ledger_after"], [e["a_ledger_before"], e["a_ledger_after"]])
    c("E3a.3", "the refusal is in the audit log", len(e["a_refusal_logged"]) == 1, e["a_refusal_logged"])
    c("E3b", "K3 flags the forced 50.00 execution",
      any("differs from the approved" in f[2] for f in kinds(e["b_findings"], "K3")), e["b_findings"])
    c("E3c.1", "baseline D-C04 (modify) not flagged by K7", e["c_baseline_K7"] == [], e["c_baseline_K7"])
    c("E3c.2", "forced execution differing from the recommendation after 'approve': K7 and K3 flag it",
      kinds(e["c_forced_findings"], "K7") and kinds(e["c_forced_findings"], "K3"), e["c_forced_findings"])

    e = o["E4"]
    c("E4.1", "deploy gate admits assistant-2026.11.2 with manifest 9cc4c56e...",
      e["activated"]["manifest_sha256"] == M2, e["activated"]["manifest_sha256"][:8])
    c("E4.2", "execution refused as stale", e["stale_refused"] and e["stale_refused"].startswith("stale"), e["stale_refused"])
    c("E4.3", "a new approval by S-103 refused: agent limit 40.00 under v15",
      e["reapproval_refused"] and "40.00" in e["reapproval_refused"], e["reapproval_refused"])
    c("E4.4", "K3 flags the forced execution of the stale approval",
      any(f[2].startswith("stale") for f in kinds(e["forced_findings"], "K3")), e["forced_findings"])

    e = o["E5"]
    c("E5a", "S-104 approving their own exception is refused",
      e["a_refused"] and "separation of duties" in e["a_refused"], e["a_refused"])
    c("E5b", "S-101 (agent) approving 120.00 is refused", e["b_refused"] and "role limit" in e["b_refused"], e["b_refused"])
    f = e["forced_findings"]
    c("E5c", "K3 flags the forced records: separation of duties (D-E5a) and role limit (D-E5b)",
      any("separation of duties" in x[2] for x in kinds(f, "K3", "D-E5a"))
      and any("role limit" in x[2] for x in kinds(f, "K3", "D-E5b")), f)

    e = o["E6"]
    c("E6a", "K3 flags an execution with no decision", any("no approval" in f[2] for f in e["a_findings"]), e["a_findings"])
    c("E6b", "K5 flags a ledger entry with no audit event", kinds(e["b_findings"], "K5"), e["b_findings"])
    c("E6n", "negative control: with K5 off, nothing reported for (b)", e["b_findings_without_K5"] == [],
      e["b_findings_without_K5"])

    e = o["E7"]
    c("E7a", "K1 broken at the edited event",
      [f[2] for f in e["a_findings"]] == [f"chain broken at event {e['a_edited_seq']}"], e["a_findings"])
    c("E7b", "K1 broken at the event after the deleted one",
      [f[2] for f in e["b_findings"]] == [f"chain broken at event {e['b_deleted_seq'] + 1}"], e["b_findings"])
    k1_c = kinds(e["c_findings"], "K1")
    c("E7c.1", "truncation: K1 verifies" if not negative else "truncation: K1 fails (negative control)",
      (k1_c == []) if not negative else (k1_c != []), k1_c)
    c("E7c.2", "truncation: K2 flags the log as shorter than the anchor",
      any("ends before" in f[2] for f in kinds(e["c_findings"], "K2")), kinds(e["c_findings"], "K2"))
    c("E7c.3", "truncation: K8 flags D-C12 as incomplete", kinds(e["c_findings"], "K8", "D-C12"), kinds(e["c_findings"], "K8"))

    e = o["E8"]
    c("E8.1", "full rewrite: K1 verifies", kinds(e["findings"], "K1") == [], kinds(e["findings"], "K1"))
    c("E8.2", "full rewrite: K2 flags a head-hash mismatch",
      any("differs from the anchored head" in f[2] for f in kinds(e["findings"], "K2")), kinds(e["findings"], "K2"))
    c("E8.3", "full rewrite with K2 off: nothing reported", e["findings_without_K2"] == [], e["findings_without_K2"])

    e = o["E9"]
    stores = set(e["canary_stores"])
    if not negative:
        c("E9.1", "the canary is in the content store and outbound.jsonl", {"content", "outbound.jsonl"} <= stores,
          e["canary_stores"])
    else:
        c("E9.1", "the canary is absent from outbound.jsonl (negative control)", "outbound.jsonl" not in stores,
          e["canary_stores"])
    c("E9.2", "the canary is in no other store", stores <= {"content", "outbound.jsonl"}, e["canary_stores"])
    banned = {"audit.jsonl", "app.log", "traces.jsonl", "ledger.jsonl", "anchor/anchors.jsonl"}
    c("E9.3", "the canary is in none of the audit log, app log, traces, ledger, anchors", not (stores & banned),
      sorted(stores & banned))
    c("E9.4", "the canary is in no recommendation prompt", e["canary_in_recommendation_prompts"] == [],
      e["canary_in_recommendation_prompts"])
    c("E9.5", "no borrower name outside the content store",
      all(set(v) <= {"content"} for v in e["names_found"].values()), e["names_found"])
    c("E9.6", "negative control: a logger writing prompts puts the canary in app.log",
      "app.log" in e["negative_control_stores"], e["negative_control_stores"])

    e = o["E10"]
    c("E10.1", "plain SHA-256 recovered after 398,842 attempts",
      e["plain"]["recovered"] and e["plain"]["attempts"] == 398842, e["plain"]["attempts"])
    c("E10.2", "HMAC: whoever holds the key recovers it the same way",
      e["keyed_with_key"]["recovered"] and e["keyed_with_key"]["attempts"] == 398842, e["keyed_with_key"]["attempts"])
    c("E10.3", "HMAC with a different random key: 0 matches in 1,000,000",
      e["keyed_other_key"]["matches"] == 0 and e["space"] == 1_000_000, e["keyed_other_key"]["matches"])

    e = o["E11"]
    c("E11.1", "before: B-1003 has items in content, keys, outbound, eval_cases",
      all(v > 0 for v in e["before"].values()) and set(e["before"]) == {"content", "keys", "outbound", "eval_cases"},
      e["before"])
    c("E11.2", "after: none in any of them", all(v == 0 for v in e["after"].values()), e["after"])
    c("E11.3", "one erased event; K1 verifies", len(e["erased_events"]) == 1 and e["K1"] == [],
      [len(e["erased_events"]), e["K1"]])
    c("E11.4", "D-C03 Q1 and the snapshot: content erased, 2026-11-20, ER-0001",
      all(x["status"] == "content erased" and x["request"] == "ER-0001" and x["when"].startswith("2026-11-20")
          for x in (e["Q1"], e["Q2_snapshot"])), [e["Q1"], e["Q2_snapshot"]])
    c("E11.5", "D-C03 policy version and Q3-Q9 answered",
      all(e["statuses"][q] == "answered" for q in ALL if q not in ("Q1", "Q2.account_snapshot")), e["statuses"])
    c("E11.6", "negative control: the phrase is found in cache.jsonl, and only there",
      e["negative_control_stores"] == ["cache.jsonl"], e["negative_control_stores"])

    e = o["E12"]
    d0, d31, d366, d731 = e["day0"], e["day31"], e["day366"], e["day731"]
    c("E12.0", "day 0: nothing purged; nine answered",
      d0["purged"] == [] and all(d0["statuses"][q] == "answered" for q in ALL), d0["purged"])
    c("E12.31", "2026-12-04: all traces and outbound requests purged; nine answered",
      {p["store"] for p in d31["purged"]} == {"traces", "outbound"} and d31["traces_left"] == 0
      and d31["outbound_left"] == 0 and all(d31["statuses"][q] == "answered" for q in ALL), d31["purged"])
    retained = [q for q in ALL if d366["statuses"][q] != "answered"]
    c("E12.366a", "2027-11-04: content, keys and eval_cases purged",
      {p["store"] for p in d366["purged"]} == {"content", "eval_cases"} and d366["keys_left"] == 0,
      [d366["purged"], d366["keys_left"]])
    c("E12.366b", "2027-11-04: Q1 and the snapshot 'content deleted by retention' (rule, date); the rest answered; K1 verifies",
      retained == ["Q1", "Q2.account_snapshot"] and d366["Q1"].get("rule") == "content-365d"
      and d366["Q1"]["status"] == "content deleted by retention" and d366["K1"] == [], [retained, d366["Q1"]])
    c("E12.731", "2028-11-03: audit purged; D-C01 not answerable; the purge-log entry is named",
      [p["store"] for p in d731["purged"]] == ["audit"] and all(v == "not answerable" for v in d731["statuses"].values())
      and "audit-730d" in (d731["why"] or ""), d731["why"])
    return out


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    negative = "--negative-control" in sys.argv
    runs = DEMO / "runs"
    run = Path(args[0]) if args else sorted(p for p in runs.iterdir() if p.is_dir())[-1]
    o = json.loads((run / "observations.json").read_text())
    results = checks(o, negative)
    lines = [f"Report for run {run.name}" + (" (NEGATIVE CONTROL)" if negative else "")]
    stable = []
    for cid, text, ok, seen in results:
        line = f"{'PASS' if ok else 'FAIL'} {cid}: {text}" + ("" if ok else f"  | observed: {seen}")
        stable.append(line)
    failed = [r for r in results if not r[2]]
    stable.append(f"{len(results) - len(failed)} of {len(results)} checks passed")
    digest = hashlib.sha256("\n".join(stable).encode()).hexdigest()
    e10 = o["E10"]
    timing = ["", "E10 timings (measured; not part of the stable section):",
              f"  plain SHA-256, 398,842 candidates: {e10['plain']['seconds']:.3f} s",
              f"  HMAC with the key, 398,842 candidates: {e10['keyed_with_key']['seconds']:.3f} s",
              f"  HMAC with another key, 1,000,000 candidates: {e10['keyed_other_key']['seconds']:.3f} s",
              f"  setup: Python {o['setup']['python']}, {o['setup']['platform']}, "
              f"load average {o['setup']['load_average_1m']} at the start"]
    print("\n".join(lines + stable + [f"stable section SHA-256: {digest}"] + timing))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
