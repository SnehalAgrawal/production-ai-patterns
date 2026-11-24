"""
Part B report: the friendlier v4 prompt against the fresh v3 baseline, from data/replies-b.json and the blind
labels. No model calls.

  python report_b.py

It refuses to run until data/blind_labels.json exists, and first checks both freezes. Two kinds of claim are
kept apart throughout:
  reproduction   whether two runs produced the same text (extraction, chunks, reply)
  outcome        whether a person's labels give the same verdict, which identical text implies but
                 different text doesn't rule out
Writes runs/b/report-b.txt and runs/b/cases-b.jsonl (git-ignored).
"""
import json
import platform
import sys

import compare
import grade
from check import verify_frozen
from common import DATA, RUNS, scorer, sha256_file, test_emails
from common_b import BASELINE_RUN, CANDIDATE_RUN, LABELLED_RUNS, REPLIES_B, RERUN, compare_runs, median_length

BLIND = DATA / "blind_labels.json"


def outcome(sc, eid: str, record: dict, blind: dict) -> dict:
    if record["reply"] is None:
        return {"outcome": compare.WRONG, "label": None}
    if record["key"] not in blind:
        raise ValueError(f"{eid}: no blind label for reply {record['key']}")
    scored = compare.blind_outcome(sc.questions(eid), blind[record["key"]])
    return {**scored, "label": scored["outcome"]}


def build(sc, runs: dict, stored_18: dict, blind: dict, emails: list[str]) -> tuple[list[str], list[dict]]:
    records = {name: runs[name]["emails"] for name in LABELLED_RUNS}
    outcomes = {name: {eid: outcome(sc, eid, records[name][eid], blind) for eid in emails} for name in LABELLED_RUNS}
    graded = {name: {eid: grade.grade(sc, eid, records[name][eid]["reply"]) for eid in emails} for name in LABELLED_RUNS}
    lines, cases = [], []

    lines.append("Reproduction (text, not outcomes)")
    for label, before, after in (("v3a against #18's stored chain", stored_18, records[BASELINE_RUN]),
                                 ("v3a against v3b", records[BASELINE_RUN], records[RERUN])):
        c = compare_runs(before, after)
        lines.append(f"  {label}: of {c['emails']} emails, same extraction {c['same_extraction']}, same chunks "
                     f"{c['same_chunks']}, same reply text {c['same_reply']}; different replies: {c['different_reply'] or 'none'}")
    changed = compare_runs(records[BASELINE_RUN], records[CANDIDATE_RUN])
    lines.append(f"  v3a against v4test (the prompt change): same reply text {changed['same_reply']} of {changed['emails']}")

    def outcome_map(name: str) -> dict[str, str]:
        return {eid: outcomes[name][eid]["outcome"] for eid in emails}

    lines += ["", "Outcome agreement between the two v3 runs (labels, not text)"]
    noise = compare.paired(outcome_map(BASELINE_RUN), outcome_map(RERUN))
    lines.append(f"  same outcome {len(noise['both_correct']) + len(noise['both_wrong'])} of {noise['emails']} · "
                 f"changed {noise['fixed'] + noise['broken'] or 'none'}")

    lines += ["", f"Email outcomes: {BASELINE_RUN} (baseline) against {CANDIDATE_RUN} (candidate), same {len(emails)} emails"]
    main_cmp = compare.paired(outcome_map(BASELINE_RUN), outcome_map(CANDIDATE_RUN))
    lines.append(f"  correct: {main_cmp['baseline_correct']} of {main_cmp['emails']} → {main_cmp['candidate_correct']} of {main_cmp['emails']}")
    lines.append(f"  both correct {len(main_cmp['both_correct'])} · both wrong {len(main_cmp['both_wrong'])} · fixed "
                 f"{len(main_cmp['fixed'])} {main_cmp['fixed']} · broken {len(main_cmp['broken'])} {main_cmp['broken']}")
    lines.append(f"  exact two-sided sign test on the changed emails: p = {main_cmp['p_two_sided']:.3f}")

    lines += ["", "Gates (blind labels, per question)"]
    for name in LABELLED_RUNS:
        scored = [o for o in outcomes[name].values() if "answerable" in o]
        lines.append(f"  {name:7} false refusals {sum(s['false_refusals'] for s in scored)} of {sum(s['answerable'] for s in scored)} "
                     f"answerable questions · false answers {sum(s['false_answers'] for s in scored)} of "
                     f"{sum(s['uncovered'] for s in scored)} uncovered · emails with no reply {len(emails) - len(scored)}")

    lines += ["", "Grader against the blind labels (positive class: labelled wrong)"]
    for name in LABELLED_RUNS:
        c = grade.calibration([(graded[name][eid]["verdict"], outcomes[name][eid]["label"]) for eid in emails])
        lines.append(f"  {name:7} missed {c['missed']} of {c['caught'] + c['missed']} wrong · false alarms {c['false_alarms']} of "
                     f"{c['false_alarms'] + c['passed']} correct · not gradeable {c['not_gradeable']} · no reply {c['no_reply']}")

    lines += ["", "Reply length (characters, median over replies)"]
    lines.append("  " + " · ".join(f"{name} {median_length(records[name])}" for name in LABELLED_RUNS))

    lines += ["", "Blind labels against 01's original labels, on v3a replies identical to a reply 01 labelled"]
    counts = {(o, b): 0 for o in (compare.CORRECT, compare.WRONG) for b in (compare.CORRECT, compare.WRONG)}
    for eid in emails:
        record = records[BASELINE_RUN][eid]
        original = sc.hand.get(record["key"]) if record["key"] else None
        if original:
            counts[(original["verdict"], outcomes[BASELINE_RUN][eid]["outcome"])] += 1
    lines.append("  " + " · ".join(f"{o} → {b}: {n}" for (o, b), n in counts.items())
                 + f" · agree {counts[('correct', 'correct')] + counts[('wrong', 'wrong')]} of {sum(counts.values())}")

    lines += ["", "Per email: v3a outcome, grader / v4test outcome, grader / v3a and v4test reply text the same?"]
    for eid in emails:
        a, b = outcomes[BASELINE_RUN][eid]["outcome"], outcomes[CANDIDATE_RUN][eid]["outcome"]
        same = records[BASELINE_RUN][eid]["reply"] == records[CANDIDATE_RUN][eid]["reply"]
        lines.append(f"  {eid}  {a:7} {graded[BASELINE_RUN][eid]['verdict']:13} {b:7} {graded[CANDIDATE_RUN][eid]['verdict']:13} "
                     f"{'same text' if same else 'text changed'}")
        for name in LABELLED_RUNS:
            cases.append({"email": eid, "run": name, "key": records[name][eid]["key"], "outcome": outcomes[name][eid],
                          "grader": graded[name][eid]})
    return lines, cases


def main() -> None:
    for name in ("FROZEN.json", "FROZEN-B.json"):
        _, problems = verify_frozen(DATA / name)
        if problems:
            sys.exit(f"{name}:\n  " + "\n  ".join(problems))
    if not BLIND.exists():
        sys.exit("data/blind_labels.json doesn't exist yet. The report runs only after the blind labels are written.")
    doc = json.loads(REPLIES_B.read_text())
    blind = json.loads(BLIND.read_text())["labels"]
    lines, cases = build(scorer(), doc["runs"], doc["stored_18_chain"], blind, test_emails())
    manifest = {"frozen_sha256": sha256_file(DATA / "FROZEN.json"), "frozen_b_sha256": sha256_file(DATA / "FROZEN-B.json"),
                "replies_b_sha256": sha256_file(REPLIES_B), "blind_labels_sha256": sha256_file(BLIND),
                "python": platform.python_version()}
    out = RUNS / "b"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report-b.txt").write_text(json.dumps(manifest) + "\n\n" + "\n".join(lines) + "\n")
    with (out / "cases-b.jsonl").open("w") as f:
        for case in cases:
            f.write(json.dumps({**case, "manifest": manifest}, ensure_ascii=False) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
