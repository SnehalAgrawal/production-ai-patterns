"""
Runs every variant: starts the stand-in services and the application as separate processes, sends the requests,
and saves three records per run (client, application, services) plus the environment.

  python run.py                      every variant, every repeat (about 15 minutes)
  python run.py --variants V0-baseline V1-faster-decode --repeats 1
  python run.py --smoke 10           10 requests per variant, saved under runs/smoke/, not reported

Runs are ordered repeat by repeat (all variants once, then again), so a slow drift on the machine affects every
variant. Then: python report.py
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time

import client
from common import HERE, RUNS, JsonLines, load_settings, variant_settings


def environment() -> dict:
    try:
        lsof = subprocess.run(["lsof", "-nP", "-iTCP:11434", "-sTCP:ESTABLISHED"], capture_output=True, text=True,
                              timeout=10)
        ollama = max(0, len(lsof.stdout.strip().splitlines()) - 1) if lsof.stdout.strip() else 0
    except (OSError, subprocess.TimeoutExpired):
        ollama = None
    return {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "loadavg": os.getloadavg(),
            "ollama_established_connections": ollama}


def start(script: str, *args: str) -> subprocess.Popen:
    process = subprocess.Popen([sys.executable, script, *args], cwd=HERE, stdout=subprocess.PIPE, text=True)
    if process.stdout.readline().strip() != "ready":
        process.kill()
        raise SystemExit(f"{script} did not start")
    return process


def run_one(variant: str, repeat: int, requests: int | None, base) -> None:
    settings = load_settings()
    cfg = variant_settings(variant)
    n = cfg["requests"] if requests is None else min(requests, cfg["requests"])
    out = base / variant / f"r{repeat}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    ports = settings["ports"]
    env = {"variant": variant, "repeat": repeat, "requests": n, "python": sys.version.split()[0],
           "implementation": platform.python_implementation(), "platform": platform.platform(),
           "machine": platform.machine(), "cpu_count": os.cpu_count(), "before": environment()}
    services = start("services.py", "--variant", variant, "--port", str(ports["services"]), "--out", str(out))
    app = start("app.py", "--variant", variant, "--port", str(ports["app"]), "--services", str(ports["services"]),
                "--out", str(out))
    try:
        began = time.monotonic()
        client.run(ports["app"], cfg, n, f"{variant}-r{repeat}", JsonLines(out / "client.jsonl"))
        time.sleep(0.3)  # let the application write its last records
        env["seconds"] = round(time.monotonic() - began, 1)
    finally:
        for process in (app, services):
            process.terminate()
            process.wait()
    env["after"] = environment()
    (out / "env.json").write_text(json.dumps(env, indent=2))
    print(f"  {variant} r{repeat}: {n} requests, {env['seconds']} s, load {env['before']['loadavg'][0]:.2f}"
          f" -> {env['after']['loadavg'][0]:.2f}, Ollama connections {env['before']['ollama_established_connections']}"
          f" -> {env['after']['ollama_established_connections']}", flush=True)


def main() -> None:
    settings = load_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", nargs="*", default=list(settings["variants"]))
    parser.add_argument("--repeats", type=int, default=settings["repeats"])
    parser.add_argument("--smoke", type=int, help="requests per variant; saved under runs/smoke/ and not reported")
    args = parser.parse_args()
    base = RUNS / "smoke" if args.smoke else RUNS
    for repeat in range(1, args.repeats + 1):
        print(f"repeat {repeat}", flush=True)
        for variant in args.variants:
            run_one(variant, repeat, args.smoke, base)


if __name__ == "__main__":
    main()
