"""
Writes data/FROZEN-B.json, before Part B's first model call: the SHA-256 of every input and every file of code
that decides a Part B result, with the versions every run must use.

  .venv/bin/python freeze_b.py

It fails, writing nothing, if: Part A's freeze doesn't verify; v4 differs from v3 in anything but the approved
sentence; the installed packages don't match python/requirements.txt; or any listed file is missing (01's
documents and emails are also counted, so none is silently left out). It never overwrites FROZEN-B.json.
"""
import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone

from check import verify_frozen
from common import DATA, DEMO, SOURCE_DATA, SOURCE_PY, rel, sha256_file
from common_b import EXPECTED, PROMPTS, prompt_difference

DOCUMENTS = sorted((SOURCE_DATA / "documents").glob("*.md"))
EMAILS = sorted((SOURCE_DATA / "emails").glob("*.txt"))
INPUTS = (
    [SOURCE_DATA / n for n in ("prompts.json", "settings.json", "splits.json", "labels.json", "tokenizer.json")]
    + DOCUMENTS + EMAILS
    + [SOURCE_PY / f"{n}.py" for n in ("pipeline", "steps", "retrieval", "search", "chunkers", "tokens", "llm", "score")]
    + [DATA / "FROZEN.json", DATA / "prompts-v4.json", DEMO / "python" / "requirements.txt"]
)
CODE = [DEMO / "PROTOCOL-B.md"] + [DEMO / "python" / f"{n}.py" for n in ("common_b", "run_b", "report_b", "worksheet", "import_labels")]


def problems() -> list[str]:
    found = []
    _, part_a = verify_frozen(DATA / "FROZEN.json")
    found += [f"Part A freeze: {p}" for p in part_a]
    found += prompt_difference(json.loads(PROMPTS["v3"].read_text()), json.loads(PROMPTS["v4"].read_text()))
    if len(DOCUMENTS) != 5 or len(EMAILS) != 40:
        found.append(f"expected 5 documents and 40 emails in 01, found {len(DOCUMENTS)} and {len(EMAILS)}")
    found += [f"missing: {rel(p)}" for p in INPUTS + CODE if not p.exists()]
    for line in (DEMO / "python" / "requirements.txt").read_text().splitlines():
        if "==" in line:
            package, pinned = line.split("==")
            try:
                installed = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                installed = "not installed"
            if installed != pinned:
                found.append(f"{package}: {installed}, pinned {pinned} (run with the demo's .venv)")
    return found


def main() -> None:
    out = DATA / "FROZEN-B.json"
    if out.exists():
        sys.exit(f"{rel(out)} already exists and is never overwritten. Record a deviation instead.")
    found = problems()
    if found:
        sys.exit("NOT FROZEN:\n  " + "\n  ".join(found))
    document = {
        "_comment": ("Written once by freeze_b.py before Part B's first model call. run_b.py and report_b.py refuse to run "
                     "if any file listed here, or in FROZEN.json, has changed."),
        "frozen_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "python": platform.python_version(),
        "expected": EXPECTED,
        "inputs": {rel(p): sha256_file(p) for p in INPUTS},
        "code": {rel(p): sha256_file(p) for p in CODE},
    }
    out.write_text(json.dumps(document, indent=1) + "\n")
    print(f"wrote {rel(out)}: {len(INPUTS)} inputs, {len(CODE)} code files")


if __name__ == "__main__":
    main()
