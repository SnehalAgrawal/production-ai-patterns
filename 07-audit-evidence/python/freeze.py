"""Write results/freeze.json: the SHA-256 of the code, before the first reported run.

The inputs (PROTOCOL.md and data/) were frozen earlier, in results/freeze-inputs.json,
before any code existed. run.py checks both on every run.
"""

import datetime as dt
import hashlib
import json
import sys

from common import DEMO

CODE = ["checker.py", "common.py", "compare.py", "evidence.py", "freeze.py", "hashes.py", "lifecycle.py",
        "reconstruct.py", "report.py", "run.py", "test_evidence.py", "workflow.py"]

if __name__ == "__main__":
    out = {"frozen_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
           "note": (sys.argv[1] if len(sys.argv) > 1 else
                    "Code frozen before the first reported run. run.py compares these hashes on every run."),
           "files": {f"python/{f}": hashlib.sha256((DEMO / "python" / f).read_bytes()).hexdigest() for f in CODE}}
    (DEMO / "results" / "freeze.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
