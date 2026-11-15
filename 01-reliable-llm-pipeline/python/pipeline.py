"""
The pipeline: one email at a time, through four steps, with the email's state saved after every step.

  1 extract   model call: the questions and the product identifiers in the email
  2 retrieve  documentation excerpts for the questions
  3 draft     model call: a reply that cites the excerpts it used
  4 send      the reply is written to the outbox (nothing is emailed); an email that fails its checks goes
              to the review queue instead

Two policies:
  none      no checks. Each step's output is passed on as it is, and every reply is sent. An output that
            can't be used at all (not JSON, or without the fields the next step needs) stops the email.
  validate  each step's output is checked before it is passed on (steps.py). A model step that fails is
            called again with its previous output and the problems, up to max_retries times; an email that
            still fails, or whose retrieval fails, goes to the review queue.

A run directory holds state/<email>.json (every step's output and every model call), outbox.jsonl (one line
per reply sent), and review.jsonl (one line per email sent to review).

  python pipeline.py RUN_DIR --split test --policy validate [--resume] [--check-outbox] [--crash]

--resume reuses the steps an email's state already records. --check-outbox skips writing a reply when the
outbox already has one for that email. --crash ends the process abruptly, right after the reply to the
email named in settings.json is written to the outbox and before its state records that.
"""
import argparse
import json
import os
from pathlib import Path

import llm
import steps
from retrieval import Index
from tokens import Tokenizer

DATA = Path(__file__).resolve().parent.parent / "data"


def load() -> dict:
    return {
        "settings": json.loads((DATA / "settings.json").read_text()),
        "prompts": json.loads((DATA / "prompts.json").read_text()),
        "documents": {p.name: p.read_text() for p in sorted((DATA / "documents").glob("*.md"))},
        "emails": {p.stem: p.read_text() for p in sorted((DATA / "emails").glob("*.txt"))},
        "splits": json.loads((DATA / "splits.json").read_text()),
    }


class Store:
    """Where a run keeps its state and its side effects."""

    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        (self.dir / "state").mkdir(parents=True, exist_ok=True)

    def state(self, eid: str) -> dict | None:
        path = self.dir / "state" / f"{eid}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def save(self, state: dict) -> None:
        path = self.dir / "state" / f"{state['email']}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n")
        os.replace(temporary, path)  # a crash leaves either the old state or the new one, never half of it

    def append(self, name: str, record: dict) -> None:
        with open(self.dir / name, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def lines(self, name: str) -> list[dict]:
        path = self.dir / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class Pipeline:
    def __init__(self, data: dict, index: Index, policy: str):
        self.data, self.index, self.policy = data, index, policy
        self.settings, self.prompts = data["settings"], data["prompts"]
        self.documentation = "\n\n".join(data["documents"].values())
        self.calls = 0

    def model_step(self, messages: list[dict], schema: dict, max_tokens: int, check) -> dict:
        """One model step: call, parse, check, and retry with the problems while the policy allows."""
        attempts = []
        while True:
            call = llm.chat(messages, schema=schema, options=self.settings["chat"]["options"], max_tokens=max_tokens)
            self.calls += 1
            output, error = steps.parse(call["content"])
            problems = [error] if error else (check(output) if self.policy == "validate" else [])
            attempts.append({**call, "problems": problems})
            if not problems or self.policy != "validate" or len(attempts) > self.settings["retries"]["max_retries"]:
                return {"attempts": attempts, "output": output, "ok": not problems}
            messages = steps.retry_messages(self.prompts, messages, call["content"], problems)

    def process(self, eid: str, store: Store, resume: bool, check_outbox: bool, crash: bool) -> dict:
        email = self.data["emails"][eid]
        state = (store.state(eid) if resume else None) or {"email": eid, "policy": self.policy, "steps": {}}
        done = state["steps"]

        def finish(status: str, reason: str | None = None) -> dict:
            state["status"], state["reason"] = status, reason
            store.save(state)
            return state

        # 1 extract
        if "extract" not in done:
            done["extract"] = self.model_step(steps.extract_messages(self.prompts, email), steps.EXTRACT_SCHEMA,
                                              self.settings["chat"]["extract_max_tokens"],
                                              lambda output: steps.check_extract(output, email))
            store.save(state)
        extracted = done["extract"]["output"]
        if self.policy == "validate" and not done["extract"]["ok"]:
            return self.review(eid, store, state, finish, "extract", done["extract"]["attempts"][-1]["problems"])
        if not isinstance(extracted, dict) or not steps.is_string_list(extracted.get("questions")):
            return finish("error", "the extraction has no usable list of questions")
        questions = extracted["questions"]

        # 2 retrieve
        if "retrieve" not in done:
            chosen = self.index.retrieve(questions)
            excerpts = [self.index.chunks[i].text for i in chosen]
            identifiers = extracted.get("identifiers") if steps.is_string_list(extracted.get("identifiers")) else []
            problems = (steps.check_retrieve(identifiers, excerpts, self.documentation,
                                             self.settings["checks"]["plan_names"])
                        if self.policy == "validate" else [])
            done["retrieve"] = {"chunks": [self.index.chunks[i].id for i in chosen], "problems": problems}
            store.save(state)
        by_id = {c.id: c for c in self.index.chunks}
        context = [by_id[c] for c in done["retrieve"]["chunks"]]
        if done["retrieve"]["problems"]:
            return self.review(eid, store, state, finish, "retrieve", done["retrieve"]["problems"])

        # 3 draft
        if "draft" not in done:
            texts = [c.text for c in context]
            done["draft"] = self.model_step(
                steps.draft_messages(self.prompts, email, questions, [(c.document, c.text) for c in context]),
                steps.DRAFT_SCHEMA, self.settings["chat"]["draft_max_tokens"],
                lambda output: steps.check_draft(output, texts, email))
            store.save(state)
        drafted = done["draft"]["output"]
        if self.policy == "validate" and not done["draft"]["ok"]:
            return self.review(eid, store, state, finish, "draft", done["draft"]["attempts"][-1]["problems"])
        if not isinstance(drafted, dict) or not isinstance(drafted.get("reply"), str):
            return finish("error", "the draft has no usable reply")

        # 4 send
        if "send" in done:  # resumed after the send was recorded: nothing left to do
            return state
        if check_outbox and any(r["email"] == eid for r in store.lines("outbox.jsonl")):
            done["send"] = {"to": "outbox", "already_there": True}
            return finish("sent")
        store.append("outbox.jsonl", {"email": eid, "reply": drafted["reply"]})
        if crash and eid == self.settings["crash"]["email"]:
            os._exit(self.settings["crash"]["exit_code"])  # no clean-up, as if the process were killed
        done["send"] = {"to": "outbox"}
        return finish("sent")

    def review(self, eid, store, state, finish, step, problems) -> dict:
        if "send" not in state["steps"]:
            store.append("review.jsonl", {"email": eid, "step": step, "problems": problems})
            state["steps"]["send"] = {"to": "review"}
        return finish("review", f"{step}: " + "; ".join(problems))

    def run(self, eids: list[str], store: Store, resume=False, check_outbox=False, crash=False) -> list[dict]:
        return [self.process(eid, store, resume, check_outbox, crash) for eid in eids]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--split", default="test", choices=["dev", "test"])
    parser.add_argument("--policy", default="validate", choices=["none", "validate"])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--check-outbox", action="store_true")
    parser.add_argument("--crash", action="store_true")
    parser.add_argument("--keep-loaded", action="store_true", help="don't unload the chat model at the end")
    args = parser.parse_args()
    data = load()
    pipeline = Pipeline(data, Index(data["settings"], data["documents"], Tokenizer()), args.policy)
    try:
        states = pipeline.run(data["splits"][args.split], Store(Path(args.run_dir)), args.resume, args.check_outbox,
                              args.crash)
    finally:
        if not args.keep_loaded:
            llm.unload(llm.chat_model())
    counts = {s: sum(x["status"] == s for x in states) for s in ("sent", "review", "error")}
    print(json.dumps({"emails": len(states), "calls": pipeline.calls, **counts}, separators=(",", ":")))


if __name__ == "__main__":
    main()
