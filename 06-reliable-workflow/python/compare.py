"""Compare repeat runs: are their results.json files identical, byte for byte?

    python compare.py runs/<a> runs/<b> runs/<c>
"""

import hashlib
import sys
from pathlib import Path


def main():
    runs = [Path(a) for a in sys.argv[1:]]
    if len(runs) < 2:
        sys.exit("give two or more run directories")
    hashes = {}
    for run in runs:
        h = hashlib.sha256((run / "results.json").read_bytes()).hexdigest()
        hashes[run.name] = h
        print(f"{run.name}  {h}")
    same = len(set(hashes.values())) == 1
    print("identical" if same else "DIFFERENT")
    sys.exit(0 if same else 1)


if __name__ == "__main__":
    main()
