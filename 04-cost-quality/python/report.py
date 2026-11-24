"""
The report: every number the README and Article #36 use, from data/runs.json, the labels and data/prices.json.

  python report.py                  with data/final_labels.json (verified by a person), or else the blind labels,
                                    marked UNVERIFIED on every labelled line
  python report.py --labels blind   with data/blind_labels.json, even when verified labels exist
  python report.py --no-labels      mechanics and spend only: everything that doesn't need a label

Writes runs/report.txt and runs/cases.jsonl (git-ignored) and prints the report.
"""
import argparse
import json
import sys

import analysis
from shared import BLIND, EVALUATION, EXPORT, FINAL, PRICES, RUNS, rel, source_module


def load_labels(choice: str) -> tuple[dict, str]:
    if choice == "none":
        return {}, "none"
    if choice == "final" or (choice == "auto" and FINAL.exists()):
        if not FINAL.exists():
            sys.exit(f"{rel(FINAL)} doesn't exist yet (verify.py import writes it)")
        document = json.loads(FINAL.read_text())
        return document["labels"], f"verified: {document['labeller']}; verified by {document['verifier']}"
    if not BLIND.exists():
        sys.exit(f"{rel(BLIND)} doesn't exist yet; run with --no-labels, or label first (labels.py)")
    document = json.loads(BLIND.read_text())
    return document["labels"], f"UNVERIFIED blind labels: {document['labeller']}"


def money(x: float | None, digits: int = 5) -> str:
    return "n/a" if x is None else f"${x:.{digits}f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--labels", choices=["final", "blind"], default="auto")
    group.add_argument("--no-labels", action="store_true")
    args = parser.parse_args()
    choice = "none" if args.no_labels else args.labels

    runs_doc = json.loads(EXPORT.read_text())["runs"]
    prices = json.loads(PRICES.read_text())
    runs = {name: r["emails"] for name, r in runs_doc.items()}
    records = {v: runs[v] for v in analysis.LABELLED}
    records["v4"] = analysis.compose_v4(runs["b0"], runs["v3"])
    label_for, label_source = load_labels(choice)
    qs = analysis.questions()
    outcomes = {v: {e: analysis.outcome(e, r, label_for, qs) for e, r in recs.items()} for v, recs in records.items()}
    summary = {v: analysis.summarize(records[v], outcomes[v], prices) for v in analysis.VARIANTS}
    cap = runs_doc["v2"]["record"]["overrides"]["chat"]["draft_max_tokens"]
    replies_b = EVALUATION / "data" / "replies-b.json"
    v3a = json.loads(replies_b.read_text())["runs"]["v3a"]["emails"] if replies_b.exists() else None
    checks = analysis.expectations(runs, cap, v3a)

    out = []
    p = out.append
    p("Article #36, 04-cost-quality: report")
    p(f"labels: {label_source}")
    p(f"prices: checked {prices['checked']}; HYPOTHETICAL (local token counts x published rates)\n")

    p("RUNS")
    for name, r in runs_doc.items():
        rec = r["record"]
        p(f"  {name:6} {rec['split']:4} models {rec['models']} overrides {rec['overrides'] or '-'} calls {rec['model_calls']} "
          f"status {rec['status']} isolated {rec['server_log']['isolated']} ({rec['server_log']['chat_lines']} chat lines) "
          f"{rec['started_utc']}")
    p("")

    p("WHAT EACH VERSION DID (20 test emails)")
    header = f"  {'':4} {'calls':>5} {'extract in':>10} {'extract out':>11} {'draft in':>8} {'draft out':>9} {'cut off':>7} " \
             f"{'no reply':>8} {'check pass':>10} {'escalated':>9}  fact check"
    p(header)
    for v in analysis.VARIANTS:
        s = summary[v]
        t = s["tokens"]
        p(f"  {v:4} {s['calls']:>5} {t.get('extract_prompt', 0):>10} {t.get('extract_output', 0):>11} "
          f"{t.get('draft_prompt', 0):>8} {t.get('draft_output', 0):>9} {s['truncated']:>7} {s['no_reply']:>8} "
          f"{s['draft_check_pass']:>10} {s['escalated']:>9}  {s['fact_check']}")
    p("  calls by model: " + "; ".join(f"{v} {summary[v]['calls_by_model']}" for v in analysis.VARIANTS))
    p("")

    if choice != "none":
        tag = "" if label_source.startswith("verified") else "  [UNVERIFIED]"
        p(f"OUTCOMES (labelled){tag}")
        p(f"  {'':4} {'correct':>7} {'failures':>8} {'false answers (of 3)':>21} {'false statements':>16}")
        for v in analysis.VARIANTS:
            s = summary[v]
            p(f"  {v:4} {s['correct']!s:>7} {s['failures']!s:>8} {s['false_answers']!s:>21} {s['false_statements']!s:>16}")
        p("")
        table = analysis.per_email(outcomes)
        emails = sorted(table["b0"])
        p(f"PER EMAIL{tag}  (C correct, W wrong, - no reply)")
        p("  " + " ".join(f"{e:>4}" for e in ["", *emails]))
        for v in analysis.VARIANTS:
            row = [{"correct": "C", "wrong": "W", analysis.NO_REPLY: "-"}[table[v][e]] for e in emails]
            p(f"  {v:>4} " + " ".join(f"{c:>4}" for c in row))
        p("")
        p(f"AGAINST b0, EMAIL BY EMAIL{tag}")
        compare = source_module("compare")
        slice_of = {e: compare.slices(qs[e]["questions"]) for e in emails}
        decisions = {}
        for v in analysis.VARIANTS[1:]:
            pairs = analysis.paired(table["b0"], table[v])
            decisions[v] = analysis.decision(summary["b0"], summary[v], pairs)
            p(f"  {v}: fixed {pairs['fixed'] or '-'}, broken {pairs['broken'] or '-'}, both correct {len(pairs['both_correct'])}, "
              f"both wrong {len(pairs['both_wrong'])}")
            binary = {k: {e: ("correct" if o == "correct" else "wrong") for e, o in table[k].items()} for k in ("b0", v)}
            uncovered = compare.by_slice(emails, slice_of, binary["b0"], binary[v])["uncovered question"]
            p(f"      slice 'uncovered question' (emails, b0 correct, {v} correct): {uncovered}")
            p(f"      decision rule: {'ADOPT' if decisions[v]['adopt'] else 'REJECT'}"
              + (f" ({'; '.join(decisions[v]['reasons'])})" if decisions[v]["reasons"] else ""))
        p("")

    p("SPEND, HYPOTHETICAL (per 20 emails; inference + query embeddings)")
    for scenario, sc in prices["scenarios"].items():
        p(f"  {scenario}: {sc['roles']}")
        for v in analysis.VARIANTS:
            s = summary[v]["spend"][scenario]
            line = (f"    {v:4} inference {money(s['inference'])} embeddings {money(s['other_metered'], 7)} total "
                    f"{money(s['total'])} per email {money(s['per_email'], 6)}")
            if choice != "none":
                line += f" per correct email {money(s['per_success'], 6)}"
            p(line)
        if choice != "none":
            base = summary["b0"]
            for v in analysis.VARIANTS[1:]:
                b = analysis.cost.break_even(base["spend"][scenario]["total"], base["failures"],
                                             summary[v]["spend"][scenario]["total"], summary[v]["failures"])
                threshold = "" if b["threshold_per_failure"] is None else f", break-even {money(b['threshold_per_failure'], 6)} per failed email"
                p(f"    {v} vs b0: saves {money(b['saved'])}, extra failures {b['extra_failures']}: {b['verdict']}{threshold}")
    p("  not measured here: fixed infrastructure and observability; labelling and human verification; downstream "
      "handling of failures (a parameter: see the break-even)")
    p("")

    v4 = records["v4"]
    escalated = [e for e, r in v4.items() if r["escalated"]]
    p(f"V4 (assembled from b0 and v3): escalated {len(escalated)}: {escalated or '-'}")
    if choice != "none":
        wrong_kept = [e for e, o in outcomes["v3"].items() if o["outcome"] == "wrong" and e not in escalated]
        p(f"  v3 replies labelled wrong that 01's draft check passed (kept, not escalated): {wrong_kept or '-'}")
    p("")

    p("EXPECTATIONS (PROTOCOL.md)")
    for name, e in checks.items():
        p(f"  {name}: {'held' if e['held'] else 'did not hold' if e['held'] is False else 'not evaluated'}: {json.dumps(e['detail'])}")
    if choice != "none":
        e7 = summary["v3"]["correct"] < summary["b0"]["correct"]
        p(f"  E7: {'held' if e7 else 'did not hold'}: correct b0 {summary['b0']['correct']}, v3 {summary['v3']['correct']}")
        wrong = [e for e, o in outcomes["v3"].items() if o["outcome"] == "wrong"]
        caught = [e for e in wrong if runs["v3"][e]["draft_check"] != []]
        e8 = 2 * len(caught) < len(wrong) if wrong else None
        p(f"  E8: {'held' if e8 else 'did not hold' if e8 is False else 'not evaluated'}: v3 replies labelled wrong {len(wrong)}, "
          f"failing 01's draft check (escalated) {len(caught)}")

    text = "\n".join(out) + "\n"
    RUNS.mkdir(exist_ok=True)
    (RUNS / "report.txt").write_text(text)
    with open(RUNS / "cases.jsonl", "w") as f:
        for v in analysis.VARIANTS:
            for e, r in records[v].items():
                f.write(json.dumps({"variant": v, "email": e, "outcome": outcomes[v][e]["outcome"], "key": r["key"],
                                    "status": r["status"], "draft_check": r["draft_check"],
                                    "escalated": r.get("escalated", False), "calls": r["calls"],
                                    "labels": label_source}) + "\n")
    print(text)


if __name__ == "__main__":
    main()
