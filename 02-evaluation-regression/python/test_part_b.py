"""
Tests for Part B: the prompt difference on the real files, and everything else on small made-up inputs.
No model calls, no Ollama, no network.

Run: python -m unittest test_part_b -v      (from this folder)
"""
import csv
import io
import json
import unittest

import report_b
from common import reply_key, sha256_text, source_module
from common_b import PROMPTS, V3_SENTENCE, V4_SENTENCE, compare_runs, count_requests, email_record, prompt_difference
from import_labels import parse
from worksheet import collect, ordered, render, reply_id

Scorer = source_module("score").Scorer

LABELS = {
    "e1": {"questions": [
        {"id": "e1q1", "asks": "How long is the refund window?", "answerable": True, "facts": [
            {"id": "e1f1", "fact": "Refunds within 30 days", "check": "mechanical", "any_of": ["UNIQUEWORDING30"],
             "evidence": [{"doc": "billing.md", "text": "Refunds are possible within 30 days."}]}]},
        {"id": "e1q2", "asks": "Is there a charity discount?", "answerable": False, "facts": []}]},
    "e2": {"questions": [{"id": "e2q1", "asks": "Where is SSO set up?", "answerable": True, "facts": [
        {"id": "e2f1", "fact": "In the admin settings", "check": "human",
         "evidence": [{"doc": "admin.md", "text": "SSO is set up in the admin settings."}]}]}]},
}


def record(eid, reply, extraction=("q",), chunks=(1, 2), status="sent"):
    return {"status": status, "reason": None if status == "sent" else "the draft has no usable reply",
            "extraction": {"questions": list(extraction)}, "chunks": list(chunks), "reply": reply,
            "key": reply and reply_key(eid, reply), "sha256": reply and sha256_text(reply)}


class Prompts(unittest.TestCase):
    def setUp(self):
        self.v3 = json.loads(PROMPTS["v3"].read_text())
        self.v4 = json.loads(PROMPTS["v4"].read_text())

    def test_real_files_differ_only_by_the_approved_sentence(self):
        self.assertEqual(prompt_difference(self.v3, self.v4), [])
        self.assertEqual(self.v3["draft"]["system"].count(V3_SENTENCE), 1)
        self.assertEqual(self.v4["draft"]["system"].count(V4_SENTENCE), 1)
        self.assertEqual((self.v3["extract"], self.v3["retry"]), (self.v4["extract"], self.v4["retry"]))

    def test_any_other_difference_is_caught(self):
        def changed(edit):
            v4 = json.loads(json.dumps(self.v4))
            edit(v4)
            return prompt_difference(self.v3, v4)
        self.assertTrue(changed(lambda p: p["extract"].update(system=p["extract"]["system"] + " ")))
        self.assertTrue(changed(lambda p: p.update(retry=p["retry"] + "!")))
        self.assertTrue(changed(lambda p: p["draft"].update(user=p["draft"]["user"] + " ")))
        self.assertTrue(changed(lambda p: p["draft"].update(system=p["draft"]["system"].replace("Support team", "Support"))))
        self.assertTrue(changed(lambda p: p.update(version="v3")))
        self.assertTrue(prompt_difference(self.v3, self.v3))  # no change at all is not the approved change


class Reproduction(unittest.TestCase):
    def test_identical(self):
        a = {"e1": record("e1", "Hi"), "e2": record("e2", "Hello")}
        c = compare_runs(a, json.loads(json.dumps(a)))
        self.assertEqual((c["same_reply"], c["different_reply"], c["stops"]), (2, [], []))

    def test_a_different_reply_is_a_finding_not_a_stop(self):
        c = compare_runs({"e1": record("e1", "Hi")}, {"e1": record("e1", "Hi there")})
        self.assertEqual((c["same_reply"], c["different_reply"], c["stops"]), (0, ["e1"], []))

    def test_same_extraction_different_chunks_stops(self):
        c = compare_runs({"e1": record("e1", "Hi")}, {"e1": record("e1", "Hi", chunks=(1, 3))})
        self.assertEqual(c["stops"], ["e1: same extraction, different chunks"])

    def test_different_extraction_and_chunks_is_not_a_stop(self):
        c = compare_runs({"e1": record("e1", "Hi")}, {"e1": record("e1", "Hi", extraction=("other",), chunks=(4,))})
        self.assertEqual(c["stops"], [])

    def test_a_new_error_stops_and_an_old_one_doesnt(self):
        before = {"e1": record("e1", "Hi"), "e2": record("e2", None, status="error")}
        after = {"e1": record("e1", None, status="error"), "e2": record("e2", None, status="error")}
        self.assertEqual(compare_runs(before, after)["stops"], ["e1: a new error (the draft has no usable reply)"])


class Records(unittest.TestCase):
    def test_email_record(self):
        state = {"email": "e1", "status": "sent", "reason": None, "steps": {
            "extract": {"output": {"questions": ["q"]}}, "retrieve": {"chunks": [3]}, "draft": {"output": {"reply": "Hi"}}}}
        r = email_record(state)
        self.assertEqual((r["reply"], r["chunks"], r["key"]), ("Hi", [3], reply_key("e1", "Hi")))
        state["steps"]["draft"]["output"] = None
        self.assertEqual((email_record(state)["reply"], email_record(state)["key"]), (None, None))

    def test_count_requests(self):
        log = ('[GIN] 2026/11/24 - 12:00:01 | 200 | 1.3s | 127.0.0.1 | POST     "/api/chat"\n'
               '[GIN] 2026/11/24 - 12:00:02 | 200 | 0.1s | 127.0.0.1 | POST     "/api/embed"\n'
               'time=... msg="something about /api/chat"\n'
               '[GIN] 2026/11/24 - 12:00:03 | 200 | 1.1s | 127.0.0.1 | POST     "/api/chat"\n')
        self.assertEqual((count_requests(log, "/api/chat"), count_requests(log, "/api/embed")), (2, 1))


class Worksheet(unittest.TestCase):
    def setUp(self):
        same = "Refunds are possible within 30 days. The documentation doesn't cover discounts."
        self.entries_a = [{"email": "e1", "arm": "chain", "reply": same, "key": reply_key("e1", same)},
                          {"email": "e2", "arm": "chain", "reply": None, "key": None}]
        runs = {}
        for n, (name, text) in enumerate((("v3a", same), ("v3b", same), ("v4test", "Thanks for getting in touch! Refunds: 30 days."))):
            runs[name] = {"emails": {"e1": record("e1", text), "e2": record("e2", f"SSO is in the admin settings, wording {n}.")}}
        self.items = collect(self.entries_a, runs)
        self.texts = {"e1": "From: a@x.example\n\nRefund?", "e2": "From: b@x.example\n\nSSO?"}

    def test_dedupes_by_key_and_keeps_every_source(self):
        same = self.items[reply_key("e1", self.entries_a[0]["reply"])]
        self.assertEqual(same["sources"], ["part A chain", "part B v3a", "part B v3b"])
        self.assertEqual(len(self.items), 5)  # e1: shared + v4test; e2: v3a, v3b, v4test (part A's e2 had no reply)

    def test_worksheet_hides_where_each_reply_came_from(self):
        md, rows = render(self.items, LABELS, self.texts)
        for hidden in ("part A", "part B", "chain", "perfect_inputs", "v3a", "v3b", "v4test", "v4", "UNIQUEWORDING30",
                       "pass", "fail", "verdict"):
            self.assertNotIn(hidden, md + rows, hidden)
        for key in self.items:
            self.assertIn(f"### Reply {reply_id(key)}", md)
        self.assertIn("Refunds within 30 days", md)
        self.assertIn('billing.md: "Refunds are possible within 30 days."', md)

    def test_csv_has_one_row_per_question_plus_false_statement(self):
        _, rows = render(self.items, LABELS, self.texts)
        parsed = list(csv.DictReader(io.StringIO(rows)))
        per_reply = {}
        for row in parsed:
            per_reply.setdefault(row["reply_id"], []).append(row["item"])
        for key, item in self.items.items():
            expected = [q["id"] for q in LABELS[item["email"]]["questions"]] + ["false_statement"]
            self.assertEqual(per_reply[reply_id(key)], expected)

    def test_order_is_fixed_by_the_seed(self):
        self.assertEqual(ordered(self.items), ordered(self.items))
        self.assertEqual(sorted(k for _, keys in ordered(self.items) for k in keys), sorted(self.items))

    def test_import(self):
        _, rows = render(self.items, LABELS, self.texts)
        filled = io.StringIO()
        writer = csv.writer(filled)
        for i, row in enumerate(csv.reader(io.StringIO(rows))):
            if i:
                row[4] = {"e1q1": "correct", "e1q2": "declined", "e2q1": "wrong", "false_statement": "no"}[row[2]]
            writer.writerow(row)
        labels, problems = parse(filled.getvalue(), self.items, LABELS)
        self.assertEqual((len(labels), problems), (5, []))
        self.assertFalse(next(iter(labels.values()))["false_statement"])

    def test_import_rejects_gaps_and_bad_values(self):
        _, rows = render(self.items, LABELS, self.texts)
        lines = rows.splitlines()
        bad = [lines[0]] + [line.replace(",,", ",maybe,", 1) for line in lines[1:3]]  # bad values, rest missing
        labels, problems = parse("\n".join(bad) + "\n" + "zzzzzzzz,e1,e1q1,x,correct,\n", self.items, LABELS)
        self.assertEqual(labels, {})
        self.assertTrue(any("unknown reply id" in p for p in problems))
        self.assertTrue(any("missing" in p for p in problems))


class ReportB(unittest.TestCase):
    def test_reproduction_and_outcomes_are_reported_apart(self):
        emails = ["e1", "e2"]
        v3 = {"e1": record("e1", "Refunds within 30 days. Discounts aren't covered."), "e2": record("e2", "In the admin settings.")}
        v4 = {"e1": record("e1", "Thanks! Refunds within 30 days, and yes, there's a discount."), "e2": record("e2", "Thanks! In the admin settings.")}
        runs = {"v3a": {"emails": v3}, "v3b": {"emails": json.loads(json.dumps(v3))}, "v4test": {"emails": v4}}
        q = {"e1q1": "correct", "e1q2": "declined"}
        blind = {v3["e1"]["key"]: {"email": "e1", "questions": q, "false_statement": False},
                 v3["e2"]["key"]: {"email": "e2", "questions": {"e2q1": "correct"}, "false_statement": False},
                 v4["e1"]["key"]: {"email": "e1", "questions": {**q, "e1q2": "answered"}, "false_statement": True},
                 v4["e2"]["key"]: {"email": "e2", "questions": {"e2q1": "correct"}, "false_statement": False}}
        sc = Scorer.__new__(Scorer)
        sc.labels, sc.hand = LABELS, {v3["e2"]["key"]: {"verdict": "correct"}}
        text = "\n".join(report_b.build(sc, runs, json.loads(json.dumps(v3)), blind, emails)[0])
        self.assertIn("v3a against #18's stored chain: of 2 emails, same extraction 2, same chunks 2, same reply text 2", text)
        self.assertIn("v3a against v4test (the prompt change): same reply text 0 of 2", text)
        self.assertIn("same outcome 2 of 2 · changed none", text)
        self.assertIn("correct: 2 of 2 → 1 of 2", text)
        self.assertIn("fixed 0 [] · broken 1 ['e1']", text)
        self.assertIn("v4test  false refusals 0 of 2 answerable questions · false answers 1 of 1 uncovered", text)
        self.assertIn("correct → correct: 1 · correct → wrong: 0 · wrong → correct: 0 · wrong → wrong: 0 · agree 1 of 1", text)


if __name__ == "__main__":
    unittest.main()
