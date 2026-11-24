"""
Part B: the v3 baseline run again, and the friendlier v4 prompt, through 01's pipeline unchanged (policy none).

  python run_b.py preflight        checks only: hashes, Ollama version, model IDs, settings, and a quiet server
  python run_b.py run v3a          the fresh baseline (v3, test)
  python run_b.py run v3b          the same again, for run-to-run variation (v3, test)
  python run_b.py reproduce        v3a against #18's stored chain run, and v3a against v3b; then pause
  python run_b.py run v4dev        v4 on the development emails (format and tone only; never labelled)
  python run_b.py run v4test       v4 on the test emails, once
  python run_b.py export           data/replies-b.json, from every run

Every run first repeats the preflight checks, takes the shared Ollama lock (never taking it over), waits until
no other client has used the server for 60 seconds, and unloads the models before and after. It records its own
model calls and the /api/chat lines in the server log during the run, to confirm nothing else used the server.
Runs go to runs/b/<name>/ (git-ignored). Each name runs once.
"""
import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

from check import verify_frozen
from common import DATA, DEMO, rel, sha256_file, source_module
from common_b import (
    BASELINE_RUN,
    CANDIDATE_RUN,
    DEV_RUN,
    EXPECTED,
    LOCK,
    PROMPTS,
    QUIET_SECONDS,
    REPLIES_B,
    RERUN,
    RUN_PLAN,
    RUNS_B,
    SERVER_LOG,
    STORED_18,
    compare_runs,
    count_requests,
    load_run,
    median_length,
)

BASE_URL = EXPECTED["resolved"]["base_url"]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def pinned_versions() -> dict[str, str]:
    lines = (DEMO / "python" / "requirements.txt").read_text().splitlines()
    return dict(line.split("==") for line in lines if "==" in line)


# ------------------------------------------------------------------------------------------- preflight


def preflight_problems() -> tuple[dict, list[str]]:
    """Everything that must hold before a model call. (facts recorded, problems)"""
    problems, facts = [], {}
    for name in ("FROZEN.json", "FROZEN-B.json"):
        _, found = verify_frozen(DATA / name)
        problems += [f"{name}: {p}" for p in found]
    for package, version in pinned_versions().items():
        installed = importlib.metadata.version(package)
        facts[package] = installed
        if installed != version:
            problems.append(f"{package} {installed} installed, {version} pinned")
    for variable in ("OLLAMA_CHAT_MODEL", "OLLAMA_EMBEDDING_MODEL", "OLLAMA_BASE_URL"):
        if variable in os.environ:
            problems.append(f"{variable} is set; unset it so 01's defaults apply")
    llm = source_module("llm")
    resolved = {"chat_model": llm.chat_model(), "embedding_model": llm.embedding_model(), "base_url": llm.base_url()}
    facts["resolved"] = resolved
    if resolved != EXPECTED["resolved"]:
        problems.append(f"01's llm module resolves {resolved}, expected {EXPECTED['resolved']}")
    version = requests.get(f"{BASE_URL}/api/version", timeout=10).json()["version"]
    facts["ollama"] = version
    if version != EXPECTED["ollama"]:
        problems.append(f"Ollama {version}, expected {EXPECTED['ollama']}")
    tags = {m["name"]: m["digest"] for m in requests.get(f"{BASE_URL}/api/tags", timeout=10).json()["models"]}
    facts["models"] = {name: tags.get(name, "")[:12] for name in EXPECTED["models"]}
    for name, digest in EXPECTED["models"].items():
        if not tags.get(name, "").startswith(digest):
            problems.append(f"{name}: ID {tags.get(name, 'missing')[:12]}, expected {digest}")
    if not SERVER_LOG.exists():
        problems.append(f"no server log at {SERVER_LOG}: isolation can't be checked")
    return facts, problems


def clients() -> int:
    """Established TCP connections to the Ollama port, from any process."""
    out = subprocess.run(["lsof", "-nP", f"-iTCP:{BASE_URL.rsplit(':', 1)[1]}", "-sTCP:ESTABLISHED"],
                         capture_output=True, text=True).stdout
    return max(0, len(out.splitlines()) - 1)  # minus the header line


def wait_for_quiet(limit_seconds: int = 1800) -> None:
    """Until no connection and no server-log change for QUIET_SECONDS in a row."""
    started, quiet_since, size = time.time(), time.time(), SERVER_LOG.stat().st_size
    while time.time() - quiet_since < QUIET_SECONDS:
        if time.time() - started > limit_seconds:
            sys.exit("the Ollama server wasn't quiet for 60 seconds within 30 minutes; not running")
        time.sleep(5)
        current = SERVER_LOG.stat().st_size
        if clients() or current != size:
            quiet_since, size = time.time(), current


def acquire_lock(name: str, limit_seconds: int = 1800) -> None:
    started = time.time()
    while True:
        try:
            LOCK.mkdir()
            break
        except FileExistsError:
            if time.time() - started > limit_seconds:
                sys.exit(f"{LOCK} is held by another session; waited 30 minutes, not taking it over")
            time.sleep(15)
    owner = {"session": "Article #33, Part B", "run": name, "pid": os.getpid(), "since_utc": now()}
    (LOCK / "owner.json").write_text(json.dumps(owner) + "\n")


def release_lock() -> None:
    (LOCK / "owner.json").unlink(missing_ok=True)
    LOCK.rmdir()


# ------------------------------------------------------------------------------------------- one run


def run(name: str) -> None:
    version, split = RUN_PLAN[name]
    out = RUNS_B / name
    if out.exists():
        sys.exit(f"{rel(out)} exists; each run name is used once")
    if version == "v4" and not (RUNS_B / "reproduce.json").exists():
        sys.exit("v4 runs wait for the reproduction (python run_b.py reproduce) and its review")
    if name == CANDIDATE_RUN and not (RUNS_B / DEV_RUN).exists():
        sys.exit("v4test runs after v4dev")
    facts, problems = preflight_problems()
    if problems:
        sys.exit("PREFLIGHT FAILED:\n  " + "\n  ".join(problems))

    pipeline, llm = source_module("pipeline"), source_module("llm")
    Index, Tokenizer = source_module("retrieval").Index, source_module("tokens").Tokenizer
    acquire_lock(name)
    try:
        wait_for_quiet()
        loaded = [m["name"] for m in requests.get(f"{BASE_URL}/api/ps", timeout=10).json()["models"]]
        llm.unload(llm.chat_model())
        llm.unload(llm.embedding_model())
        offset, started = SERVER_LOG.stat().st_size, now()
        data = pipeline.load()
        data["prompts"] = json.loads(PROMPTS[version].read_text())
        runner = pipeline.Pipeline(data, Index(data["settings"], data["documents"], Tokenizer()), "none")
        try:
            states = runner.run(data["splits"][split], pipeline.Store(out))
        finally:
            llm.unload(llm.chat_model())
            llm.unload(llm.embedding_model())
        ended = now()
        with SERVER_LOG.open("rb") as f:
            f.seek(offset)
            window = f.read().decode(errors="replace")
    finally:
        release_lock()
    chat_lines = count_requests(window, "/api/chat")
    record = {
        "name": name, "prompt_version": version, "prompt_sha256": sha256_file(PROMPTS[version]), "split": split,
        "policy": "none", "started_utc": started, "ended_utc": ended, "model_calls": runner.calls,
        "status": {s: sum(x["status"] == s for x in states) for s in ("sent", "error")},
        "loaded_before_unload": loaded,
        "server_log": {"chat_lines": chat_lines, "embed_lines": count_requests(window, "/api/embed"),
                       "isolated": chat_lines == runner.calls,
                       "rotated": SERVER_LOG.stat().st_size < offset},
        "preflight": facts, "python": platform.python_version(), "platform": platform.platform(),
    }
    (out / "run.json").write_text(json.dumps(record, indent=1) + "\n")
    print(json.dumps(record, indent=1))
    if not record["server_log"]["isolated"]:
        print(f"\nFLAGGED: {chat_lines} /api/chat lines in the window for {runner.calls} calls of this run. "
              "Per PROTOCOL-B.md, the run is repeated once under a new name, recorded as a deviation.")


# ------------------------------------------------------------------------------------------- reproduction, export


def reproduce() -> None:
    for name in (BASELINE_RUN, RERUN):
        if not (RUNS_B / name / "run.json").exists():
            sys.exit(f"run {name} first")
    if not STORED_18.exists():
        sys.exit(f"#18's stored chain run is not on this machine ({rel(STORED_18)})")
    v3a, v3b, stored = load_run(RUNS_B / BASELINE_RUN), load_run(RUNS_B / RERUN), load_run(STORED_18)
    result = {"v3a_against_18": compare_runs(stored, v3a), "v3a_against_v3b": compare_runs(v3a, v3b),
              "isolation": {n: json.loads((RUNS_B / n / "run.json").read_text())["server_log"] for n in (BASELINE_RUN, RERUN)},
              "median_reply_length": {"18": median_length(stored), "v3a": median_length(v3a), "v3b": median_length(v3b)}}
    (RUNS_B / "reproduce.json").write_text(json.dumps(result, indent=1) + "\n")
    for label, c in (("v3a against #18's stored chain", result["v3a_against_18"]), ("v3a against v3b", result["v3a_against_v3b"])):
        print(f"{label}: of {c['emails']} emails, same extraction {c['same_extraction']}, same chunks {c['same_chunks']}, "
              f"same reply text {c['same_reply']}; different replies: {c['different_reply'] or 'none'}")
        for stop in c["stops"]:
            print(f"  STOP: {stop}")
    print("isolation:", json.dumps(result["isolation"]))
    print("Reply text only: whether outcomes agree is for the labels. Pause here for review before any v4 run.")


def export() -> None:
    if REPLIES_B.exists():
        sys.exit(f"{rel(REPLIES_B)} already exists; the export runs once")
    missing = [n for n in RUN_PLAN if not (RUNS_B / n / "run.json").exists()]
    if missing:
        sys.exit(f"runs missing: {missing}")
    document = {
        "_comment": ("Every Part B run, exported by run_b.py export: per run, its record (run.json) and, per email, "
                     "the extraction, retrieved chunk ids, reply, 01-style label key and SHA-256. 'stored_18_chain' is "
                     "#18's chain run from 01's local runs, for the reproduction comparison."),
        "runs": {n: {"record": json.loads((RUNS_B / n / "run.json").read_text()), "emails": load_run(RUNS_B / n)}
                 for n in RUN_PLAN},
        "stored_18_chain": load_run(STORED_18),
    }
    REPLIES_B.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {rel(REPLIES_B)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    one = sub.add_parser("run")
    one.add_argument("name", choices=list(RUN_PLAN))
    sub.add_parser("reproduce")
    sub.add_parser("export")
    args = parser.parse_args()
    if args.command == "preflight":
        facts, problems = preflight_problems()
        print(json.dumps(facts, indent=1))
        print(f"connections to the Ollama port now: {clients()}; lock {'held' if LOCK.exists() else 'free'}")
        if problems:
            sys.exit("PREFLIGHT FAILED:\n  " + "\n  ".join(problems))
        print("preflight passed (no model call made)")
    elif args.command == "run":
        run(args.name)
    elif args.command == "reproduce":
        reproduce()
    else:
        export()


if __name__ == "__main__":
    main()
