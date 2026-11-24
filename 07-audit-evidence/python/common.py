"""Shared helpers: paths, canonical JSON, hashes, the fake clock, manifests, action fingerprints.

The rules here are fixed in PROTOCOL.md ("Rules fixed in advance"); keep them in step with it.
"""

import datetime as dt
import hashlib
import hmac
import json
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent
DATA = DEMO / "data"
ZERO = "0" * 64


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def keyed(key: bytes, data: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def load(name: str, data_dir: Path = DATA):
    return json.loads((data_dir / name).read_text(encoding="utf-8"))


# --- fake clock: ISO 8601 UTC strings ------------------------------------------------------

def parse(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fmt(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plus(ts: str, minutes: float = 0, days: float = 0) -> str:
    return fmt(parse(ts) + dt.timedelta(minutes=minutes, days=days))


# --- actions -------------------------------------------------------------------------------

def cents(amount) -> int:
    return round(float(amount) * 100)


def normal_action(action: dict) -> dict:
    """The canonical form of an action: what the fingerprint covers."""
    out = {"action": action["action"]}
    if "amount" in action:
        out["amount_cents"] = cents(action["amount"])
    if "months" in action:
        out["months"] = int(action["months"])
    return out


def action_sha(action: dict) -> str:
    return sha(canon(normal_action(action)))


# --- release manifests ---------------------------------------------------------------------

def manifest(release_id: str, data_dir: Path = DATA) -> dict:
    """The manifest for a release, computed from data/releases.json and the files it names."""
    spec = load("releases.json", data_dir)["releases"][release_id]
    policies = load("policies.json", data_dir)["versions"]
    components = {}
    for name, component in spec.items():
        component = dict(component)
        if "file" in component:
            component["sha256"] = sha((data_dir / component["file"]).read_bytes())
        if name == "policy":
            component["sha256"] = sha(canon(policies[component["version"]]))
        components[name] = component
    return {"release": release_id, "components": components}


def manifest_sha(m: dict) -> str:
    return sha(canon(m))


def diff_components(a: dict, b: dict) -> list[str]:
    names = set(a["components"]) | set(b["components"])
    return sorted(n for n in names if a["components"].get(n) != b["components"].get(n))
