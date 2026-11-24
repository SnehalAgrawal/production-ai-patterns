"""Run one workflow in its own process, so a crash point can end it for real.

    python worker.py DIR EMAIL --design C [--run-id N] [--owner NAME]

Exit codes: 0 the run ended (completed, held, handed over, ...), 3 the record is incompatible and the run
refused to start, 70 the process stopped at the crash point named in the CRASH_AT environment variable.
"""

import argparse
import json
import sys

from common import REFUSED_EXIT
from workflow import DESIGNS, Run


def main():
    p = argparse.ArgumentParser()
    p.add_argument("dir")
    p.add_argument("email")
    p.add_argument("--design", default="C", choices=sorted(DESIGNS))
    p.add_argument("--run-id", type=int, default=1)
    p.add_argument("--owner", default="worker")
    a = p.parse_args()
    status = Run(a.dir, a.email, DESIGNS[a.design], owner=a.owner, run_id=a.run_id).run()
    print(json.dumps({"status": status}))
    sys.exit(REFUSED_EXIT if status == "refused" else 0)


if __name__ == "__main__":
    main()
