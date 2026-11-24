"""Run everything once and save the observations: python run.py   (then: python report.py)

Order: check the freeze manifest, calibrate this machine's timing overhead, Part A (policy and tools against the
stand-in), the fake-clock simulations, then Part B (each SDK in its own process, with ../.venv/bin/python).
Writes runs/<UTC time>/observations.json (runs/ is not committed).

    python run.py --skip-sdk      Part A and the simulations only (standard library, no virtual environment)
    python run.py --only A7       one Part A scenario, for development (not a full run)
"""

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent
FROZEN = ["PROTOCOL.md", "python/policy.py", "python/standin.py", "python/http_send.py", "python/tools.py",
          "python/scenarios_a.py", "python/simulate.py", "python/sdk_probe.py", "python/run.py",
          "python/report.py", "python/compare.py", "python/test_policy.py", "requirements-sdk.txt"]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_check():
    manifest = DEMO / "results" / "freeze.json"
    current = {f: sha256(DEMO / f) for f in FROZEN if (DEMO / f).exists()}
    if not manifest.exists():
        return {"manifest": None, "current": current, "matches": None}
    frozen = json.loads(manifest.read_text())
    changed = sorted(f for f in FROZEN if frozen["files"].get(f) != current.get(f))
    return {"frozen_at_utc": frozen["frozen_at_utc"], "current": current, "changed": changed,
            "matches": not changed}


def calibrate():
    """How far this machine's sleeps overshoot, and how long a local round trip to the stand-in takes."""
    from http_send import send_chat
    from standin import StandIn
    over = []
    for _ in range(20):
        t = time.monotonic()
        time.sleep(0.05)
        over.append(time.monotonic() - t - 0.05)
    trips = []
    with StandIn(model=[{"do": "ok"}]) as s:
        for _ in range(20):
            t = time.monotonic()
            send_chat(s.url, timeout=2.0)
            trips.append(time.monotonic() - t)
    return {"sleep_50ms_overshoot_s": {"median": round(statistics.median(over), 5), "max": round(max(over), 5)},
            "local_round_trip_s": {"median": round(statistics.median(trips), 5), "max": round(max(trips), 5)}}


def environment():
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=DEMO, capture_output=True, text=True).stdout.strip()
        except OSError:
            return None
    return {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
            "processor": subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                        text=True).stdout.strip() if sys.platform == "darwin" else platform.processor(),
            "load_average": [round(x, 2) for x in os.getloadavg()],
            "repository_head": git("rev-parse", "--short", "HEAD"),
            "demo_files_uncommitted": bool(git("status", "--porcelain", "--", "."))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-sdk", action="store_true")
    ap.add_argument("--only")
    args = ap.parse_args()
    sys.path.insert(0, str(HERE))
    import scenarios_a
    import simulate

    started = datetime.now(timezone.utc)
    obs = {"started_utc": started.isoformat(timespec="seconds"), "freeze": freeze_check(),
           "environment": environment(), "calibration": calibrate(), "part_a": {}}
    for name, fn in scenarios_a.SCENARIOS.items():
        if args.only and name != args.only:
            continue
        print(f"Part A {name} ...", flush=True)
        obs["part_a"][name] = fn()
    if not args.only:
        print("Simulations ...", flush=True)
        obs["simulation"] = {"amplification": simulate.amplification(), "jitter": simulate.jitter_burst()}
        obs["part_b"] = {}
        venv_python = DEMO / ".venv" / "bin" / "python"
        if args.skip_sdk or not venv_python.exists():
            obs["part_b"] = None
        else:
            env = {k: v for k, v in os.environ.items()
                   if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL",
                                "OPENAI_LOG", "ANTHROPIC_LOG")}
            for sdk in ("openai", "anthropic"):
                print(f"Part B {sdk} ...", flush=True)
                done = subprocess.run([str(venv_python), "sdk_probe.py", sdk], cwd=HERE, env=env,
                                      capture_output=True, text=True, timeout=300)
                obs["part_b"][sdk] = json.loads(done.stdout) if done.returncode == 0 else {"error": done.stderr[-2000:]}
    obs["finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    obs["environment"]["load_average_end"] = [round(x, 2) for x in os.getloadavg()]
    stamp = started.strftime("%Y%m%dT%H%M%SZ") + ("-" + args.only if args.only else "")
    out = DEMO / "runs" / stamp
    out.mkdir(parents=True, exist_ok=True)
    (out / "observations.json").write_text(json.dumps(obs, indent=1))
    print(f"Wrote {out / 'observations.json'}")


if __name__ == "__main__":
    main()
