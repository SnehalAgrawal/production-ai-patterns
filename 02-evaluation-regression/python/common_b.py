"""
Shared by Part B: what every run must use, where runs are kept, how two runs are compared, and the one
approved difference between the v3 and v4 prompts.

Part A's modules (common, check, grade, compare, report) are frozen; Part B imports them and adds this module.
"""
import json
import os
import statistics
from pathlib import Path

from common import DATA, RUNS, SOURCE, SOURCE_DATA, reply_key, sha256_text

RUNS_B = RUNS / "b"
REPLIES_B = DATA / "replies-b.json"
PROMPTS = {"v3": SOURCE_DATA / "prompts.json", "v4": DATA / "prompts-v4.json"}

# Each run name is used once, with a fixed prompt version and split (PROTOCOL-B.md).
RUN_PLAN = {"v3a": ("v3", "test"), "v3b": ("v3", "test"), "v4dev": ("v4", "dev"), "v4test": ("v4", "test")}
BASELINE_RUN, RERUN, DEV_RUN, CANDIDATE_RUN = "v3a", "v3b", "v4dev", "v4test"
LABELLED_RUNS = (BASELINE_RUN, RERUN, CANDIDATE_RUN)  # the test split; v4dev is never labelled
STORED_18 = SOURCE / "runs" / "python" / "test-none"  # #18's chain run, local to the machine that ran it

EXPECTED = {
    "ollama": "0.40.17",
    "models": {"llama3.2:3b": "a80c4f17acd5", "nomic-embed-text:latest": "0a109f422b47"},
    "resolved": {"chat_model": "llama3.2:3b", "embedding_model": "nomic-embed-text", "base_url": "http://localhost:11434"},
}
SERVER_LOG = Path.home() / ".ollama" / "logs" / "server.log"
LOCK = Path(os.environ.get("TMPDIR", "/tmp")) / "snehalagrawal-ollama.lock"
QUIET_SECONDS = 60
WORKSHEET_SEED = 33

V3_SENTENCE = ('- Be polite and brief. Greet the customer by name, don\'t repeat their email, and sign the reply '
               '"Support team".')
V4_SENTENCE = ('- Be warm and friendly, and thank the customer for getting in touch. Greet the customer by name, '
               'don\'t repeat their email, and sign the reply "Support team".')


def prompt_difference(v3: dict, v4: dict) -> list[str]:
    """Problems, if v4 differs from v3 in anything but the version label and the one approved drafting sentence."""
    problems = []
    if v4.get("version") != "v4":
        problems.append(f"v4's version label is {v4.get('version')!r}")
    if set(v3) != set(v4):
        problems.append("the two prompt files have different fields")
    for field in ("extract", "retry"):
        if v3.get(field) != v4.get(field):
            problems.append(f"the {field} prompt differs")
    if v3["draft"]["user"] != v4["draft"]["user"]:
        problems.append("the draft user template differs")
    old, new = v3["draft"]["system"].split("\n"), v4["draft"]["system"].split("\n")
    changed = [(a, b) for a, b in zip(old, new) if a != b]
    if len(old) != len(new) or changed != [(V3_SENTENCE, V4_SENTENCE)]:
        problems.append("the draft system prompt differs in something other than the approved sentence")
    return problems


def count_requests(log_text: str, endpoint: str) -> int:
    """Requests to one endpoint in Ollama server log text (its [GIN] access lines)."""
    return sum(1 for line in log_text.splitlines() if "[GIN]" in line and f'"{endpoint}"' in line)


# ------------------------------------------------------------------------------------------- runs as records


def email_record(state: dict) -> dict:
    """What a run did for one email, from 01's pipeline state: extraction, retrieved chunks, reply, status."""
    steps = state.get("steps", {})
    extraction = steps.get("extract", {}).get("output")
    chunks = steps.get("retrieve", {}).get("chunks")
    output = steps.get("draft", {}).get("output")
    reply = output.get("reply") if isinstance(output, dict) and isinstance(output.get("reply"), str) else None
    record = {"status": state.get("status"), "reason": state.get("reason"), "extraction": extraction,
              "chunks": chunks, "reply": reply, "key": None, "sha256": None}
    if reply is not None:
        record["key"], record["sha256"] = reply_key(state["email"], reply), sha256_text(reply)
    return record


def load_run(run_dir: Path) -> dict[str, dict]:
    """email id -> record, for every state file in a run directory."""
    return {p.stem: email_record(json.loads(p.read_text())) for p in sorted((run_dir / "state").glob("*.json"))}


def compare_runs(before: dict[str, dict], after: dict[str, dict]) -> dict:
    """
    Two runs of the same prompt over the same emails, compared as text, step by step.

    This compares what was produced, not whether it was right: identical replies are a claim about
    reproduction; whether outcomes agree is a separate question for the labels.

    Stop conditions (PROTOCOL-B.md): different chunks for an email whose extraction is identical, or an
    error in 'after' where 'before' had none. A different reply alone is a finding, not a stop.
    """
    if set(before) != set(after):
        raise ValueError("the two runs cover different emails")
    rows, stops = [], []
    for eid in sorted(before):
        a, b = before[eid], after[eid]
        row = {"email": eid, "same_extraction": a["extraction"] == b["extraction"],
               "same_chunks": a["chunks"] == b["chunks"], "same_reply": a["reply"] == b["reply"],
               "status": (a["status"], b["status"])}
        rows.append(row)
        if row["same_extraction"] and not row["same_chunks"]:
            stops.append(f"{eid}: same extraction, different chunks")
        if b["status"] == "error" and a["status"] != "error":
            stops.append(f"{eid}: a new error ({b['reason']})")
    return {
        "emails": len(rows),
        "same_extraction": sum(r["same_extraction"] for r in rows),
        "same_chunks": sum(r["same_chunks"] for r in rows),
        "same_reply": sum(r["same_reply"] for r in rows),
        "different_reply": [r["email"] for r in rows if not r["same_reply"]],
        "rows": rows,
        "stops": stops,
    }


def median_length(records: dict[str, dict]) -> float | None:
    lengths = [len(r["reply"]) for r in records.values() if r["reply"] is not None]
    return statistics.median(lengths) if lengths else None
