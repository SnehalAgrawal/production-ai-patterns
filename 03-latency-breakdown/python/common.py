"""
Shared by every script: the settings, the clock, the seeded delays, and JSON lines.

Every timestamp is time.monotonic_ns(). Python's documentation: a clock "that cannot go backwards", the same for all
processes (on macOS since Python 3.10), so the client's, the application's and the stand-in services' timestamps can
be subtracted from each other. See PROTOCOL.md, "Clock".
"""
import copy
import hashlib
import json
import math
import random
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
RUNS = ROOT / "runs"
NS_PER_MS = 1_000_000


def now_ns() -> int:
    return time.monotonic_ns()


def sleep_until(target_ns: int) -> None:
    """Sleep until a target time, so a series of steps doesn't accumulate each sleep's overshoot."""
    left = target_ns - now_ns()
    if left > 0:
        time.sleep(left / 1e9)


def load_settings() -> dict:
    return json.loads((DATA / "settings.json").read_text())


def merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def variant_settings(name: str) -> dict:
    settings = load_settings()
    config = merge(settings["base"], settings["variants"][name])
    config["seed"] = settings["seed"]
    config["variant"] = name
    return config


def rng(seed: int, *parts) -> random.Random:
    """A random generator fixed by the seed and a name, e.g. rng(35, "billing", 12): the same draw in every run."""
    return random.Random(":".join(str(p) for p in (seed, *parts)))


def jitter(seed: int, sigma: float, *parts) -> float:
    """A multiplicative log-normal factor with median 1, fixed per seed and name."""
    return math.exp(rng(seed, "jitter", *parts).gauss(0.0, sigma)) if sigma else 1.0


def needs_tool(config: dict, index: int) -> bool:
    return index >= 0 and rng(config["seed"], "tool", index).random() < config["tool_share"]


def billing_is_slow(config: dict, index: int) -> bool:
    p = config["billing"]["slow_probability"]
    return index >= 0 and p > 0 and rng(config["seed"], "billing-slow", index).random() < p


class JsonLines:
    """Append one JSON object per line, from several threads."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict) -> None:
        line = json.dumps(record, separators=(",", ":")) + "\n"
        with self.lock, open(self.path, "a") as f:
            f.write(line)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
