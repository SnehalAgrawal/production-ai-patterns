"""
Run every scenario with all safeguards on, a negative control (nothing removed), and the ablation (each
safeguard removed on its own). Writes results/observations-run<N>.json and results/report-run<N>.txt.

  python run.py --run 1

No model, no network, no randomness: the clock is fake, so repeated runs must be byte-identical.
"""
import argparse
import hashlib
import json
from pathlib import Path

from desk import SAFEGUARDS
from scenarios import SCENARIOS, env, refund, run

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
FROZEN = ["PROTOCOL.md", "PROTOCOL-ADDENDUM.md", "PROTOCOL-ADDENDUM-2.md", "PROTOCOL-ADDENDUM-3.md", "data/accounts.json", "data/directory.json", "data/policy.json",
          "python/billing.py", "python/desk.py", "python/scenarios.py", "python/run.py", "python/test_desk.py"]

GID = {g: f"G{i}" for i, g in enumerate(SAFEGUARDS, start=1)}

# From PROTOCOL.md ("Ablation: predictions") as amended by PROTOCOL-ADDENDUM.md, -2 and -3.
# Unlisted cells: predicted unchanged.
PREDICTED = {"G1": ["R05"], "G2": ["R06"], "G3": ["R07"], "G4": ["R08", "R24", "R25", "R27"],
             "G5": ["R09", "R23", "R24", "R25", "R27", "R28", "R32", "R34"], "G6": ["R10", "R33"], "G7": ["R11"],
             "G8": ["R11", "R12"], "G9": ["R13", "R23", "R32"], "G10": ["R14", "R22", "R31"], "G11": ["R15"],
             "G12": ["R16"], "G13": ["R17", "R35"], "G14": ["R18", "R28"],
             "G15": ["R19", "R23", "R24", "R25", "R26", "R27", "R29", "R30", "R31", "R32", "R33", "R34"],
             "G16": ["R20", "R26", "R30"]}


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_status() -> tuple[bool, list[str]]:
    frozen = RESULTS / "freeze.json"
    if not frozen.exists():
        return False, ["no results/freeze.json"]
    recorded = json.loads(frozen.read_text())["sha256"]
    bad = [f for f in FROZEN if recorded.get(f) != file_sha(ROOT / f)]
    return not bad, bad


def money(o: dict) -> list:
    return o["money"]["refunds"] + [["credit", c[0], c[1], c[2]] for c in o["money"]["credits"]]


def _minus(a: list, b: list) -> list:
    """Multiset difference: two identical refunds are two refunds."""
    rest = [json.dumps(x) for x in b]
    out = []
    for x in a:
        k = json.dumps(x)
        if k in rest:
            rest.remove(k)
        else:
            out.append(x)
    return out


def classify(base: dict, new: dict) -> list[str]:
    """What changed: money, messages, review load and statuses, gold labels."""
    kinds = []
    added, missing = _minus(money(new), money(base)), _minus(money(base), money(new))
    if added:
        kinds.append("money moved: " + "; ".join(_fmt_money(m) for m in added))
    if missing:
        kinds.append("money not moved: " + "; ".join(_fmt_money(m) for m in missing))
    sent, unsent = _minus(new["messages"], base["messages"]), _minus(base["messages"], new["messages"])
    kinds += [f'message sent: "{m}"' for m in sent] + [f'message not sent: "{m}"' for m in unsent]
    kinds += [f"notified {n[1]}: {n[2]}" for n in _minus(new["notifications"], base["notifications"])]
    if len(new["items"]) != len(base["items"]) or len(new["decisions"]) != len(base["decisions"]):
        kinds.append(f"review load: {len(new['items'])} items, {len(new['decisions'])} decisions"
                     f" (all-on: {len(base['items'])}, {len(base['decisions'])})")
    st = lambda o: [f"{i['id']} {i['status']} v{i['version']}" for i in o["items"]]  # noqa: E731
    if st(new) != st(base):
        kinds.append(f"status: {', '.join(st(new))} (all-on: {', '.join(st(base))})")
    gold = lambda o: [r for r in o["labels"] if r["kind"] == "gold"]  # noqa: E731
    if gold(new) != gold(base):
        kinds.append("gold labels: " + "; ".join(f"{r['item']} {r['value']} ({r['source']})" for r in gold(new)))
    return kinds or ["other: " + ", ".join(k for k in new if new[k] != base[k])]


def _fmt_money(m) -> str:
    if m[0] == "credit":
        who = ", ".join(m[3]) if m[3] else "automatic"
        return f"${m[2]:.2f} credit to {m[1]} (approved by: {who})"
    who = ", ".join(m[2]) if m[2] else "no approval"
    return f"${m[1]:.2f} refund on {m[0]} (approved by: {who})"


def scenario_line(sid: str, o: dict) -> list[str]:
    lines = []
    items = ", ".join(f"{i['id']} {i['tier']} -> {i['status']}" + (f" (v{i['version']})" if i["version"] > 1 else "")
                      + (" escalated" if i["escalated"] else "") for i in o["items"]) or "no review item"
    lines.append(f"{sid}  {items}")
    refused = [f"{d[2]} {d[3]} refused ({d[5]})" for d in o["decisions"] if not d[4]]
    accepted = [f"{d[2]} {d[3]}" for d in o["decisions"] if d[4]]
    if accepted or refused:
        lines.append("     decisions: " + "; ".join(accepted + refused))
    lines.append("     money: " + ("; ".join(_fmt_money(m) for m in money(o)) or "none"))
    for m in o["messages"]:
        lines.append(f'     sent: "{m}"')
    for n in o["notifications"]:
        lines.append(f"     notified {n[1]}: {n[2]}")
    if o["seeded"]["seeded_decided"]:
        s = o["seeded"]
        lines.append(f"     seeded cases: {s['caught']} of {s['should_reject']} that should be rejected were caught")
    return lines


def screen(view: dict) -> list[str]:
    a = view["action"]
    action = f"{a['tool']}(invoice_id={a['invoice_id']!r}, amount={a['amount']:.2f})" if "invoice_id" in a \
        else f"{a['tool']}(text={a['text']!r})"
    ev = view["evidence"]
    lines = [f"{view['item_id']} v{view['version']}  {view['tier']}  may decide: {', '.join(view['may_decide'])}"
             f"  approvals needed: {view['approvals_needed']}  expires {view['expires_at']}",
             f"  customer said:  {view['customer_message']!r}",
             f"  action:         {action}",
             f"  requested by:   {view['requested_by']}",
             "  records (billing):"]
    lines += [f"    {c['id']}  {c['date']}  ${c['amount']}  {c['invoice']}" for c in ev["charges"]]
    lines.append(f"    refunded: {ev['refunded']}   credited: {ev['credited']}")
    lines.append(f"    open disputes: {ev['open_disputes'] or 'none'}")
    lines.append(f"  claims:         {view['claims'] or 'none'}")
    lines.append(f"  action_sha256   {view['action_sha'][:16]}...   evidence_sha256 {view['evidence_sha'][:16]}...")
    return lines


def walkthrough() -> list[str]:
    """R10 step by step, to show what the reviewer saw, what changed, and what the desk did."""
    d = env()
    s = d.submit(refund("INV-1002", 25, claims={"duplicate_charge": True}, reason="duplicate charge PAY-5006",
                        message="I was charged twice for my October invoice. Please refund the extra charge."))
    v1 = d.view(s["item_id"])
    out = ["The screen ana approved from:"] + screen(v1)
    d.decide(s["item_id"], "ana", "approve", v1)
    d.clock.advance(minutes=5)
    d.billing.open_dispute("PAY-5006", "duplicate charge, raised with the customer's bank")
    result = d.execute(s["item_id"], "worker-1")
    out.append(f"Executor, 5 minutes later, after a chargeback was opened: {result['refusal']}")
    out += [f"  {c}" for c in result["changes"]]
    out.append("The item back in the queue:")
    out += screen(d.view(s["item_id"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, required=True)
    args = ap.parse_args()

    ok, bad = freeze_status()
    base = {sid: run(sid) for sid in SCENARIOS}
    control = {sid: run(sid) for sid in SCENARIOS}
    ablation = {}
    for g in SAFEGUARDS:
        without = [s for s in SAFEGUARDS if s != g]
        ablation[GID[g]] = {sid: run(sid, without) for sid in SCENARIOS}

    observations = {"baseline": base, "negative_control": control, "ablation": ablation}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"observations-run{args.run}.json").write_text(json.dumps(observations, indent=1, sort_keys=True) + "\n")

    r = [f"Review desk, run {args.run}. Freeze: matches={ok}" + ("" if ok else f" (differs: {', '.join(bad)})"), ""]
    r += ["== All safeguards on", ""]
    for sid, o in base.items():
        r += scenario_line(sid, o)
    r += ["", "R19 labels exported:"] + [f"  {json.dumps(x, sort_keys=True)}" for x in base["R19"]["labels"]]
    r += ["", "== Walkthrough: R10, evidence changed after approval", ""] + walkthrough()

    same = all(control[s] == base[s] for s in SCENARIOS)
    r += ["", f"== Determinism check (the all-on run repeated): {'identical in every scenario' if same else 'DIFFERS'}"]

    r += ["", "== Ablation: one safeguard off, everything else on", ""]
    summary = []
    for g in SAFEGUARDS:
        gid = GID[g]
        changed = [sid for sid in SCENARIOS if ablation[gid][sid] != base[sid]]
        predicted = PREDICTED[gid]
        held = all(p in changed for p in predicted)
        extra = [c for c in changed if c not in predicted]
        summary.append((gid, g, changed, held, extra))
        r.append(f"{gid} {g} off: changed {', '.join(changed) or 'nothing'}"
                 f"   predicted to change {', '.join(predicted)}: {'all changed' if held else 'NOT ALL CHANGED'}"
                 + (f"   unpredicted: {', '.join(extra)}" if extra else ""))
        for sid in changed:
            for k in classify(base[sid], ablation[gid][sid]):
                r.append(f"    {sid}: {k}")
    r += ["", "== Summary (whether each predicted scenario changed; read the harm in the differences above)", ""]
    r += [f"{gid:<4} {g:<26} predicted {'changed' if held else 'NOT ALL':<8} changed {len(changed):>2}"
          + (f"  (unpredicted: {', '.join(extra)})" if extra else "") for gid, g, changed, held, extra in summary]
    (RESULTS / f"report-run{args.run}.txt").write_text("\n".join(r) + "\n")
    print("\n".join(r))


if __name__ == "__main__":
    main()
