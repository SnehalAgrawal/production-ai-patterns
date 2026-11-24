"""Compare repeat runs: is the stable section identical, and how much do E10's timings vary?

    python compare.py runs/<a> runs/<b> runs/<c>
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    runs = [Path(p) for p in sys.argv[1:]]
    digests, timings = [], {"plain": [], "keyed_with_key": [], "keyed_other_key": []}
    for run in runs:
        out = subprocess.run([sys.executable, str(HERE / "report.py"), str(run)], capture_output=True, text=True).stdout
        digests.append(next(line.split(": ")[1] for line in out.splitlines() if line.startswith("stable section SHA-256")))
        e10 = json.loads((run / "observations.json").read_text())["E10"]
        for k in timings:
            timings[k].append(e10[k]["seconds"])
    for run, d in zip(runs, digests):
        print(f"{run.name}  stable section {d}")
    print(f"stable sections identical: {len(set(digests)) == 1}")
    for k, v in timings.items():
        print(f"E10 {k}: {min(v):.3f}-{max(v):.3f} s over {len(v)} runs")


if __name__ == "__main__":
    main()
