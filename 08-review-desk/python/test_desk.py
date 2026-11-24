"""
The expectations in PROTOCOL.md (all safeguards on), one test per scenario, plus a few unit checks.

  python -m unittest test_desk -v

What these establish: this desk produces the protocol's outcomes for these scripted inputs. Not that a
production review system is safe, and nothing about how real reviewers behave.
"""
import unittest

from desk import action_sha
from scenarios import env, refund, run


def refunds(o):
    return [(r[0], r[1]) for r in o["money"]["refunds"]]


def refusals(o):
    return [(d[2], d[5]) for d in o["decisions"] if not d[4]]


def statuses(o):
    return [i["status"] for i in o["items"]]


class Scenarios(unittest.TestCase):
    def test_r01_informational_reply_is_sent_without_review(self):
        o = run("R01")
        self.assertEqual(o["items"], [])
        self.assertEqual(len(o["messages"]), 1)

    def test_r02_small_store_credit_runs_automatically(self):
        o = run("R02")
        self.assertEqual(o["items"], [])
        self.assertEqual(o["money"]["credits"], [["C-1001", 25.0, None]])

    def test_r03_within_policy_refund_approved_once(self):
        o = run("R03")
        self.assertEqual(statuses(o), ["completed"])
        self.assertEqual(refunds(o), [("INV-1002", 25.0)])

    def test_r04_support_cannot_approve_an_exception(self):
        o = run("R04")
        self.assertEqual(refusals(o), [("ana", "not_authorized")])
        self.assertEqual(o["money"]["refunds"], [["INV-1001", 25.0, ["chen"]]])

    def test_r05_a_claimed_role_is_ignored(self):
        o = run("R05")
        self.assertEqual(refusals(o), [("ana", "not_authorized")])
        self.assertEqual(refunds(o), [])

    def test_r06_authority_is_checked_when_the_decision_lands(self):
        o = run("R06")
        self.assertEqual(refusals(o), [("dee", "not_authorized")])
        self.assertEqual(refunds(o), [])

    def test_r07_requester_cannot_approve_own_request(self):
        o = run("R07")
        self.assertEqual(refusals(o), [("chen", "requester")])
        self.assertEqual(o["money"]["refunds"], [["INV-1001", 25.0, ["dee"]]])

    def test_r08_high_value_needs_two_people(self):
        d = env()
        s = d.submit(refund("INV-3001", 600, customer="C-3001", conversation="c"))
        d.decide(s["item_id"], "chen", "approve", d.view(s["item_id"]))
        self.assertEqual(d.item(s["item_id"])["status"], "pending")
        self.assertFalse(d.execute(s["item_id"], "w")["ok"])
        o = run("R08")
        self.assertEqual(o["money"]["refunds"], [["INV-3001", 600.0, ["chen", "dee"]]])

    def test_r09_approval_of_a_different_action_is_refused(self):
        o = run("R09")
        self.assertEqual(refusals(o), [("ana", "action_changed")])
        self.assertEqual(refunds(o), [])

    def test_r10_evidence_changed_after_approval_reopens_the_item(self):
        o = run("R10")
        self.assertEqual([(i["status"], i["version"]) for i in o["items"]], [("pending", 2)])
        self.assertEqual(refunds(o), [])

    def test_r11_edited_amount_still_meets_the_hard_checks(self):
        o = run("R11")
        self.assertEqual(statuses(o), ["refused_at_execution"])
        self.assertEqual(refunds(o), [])

    def test_r12_the_edited_reply_is_sent(self):
        o = run("R12")
        self.assertEqual(len(o["messages"]), 1)
        self.assertTrue(o["messages"][0].startswith("Your refund request"))

    def test_r13_rejected_item_is_not_executed(self):
        o = run("R13")
        self.assertEqual(statuses(o), ["rejected"])
        self.assertEqual(refunds(o), [])

    def test_r14_two_workers_one_refund(self):
        self.assertEqual(refunds(run("R14")), [("INV-1002", 10.0)])

    def test_r15_silence_escalates_then_expires(self):
        o = run("R15")
        self.assertEqual([(i["status"], i["escalated"]) for i in o["items"]], [("expired", 1)])
        self.assertEqual(len(o["notifications"]), 1)
        self.assertIn("nothing has been refunded", o["messages"][0])
        self.assertEqual(refunds(o), [])

    def test_r16_an_abandoned_claim_lapses(self):
        o = run("R16")
        self.assertEqual(o["money"]["refunds"], [["INV-1002", 25.0, ["ben"]]])

    def test_r17_duplicate_submission_is_one_item(self):
        o = run("R17")
        self.assertEqual(len(o["items"]), 1)
        self.assertEqual(len(o["decisions"]), 1)
        self.assertEqual(refunds(o), [("INV-1002", 25.0)])

    def test_r18_unsupported_claim_cannot_be_approved(self):
        o = run("R18")
        self.assertEqual(statuses(o), ["needs_evidence"])
        self.assertEqual(refusals(o), [("ana", "needs_evidence")])
        self.assertEqual(refunds(o), [])

    def test_r19_approval_is_not_a_gold_label(self):
        o = run("R19")
        self.assertEqual(refunds(o), [("INV-1003", 15.0)])
        kinds = [(r["kind"], r["value"]) for r in o["labels"]]
        self.assertEqual(kinds, [("operational_decision", "approved"), ("gold", "wrong")])

    def test_r20_seeded_case_measured_and_inert(self):
        o = run("R20")
        self.assertEqual(o["seeded"], {"seeded_decided": 1, "should_reject": 1, "caught": 0})
        self.assertEqual(refunds(o), [])

    def test_r21_escalation_with_a_recommendation(self):
        o = run("R21")
        self.assertEqual([d[2:5] for d in o["decisions"]], [["ana", "escalate", True], ["chen", "approve", True]])
        self.assertEqual(o["money"]["refunds"], [["INV-1001", 25.0, ["chen"]]])

    def test_r22_unknown_outcome_retry_finds_the_refund(self):
        o = run("R22")
        self.assertEqual(statuses(o), ["completed"])
        self.assertEqual(refunds(o), [("INV-1002", 25.0)])

    # Second freeze (PROTOCOL-ADDENDUM.md)

    def test_r23_a_revision_after_approval_is_not_executed(self):
        o = run("R23")
        self.assertEqual([(i["status"], i["version"]) for i in o["items"]], [("pending", 2)])
        self.assertEqual(refunds(o), [])

    def test_r24_an_approval_of_600_does_not_count_for_599(self):
        o = run("R24")
        self.assertEqual(o["money"]["refunds"], [["INV-3001", 599.0, ["dee", "chen"]]])

    def test_r25_second_approver_on_a_stale_screen_is_refused(self):
        o = run("R25")
        self.assertEqual(refusals(o), [("dee", "action_changed")])
        self.assertEqual(statuses(o), ["pending"])
        self.assertEqual(refunds(o), [])

    def test_r26_an_expired_seeded_case_sends_nothing(self):
        o = run("R26")
        self.assertEqual(statuses(o), ["expired"])
        self.assertEqual(o["messages"], [])

    # Third freeze (PROTOCOL-ADDENDUM-2.md)

    def test_r27_an_edit_cannot_lower_the_number_of_approvers(self):
        d = env()
        s = d.submit(refund("INV-3001", 600, customer="C-3001", conversation="c"))
        d.decide(s["item_id"], "chen", "approve", d.view(s["item_id"]))
        d.decide(s["item_id"], "dee", "approve_with_edit", d.view(s["item_id"]), edit={"amount": 450})
        self.assertEqual((d.item(s["item_id"])["status"], d.view(s["item_id"])["approvals_needed"]), ("pending", 2))
        o = run("R27")
        self.assertEqual(o["money"]["refunds"], [["INV-3001", 450.0, ["dee", "chen"]]])

    def test_r28_a_revision_goes_through_intake(self):
        o = run("R28")
        self.assertEqual([(i["status"], i["version"]) for i in o["items"]], [("needs_evidence", 2)])
        self.assertEqual(refusals(o), [("ana", "needs_evidence")])
        self.assertEqual(refunds(o), [])

    def test_r29_store_credit_runs_as_credit_and_edits_keep_the_tool(self):
        o = run("R29")
        self.assertEqual(refusals(o), [("chen", "edit_not_allowed")])
        self.assertEqual((o["money"]["refunds"], o["money"]["credits"]), ([], [["C-3001", 100.0, ["chen"]]]))

    def test_r30_seeded_store_credit_is_not_automatic(self):
        o = run("R30")
        self.assertEqual(len(o["items"]), 1)
        self.assertEqual((o["money"]["refunds"], o["money"]["credits"]), ([], []))

    def test_r31_no_revision_while_the_outcome_is_unknown(self):
        o = run("R31")
        self.assertEqual(statuses(o), ["completed"])
        self.assertEqual(refunds(o), [("INV-1002", 25.0)])

    def test_r32_a_change_between_checks_and_write_stops_the_write(self):
        o = run("R32")
        self.assertEqual([(i["status"], i["version"]) for i in o["items"]], [("pending", 2)])
        self.assertEqual(refunds(o), [])

    # Fourth freeze (PROTOCOL-ADDENDUM-3.md)

    def test_r33_a_credit_counts_against_the_invoice(self):
        o = run("R33")
        self.assertEqual([(i["status"], i["version"]) for i in o["items"]], [("pending", 2)])
        self.assertEqual((refunds(o), o["money"]["credits"]), ([], [["C-1001", 25.0, None]]))

    def test_r34_a_decision_from_an_older_version_is_refused(self):
        o = run("R34")
        self.assertEqual(refusals(o), [("ana", "version_changed")])
        self.assertEqual(refunds(o), [])

    def test_r35_a_revision_cannot_duplicate_another_open_item(self):
        d = env()
        d.submit(refund("INV-1002", 25, conversation="c", claims={"duplicate_charge": True}))
        s = d.submit(refund("INV-1002", 10, conversation="c", claims={"duplicate_charge": True}))
        same = {"tool": "refund", "customer": "C-1001", "invoice_id": "INV-1002", "amount": 25}
        out = d.revise(s["item_id"], same, by="assistant", claims={"duplicate_charge": True})
        self.assertEqual((out["refusal"], out["item_id"]), ("duplicate_of", "RV-001"))
        self.assertEqual(d.item(s["item_id"])["action"]["amount"], 10)


class Units(unittest.TestCase):
    def test_a_credit_counts_toward_the_invoice_cap(self):
        d = env()
        d.submit({"tool": "store_credit", "customer": "C-1001", "invoice_id": "INV-1002", "amount": 25,
                  "conversation_id": "c1", "requested_by": "assistant"})
        self.assertEqual(d.submit(refund("INV-1002", 25, conversation="c2"))["route"], "refused_by_checks")

    def test_revision_cannot_change_customer_or_use_a_refused_tool(self):
        d = env()
        s = d.submit(refund("INV-1002", 25, claims={"duplicate_charge": True}))
        other = {"tool": "refund", "customer": "C-2042", "invoice_id": "INV-2042", "amount": 25}
        closing = {"tool": "close_account", "customer": "C-1001", "invoice_id": "INV-1002", "amount": 25}
        self.assertEqual(d.revise(s["item_id"], other, by="assistant")["refusal"], "customer_changed")
        self.assertEqual(d.revise(s["item_id"], closing, by="assistant")["refusal"], "tool_not_available")

    def test_the_screen_shows_the_edited_action(self):
        d = env()
        s = d.submit(refund("INV-3001", 600, customer="C-3001", conversation="c"))
        d.decide(s["item_id"], "chen", "approve_with_edit", d.view(s["item_id"]), edit={"amount": 550})
        v = d.view(s["item_id"])
        self.assertEqual((v["action"]["amount"], v["edited_from"]["amount"]), (550, 600))

    def test_action_fingerprint_ignores_the_reason(self):
        a = {"tool": "refund", "customer": "C-1001", "invoice_id": "INV-1002", "amount": 25}
        self.assertEqual(action_sha(a), action_sha({**a, "reason": "anything"}))
        self.assertNotEqual(action_sha(a), action_sha({**a, "amount": 25.01}))

    def test_tool_not_available_to_the_model(self):
        d = env()
        out = d.submit({"tool": "close_account", "customer": "C-1001", "conversation_id": "c",
                        "requested_by": "assistant"})
        self.assertEqual(out["route"], "refused")

    def test_hard_checks_refuse_another_customers_invoice_without_a_person(self):
        d = env()
        self.assertEqual(d.submit(refund("INV-2042", 25))["route"], "refused_by_checks")

    def test_rejection_needs_a_listed_reason(self):
        d = env()
        s = d.submit(refund("INV-1002", 25, claims={"duplicate_charge": True}))
        out = d.decide(s["item_id"], "ana", "reject", d.view(s["item_id"]), reason="because")
        self.assertEqual(out["refusal"], "reason_required")

    def test_auditor_must_be_independent_of_the_decision(self):
        d = env()
        s = d.submit(refund("INV-1002", 25, claims={"duplicate_charge": True}))
        d.decide(s["item_id"], "ana", "approve", d.view(s["item_id"]))
        self.assertEqual(d.audit(s["item_id"], "ana", "correct", "fine")["refusal"], "not_independent")

    def test_late_decision_on_an_expired_item_is_refused_before_the_sweeper_runs(self):
        d = env()
        s = d.submit(refund("INV-1002", 25, claims={"duplicate_charge": True}))
        seen = d.view(s["item_id"])
        d.clock.advance(hours=25)
        self.assertEqual(d.decide(s["item_id"], "ana", "approve", seen)["refusal"], "expired")

    def test_the_screen_does_not_reveal_a_seeded_case(self):
        d = env()
        s = d.submit(refund("INV-1003", 15, conversation="seed"), seeded_expected="reject")
        self.assertNotIn("seeded", " ".join(d.view(s["item_id"]).keys()))


if __name__ == "__main__":
    unittest.main()
