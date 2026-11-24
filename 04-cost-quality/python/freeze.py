"""
FROZEN.json: the SHA-256 of every input and every piece of code that decides a result, written once, before the
first run (PROTOCOL.md). run.py refuses to run, and the tests fail, if any of them changed.

  python freeze.py          writes data/FROZEN.json; never overwrites it
  python freeze.py --check  verifies every hash, prints problems
"""
import argparse
import json
import sys
from datetime import datetime, timezone

from shared import DEMO, EVALUATION, FROZEN, ROOT, SOURCE, rel, sha256_file

THIS = ["PROTOCOL.md", "data/variants.json", "data/prices.json", "python/requirements.txt",
        *(f"python/{m}.py" for m in ("shared", "cost", "run", "analysis", "report", "labels", "verify", "freeze"))]
FROM_01 = ["data/settings.json", "data/prompts.json", "data/labels.json", "data/splits.json", "data/tokenizer.json",
           *(f"python/{m}.py" for m in ("pipeline", "steps", "retrieval", "chunkers", "tokens", "score", "llm", "search"))]
FROM_02 = ["data/replies-b.json", "data/blind_labels.json",
           *(f"python/{m}.py" for m in ("common", "common_b", "compare", "grade", "worksheet", "import_labels"))]


def frozen_paths():
    paths = [DEMO / p for p in THIS] + [SOURCE / p for p in FROM_01] + [EVALUATION / p for p in FROM_02]
    paths += sorted((SOURCE / "data" / "emails").glob("*.txt")) + sorted((SOURCE / "data" / "documents").glob("*.md"))
    return paths


def verify_frozen() -> list[str]:
    if not FROZEN.exists():
        return ["data/FROZEN.json doesn't exist: run python freeze.py before any run"]
    recorded = json.loads(FROZEN.read_text())["files"]
    problems = []
    for path in frozen_paths():
        name = rel(path)
        if name not in recorded:
            problems.append(f"{name} is not in FROZEN.json")
        elif not path.exists():
            problems.append(f"{name} is missing")
        elif sha256_file(path) != recorded[name]:
            problems.append(f"{name} changed since the freeze")
    for name in recorded:
        if not (ROOT / name).exists():
            problems.append(f"{name} is missing")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        problems = verify_frozen()
        print("\n".join(problems) or "every frozen file matches")
        sys.exit(1 if problems else 0)
    if FROZEN.exists():
        sys.exit(f"{rel(FROZEN)} already exists and is never overwritten")
    files = {rel(p): sha256_file(p) for p in frozen_paths()}
    FROZEN.write_text(json.dumps({"frozen_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                                  "files": files}, indent=1) + "\n")
    print(f"wrote {rel(FROZEN)}: {len(files)} files")


if __name__ == "__main__":
    main()
