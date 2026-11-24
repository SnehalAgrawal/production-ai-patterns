"""
Paths, hashing, and access to 01-reliable-llm-pipeline's frozen test material.

01 is read-only here. Its scoring module (python/score.py) and its matching rules (python/steps.py) are
imported, not copied, so the fact check below is exactly the one 01 defined before any reply existed.
"""
import hashlib
import importlib
import json
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent  # 02-evaluation-regression/
ROOT = DEMO.parent  # the repository
DATA = DEMO / "data"
RUNS = DEMO / "runs"  # reports and per-case records; git-ignored
SOURCE = ROOT / "01-reliable-llm-pipeline"
SOURCE_DATA = SOURCE / "data"
SOURCE_PY = SOURCE / "python"

# The two arms of Part A, both prompt v3, on the same 20 test emails.
#   chain            01's pipeline end to end with no checks: extract, retrieve, draft
#   perfect_inputs   drafting alone, from the labelled questions with every evidence passage in context
BASELINE = "chain"
CANDIDATE = "perfect_inputs"
ARMS = (BASELINE, CANDIDATE)


def source_module(name: str):
    """Import one of 01's modules (score, steps) from 01's python/ folder, unchanged."""
    if str(SOURCE_PY) not in sys.path:
        sys.path.append(str(SOURCE_PY))
    return importlib.import_module(name)


def scorer():
    """01's Scorer: the labels (data/labels.json) and 01's hand labels (data/hand_labels.json)."""
    return source_module("score").Scorer()


def reply_key(eid: str, reply: str) -> str:
    """01's label key: the first 16 hex digits of SHA-256 over 'email id, newline, reply'."""
    return source_module("score").Scorer.key(eid, reply)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    """A path relative to the repository root, as recorded in FROZEN.json."""
    return path.resolve().relative_to(ROOT).as_posix()


def test_emails() -> list[str]:
    return json.loads((SOURCE_DATA / "splits.json").read_text())["test"]


def load_replies(path: Path = DATA / "replies.json") -> list[dict]:
    return json.loads(path.read_text())["replies"]
