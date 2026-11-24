"""
Tests for Part A, on small made-up inputs: no model calls, and no use of the real labels or replies.

Run: python -m unittest -v      (from this folder)
"""
import json
import tempfile
import unittest
from pathlib import Path

import compare
import grade
from check import verify_frozen, verify_replies
from common import reply_key, sha256_file, sha256_text, source_module

Scorer = source_module("score").Scorer

LABELS = {
    # one answerable question with a mechanical and a human fact, and one question the docs don't cover
    "x1": {"questions": [
        {"id": "x1q1", "answerable": True, "facts": [
            {"id": "x1f1", "check": "mechanical", "any_of": ["30 days"]},
            {"id": "x1f2", "check": "human"}]},
        {"id": "x1q2", "answerable": False, "facts": []}]},
    # only a human fact: nothing for the grader to look for
    "x2": {"questions": [{"id": "x2q1", "answerable": True, "facts": [{"id": "x2f1", "check": "human"}]}]},
}


def fake_scorer(hand: dict | None = None):
    sc = Scorer.__new__(Scorer)  # 01's class, without reading 01's files
    sc.labels, sc.hand = LABELS, hand or {}
    return sc


class Grader(unittest.TestCase):
    def test_pass_lists_what_was_not_checked(self):
        r = grade.grade(fake_scorer(), "x1", "You can get a refund within 30 days.")
        self.assertEqual(r["verdict"], grade.PASS)
        self.assertEqual(r["not_checked"], {"human_facts": ["x1f2"], "uncovered_questions": ["x1q2"]})

    def test_missing_wording_fails(self):
        r = grade.grade(fake_scorer(), "x1", "You can get a refund within thirty days.")
        self.assertEqual((r["verdict"], r["missing"]), (grade.FAIL, ["x1f1"]))

    def test_whole_words_only(self):
        self.assertEqual(grade.grade(fake_scorer(), "x1", "within 130 days")["verdict"], grade.FAIL)

    def test_no_mechanical_fact_is_not_gradeable(self):
        self.assertEqual(grade.grade(fake_scorer(), "x2", "anything")["verdict"], grade.NOT_GRADEABLE)

    def test_no_reply(self):
        self.assertEqual(grade.grade(fake_scorer(), "x1", None)["verdict"], grade.NO_REPLY)


class Calibration(unittest.TestCase):
    def test_counts_both_directions_and_keeps_the_rest_apart(self):
        rows = [("pass", "wrong"), ("pass", "wrong"), ("fail", "wrong"), ("fail", "correct"),
                ("pass", "correct"), ("not gradeable", "wrong"), ("no reply", None), ("pass", None)]
        self.assertEqual(grade.calibration(rows), {"caught": 1, "missed": 2, "false_alarms": 1, "passed": 1,
                                                   "not_gradeable": 1, "no_reply": 1, "unlabelled": 1})


class SignTest(unittest.TestCase):
    def test_known_values(self):
        self.assertAlmostEqual(compare.sign_test(8, 3), 0.2265625)   # 2 × (1 + 11 + 55 + 165) / 2^11
        # C(22, 0..6) = 1 + 22 + 231 + 1540 + 7315 + 26334 + 74613 = 110056
        self.assertAlmostEqual(compare.sign_test(16, 6), 2 * 110056 / 2**22)
        self.assertAlmostEqual(compare.sign_test(5, 0), 0.0625)       # 2 / 2^5
        self.assertEqual(compare.sign_test(0, 0), 1.0)
        self.assertEqual(compare.sign_test(3, 3), 1.0)

    def test_symmetric(self):
        self.assertEqual(compare.sign_test(2, 7), compare.sign_test(7, 2))


class Paired(unittest.TestCase):
    BASE = {"a": "correct", "b": "wrong", "c": "wrong", "d": "correct"}

    def test_self_comparison_has_no_flips(self):
        p = compare.paired(self.BASE, dict(self.BASE))
        self.assertEqual((p["fixed"], p["broken"], p["p_two_sided"]), ([], [], 1.0))

    def test_flips_in_both_directions(self):
        p = compare.paired(self.BASE, {"a": "wrong", "b": "correct", "c": "correct", "d": "correct"})
        self.assertEqual((p["fixed"], p["broken"], p["both_correct"], p["both_wrong"]), (["b", "c"], ["a"], ["d"], []))
        self.assertEqual((p["baseline_correct"], p["candidate_correct"]), (2, 3))

    def test_arms_must_cover_the_same_emails(self):
        with self.assertRaises(ValueError):
            compare.paired(self.BASE, {"a": "correct"})


class BlindLabels(unittest.TestCase):
    QS = LABELS["x1"]["questions"]

    def test_correct_needs_every_rule(self):
        ok = {"questions": {"x1q1": "correct", "x1q2": "declined"}, "false_statement": False}
        self.assertEqual(compare.blind_outcome(self.QS, ok)["outcome"], "correct")
        for change in ({"false_statement": True}, {"questions": {"x1q1": "omitted", "x1q2": "declined"}}):
            self.assertEqual(compare.blind_outcome(self.QS, {**ok, **change})["outcome"], "wrong")

    def test_gates(self):
        r = compare.blind_outcome(self.QS, {"questions": {"x1q1": "declined", "x1q2": "answered"}, "false_statement": False})
        self.assertEqual((r["false_refusals"], r["answerable"], r["false_answers"], r["uncovered"]), (1, 1, 1, 1))

    def test_schema_errors_are_errors(self):
        bad = [{"questions": {"x1q1": "correct"}, "false_statement": False},                       # question missing
               {"questions": {"x1q1": "correct", "x1q2": "correct"}, "false_statement": False},    # not allowed for uncovered
               {"questions": {"x1q1": "answered", "x1q2": "declined"}, "false_statement": False},  # not allowed for answerable
               {"questions": {"x1q1": "correct", "x1q2": "declined"}}]                             # no false_statement
        for label in bad:
            with self.assertRaises(ValueError):
                compare.blind_outcome(self.QS, label)


class Slices(unittest.TestCase):
    def test_from_labels(self):
        self.assertEqual(compare.slices(LABELS["x1"]["questions"]),
                         {"questions": "2", "uncovered question": "yes", "facts": "mixed"})
        self.assertEqual(compare.slices(LABELS["x2"]["questions"])["facts"], "all human")


class Checks(unittest.TestCase):
    def entries(self):
        e = []
        for arm in ("chain", "perfect_inputs"):
            for eid, reply in (("x1", f"{arm}: 30 days"), ("x2", None)):
                if reply is None:
                    e.append({"email": eid, "arm": arm, "reply": None, "key": None, "sha256": None, "missing": "error"})
                else:
                    e.append({"email": eid, "arm": arm, "reply": reply, "key": reply_key(eid, reply), "sha256": sha256_text(reply)})
        return e

    def test_clean(self):
        e = self.entries()
        hand = {x["key"]: {"verdict": "correct"} for x in e if x["key"]}
        self.assertEqual(verify_replies(e, hand, ["x1", "x2"]), [])

    def test_altered_reply_is_caught(self):
        e = self.entries()
        hand = {x["key"]: {"verdict": "correct"} for x in e if x["key"]}
        e[0]["reply"] += " (edited)"
        problems = verify_replies(e, hand, ["x1", "x2"])
        self.assertTrue(any("key doesn't match" in p for p in problems))
        self.assertTrue(any("SHA-256 doesn't match" in p for p in problems))

    def test_unlabelled_reply_and_missing_email_are_caught(self):
        e = self.entries()
        problems = verify_replies(e[1:], {}, ["x1", "x2"])
        self.assertTrue(any("not in 01's hand_labels" in p for p in problems))
        self.assertTrue(any("chain: covers 1" in p for p in problems))

    def test_frozen_file_change_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("frozen")
            frozen = root / "FROZEN.json"
            frozen.write_text(json.dumps({"inputs": {"a.txt": sha256_file(root / "a.txt")}, "code": {"b.py": "0" * 64}}))
            checked, problems = verify_frozen(frozen, root)
            self.assertEqual((checked, problems), (2, ["frozen file missing: b.py"]))
            (root / "a.txt").write_text("changed")
            self.assertIn("changed since the freeze: a.txt", verify_frozen(frozen, root)[1])


class ReportOnFixtures(unittest.TestCase):
    """The report path runs end to end on made-up inputs, so it is exercised before any real report exists."""

    def setUp(self):
        texts = {("chain", "x1"): "chain: 30 days", ("chain", "x2"): None,
                 ("perfect_inputs", "x1"): "thirty days", ("perfect_inputs", "x2"): "something"}
        self.entries = [{"email": eid, "arm": arm, "reply": t, "key": t and reply_key(eid, t), "sha256": t and sha256_text(t),
                         "missing": None if t else "error"} for (arm, eid), t in texts.items()]
        key = {(e["arm"], e["email"]): e["key"] for e in self.entries}
        original = {key[("chain", "x1")]: "correct", key[("perfect_inputs", "x1")]: "wrong",
                    key[("perfect_inputs", "x2")]: "correct"}
        self.sc = fake_scorer({k: {"verdict": v} for k, v in original.items()})
        self.blind = {
            key[("chain", "x1")]: {"email": "x1", "questions": {"x1q1": "correct", "x1q2": "declined"}, "false_statement": False},
            key[("perfect_inputs", "x1")]: {"email": "x1", "questions": {"x1q1": "wrong", "x1q2": "declined"}, "false_statement": False},
            key[("perfect_inputs", "x2")]: {"email": "x2", "questions": {"x2q1": "declined"}, "false_statement": False},
        }

    def test_blind_report(self):
        import report
        lines, cases = report.report(self.sc, self.entries, ["x1", "x2"], "blind", self.blind)
        text = "\n".join(lines)
        self.assertIn("chain            missed 0 of 0 wrong · false alarms 0 of 1 correct · not gradeable 0 · no reply 1", text)
        self.assertIn("perfect_inputs   missed 0 of 1 wrong · false alarms 0 of 0 correct · not gradeable 1 · no reply 0", text)
        self.assertIn("correct: 1 of 2 → 0 of 2", text)
        self.assertIn("fixed 0 [] · broken 1 ['x1']", text)
        self.assertIn("correct → correct: 1 · correct → wrong: 1 · wrong → correct: 0 · wrong → wrong: 1 · agree 2 of 3", text)
        self.assertIn("chain            false refusals 0 of 1 answerable questions · false answers 0 of 1 uncovered", text)
        self.assertIn("perfect_inputs   false refusals 1 of 2 answerable questions · false answers 0 of 1 uncovered", text)
        self.assertEqual(len(cases), 4)

    def test_original_report_has_no_gates(self):
        import report
        text = "\n".join(report.report(self.sc, self.entries, ["x1", "x2"], "original", self.blind)[0])
        self.assertIn("correct: 1 of 2 → 1 of 2", text)
        self.assertNotIn("Gates", text)

    def test_controls_pass(self):
        import report
        out = report.controls(self.sc, self.entries, ["x1", "x2"])
        self.assertFalse(any(line.startswith("CONTROL FAILED") for line in out))
        self.assertIn("baseline compared with itself: 0 flips (expected 0)", out)


if __name__ == "__main__":
    unittest.main()
