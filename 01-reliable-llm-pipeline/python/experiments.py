"""
Experiments 1 to 3 on one split of the emails (test by default), from real runs:

  1. Each step on its own, and the chain. Extraction on the email; retrieval from the labelled questions;
     a draft from the labelled questions and gold excerpts (the retrieved ones plus any chunk holding a
     missing evidence passage). Then the pipeline with no checks, from email to outbox.
  2. Checks between steps: what reaches the outbox with no checks, with checks but no retries, and with
     checks and retries. "Checks, no retries" is read from the checked run: an email stops at the first
     check that fails, and everything before that is the same request as in the checked run.
  3. Retries: which failures a retry with the problems fixes, and at what cost; and what the same request
     sent again, without the problems, returns.

Runs are kept in ../runs/python/<split>-*/. With --report, the report is printed from them again without
model calls. Every reply without a hand label is written to ../runs/python/<split>-to-read.md.
"""
import argparse
import json
import shutil
from pathlib import Path

import chunkers
import llm
import pipeline
import steps
from retrieval import Index
from score import Scorer
from tokens import Tokenizer

RUNS = Path(__file__).resolve().parent.parent / "runs" / "python"


def fresh(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def gold_context(index: Index, scorer: Scorer, eid: str) -> tuple[list[int], list[int]]:
    """Chunks retrieved for the labelled questions, plus the first chunk holding each missing evidence passage."""
    chosen = index.retrieve([q["asks"] for q in scorer.questions(eid)])
    added = []
    for q in scorer.questions(eid):
        for fact in q["facts"]:
            if not scorer.supported(fact, [index.chunks[i].text for i in chosen + added]):
                added.append(next(i for i, c in enumerate(index.chunks) if scorer.supported(fact, [c.text])))
    return chosen, added


def run_all(data: dict, split: str) -> None:
    index = Index(data["settings"], data["documents"], Tokenizer())
    eids = data["splits"][split]
    scorer = Scorer()
    options, prompts = data["settings"]["chat"]["options"], data["prompts"]
    try:
        for policy in ("none", "validate"):
            pipeline.Pipeline(data, index, policy).run(eids, pipeline.Store(fresh(RUNS / f"{split}-{policy}")))
            llm.unload(llm.chat_model())  # each run starts with the model freshly loaded

        isolated = fresh(RUNS / f"{split}-isolated")
        for eid in eids:
            chosen, added = gold_context(index, scorer, eid)
            context = [index.chunks[i] for i in chosen + added]
            questions = [q["asks"] for q in scorer.questions(eid)]
            call = llm.chat(steps.draft_messages(prompts, data["emails"][eid], questions,
                                                 [(c.document, c.text) for c in context]),
                            schema=steps.DRAFT_SCHEMA, options=options,
                            max_tokens=data["settings"]["chat"]["draft_max_tokens"])
            record = {"email": eid, "questions": questions, "chunks": [c.id for c in context],
                      "added": [index.chunks[i].id for i in added], "call": call, "output": steps.parse(call["content"])[0]}
            (isolated / f"{eid}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
        llm.unload(llm.chat_model())

        # The same first request again, for every model step whose first attempt failed its checks.
        store, repeats = pipeline.Store(RUNS / f"{split}-validate"), []
        by_id = {c.id: c for c in index.chunks}
        for eid in eids:
            state, email = store.state(eid), data["emails"][eid]
            for step in ("extract", "draft"):
                if step not in state["steps"] or not state["steps"][step]["attempts"][0]["problems"]:
                    continue
                if step == "extract":
                    messages, schema, limit = steps.extract_messages(prompts, email), steps.EXTRACT_SCHEMA, "extract_max_tokens"
                else:
                    context = [by_id[c] for c in state["steps"]["retrieve"]["chunks"]]
                    messages = steps.draft_messages(prompts, email, state["steps"]["extract"]["output"]["questions"],
                                                    [(c.document, c.text) for c in context])
                    schema, limit = steps.DRAFT_SCHEMA, "draft_max_tokens"
                call = llm.chat(messages, schema=schema, options=options, max_tokens=data["settings"]["chat"][limit])
                first = state["steps"][step]["attempts"][0]["content"]
                repeats.append({"email": eid, "step": step, "same": call["content"] == first, "content": call["content"]})
        (RUNS / f"{split}-repeat.json").write_text(json.dumps(repeats, indent=1, ensure_ascii=False) + "\n")
    finally:
        llm.unload(llm.chat_model())
        llm.unload(llm.embedding_model())


# ------------------------------------------------------------------------------------------- report


def tenths(numerator: int, denominator: int) -> str:
    """numerator / denominator to one decimal, rounding halves up, with integers only (same in JavaScript)."""
    q = (20 * numerator + denominator) // (2 * denominator)
    return f"{q // 10}.{q % 10}"


class Report:
    def __init__(self, data: dict, split: str):
        self.data, self.split = data, split
        self.eids = data["splits"][split]
        self.scorer = Scorer()
        self.chunks = {c.id: c for c in chunkers.chunk(data["settings"]["chunking"], data["documents"], Tokenizer())}
        self.none = pipeline.Store(RUNS / f"{split}-none")
        self.checked = pipeline.Store(RUNS / f"{split}-validate")
        self.isolated = {eid: json.loads((RUNS / f"{split}-isolated" / f"{eid}.json").read_text()) for eid in self.eids}
        self.repeats = json.loads((RUNS / f"{split}-repeat.json").read_text())
        self.unread: dict[str, tuple[str, str, str]] = {}

    def verdict(self, eid: str, reply: str | None, where: str) -> str | None:
        if reply is None:
            return "none"
        v = self.scorer.verdict(eid, reply)
        if v is None:
            self.unread.setdefault(self.scorer.key(eid, reply), (eid, reply, where))
        return v

    @staticmethod
    def reply(state: dict, attempt: int = -1) -> str | None:
        draft = state["steps"].get("draft")
        if not draft:
            return None
        output = steps.parse(draft["attempts"][attempt]["content"])[0]
        return output.get("reply") if isinstance(output, dict) and isinstance(output.get("reply"), str) else None

    def first_stop(self, state: dict) -> str | None:
        """Where 'checks, no retries' stops this email: the first failing check, or None if it is sent."""
        s = state["steps"]
        if s["extract"]["attempts"][0]["problems"]:
            return "extract"
        if s["retrieve"]["problems"]:
            return "retrieve"
        if s["draft"]["attempts"][0]["problems"]:
            return "draft"
        return None

    def print(self) -> None:
        n, sc = len(self.eids), self.scorer
        none = {e: self.none.state(e) for e in self.eids}
        checked = {e: self.checked.state(e) for e in self.eids}
        print(f"Split: {self.split}, {n} emails, prompts {self.data['prompts']['version']}")

        # 1 ------------------------------------------------------------------------------------------
        extraction_ok, identifiers_ok, retrieval_alone, draft_alone, chain_ok = [], [], [], [], []
        first_failure = {"extraction": 0, "retrieval": 0, "draft": 0}
        for eid in self.eids:
            s = none[eid]["steps"]
            extracted = s["extract"]["output"] if isinstance(s["extract"]["output"], dict) else {}
            questions = extracted.get("questions") if steps.is_string_list(extracted.get("questions")) else []
            ids = extracted.get("identifiers") if steps.is_string_list(extracted.get("identifiers")) else []
            e_ok = sc.extraction(eid, questions)["ok"]
            extraction_ok.append(e_ok)
            identifiers_ok.append(sc.identifiers(eid, ids))
            alone = self.isolated[eid]
            retrieval_alone.append(sc.retrieval(eid, [self.chunks[c].text for c in alone["chunks"] if c not in alone["added"]])["ok"])
            output = alone["output"]
            draft_reply = output.get("reply") if isinstance(output, dict) and isinstance(output.get("reply"), str) else None
            draft_alone.append(self.verdict(eid, draft_reply, "draft on its own") == "correct")
            r_ok = "retrieve" in s and sc.retrieval(eid, [self.chunks[c].text for c in s["retrieve"]["chunks"]])["ok"]
            correct = none[eid]["status"] == "sent" and self.verdict(eid, self.reply(none[eid]), "no checks") == "correct"
            chain_ok.append(correct)
            if not correct:
                first_failure["extraction" if not e_ok else "retrieval" if not r_ok else "draft"] += 1
        a, b, c = sum(extraction_ok), sum(retrieval_alone), sum(draft_alone)
        print("\n1. Each step on its own, and the chain with no checks (emails where the step did its job)")
        print(f"   extraction: questions paired with the labels        {a:>3} of {n}")
        print(f"     (identifiers exactly as labelled                  {sum(identifiers_ok):>3} of {n}, not part of the step's score)")
        print(f"   retrieval from the labelled questions: evidence for every fact   {b:>3} of {n}")
        print(f"   draft from the labelled questions and gold excerpts: correct     {c:>3} of {n}")
        print(f"   if the steps failed independently: {tenths(a * b * c, n * n)} of {n} emails correct end to end")
        print(f"   measured, the chain with no checks: {sum(chain_ok)} of {n} replies correct")
        print(f"   where each wrong chain reply first went wrong: extraction {first_failure['extraction']}, "
              f"retrieval {first_failure['retrieval']}, drafting {first_failure['draft']}")

        # 2 ------------------------------------------------------------------------------------------
        print("\n2. What reaches the outbox")
        rows = []
        unchecked = {e: (self.reply(none[e]) if none[e]["status"] == "sent" else None) for e in self.eids}
        sent = [e for e in self.eids if none[e]["status"] == "sent"]
        rows.append(("no checks", sent, [e for e in self.eids if none[e]["status"] != "sent"], {e: unchecked[e] for e in sent}))
        stops = {e: self.first_stop(checked[e]) for e in self.eids}
        sent = [e for e in self.eids if stops[e] is None]
        rows.append(("checks, no retries", sent, [e for e in self.eids if stops[e]], {e: self.reply(checked[e], 0) for e in sent}))
        sent = [e for e in self.eids if checked[e]["status"] == "sent"]
        rows.append(("checks and retries", sent, [e for e in self.eids if checked[e]["status"] != "sent"],
                     {e: self.reply(checked[e]) for e in sent}))
        print(f"   {'policy':<22}{'sent':>6}{'correct':>9}{'wrong':>7}{'held':>6}{'held, would have been wrong':>30}"
              f"{'held, would have been correct':>32}")
        for name, sent, held, replies in rows:
            verdicts = [self.verdict(e, replies[e], name) for e in sent]
            would = [self.verdict(e, unchecked[e], "no checks") for e in held]
            print(f"   {name:<22}{len(sent):>6}{verdicts.count('correct'):>9}{verdicts.count('wrong'):>7}{len(held):>6}"
                  f"{sum(v in ('wrong', 'none') for v in would):>30}{would.count('correct'):>32}")
        same = sum(none[e]["steps"]["extract"]["attempts"][0]["content"] == checked[e]["steps"]["extract"]["attempts"][0]["content"]
                   and (("draft" not in none[e]["steps"]) or ("draft" not in checked[e]["steps"]) or
                        none[e]["steps"]["draft"]["attempts"][0]["content"] == checked[e]["steps"]["draft"]["attempts"][0]["content"])
                   for e in self.eids)
        print(f"   first attempts identical in the two runs: {same} of {n} emails")
        print("   held back, by the first check that failed:")
        for e in self.eids:
            if stops[e]:
                s = checked[e]["steps"]
                problems = s["retrieve"]["problems"] if stops[e] == "retrieve" else s[stops[e]]["attempts"][0]["problems"]
                print(f"     {e} {stops[e]}: {'; '.join(problems)}")

        # 3 ------------------------------------------------------------------------------------------
        print("\n3. Retries with the problems")
        for step in ("extract", "draft"):
            failed = [e for e in self.eids if step in checked[e]["steps"] and checked[e]["steps"][step]["attempts"][0]["problems"]]
            fixed = [e for e in failed if checked[e]["steps"][step]["ok"]]
            extra = sum(len(checked[e]["steps"][step]["attempts"]) - 1 for e in failed)
            after = {k: sum(len(checked[e]["steps"][step]["attempts"]) == k + 1 and checked[e]["steps"][step]["ok"] for e in failed)
                     for k in (1, 2)}
            print(f"   {step}: {len(failed)} first attempts failed; fixed by retry 1: {after[1]}, by retry 2: {after[2]}; "
                  f"still failing: {len(failed) - len(fixed)}; extra calls: {extra}")
        print(f"   the same first request sent again, without the problems: {sum(r['same'] for r in self.repeats)} of {len(self.repeats)} "
              "outputs identical to the first attempt")
        calls = {name: 0 for name in ("no checks", "checks, no retries", "checks and retries")}
        for e in self.eids:
            calls["no checks"] += sum(len(none[e]["steps"][s]["attempts"]) for s in ("extract", "draft") if s in none[e]["steps"])
            calls["checks and retries"] += sum(len(checked[e]["steps"][s]["attempts"]) for s in ("extract", "draft")
                                               if s in checked[e]["steps"])
            stop = stops[e]
            calls["checks, no retries"] += 1 + (stop in (None, "draft"))
        print("   model calls: " + ", ".join(f"{k} {v}" for k, v in calls.items()))

        self.write_unread()

    def write_unread(self) -> None:
        path = RUNS / f"{self.split}-to-read.md"
        lines = [f"# Replies without a hand label ({len(self.unread)})\n"]
        for key, (eid, reply, where) in sorted(self.unread.items(), key=lambda x: (x[1][0], x[0])):
            lines.append(f"## {eid} `{key}` ({where})\n")
            for q in self.scorer.questions(eid):
                lines.append(f"- {q['id']} {'' if q['answerable'] else '(unanswerable) '}{q['asks']}")
                found = self.scorer.mechanical(eid, reply)
                for f in q["facts"]:
                    mark = ("present" if found[f["id"]] else "MISSING") if f["check"] == "mechanical" else "human"
                    lines.append(f"  - {f['id']} [{mark}] {f['fact']}")
            lines.append("\n```text\n" + reply + "\n```\n")
        path.write_text("\n".join(lines) + "\n")
        print(f"\n{len(self.unread)} replies need a hand label (listed in {path.name})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="test", choices=["dev", "test"])
    parser.add_argument("--report", action="store_true", help="print the report from the saved runs")
    args = parser.parse_args()
    data = pipeline.load()
    if not args.report:
        run_all(data, args.split)
    Report(data, args.split).print()


if __name__ == "__main__":
    main()
