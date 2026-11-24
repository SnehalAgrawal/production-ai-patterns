"""
Checks that the inputs are the frozen ones, with no model calls:

  - every file listed in data/FROZEN.json still has the SHA-256 recorded there (a changed file is an error,
    never a reason to refresh the hashes)
  - each arm covers exactly the 20 test emails, once each
  - every reply's key and SHA-256 match its text
  - every reply's key is in 01's data/hand_labels.json: these are the exact texts that were labelled

Run: python check.py      (exit code 1 on any problem)
"""
import json
import sys
from pathlib import Path

from common import ARMS, DATA, ROOT, load_replies, reply_key, scorer, sha256_file, sha256_text, test_emails


def verify_frozen(frozen_path: Path = DATA / "FROZEN.json", root: Path = ROOT) -> tuple[int, list[str]]:
    """(files checked, problems)."""
    if not frozen_path.exists():
        return 0, [f"{frozen_path.name} is missing: run freeze.py once, before the first report"]
    frozen = json.loads(frozen_path.read_text())
    checked, problems = 0, []
    for group in ("inputs", "code"):
        for path, digest in frozen[group].items():
            checked += 1
            file = root / path
            if not file.exists():
                problems.append(f"frozen file missing: {path}")
            elif sha256_file(file) != digest:
                problems.append(f"changed since the freeze: {path}")
    return checked, problems


def verify_replies(entries: list[dict], hand: dict, emails: list[str]) -> list[str]:
    problems = []
    for arm in ARMS:
        covered = [e["email"] for e in entries if e["arm"] == arm]
        if sorted(covered) != sorted(emails):
            problems.append(f"{arm}: covers {len(covered)} entries, not each of the {len(emails)} test emails once")
    for e in entries:
        where = f"{e['arm']} {e['email']}"
        if e["arm"] not in ARMS:
            problems.append(f"{where}: unknown arm")
        if e["reply"] is None:
            if not e.get("missing"):
                problems.append(f"{where}: no reply and no reason recorded")
            continue
        if reply_key(e["email"], e["reply"]) != e["key"]:
            problems.append(f"{where}: key doesn't match the reply text")
        if sha256_text(e["reply"]) != e["sha256"]:
            problems.append(f"{where}: SHA-256 doesn't match the reply text")
        if e["key"] not in hand:
            problems.append(f"{where}: key not in 01's hand_labels.json, so this isn't a text that was labelled")
    return problems


def run_all() -> tuple[list[str], list[str]]:
    """(summary lines, problems)."""
    checked, problems = verify_frozen()
    entries = load_replies()
    problems += verify_replies(entries, scorer().hand, test_emails())
    lines = [f"frozen files checked: {checked}"]
    for arm in ARMS:
        mine = [e for e in entries if e["arm"] == arm]
        absent = [e["email"] for e in mine if e["reply"] is None]
        lines.append(f"{arm}: {len(mine) - len(absent)} replies" + (f", no reply for {', '.join(absent)}" if absent else ""))
    labelled = sum(1 for e in entries if e["reply"] is not None and e["key"] in scorer().hand)
    lines.append(f"reply keys found in 01's hand_labels.json: {labelled} of {sum(e['reply'] is not None for e in entries)}")
    return lines, problems


def main() -> None:
    lines, problems = run_all()
    print("\n".join(lines))
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
