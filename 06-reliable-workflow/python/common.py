"""Shared helpers: fixtures, a fake clock shared by every process in a scenario, crash points, SQLite."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent
DATA = DEMO / "data"

CRASH_EXIT = 70  # the process "dies" at a crash point
REFUSED_EXIT = 3  # a resume refused to run (incompatible record)

# The crash sweep's points (PROTOCOL.md, E6), mapped to the names the code checks.
CRASH_POINTS = {
    "P01": "understand.after_model",
    "P02": "understand.after_save",
    "P03": "check.after_save",
    "P04": "change_plan.before_call",
    "P05": "billing.after_commit",
    "P06": "change_plan.after_record",
    "P07": "apply_credit.before_call",
    "P08": "credits.after_commit",
    "P09": "apply_credit.after_record",
    "P10": "helpdesk.after_commit",
    "P11": "draft.after_save",
    "P12": "email.after_commit",
    "P13": "workflow.after_complete",
}


def load_fixtures():
    return json.loads((DATA / "fixtures.json").read_text())


def crash_point(name):
    """Exit at once, without cleanup, if this is the configured crash point."""
    if os.environ.get("CRASH_AT") == name:
        os._exit(CRASH_EXIT)


def connect(path):
    """A connection in autocommit mode: every transaction is an explicit BEGIN ... COMMIT."""
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    return db


def write_json(path, value):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True))
    os.replace(tmp, path)


class Clock:
    """A fake clock in a file, so a crashed process and its replacement share one timeline."""

    def __init__(self, directory):
        self.path = Path(directory) / "clock.json"

    def start(self, iso):
        seconds = int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
        write_json(self.path, {"now": seconds})

    def now(self):
        return json.loads(self.path.read_text())["now"]

    def advance(self, seconds):
        write_json(self.path, {"now": self.now() + seconds})

    def iso(self):
        return datetime.fromtimestamp(self.now(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scenario_config(directory):
    """Faults and service capabilities for this scenario (scenario.json)."""
    path = Path(directory) / "scenario.json"
    return json.loads(path.read_text()) if path.exists() else {}
