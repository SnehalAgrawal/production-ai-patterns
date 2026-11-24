"""
Writes data/FROZEN.json: the SHA-256 of every input and every file of code that decides a Part A result.

Run once, before the first report. It refuses to overwrite an existing FROZEN.json: if a frozen file has to
change, record the deviation in the README instead of refreshing the hashes.
"""
import json
import platform
import sys
from datetime import datetime, timezone

from common import DATA, DEMO, SOURCE_DATA, SOURCE_PY, rel, sha256_file

INPUTS = [
    SOURCE_DATA / "labels.json",       # the facts, their accepted wordings, and evidence (01, commit 08bf05c)
    SOURCE_DATA / "splits.json",       # development and test emails
    SOURCE_DATA / "hand_labels.json",  # 01's verdict for each of the 39 replies
    SOURCE_PY / "score.py",            # 01's fact check and label key, imported
    SOURCE_PY / "steps.py",            # 01's normalizing and whole-word matching, imported
    DATA / "replies.json",             # the 39 replies, exported once
]
CODE = [DEMO / "PROTOCOL.md"] + [DEMO / "python" / f"{name}.py" for name in ("common", "check", "grade", "compare", "report")]


def main() -> None:
    out = DATA / "FROZEN.json"
    if out.exists():
        sys.exit(f"{rel(out)} already exists and is never overwritten. Record a deviation instead.")
    document = {
        "_comment": ("Written once by freeze.py before the first report. check.py, and so report.py, refuse to run "
                     "if any file listed here has changed."),
        "frozen_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "python": platform.python_version(),
        "inputs": {rel(p): sha256_file(p) for p in INPUTS},
        "code": {rel(p): sha256_file(p) for p in CODE},
    }
    out.write_text(json.dumps(document, indent=1) + "\n")
    print(f"wrote {rel(out)}: {len(INPUTS)} inputs, {len(CODE)} code files")


if __name__ == "__main__":
    main()
