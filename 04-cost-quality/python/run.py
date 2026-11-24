"""
The runs: 01's support assistant, unchanged, with one thing changed per run (data/variants.json).

  python run.py preflight      checks only: frozen hashes, packages, Ollama version, model IDs; no model call
  python run.py run NAME       one run, in the order of data/variants.json (b0dev, b0, v1, v2, v3, v3r)
  python run.py export         data/runs.json from every run (once, after the last run)

What a run changes, and nothing else:
  - the chat model per step (extraction and drafting can use different models), by wrapping 01's model step;
  - values in 01's settings (the retrieval budget, the drafting output cap).
01's prompts (v3), emails, documents, retrieval code and checks are used as they are, with policy 'none': every
reply is sent as the model wrote it, as in #18's chain run and #33's runs.

Every run repeats the preflight, takes the shared Ollama lock (never taking it over), waits until no other client
has used the server for 60 seconds, unloads loaded models before and the run's models after, and compares its own
model calls with the /api/chat lines in the server log for the run's window. Runs go to runs/<name>/ (git-ignored).
Each name runs once.
"""
import argparse
import copy
import importlib.metadata
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from freeze import verify_frozen
from shared import (
    DEMO,
    EXPORT,
    RUNS,
    SOURCE_DATA,
    emails,
    rel,
    reply_key,
    sha256_file,
    sha256_json,
    sha256_text,
    source_module,
    variants,
)

BASE_URL = "http://localhost:11434"
SERVER_LOG = Path.home() / ".ollama" / "logs" / "server.log"
LOCK = Path(os.environ.get("TMPDIR", "/tmp")) / "snehalagrawal-ollama.lock"
QUIET_SECONDS = 60
EMBEDDING_MODEL = "nomic-embed-text:latest"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------------------------------- what a run uses


def cap_from(run_dir: Path) -> int:
    """v2's output cap: the median output tokens of a run's draft calls, rounded up to the next multiple of 10."""
    counts = []
    for path in sorted((run_dir / "state").glob("*.json")):
        draft = json.loads(path.read_text())["steps"].get("draft")
        if draft:
            counts.append(draft["attempts"][0]["output_tokens"])
    if not counts:
        raise ValueError(f"{rel(run_dir)} has no draft calls")
    return int(math.ceil(statistics.median(counts) / 10) * 10)


def settings_for(name: str) -> tuple[dict, dict]:
    """(01's settings with this run's overrides applied, the overrides as applied)."""
    plan = variants()["runs"][name]
    settings = json.loads((SOURCE_DATA / "settings.json").read_text())
    applied = copy.deepcopy(plan["overrides"])
    for section, values in applied.items():
        for key, value in values.items():
            if value == "cap_from_b0dev":
                if not (RUNS / "b0dev" / "run.json").exists():
                    raise SystemExit("v2's cap comes from b0dev: run b0dev first")
                values[key] = value = cap_from(RUNS / "b0dev")
            if key not in settings[section]:
                raise KeyError(f"{section}.{key} is not one of 01's settings")
            settings[section][key] = value
    return settings, applied


def variant_pipeline(models: dict[str, str]):
    """01's Pipeline with one chat model per step. Each recorded call also records its model."""
    pipeline, steps, llm = source_module("pipeline"), source_module("steps"), source_module("llm")

    class VariantPipeline(pipeline.Pipeline):
        def __init__(self, data, index):
            super().__init__(data, index, "none")
            self.by_model = Counter()

        def model_step(self, messages, schema, max_tokens, check):
            model = models["extract" if schema is steps.EXTRACT_SCHEMA else "draft"]
            original = llm.chat_model
            llm.chat_model = lambda: model  # 01's llm.chat() asks chat_model() for the model on every call
            try:
                result = super().model_step(messages, schema, max_tokens, check)
            finally:
                llm.chat_model = original
            for attempt in result["attempts"]:
                attempt["model"] = model
                self.by_model[model] += 1
            return result

    return VariantPipeline


# ------------------------------------------------------------------------------------------- preflight


def pinned_versions() -> dict[str, str]:
    lines = (DEMO / "python" / "requirements.txt").read_text().splitlines()
    return dict(line.split("==") for line in lines if "==" in line)


def preflight_problems() -> tuple[dict, list[str]]:
    expected = variants()["expected"]
    facts, problems = {}, []
    problems += [f"FROZEN.json: {p}" for p in verify_frozen()]
    for package, version in pinned_versions().items():
        installed = importlib.metadata.version(package)
        facts[package] = installed
        if installed != version:
            problems.append(f"{package} {installed} installed, {version} pinned")
    for variable in ("OLLAMA_CHAT_MODEL", "OLLAMA_EMBEDDING_MODEL", "OLLAMA_BASE_URL"):
        if variable in os.environ:
            problems.append(f"{variable} is set; unset it so 01's defaults apply")
    llm = source_module("llm")
    if (llm.embedding_model(), llm.base_url()) != ("nomic-embed-text", BASE_URL):
        problems.append(f"01's llm module resolves {llm.embedding_model()} at {llm.base_url()}")
    facts["ollama"] = requests.get(f"{BASE_URL}/api/version", timeout=10).json()["version"]
    if facts["ollama"] != expected["ollama"]:
        problems.append(f"Ollama {facts['ollama']}, expected {expected['ollama']}")
    tags = {m["name"]: m["digest"] for m in requests.get(f"{BASE_URL}/api/tags", timeout=10).json()["models"]}
    facts["models"] = {name: tags.get(name, "")[:12] for name in expected["models"]}
    for name, digest in expected["models"].items():
        if not tags.get(name, "").startswith(digest):
            problems.append(f"{name}: ID {tags.get(name, 'missing')[:12]}, expected {digest}")
    if not SERVER_LOG.exists():
        problems.append(f"no server log at {SERVER_LOG}: isolation can't be checked")
    return facts, problems


def clients() -> int:
    out = subprocess.run(["lsof", "-nP", "-iTCP:11434", "-sTCP:ESTABLISHED"], capture_output=True, text=True).stdout
    return max(0, len(out.splitlines()) - 1)


def wait_for_quiet(limit_seconds: int = 1800) -> None:
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
    owner = {"session": "Article #36, 04-cost-quality", "run": name, "pid": os.getpid(), "since_utc": now()}
    (LOCK / "owner.json").write_text(json.dumps(owner) + "\n")


def release_lock() -> None:
    (LOCK / "owner.json").unlink(missing_ok=True)
    LOCK.rmdir()


def count_requests(log_text: str, endpoint: str) -> int:
    return sum(1 for line in log_text.splitlines() if "[GIN]" in line and f'"{endpoint}"' in line)


def unload(model: str) -> None:
    requests.post(f"{BASE_URL}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60).raise_for_status()


# ------------------------------------------------------------------------------------------- one run


def run(name: str) -> None:
    plan_all = variants()
    plan = plan_all["runs"][name]
    out = RUNS / name
    if out.exists():
        sys.exit(f"{rel(out)} exists; each run name is used once")
    order = plan_all["order"]
    missing = [n for n in order[:order.index(name)] if not (RUNS / n / "run.json").exists()]
    if missing:
        sys.exit(f"runs go in the order {order}; first run {missing}")
    facts, problems = preflight_problems()
    if problems:
        sys.exit("PREFLIGHT FAILED:\n  " + "\n  ".join(problems))
    settings, applied = settings_for(name)

    pipeline = source_module("pipeline")
    Index, Tokenizer = source_module("retrieval").Index, source_module("tokens").Tokenizer
    models = plan["models"]
    acquire_lock(name)
    try:
        wait_for_quiet()
        loaded = [m["name"] for m in requests.get(f"{BASE_URL}/api/ps", timeout=10).json()["models"]]
        for model in loaded:
            unload(model)
        offset, started = SERVER_LOG.stat().st_size, now()
        data = pipeline.load()
        data["settings"] = settings
        runner = variant_pipeline(models)(data, Index(settings, data["documents"], Tokenizer()))
        try:
            states = runner.run(emails(plan["split"]), pipeline.Store(out))
        finally:
            for model in sorted(set(models.values())) + [EMBEDDING_MODEL]:
                unload(model)
        ended = now()
        with SERVER_LOG.open("rb") as f:
            f.seek(offset)
            window = f.read().decode(errors="replace")
    finally:
        release_lock()
    chat_lines = count_requests(window, "/api/chat")
    record = {
        "name": name, "split": plan["split"], "models": models, "overrides": applied,
        "settings_sha256": sha256_json(settings), "prompts_sha256": sha256_file(SOURCE_DATA / "prompts.json"),
        "policy": "none", "started_utc": started, "ended_utc": ended, "model_calls": runner.calls,
        "calls_by_model": dict(runner.by_model),
        "status": {s: sum(x["status"] == s for x in states) for s in ("sent", "error")},
        "loaded_before_run": loaded,
        "server_log": {"chat_lines": chat_lines, "embed_lines": count_requests(window, "/api/embed"),
                       "isolated": chat_lines == runner.calls, "rotated": SERVER_LOG.stat().st_size < offset},
        "preflight": facts, "python": platform.python_version(), "platform": platform.platform(),
    }
    (out / "run.json").write_text(json.dumps(record, indent=1) + "\n")
    print(json.dumps(record, indent=1))
    if not record["server_log"]["isolated"]:
        print(f"\nFLAGGED: {chat_lines} /api/chat lines in the window for {runner.calls} calls of this run. "
              "Per PROTOCOL.md, the run is repeated once under a new name, recorded as a deviation.")


# ------------------------------------------------------------------------------------------- export


def email_record(state: dict, chunk_text: dict[str, str], tokenizer, query_prefix: str) -> dict:
    """What a run did for one email: extraction, chunks, reply, every model call, and 01's draft check."""
    steps_module = source_module("steps")
    eid, done = state["email"], state["steps"]
    extraction = done.get("extract", {}).get("output")
    chunks = done.get("retrieve", {}).get("chunks")
    draft = done.get("draft")
    output = draft["output"] if draft else None
    reply = output.get("reply") if isinstance(output, dict) and isinstance(output.get("reply"), str) else None
    calls = [{"step": step, **{k: a[k] for k in ("model", "prompt_tokens", "output_tokens", "done_reason", "seconds")}}
             for step in ("extract", "draft") if step in done for a in done[step]["attempts"]]
    check = None
    if draft:
        email = (SOURCE_DATA / "emails" / f"{eid}.txt").read_text()
        _, parse_error = steps_module.parse(draft["attempts"][-1]["content"])
        check = [parse_error] if parse_error else steps_module.check_draft(output, [chunk_text[c] for c in chunks],
                                                                            email)
    questions = extraction.get("questions") if isinstance(extraction, dict) else None
    embedded = chunks is not None and steps_module.is_string_list(questions)
    return {
        "status": state["status"], "reason": state["reason"], "extraction": extraction, "chunks": chunks,
        "reply": reply, "key": reply_key(eid, reply) if reply is not None else None,
        "sha256": sha256_text(reply) if reply is not None else None,
        "draft_inputs_sha256": sha256_json({"extraction": extraction, "chunks": chunks}) if draft else None,
        "calls": calls, "draft_check": check,
        "query_embeddings": len(questions) if embedded else 0,
        "query_embedding_tokens": sum(tokenizer.count(query_prefix + q) for q in questions) if embedded else 0,
    }


def export() -> None:
    if EXPORT.exists():
        sys.exit(f"{rel(EXPORT)} already exists; the export runs once")
    plan = variants()
    missing = [n for n in plan["order"] if not (RUNS / n / "run.json").exists()]
    if missing:
        sys.exit(f"runs missing: {missing}")
    pipeline, chunkers = source_module("pipeline"), source_module("chunkers")
    tokenizer = source_module("tokens").Tokenizer()
    data = pipeline.load()
    chunk_text = {c.id: c.text for c in chunkers.chunk(data["settings"]["chunking"], data["documents"], tokenizer)}
    prefix = data["settings"]["embedding"]["query_prefix"]
    runs = {}
    for name in plan["order"]:
        states = [json.loads(p.read_text()) for p in sorted((RUNS / name / "state").glob("*.json"))]
        runs[name] = {"record": json.loads((RUNS / name / "run.json").read_text()),
                      "emails": {s["email"]: email_record(s, chunk_text, tokenizer, prefix) for s in states}}
    document = {"_comment": ("Every run, exported by run.py export: per run, its record (run.json) and, per email, "
                             "the extraction, retrieved chunk ids, reply, 01-style label key, every model call with "
                             "its token counts, and 01's draft check applied to the draft."), "runs": runs}
    EXPORT.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {rel(EXPORT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    one = sub.add_parser("run")
    one.add_argument("name", choices=variants()["order"])
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
    else:
        export()


if __name__ == "__main__":
    main()
