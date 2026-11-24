"""Unit tests: validation levels, the credit service's keys, the claim, the relay. No model; about a second.

    python -m unittest test_workflow.py
"""

import json
import tempfile
import threading
import unittest
from pathlib import Path

import validate as v
from common import Clock, load_fixtures, write_json
from record import Record
from services import Credits, Email, KeyReused, seed_all
from workflow import DESIGNS, Run

FX = load_fixtures()
SUB = {"org": "org-acme", "plan": "Pro", "members": 4, "next_period_start": "2026-12-01"}
INVOICE = {"id": "INV-1043", "org": "org-acme", "amount_cents": 2000, "disputed": 0,
           "charges": [{"id": "CH-5501", "status": "succeeded"}, {"id": "CH-5502", "status": "succeeded"}]}
TEXT = FX["emails"]["e01"]["text"]
POLICY = FX["policies"]["1"]


def scenario(config=None):
    d = Path(tempfile.mkdtemp())
    write_json(d / "scenario.json", config or {})
    Clock(d).start(FX["start_time"])
    seed_all(d, FX)
    return d


class Validation(unittest.TestCase):
    def reading(self, name="acme_1043"):
        reading, checks = v.parse_reading(FX["readings"][name])
        self.assertIsNotNone(reading, checks)
        return reading

    def test_cut_off_json_fails_syntactic(self):
        reading, checks = v.parse_reading(FX["readings"]["cut_off"])
        self.assertIsNone(reading)
        self.assertEqual(checks[-1]["level"], "syntactic")

    def test_valid_json_with_a_wrong_value_fails_schema(self):
        reading, checks = v.parse_reading(json.dumps({"intent": "change_plan_and_credit", "target_plan": "Gold",
                                                      "effective": "next_billing_period", "invoice": "INV-1043",
                                                      "reason": "duplicate_charge"}))
        self.assertIsNone(reading)
        self.assertEqual((checks[-1]["level"], checks[-1]["ok"]), ("schema", False))

    def test_amount_is_computed_from_billing(self):
        decision, _ = v.decide(self.reading(), TEXT, "org-acme", SUB, INVOICE, POLICY, 5)
        self.assertEqual(decision["amount_cents"], 2000)
        self.assertEqual(decision["effective"], "2026-12-01")

    def test_each_level_can_fail(self):
        cases = [
            (self.reading("acme_1043_now"), SUB, INVOICE, POLICY, "business_rule"),
            (self.reading(), {**SUB, "members": 7}, INVOICE, POLICY, "business_rule"),
            (self.reading("acme_1034"), SUB, INVOICE, POLICY, "evidence"),
            (self.reading(), SUB, None, POLICY, "evidence"),
            (self.reading(), SUB, {**INVOICE, "org": "org-other"}, POLICY, "evidence"),
            (self.reading(), SUB, {**INVOICE, "charges": INVOICE["charges"][:1]}, POLICY, "evidence"),
            (self.reading(), SUB, INVOICE, FX["policies"]["2"], "approval"),
        ]
        for reading, sub, invoice, policy, level in cases:
            decision, checks = v.decide(reading, TEXT, "org-acme", sub, invoice, policy, 5)
            self.assertIsNone(decision)
            self.assertEqual(checks[-1]["level"], level)

    def test_dispute_is_checked_only_when_asked(self):
        disputed = {**INVOICE, "disputed": 1}
        self.assertIsNotNone(v.decide(self.reading(), TEXT, "org-acme", SUB, disputed, POLICY, 5)[0])
        self.assertIsNone(v.decide(self.reading(), TEXT, "org-acme", SUB, disputed, POLICY, 5, True)[0])

    def test_draft_must_state_the_recorded_facts(self):
        facts = {"amount": "$20.00", "date": "1 December 2026"}
        self.assertIsNotNone(v.parse_draft(FX["drafts"]["acme_ok"], facts)[0])
        self.assertIsNone(v.parse_draft(FX["drafts"]["acme_ok"], {**facts, "amount": "$25.00"})[0])


class CreditKeys(unittest.TestCase):
    def test_a_repeat_returns_the_first_result(self):
        c = Credits(scenario())
        first = c.apply_credit("org-acme", "INV-1043", 2000, key="k")
        again = c.apply_credit("org-acme", "INV-1043", 2000, key="k")
        self.assertEqual((first["replayed"], again["replayed"], again["credit_id"]), (False, True, first["credit_id"]))
        self.assertEqual(len(c.rows()), 1)

    def test_same_key_different_amount_is_rejected(self):
        c = Credits(scenario())
        c.apply_credit("org-acme", "INV-1043", 2000, key="k")
        with self.assertRaises(KeyReused):
            c.apply_credit("org-acme", "INV-1043", 2500, key="k")
        self.assertEqual(len(c.rows()), 1)

    def test_a_pruned_key_makes_a_second_credit(self):
        d = scenario({"credits": {"retention_hours": 24}})
        c = Credits(d)
        c.apply_credit("org-acme", "INV-1043", 2000, key="k")
        Clock(d).advance(24 * 3600)
        self.assertFalse(c.apply_credit("org-acme", "INV-1043", 2000, key="k")["replayed"])
        self.assertEqual(len(c.rows()), 2)

    def test_race_at_the_receiver(self):
        for mode, expected in (("check_then_insert", 4), ("keys", 1)):
            d = scenario({"credits": {"mode": mode}})
            barrier = threading.Barrier(4)

            def go(d=d, barrier=barrier):
                Credits(d).apply_credit("org-acme", "INV-1043", 2000, key="k", between=barrier.wait)

            threads = [threading.Thread(target=go) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(Credits(d).rows()), expected, mode)


class RecordAndRelay(unittest.TestCase):
    def test_only_one_claim_while_a_lease_is_held(self):
        d = scenario()
        r = Record(d, Clock(d))
        r.create("wf", "e01", "org-acme", 1, ["understand"])
        self.assertIsNotNone(r.claim("wf", "a", 60))
        self.assertIsNone(r.claim("wf", "b", 60))
        Clock(d).advance(61)
        self.assertIsNotNone(r.claim("wf", "b", 60))

    def test_a_completed_workflow_sends_one_email_and_reruns_send_nothing(self):
        d = scenario()
        self.assertEqual(Run(d, "e01", DESIGNS["C"]).run(), "completed")
        self.assertEqual(Run(d, "e01", DESIGNS["C"]).run(), "completed")
        self.assertEqual(len(Email(d).rows()), 1)
        self.assertEqual(len(Credits(d).rows()), 1)

    def test_email_service_deduplicates_by_message_id(self):
        d = scenario()
        e = Email(d)
        e.send("org-acme", "s", "b", message_id="m")
        self.assertTrue(e.send("org-acme", "s", "b", message_id="m")["replayed"])
        self.assertEqual(len(e.rows()), 1)


if __name__ == "__main__":
    unittest.main()
