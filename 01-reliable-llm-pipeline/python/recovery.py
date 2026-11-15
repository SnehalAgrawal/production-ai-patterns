"""
Experiment 4: a crash, and three ways to recover from it.

The checked pipeline runs over the split in settings.json as a separate process, which ends abruptly right
after the reply to one email is written to the outbox and before that email's state records it. Then each
recovery starts from its own copy of what the crash left behind:

  restart   run every email again; the outbox survives (it stands for email already sent), the state doesn't
  resume    reuse every step the saved state records, and run the rest
  resume, check outbox   the same, and before writing a reply, look for one already in the outbox

For each: the model calls the recovery made, and the outbox and review entries written twice.
Each process starts with the chat model unloaded.
"""
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import llm
import pipeline

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "runs" / "python" / "recovery"


def run(run_dir: Path, split: str, *flags: str) -> subprocess.CompletedProcess:
    llm.unload(llm.chat_model())
    command = [sys.executable, str(HERE / "pipeline.py"), str(run_dir), "--split", split, "--policy", "validate", *flags]
    return subprocess.run(command, capture_output=True, text=True, cwd=HERE)


def twice(store: pipeline.Store, name: str) -> list[str]:
    return sorted(e for e, n in Counter(r["email"] for r in store.lines(name)).items() if n > 1)


def main() -> None:
    data = pipeline.load()
    crash = data["settings"]["crash"]
    split = crash["split"]
    if RUNS.exists():
        shutil.rmtree(RUNS)
    RUNS.mkdir(parents=True)

    crashed = RUNS / "crashed"
    result = run(crashed, split, "--crash", "--keep-loaded")
    store = pipeline.Store(crashed)
    states = [store.state(e) for e in data["splits"][split] if store.state(e)]
    calls = sum(len(s["steps"][k]["attempts"]) for s in states for k in ("extract", "draft") if k in s["steps"])
    print(f"4. A crash right after the reply to {crash['email']} was written to the outbox, before its state recorded it")
    print(f"   the crashed run: exit code {result.returncode}, {len(states)} of {len(data['splits'][split])} emails "
          f"started, {calls} model calls, {len(store.lines('outbox.jsonl'))} replies in the outbox, "
          f"{len(store.lines('review.jsonl'))} in the review queue")
    print(f"   state of {crash['email']} after the crash: steps {', '.join(store.state(crash['email'])['steps'])}")

    first = {r["email"]: r["reply"] for r in store.lines("outbox.jsonl")}
    print(f"   {'recovery':<30}{'exit':>5}{'calls':>7}{'outbox':>8}{'sent twice':>12}{'same text':>11}{'reviewed twice':>16}")
    for name, flags, keep_state in (("restart", [], False), ("resume", ["--resume"], True),
                                    ("resume, check outbox", ["--resume", "--check-outbox"], True)):
        target = RUNS / name.replace(", ", "-").replace(" ", "-")
        if keep_state:
            shutil.copytree(crashed, target)
        else:
            target.mkdir()
            for f in ("outbox.jsonl", "review.jsonl"):
                if (crashed / f).exists():
                    shutil.copy(crashed / f, target / f)
        result = run(target, split, *flags)
        summary = json.loads(result.stdout.strip().splitlines()[-1])
        out = pipeline.Store(target)
        doubled = twice(out, "outbox.jsonl")
        same = sum(all(r["reply"] == first[e] for r in out.lines("outbox.jsonl") if r["email"] == e) for e in doubled)
        print(f"   {name:<30}{result.returncode:>5}{summary['calls']:>7}{len(out.lines('outbox.jsonl')):>8}"
              f"{len(doubled):>12}{same:>11}{len(twice(out, 'review.jsonl')):>16}")
        if doubled:
            print(f"     sent twice: {', '.join(doubled)}")
    llm.unload(llm.chat_model())
    llm.unload(llm.embedding_model())


if __name__ == "__main__":
    main()
