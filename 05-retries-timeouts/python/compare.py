"""Compare repeat runs: python compare.py runs/<a> runs/<b> runs/<c>

Prints whether the stable part of each report (counts, outcomes, classes, pass/fail) is identical, line by line
where it isn't, and the range of every timing across the runs. Reads each run's report.txt (write it with
report.py first).
"""

import re
import sys
from pathlib import Path


def sections(path):
    text = (Path(path) / "report.txt").read_text()
    stable = text.split("== Stable ==\n", 1)[1].split("\n\nStable digest:", 1)[0].splitlines()
    digest = re.search(r"Stable digest: (\w+)", text).group(1)
    timings = text.split("== Timings (seconds; vary between runs) ==\n", 1)[1].splitlines()
    return stable, digest, timings


def main(paths):
    runs = [sections(p) for p in paths]
    print("Runs:", ", ".join(Path(p).name for p in paths))
    digests = [d for _, d, _ in runs]
    print("Stable digests:", *digests, sep="\n  ")
    if len(set(digests)) == 1:
        print("Stable output: identical in all runs")
    else:
        print("Stable output: DIFFERS")
        for i, lines in enumerate(zip(*(s for s, _, _ in runs))):
            if len(set(lines)) > 1:
                print(f"  line {i}:", *lines, sep="\n    ")
    print("\nTiming ranges across runs (min to max of each number, in order):")
    for lines in zip(*(t for _, _, t in runs)):
        label = re.split(r"[:\d]", lines[0], maxsplit=1)[0] if lines[0] else ""
        numbers = [[float(x) for x in re.findall(r"-?\d+\.\d+", line)] for line in lines]
        if not numbers[0] or len({len(n) for n in numbers}) != 1:
            print(" ", lines[0], "| (not comparable number by number)")
            continue
        ranges = [f"{min(col):g}-{max(col):g}" if min(col) != max(col) else f"{col[0]:g}" for col in zip(*numbers)]
        head = lines[0].split(":")[0] if ":" in lines[0] else label.strip()
        print(f"  {head}: {', '.join(ranges)}")


if __name__ == "__main__":
    main(sys.argv[1:])
