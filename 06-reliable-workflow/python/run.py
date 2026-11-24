"""Run every scenario in PROTOCOL.md and write runs/<time>/results.json.

    python run.py          checks results/freeze.json first and refuses to run if anything changed
    python run.py --dev    development run: no freeze check (not reported)

results.json holds counts, statuses and values only: no timings, no paths, no wall-clock times, so repeat
runs can be compared byte for byte (compare.py).
"""

import argparse
import json
import platform
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from freeze import verify
from scenarios import ALL

DEMO = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dev", action="store_true")
    a = p.parse_args()
    if not a.dev:
        problems = verify()
        if problems:
            sys.exit("freeze check failed:\n" + "\n".join(problems))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = DEMO / "runs" / (stamp + ("-dev" if a.dev else ""))
    work = out / "work"
    results = {"environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version},
               "results": {}}
    for name, scenario in ALL.items():
        print(f"{name} ...", flush=True)
        results["results"][name] = scenario(work)
    (out / "results.json").write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
    print(f"wrote {out / 'results.json'}")


if __name__ == "__main__":
    main()
