"""
Paths, hashing, the variant plan, and access to 01's pipeline and 02's labelling code.

01-reliable-llm-pipeline and 02-evaluation-regression are read-only here. Their modules are imported from
their own folders, unchanged:

  from 01: pipeline, steps, retrieval, chunkers, tokens, score, llm   (the support assistant and its checks)
  from 02: compare (the outcome of a reply from its per-question label), grade (the mechanical fact check),
           worksheet and import_labels (the blind worksheet and its import)

This module is called shared.py, not common.py, because 02 has a common.py that its own modules import.
"""
import hashlib
import importlib
import json
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent  # 04-cost-quality/
ROOT = DEMO.parent  # the repository
DATA = DEMO / "data"
RUNS = DEMO / "runs"  # one folder per run, git-ignored
WORKSHEET = DEMO / "worksheet"
SOURCE = ROOT / "01-reliable-llm-pipeline"
SOURCE_DATA = SOURCE / "data"
EVALUATION = ROOT / "02-evaluation-regression"

VARIANTS = DATA / "variants.json"
PRICES = DATA / "prices.json"
FROZEN = DATA / "FROZEN.json"
EXPORT = DATA / "runs.json"
BLIND = DATA / "blind_labels.json"
FINAL = DATA / "final_labels.json"


def source_module(name: str):
    """Import a module from 01's python/ folder (first) or 02's (second), unchanged."""
    for folder in (SOURCE / "python", EVALUATION / "python"):
        if str(folder) not in sys.path:
            sys.path.append(str(folder))
    return importlib.import_module(name)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_json(value) -> str:
    """A hash of a JSON value that doesn't depend on key order or spacing."""
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def rel(path: Path) -> str:
    return Path(path).resolve().relative_to(ROOT).as_posix()


def reply_key(eid: str, reply: str) -> str:
    """01's label key: the first 16 hex digits of SHA-256 over 'email id, newline, reply'."""
    return source_module("score").Scorer.key(eid, reply)


def variants() -> dict:
    return json.loads(VARIANTS.read_text())


def emails(split: str) -> list[str]:
    return json.loads((SOURCE_DATA / "splits.json").read_text())[split]


def labels() -> dict:
    """01's labels: per email, its questions, whether each is answerable, and the facts a reply must state."""
    return json.loads((SOURCE_DATA / "labels.json").read_text())["emails"]
