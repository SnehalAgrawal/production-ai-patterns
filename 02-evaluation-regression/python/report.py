"""
Part A: the grader against a person's labels, and the two arms compared case by case. No model calls.

  python report.py --controls          checks and controls only; prints no grader verdict and no label
  python report.py --labels blind      the report, against the blind labels (data/blind_labels.json)
  python report.py --labels original   the report, against 01's hand labels

Both reports refuse to run until data/blind_labels.json exists (PROTOCOL.md: the report runs only after the
blind labels are written, so the labeller can't have seen any result). Every run first runs check.py's checks.
Reports and per-case records are written to runs/ (git-ignored).
"""
import argparse
import json
import platform
import sys

import compare
import grade
from check import run_all
from common import ARMS, BASELINE, CANDIDATE, DATA, RUNS, load_replies, scorer, sha256_file, test_emails

BLIND = DATA / "blind_labels.json"


def outcomes_original(sc, entries: list[dict]) -> dict[tuple[str, str], dict]:
    result = {}
    for e in entries:
        if e["reply"] is None:
            result[(e["arm"], e["email"])] = {"outcome": compare.WRONG, "label": None}
            continue
        verdict = sc.verdict(e["email"], e["reply"])
        if verdict is None:
            raise ValueError(f"{e['arm']} {e['email']}: no original hand label for this reply")
        result[(e["arm"], e["email"])] = {"outcome": verdict, "label": verdict}
    return result


def outcomes_blind(sc, entries: list[dict], labels: dict) -> dict[tuple[str, str], dict]:
    result = {}
    for e in entries:
        if e["reply"] is None:
            result[(e["arm"], e["email"])] = {"outcome": compare.WRONG, "label": None}
            continue
        if e["key"] not in labels:
            raise ValueError(f"{e['arm']} {e['email']}: no blind label for reply {e['key']}")
        scored = compare.blind_outcome(sc.questions(e["email"]), labels[e["key"]])
        result[(e["arm"], e["email"])] = {**scored, "label": scored["outcome"]}
    return result


def agreement(sc, entries: list[dict], labels: dict) -> dict[tuple[str, str], int]:
    """Blind outcome against 01's original verdict, per reply that has both: counts in both directions."""
    counts = {(o, b): 0 for o in (compare.CORRECT, compare.WRONG) for b in (compare.CORRECT, compare.WRONG)}
    for e in entries:
        if e["reply"] is None:
            continue
        original = sc.verdict(e["email"], e["reply"])
        blind = compare.blind_outcome(sc.questions(e["email"]), labels[e["key"]])["outcome"]
        counts[(original, blind)] += 1
    return counts


def controls(sc, entries: list[dict], emails: list[str]) -> list[str]:
    """Controls that must hold whatever the labels say. They print counts only, never a verdict or a label."""
    lines, failures = [], []
    first = [grade.grade(sc, e["email"], e["reply"]) for e in entries]
    second = [grade.grade(sc, e["email"], e["reply"]) for e in entries]
    same = sum(a == b for a, b in zip(first, second))
    lines.append(f"grader run twice: identical records for {same} of {len(entries)} entries")
    if same != len(entries):
        failures.append("the grader is not deterministic")

    original = outcomes_original(sc, entries)
    base = {eid: original[(BASELINE, eid)]["outcome"] for eid in emails}
    itself = compare.paired(base, dict(base))
    flips = len(itself["fixed"]) + len(itself["broken"])
    lines.append(f"baseline compared with itself: {flips} flips (expected 0)")
    if flips:
        failures.append("the self-comparison produced flips")

    altered = dict(base)
    eid = sorted(altered)[0]
    altered[eid] = compare.CORRECT if altered[eid] == compare.WRONG else compare.WRONG
    changed = compare.paired(base, altered)
    flips = len(changed["fixed"]) + len(changed["broken"])
    lines.append(f"baseline compared with a copy with one outcome altered: {flips} flip (expected 1)")
    if flips != 1:
        failures.append("the comparison missed a deliberately altered outcome")
    return lines + [f"CONTROL FAILED: {f}" for f in failures]


def report(sc, entries: list[dict], emails: list[str], source: str, blind: dict) -> tuple[list[str], list[dict]]:
    """The Part A report against one label source. 'blind' is the labels mapping of data/blind_labels.json."""
    outcomes = outcomes_original(sc, entries) if source == "original" else outcomes_blind(sc, entries, blind)
    graded = {(e["arm"], e["email"]): grade.grade(sc, e["email"], e["reply"]) for e in entries}
    slice_of = {eid: compare.slices(sc.questions(eid)) for eid in emails}
    lines, cases = [f"labels: {source}", ""], []

    lines.append("Grader against the labels (positive class: labelled wrong)")
    for arm in ARMS + ("both arms",):
        arms = ARMS if arm == "both arms" else (arm,)
        rows = [(graded[(a, eid)]["verdict"], outcomes[(a, eid)]["label"]) for a in arms for eid in emails]
        c = grade.calibration(rows)
        wrong, correct = c["caught"] + c["missed"], c["false_alarms"] + c["passed"]
        lines.append(f"  {arm:15}  missed {c['missed']} of {wrong} wrong · false alarms {c['false_alarms']} of {correct} correct"
                     f" · not gradeable {c['not_gradeable']} · no reply {c['no_reply']}")

    lines += ["", f"Email outcomes, {BASELINE} (baseline) against {CANDIDATE} (candidate), same {len(emails)} emails"]
    base = {eid: outcomes[(BASELINE, eid)]["outcome"] for eid in emails}
    cand = {eid: outcomes[(CANDIDATE, eid)]["outcome"] for eid in emails}
    p = compare.paired(base, cand)
    lines.append(f"  correct: {p['baseline_correct']} of {p['emails']} → {p['candidate_correct']} of {p['emails']}")
    lines.append(f"  both correct {len(p['both_correct'])} · both wrong {len(p['both_wrong'])} · "
                 f"fixed {len(p['fixed'])} {p['fixed']} · broken {len(p['broken'])} {p['broken']}")
    lines.append(f"  exact two-sided sign test on the changed emails: p = {p['p_two_sided']:.3f}")

    counts = agreement(sc, entries, blind)
    lines += ["", "Blind labels against 01's original labels, per reply (original → blind)"]
    lines.append("  " + " · ".join(f"{o} → {b}: {n}" for (o, b), n in counts.items())
                 + f" · agree {counts[('correct', 'correct')] + counts[('wrong', 'wrong')]} of {sum(counts.values())}")

    if source == "blind":
        lines += ["", "Gates (blind labels, per question)"]
        for arm in ARMS:
            scored = [outcomes[(arm, eid)] for eid in emails if "answerable" in outcomes[(arm, eid)]]
            lines.append(f"  {arm:15}  false refusals {sum(s['false_refusals'] for s in scored)} of "
                         f"{sum(s['answerable'] for s in scored)} answerable questions · false answers "
                         f"{sum(s['false_answers'] for s in scored)} of {sum(s['uncovered'] for s in scored)} uncovered")

    lines += ["", "Slices: emails, baseline correct, candidate correct"]
    for name, values in compare.by_slice(emails, slice_of, base, cand).items():
        lines.append(f"  {name}: " + " · ".join(f"{v} ({n}: {b} → {c})" for v, (n, b, c) in values.items()))

    lines += ["", "Per email: baseline outcome, grader / candidate outcome, grader"]
    for eid in emails:
        b, c = graded[(BASELINE, eid)], graded[(CANDIDATE, eid)]
        lines.append(f"  {eid}  {base[eid]:7} {b['verdict']:13} {cand[eid]:7} {c['verdict']:13}"
                     f"  missing: {b['missing'] or '-'} / {c['missing'] or '-'}")
        for arm in ARMS:
            e = next(x for x in entries if x["arm"] == arm and x["email"] == eid)
            cases.append({"email": eid, "arm": arm, "key": e["key"], "slices": slice_of[eid],
                          "outcome": outcomes[(arm, eid)], "grader": graded[(arm, eid)]})
    return lines, cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--controls", action="store_true")
    group.add_argument("--labels", choices=["blind", "original"])
    args = parser.parse_args()

    lines, problems = run_all()
    print("\n".join(lines))
    if problems:
        sys.exit("\nPROBLEMS:\n  " + "\n  ".join(problems))
    sc, entries, emails = scorer(), load_replies(), test_emails()
    if args.controls:
        out = controls(sc, entries, emails)
        print("\n".join(out))
        if any(line.startswith("CONTROL FAILED") for line in out):
            sys.exit(1)
        return
    if not BLIND.exists():
        sys.exit("data/blind_labels.json doesn't exist yet. The report runs only after the blind labels are written.")
    out, cases = report(sc, entries, emails, args.labels, json.loads(BLIND.read_text())["labels"])
    manifest = {"labels": args.labels, "frozen_sha256": sha256_file(DATA / "FROZEN.json"),
                "blind_labels_sha256": sha256_file(BLIND), "python": platform.python_version(),
                "platform": platform.platform()}
    RUNS.mkdir(exist_ok=True)
    (RUNS / f"report-{args.labels}.txt").write_text(json.dumps(manifest) + "\n\n" + "\n".join(out) + "\n")
    with (RUNS / f"cases-{args.labels}.jsonl").open("w") as f:
        for case in cases:
            f.write(json.dumps({**case, "manifest": manifest}, ensure_ascii=False) + "\n")
    print("\n" + "\n".join(out))


if __name__ == "__main__":
    main()
