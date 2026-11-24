"""
Tests for the analysis and the report on made-up runs, so every path the real results take has run before the
freeze: v4's assembly and its hash precondition, outcomes, spend, the decision rule, the expectations, and the
whole report (with and without labels).

  python -m unittest -v test_report
"""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analysis
import report
import run
from shared import emails, labels, reply_key, sha256_json

PRICES = {"checked": "test", "embedding": {"input": 0.02},
          "scenarios": {"s": {"roles": {"big": "B", "small": "S"},
                              "models": {"B": {"input": 2.0, "output": 10.0}, "S": {"input": 0.1, "output": 0.5}}}}}


def record(eid: str, reply: str | None, model: str = "big", draft_out: int = 100, check=(), inputs="x",
           done="stop") -> dict:
    extraction = {"questions": ["q"], "identifiers": []}
    chunks = ["c1"]
    return {
        "status": "sent" if reply is not None else "error", "reason": None, "extraction": extraction,
        "chunks": chunks, "reply": reply, "key": reply_key(eid, reply) if reply is not None else None,
        "sha256": None, "draft_inputs_sha256": sha256_json({"extraction": extraction, "chunks": chunks, "i": inputs}),
        "calls": [{"step": "extract", "model": "big", "prompt_tokens": 300, "output_tokens": 30, "done_reason": "stop",
                   "seconds": 0.1},
                  {"step": "draft", "model": model, "prompt_tokens": 1500, "output_tokens": draft_out,
                   "done_reason": done, "seconds": 1.0}],
        "draft_check": list(check), "query_embeddings": 1, "query_embedding_tokens": 10,
    }


def label_for(eid: str, correct: bool) -> dict:
    qs = labels()[eid]["questions"]
    values = {q["id"]: ("correct" if q["answerable"] else "declined") if correct else
              ("wrong" if q["answerable"] else "answered") for q in qs}
    return {"email": eid, "questions": values, "false_statement": not correct, "note": ""}


class V4(unittest.TestCase):
    def test_check_decides_and_hash_guards(self):
        b0 = {"e02": record("e02", "big reply"), "e04": record("e04", "big reply 4")}
        v3 = {"e02": record("e02", "small reply", "small"), "e04": record("e04", "small 4", "small", check=["bad"])}
        v4 = analysis.compose_v4(b0, v3)
        self.assertEqual((v4["e02"]["from"], v4["e02"]["escalated"]), ("v3", False))
        self.assertEqual((v4["e04"]["from"], v4["e04"]["escalated"]), ("b0", True))
        self.assertEqual([c["model"] for c in v4["e04"]["calls"]], ["big", "small", "big"])
        v3["e04"] = record("e04", "small 4", "small", check=["bad"], inputs="different")
        with self.assertRaises(ValueError):
            analysis.compose_v4(b0, v3)

    def test_no_draft_in_either(self):
        b0 = {"e02": {**record("e02", None), "draft_inputs_sha256": None, "draft_check": None}}
        v3 = {"e02": {**record("e02", None), "draft_inputs_sha256": None, "draft_check": None}}
        self.assertFalse(analysis.compose_v4(b0, v3)["e02"]["escalated"])


class Outcomes(unittest.TestCase):
    def test_outcome_and_summary(self):
        qs = labels()
        recs = {"e02": record("e02", "a"), "e04": record("e04", "b"), "e06": record("e06", None, done="length")}
        lab = {recs["e02"]["key"]: label_for("e02", True), recs["e04"]["key"]: label_for("e04", False)}
        outs = {e: analysis.outcome(e, r, lab, qs) for e, r in recs.items()}
        self.assertEqual([outs[e]["outcome"] for e in ("e02", "e04", "e06")], ["correct", "wrong", "no reply"])
        s = analysis.summarize(recs, outs, PRICES)
        self.assertEqual((s["correct"], s["failures"], s["no_reply"], s["truncated"]), (1, 2, 1, 1))
        # 3 emails x (300 in + 30 out) at B, plus 3 x (1500 in + 100 out) at B, plus 30 embedding tokens
        expected = (3 * (300 * 2 + 30 * 10) + 3 * (1500 * 2 + 100 * 10)) / 1e6 + 30 * 0.02 / 1e6
        self.assertAlmostEqual(s["spend"]["s"]["total"], expected)
        self.assertAlmostEqual(s["spend"]["s"]["per_success"], expected)

    def test_unlabelled_reply_is_not_a_guess(self):
        out = analysis.outcome("e02", record("e02", "unseen"), {}, labels())
        self.assertEqual((out["outcome"], out["labelled"]), (None, False))

    def test_decision_rule(self):
        base = {"false_answers": 3, "no_reply": 1}
        self.assertTrue(analysis.decision(base, {"false_answers": 3, "no_reply": 1},
                                          {"broken": [], "fixed": ["e02"]})["adopt"])
        self.assertFalse(analysis.decision(base, {"false_answers": 3, "no_reply": 1},
                                           {"broken": ["e04"], "fixed": []})["adopt"])
        self.assertFalse(analysis.decision(base, {"false_answers": 3, "no_reply": 2},
                                           {"broken": [], "fixed": []})["adopt"])


class Mechanics(unittest.TestCase):
    def test_cap_rule(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "state").mkdir()
            for i, n in enumerate((80, 101, 150)):
                state = {"steps": {"draft": {"attempts": [{"output_tokens": n}]}}}
                (Path(d) / "state" / f"e{i}.json").write_text(json.dumps(state))
            self.assertEqual(run.cap_from(Path(d)), 110)

    def test_expectations_on_consistent_runs(self):
        test = emails("test")
        b0 = {e: record(e, f"reply {e}", draft_out=200 if e == "e02" else 80) for e in test}
        v1 = {e: {**copy.deepcopy(b0[e]), "calls": [c if c["step"] == "extract" else {**c, "prompt_tokens": 900}
                                                     for c in b0[e]["calls"]]} for e in test}
        v2 = copy.deepcopy(b0)
        v2["e02"] = {**record("e02", None, draft_out=100, done="length")}
        v3 = {e: {**record(e, f"small {e}", "small", draft_out=80)} for e in test}
        runs = {"b0": b0, "v1": v1, "v2": v2, "v3": v3, "v3r": copy.deepcopy(v3)}
        result = analysis.expectations(runs, cap=100, v3a=copy.deepcopy(b0))
        self.assertEqual({k: v["held"] for k, v in result.items()},
                         {"E1": True, "E2": True, "E3": True, "E4": True, "E5": True, "E6": True})
        v2["e04"] = record("e04", "changed", draft_out=80)
        self.assertFalse(analysis.expectations(runs, cap=100, v3a=None)["E3"]["held"])


class WholeReport(unittest.TestCase):
    def test_report_runs_on_made_up_results(self):
        test = emails("test")
        b0 = {e: record(e, f"reply {e}") for e in test}
        v3 = {e: record(e, f"small {e}", "small", check=["bad"] if e == "e04" else []) for e in test}
        runs = {name: {"record": {"split": "test", "models": {}, "overrides": {"chat": {"draft_max_tokens": 110}}
                                  if name == "v2" else {}, "model_calls": 40, "status": {},
                                  "server_log": {"isolated": True, "chat_lines": 40}, "started_utc": "t"},
                       "emails": copy.deepcopy(v3 if name in ("v3", "v3r") else b0)}
                for name in ("b0dev", "b0", "v1", "v2", "v3", "v3r")}
        blind = {r["key"]: label_for(e, e != "e06") for recs in (b0, v3) for e, r in recs.items()}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "runs.json").write_text(json.dumps({"runs": runs}))
            (d / "prices.json").write_text(json.dumps(PRICES))
            (d / "blind.json").write_text(json.dumps({"labeller": "test", "labels": blind}))
            patches = [mock.patch.object(report, "EXPORT", d / "runs.json"),
                       mock.patch.object(report, "PRICES", d / "prices.json"),
                       mock.patch.object(report, "BLIND", d / "blind.json"),
                       mock.patch.object(report, "FINAL", d / "missing.json"),
                       mock.patch.object(report, "RUNS", d / "out")]
            for argv in (["report.py"], ["report.py", "--no-labels"]):
                with contextlib.ExitStack() as stack:
                    for p in patches:
                        stack.enter_context(p)
                    stack.enter_context(mock.patch("sys.argv", argv))
                    buffer = io.StringIO()
                    with contextlib.redirect_stdout(buffer):
                        report.main()
                text = buffer.getvalue()
                self.assertIn("SPEND, HYPOTHETICAL", text)
                self.assertIn("V4 (assembled from b0 and v3): escalated 1: ['e04']", text)
                if argv == ["report.py"]:
                    self.assertIn("UNVERIFIED", text)
                    self.assertIn("decision rule", text)
                    self.assertIn("E8:", text)


if __name__ == "__main__":
    unittest.main()
