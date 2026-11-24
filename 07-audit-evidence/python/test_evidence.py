"""Unit tests for the evidence pieces, independent of the scenarios.

    python -m unittest test_evidence.py
"""

import json
import tempfile
import unittest
from pathlib import Path

from checker import check
from common import action_sha, load, manifest, manifest_sha
from evidence import AuditLog, ContentStore, check_anchor, verify_chain, write_anchor, write_jsonl
from lifecycle import erase, purge
from reconstruct import reconstruct
from workflow import Refused, Workflow, run_baseline


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_manifests_reproduce_the_evaluated_hashes(self):
        for e in load("evaluations.json")["evaluations"]:
            self.assertEqual(manifest_sha(manifest(e["release"])), e["manifest_sha256"])

    def test_action_fingerprint_ignores_rationale_and_float_noise(self):
        self.assertEqual(action_sha({"action": "fee_waiver", "amount": 35}),
                         action_sha({"action": "fee_waiver", "amount": 35.000000001, "rationale": "x"}))
        self.assertNotEqual(action_sha({"action": "fee_waiver", "amount": 35}),
                            action_sha({"action": "fee_waiver", "amount": 35.01}))

    def test_chain_detects_an_edit(self):
        log = AuditLog(self.root / "audit.jsonl")
        for i in range(3):
            log.append("2026-11-03T09:00:00Z", "x", "t", {"i": i})
        self.assertIsNone(verify_chain(log.events()))
        events = log.events()
        events[1]["data"]["i"] = 9
        self.assertEqual(verify_chain(events), 2)

    def test_anchor_detects_truncation(self):
        log = AuditLog(self.root / "audit.jsonl")
        for i in range(3):
            log.append("2026-11-03T09:00:00Z", "x", "t", {"i": i})
        write_anchor(self.root, "2026-11-03T09:01:00Z")
        self.assertIsNone(check_anchor(self.root))
        write_jsonl(self.root / "audit.jsonl", log.events()[:-1])
        self.assertIsNotNone(check_anchor(self.root))

    def test_content_digest_is_keyed_per_subject(self):
        store = ContentStore(self.root)
        _, a = store.put("B-1", "x", "same text", "2026-11-03T09:00:00Z")
        _, b = store.put("B-2", "x", "same text", "2026-11-03T09:00:00Z")
        self.assertNotEqual(a, b)

    def test_baseline_is_clean_and_reconstructs(self):
        run_baseline(self.root)
        self.assertEqual(check(self.root), [])
        answers = reconstruct(self.root, "D-C01")
        self.assertEqual(answers["Q1"]["status"], "answered")
        self.assertEqual(answers["Q7"]["executed"], {"action": "fee_waiver", "amount": 35.0})

    def test_executor_refuses_without_approval(self):
        wf = Workflow(self.root)
        wf.activate("assistant-2026.11.1", "2026-11-03T08:00:00Z")
        wf.process("C01")
        with self.assertRaises(Refused):
            wf.execute("D-C01", "2026-11-03T09:30:00Z", {"action": "fee_waiver", "amount": 35.0})

    def test_erasure_leaves_a_verifiable_chain(self):
        run_baseline(self.root)
        erase(self.root, "B-1001", "ER-T", "2026-11-20T00:00:00Z")
        self.assertEqual([f for f in check(self.root) if f["check"] == "K1"], [])
        self.assertEqual(reconstruct(self.root, "D-C01")["Q1"]["status"], "content erased")
        self.assertEqual(reconstruct(self.root, "D-C01")["Q6"]["status"], "answered")

    def test_partial_audit_purge_keeps_the_rest_verifiable(self):
        run_baseline(self.root)
        log = AuditLog(self.root / "audit.jsonl")
        log.append("2027-06-01T00:00:00Z", "note", "t", {})
        purge(self.root, "2028-11-03T00:00:00Z")
        self.assertEqual(len(log.events()), 1)
        self.assertEqual([f for f in check(self.root) if f["check"] == "K1"], [])
        log.append("2027-06-02T00:00:00Z", "note", "t", {})
        self.assertEqual([f for f in check(self.root) if f["check"] == "K1"], [])
        self.assertEqual(json.loads((self.root / "purge_log.jsonl").read_text().splitlines()[-1])["store"], "audit")


    def test_checker_survives_a_partial_audit_purge(self):
        # Deviation D3: found in review. The release activation ages out first; the checker must report it.
        run_baseline(self.root)
        purge(self.root, "2028-11-02T10:00:00Z")
        findings = check(self.root)
        self.assertTrue(any("no release activation" in f["finding"] for f in findings))

    def test_retention_is_blamed_only_for_content_it_covers(self):
        # Deviation D3: an unlogged deletion must not be attributed to a retention rule.
        run_baseline(self.root)
        purge(self.root, "2027-11-04T00:00:00Z")
        self.assertEqual(reconstruct(self.root, "D-C01")["Q1"]["status"], "content deleted by retention")
        other = Path(self.tmp.name) / "other"
        run_baseline(other)
        (other / "content" / "B-1001" / "D-C01-letter.json").unlink()
        self.assertEqual(reconstruct(other, "D-C01")["Q1"]["status"], "not answerable")


if __name__ == "__main__":
    unittest.main()
