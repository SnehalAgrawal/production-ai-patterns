"""Freeze the protocol, the data and the code by SHA-256, and check the freeze.

    python freeze.py           write results/freeze.json (once, before the first reported run)
    python freeze.py --check   compare the files with results/freeze.json
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent
FREEZE = DEMO / "results" / "freeze.json"


def frozen_files():
    files = [DEMO / "PROTOCOL.md", DEMO / "data" / "fixtures.json"]
    files += sorted((DEMO / "python").glob("*.py"))
    return files


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    if not FREEZE.exists():
        return ["results/freeze.json is missing: run python freeze.py first"]
    frozen = json.loads(FREEZE.read_text())["files"]
    current = {str(f.relative_to(DEMO)): digest(f) for f in frozen_files()}
    problems = [f"changed: {name}" for name in frozen if current.get(name) != frozen[name]]
    problems += [f"not frozen: {name}" for name in current if name not in frozen]
    return problems


def main():
    if "--check" in sys.argv:
        problems = verify()
        print("\n".join(problems) or "freeze ok")
        sys.exit(1 if problems else 0)
    if FREEZE.exists():
        sys.exit("results/freeze.json exists; a freeze is written once")
    FREEZE.parent.mkdir(exist_ok=True)
    files = {str(f.relative_to(DEMO)): digest(f) for f in frozen_files()}
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    FREEZE.write_text(json.dumps({"frozen_at": stamp, "files": files}, indent=1, sort_keys=True) + "\n")
    print(f"frozen {len(files)} files at {stamp}")


if __name__ == "__main__":
    main()
