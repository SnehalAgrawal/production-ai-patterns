"""A scripted stand-in for the model. No model is run.

Each email has a list of raw outputs per step in data/fixtures.json. The n-th call for (email, step) gets
the n-th output (the last one repeats). "UNAVAILABLE" means the call fails. Calls are logged to an
append-only file before the output is returned, so a call made just before a crash still counts.
"""

import json
import os
from pathlib import Path


class ModelUnavailable(Exception):
    pass


class ScriptedModel:
    def __init__(self, directory, fixtures):
        self.log = Path(directory) / "model_calls.jsonl"
        self.fixtures = fixtures

    def calls(self, email_id=None, step=None):
        if not self.log.exists():
            return 0
        rows = [json.loads(line) for line in self.log.read_text().splitlines() if line]
        return sum(1 for r in rows if (email_id is None or r["email"] == email_id)
                   and (step is None or r["step"] == step))

    def call(self, email_id, step, problems=None):
        n = self.calls(email_id, step)
        script = self.fixtures["emails"][email_id]["model"][step]
        name = script[min(n, len(script) - 1)]
        with self.log.open("a") as f:
            f.write(json.dumps({"email": email_id, "step": step, "n": n + 1, "output": name,
                                "repair": bool(problems)}) + "\n")
            f.flush()
            os.fsync(f.fileno())
        if name == "UNAVAILABLE":
            raise ModelUnavailable(f"{step}: model unavailable")
        library = self.fixtures["readings"] if step == "understand" else self.fixtures["drafts"]
        return library[name]
