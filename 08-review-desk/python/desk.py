"""
The review desk: where proposals that need a person wait, get decided, and turn into actions.

  submit()   route a proposal: refuse it, run it automatically, or open a review item
  view()     the screen a reviewer decides from (and the fingerprints a decision must quote)
  claim()    take an item, for a limited time
  decide()   record a decision, if this reviewer may make it, about what they were shown
  prepare()  the executor's checks, just before it acts
  commit()   the executor's single write to the billing service
  tick()     the sweeper: escalate at the SLA, expire at the deadline
  audit()    an independent check of a decided item, after the fact
  export_labels()  what the decisions are worth as evaluation data

No model is called. Every safeguard is named in SAFEGUARDS and can be switched off on its own (run.py runs the ablation).
"""
import hashlib
import json
import re
import sqlite3
from datetime import date, timedelta

from billing import Billing, BillingUnavailable, FakeClock, cents

SAFEGUARDS = (
    "authority_from_directory",   # G1
    "authority_at_decision",      # G2
    "requester_cannot_approve",   # G3
    "two_person_rule",            # G4
    "bind_to_action",             # G5
    "bind_to_evidence",           # G6
    "validate_at_execution",      # G7
    "execute_final_version",      # G8
    "executor_checks_decision",   # G9
    "execute_once",               # G10
    "silence_is_not_consent",     # G11
    "claim_lease",                # G12
    "dedupe_submissions",         # G13
    "evidence_gate",              # G14
    "label_provenance",           # G15
    "seeded_cases_inert",         # G16
)

OPEN = ("pending", "needs_evidence", "approved", "execution_failed")
TOOLS = ("refund", "store_credit", "send_reply")
TIER_RANK = {"reply": 0, "within_policy": 0, "exception": 1, "high_value": 2}
EXECUTABLE = ("approved", "execution_failed")

SCHEMA = """
CREATE TABLE items (
  id TEXT PRIMARY KEY, conversation_id TEXT, customer TEXT, requested_by TEXT, dedupe_key TEXT,
  route TEXT, tier TEXT, status TEXT, version INTEGER,
  action TEXT, action_sha TEXT, final_action TEXT,
  evidence TEXT, evidence_sha TEXT, customer_message TEXT, claims TEXT, edited_by TEXT,
  created_at TEXT, sla_at TEXT, expires_at TEXT, escalated INTEGER DEFAULT 0,
  claimed_by TEXT, claim_roles TEXT, lease_until TEXT,
  seeded INTEGER DEFAULT 0, seeded_expected TEXT
);
CREATE TABLE decisions (
  n INTEGER PRIMARY KEY, item_id TEXT, version INTEGER, reviewer TEXT, decision TEXT, accepted INTEGER,
  refusal TEXT, reason TEXT, edit TEXT, seen_action_sha TEXT, seen_evidence_sha TEXT, approved_action_sha TEXT, at TEXT
);
CREATE TABLE executions (key TEXT PRIMARY KEY, item_id TEXT, result TEXT, at TEXT);
CREATE TABLE events (n INTEGER PRIMARY KEY, at TEXT, item_id TEXT, actor TEXT, kind TEXT, data TEXT);
CREATE TABLE notifications (n INTEGER PRIMARY KEY, at TEXT, to_role TEXT, item_id TEXT, text TEXT);
CREATE TABLE audits (n INTEGER PRIMARY KEY, item_id TEXT, auditor TEXT, verdict TEXT, reason TEXT, at TEXT);
"""


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def action_sha(action: dict) -> str:
    """Fingerprint of what will run. The assistant's reason is not part of the action."""
    if action["tool"] == "send_reply":
        return sha({"tool": "send_reply", "customer": action["customer"], "text": action["text"]})
    return sha({"tool": action["tool"], "customer": action["customer"], "invoice_id": action["invoice_id"],
                "amount_cents": cents(action["amount"])})


class Desk:
    def __init__(self, clock: FakeClock, billing: Billing, directory: dict, policy: dict, safeguards=SAFEGUARDS):
        self.clock, self.billing, self.directory, self.policy = clock, billing, directory, policy
        self.on = set(safeguards)
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.reply_pattern = re.compile(policy["reply_review_pattern"], re.IGNORECASE)
        self._next = 0
        self._approved_by: dict[str, list[str]] = {}   # refund id -> the accepted approvals it executed on

    def _approvals(self, item_id: str) -> list[sqlite3.Row]:
        """Accepted approvals on the item's current version."""
        it = self.item(item_id)
        return self.db.execute(
            "SELECT reviewer, approved_action_sha FROM decisions WHERE item_id = ? AND version = ? AND accepted = 1"
            " AND decision IN ('approve', 'approve_with_edit') ORDER BY n", (item_id, it["version"])).fetchall()

    def _approvers(self, item_id: str) -> list[str]:
        """The approvals that count: with bind_to_action, only those of the action that is now effective."""
        it = self.item(item_id)
        return self._approvers_of(item_id, effective(it))

    def _approvers_of(self, item_id: str, action: dict) -> list[str]:
        rows = self._approvals(item_id)
        if "bind_to_action" in self.on:
            rows = [r for r in rows if r["approved_action_sha"] == action_sha(action)]
        return list(dict.fromkeys(r["reviewer"] for r in rows))

    # ----- records -----

    def _event(self, item_id, actor, kind, data=None):
        self.db.execute("INSERT INTO events (at, item_id, actor, kind, data) VALUES (?,?,?,?,?)",
                        (self.clock.iso(), item_id, actor, kind, json.dumps(data or {}, sort_keys=True)))

    def item(self, item_id: str) -> dict:
        row = self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        d = dict(row)
        for k in ("action", "final_action", "evidence", "claim_roles", "claims"):
            d[k] = json.loads(d[k]) if d[k] else None
        return d

    def _set(self, item_id, **fields):
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = [json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for v in fields.values()]
        self.db.execute(f"UPDATE items SET {cols} WHERE id = ?", (*vals, item_id))

    # ----- facts from the system of record -----

    def evidence(self, customer: str) -> dict:
        """The account's records, read from billing. Their fingerprint binds a decision. (The proposal's claims
        are shown next to them but aren't part of the evidence.)"""
        b = self.billing
        invoices = sorted(i["id"] for i in b.invoices.values() if i["customer"] == customer)
        return {
            "customer": customer,
            "invoices": [{k: b.invoices[i][k] for k in ("id", "date", "amount", "description")} for i in invoices],
            "charges": [{k: p[k] for k in ("id", "date", "amount", "invoice")}
                        for p in b.payments if p["customer"] == customer and p["type"] == "charge"
                        and p["status"] == "succeeded"],
            "refunded": {i: b.refunded_cents(i) / 100 for i in invoices},
            "credited": {i: b.credited_cents(i) / 100 for i in invoices},
            "open_disputes": [d["id"] + " on " + d["payment"] for i in invoices for d in b.open_disputes(i)],
        }

    def hard_checks(self, action: dict) -> list[str]:
        """What code can decide alone. Returns the failures (empty = passed)."""
        inv = self.billing.invoice(action["invoice_id"])
        if inv is None or inv["customer"] != action["customer"]:
            return [f"{action['invoice_id']} is not one of {action['customer']}'s invoices"]
        amount = action["amount"]
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0 \
                or cents(amount) != round(amount * 100, 6):
            return [f"{amount!r} is not a valid amount"]
        left = self.billing.left_to_refund_cents(inv["id"])
        if cents(amount) > left:
            return [f"${amount:.2f} requested, only ${left / 100:.2f} left to refund on {inv['id']}"]
        return []

    def tier(self, action: dict) -> str:
        if action["tool"] == "send_reply":
            return "reply"
        inv = self.billing.invoice(action["invoice_id"])
        if cents(action["amount"]) >= cents(self.policy["high_value_min"]):
            return "high_value"
        age = (date.fromisoformat(self.clock.iso()[:10]) - date.fromisoformat(inv["date"])).days
        if age > self.policy["refund_window_days"] or cents(action["amount"]) > cents(inv["amount"]):
            return "exception"
        return "within_policy"

    def item_tier(self, proposal: dict, action: dict) -> str:
        """The tier of the action that would run, never below the tier of the original proposal."""
        a, p = self.tier(action), self.tier(proposal)
        return a if TIER_RANK[a] >= TIER_RANK[p] else p

    def live_tier(self, it: dict) -> str:
        return self.item_tier(it["action"], effective(it))

    def roles(self, reviewer: str) -> list[str]:
        entry = self.directory["reviewers"].get(reviewer)
        return list(entry["roles"]) if entry else []

    # ----- intake -----

    def submit(self, proposal: dict, seeded_expected: str | None = None) -> dict:
        """proposal: tool, customer, conversation_id, requested_by, and invoice_id/amount or text; optional
        claims (structured, e.g. {"duplicate_charge": true}), reason, customer_message, job_queued."""
        action = {k: proposal[k] for k in ("tool", "customer", "invoice_id", "amount", "text") if k in proposal}
        tool = action["tool"]
        if tool in self.policy["not_available_to_model"]:
            return {"route": "refused", "detail": f"{tool} is not available to the assistant"}

        if tool == "send_reply" and not self.reply_pattern.search(action["text"]) and not seeded_expected:
            self.billing.send(action["customer"], action["text"], source="auto")
            sampled = int(sha(proposal["conversation_id"])[:8], 16) % 100 < self.policy["audit_sample_percent"]
            return {"route": "auto", "audit_sample": sampled}

        if tool in ("refund", "store_credit"):
            failures = self.hard_checks(action)
            if failures:
                return {"route": "refused_by_checks", "detail": failures[0]}
        if tool == "store_credit":
            inv = self.billing.invoice(action["invoice_id"])
            age = (date.fromisoformat(self.clock.iso()[:10]) - date.fromisoformat(inv["date"])).days
            seeded_inert = seeded_expected and "seeded_cases_inert" in self.on
            if cents(action["amount"]) <= cents(self.policy["store_credit_auto_max"]) \
                    and age <= self.policy["refund_window_days"] and not seeded_inert:
                self.billing.credit(action["customer"], action["amount"], note=f"credit for {inv['id']}",
                                    invoice_id=inv["id"])
                return {"route": "auto"}

        a_sha = action_sha(action)
        dedupe_key = sha({"conversation": proposal["conversation_id"], "action": a_sha})
        if "dedupe_submissions" in self.on and not seeded_expected:
            row = self.db.execute(
                f"SELECT id FROM items WHERE dedupe_key = ? AND status IN ({','.join('?' * len(OPEN))})",
                (dedupe_key, *OPEN)).fetchone()
            if row:
                self._event(row["id"], proposal["requested_by"], "duplicate_submission")
                return {"route": "duplicate_of", "item_id": row["id"]}

        claims = proposal.get("claims") or {}
        ev = self.evidence(action["customer"])
        status = "needs_evidence" if self._gate_fails(action, claims) else "pending"

        self._next += 1
        item_id = f"RV-{self._next:03d}"
        now = self.clock.now
        self.db.execute(
            "INSERT INTO items (id, conversation_id, customer, requested_by, dedupe_key, route, tier, status, version,"
            " action, action_sha, evidence, evidence_sha, customer_message, claims, created_at, sla_at, expires_at,"
            " seeded, seeded_expected) VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, proposal["conversation_id"], action["customer"], proposal["requested_by"], dedupe_key,
             "review", self.tier(action), status, json.dumps(action, sort_keys=True), a_sha,
             json.dumps(ev, sort_keys=True), sha(ev), proposal.get("customer_message"),
             json.dumps(claims, sort_keys=True), self.clock.iso(),
             _iso(now + timedelta(hours=self.policy["sla_hours"])),
             _iso(now + timedelta(hours=self.policy["expiry_hours"])),
             1 if seeded_expected else 0, seeded_expected))
        self._event(item_id, proposal["requested_by"], "submitted",
                    {"reason": proposal.get("reason"), "status": status})
        return {"route": status if status == "needs_evidence" else "review", "item_id": item_id}

    def _gate_fails(self, action: dict, claims: dict) -> bool:
        """The evidence gate: a structured claim the records don't support."""
        if "evidence_gate" not in self.on or action["tool"] == "send_reply" or not claims.get("duplicate_charge"):
            return False
        return len(self.billing.charges(action["invoice_id"])) < 2

    def revise(self, item_id: str, new_action: dict, by: str, claims: dict | None = None) -> dict:
        """The requester amends its open proposal (for example, a re-run picked a different invoice).
        A revision goes through the same intake as a submission and carries its own claims. With
        bind_to_action, it is a new version: earlier approvals and edits no longer count."""
        it = self.item(item_id)
        claims = claims or {}
        if it["status"] == "execution_failed":
            return {"accepted": False, "refusal": "outcome_unknown"}
        if new_action["tool"] not in TOOLS or new_action["tool"] in self.policy["not_available_to_model"]:
            return {"accepted": False, "refusal": "tool_not_available"}
        if new_action["customer"] != it["customer"]:
            return {"accepted": False, "refusal": "customer_changed"}
        if new_action["tool"] != it["action"]["tool"]:
            return {"accepted": False, "refusal": "tool_changed"}
        if new_action["tool"] != "send_reply" and self.hard_checks(new_action):
            return {"accepted": False, "refusal": "hard_check"}
        gate = self._gate_fails(new_action, claims)
        dedupe_key = sha({"conversation": it["conversation_id"], "action": action_sha(new_action)})
        if "dedupe_submissions" in self.on:
            other = self.db.execute(
                f"SELECT id FROM items WHERE dedupe_key = ? AND id != ? AND status IN ({','.join('?' * len(OPEN))})",
                (dedupe_key, item_id, *OPEN)).fetchone()
            if other:
                return {"accepted": False, "refusal": "duplicate_of", "item_id": other["id"]}
        fields = dict(action=new_action, action_sha=action_sha(new_action), tier=self.tier(new_action),
                      claims=claims, dedupe_key=dedupe_key)
        if "bind_to_action" in self.on:
            if it["status"] not in OPEN:
                return {"accepted": False, "refusal": "not_open"}
            current = self.evidence(it["customer"])
            fields.update(final_action=None, edited_by=None, version=it["version"] + 1, claimed_by=None,
                          lease_until=None, evidence=current, evidence_sha=sha(current),
                          status="needs_evidence" if gate else "pending")
        elif gate:
            fields.update(status="needs_evidence")
        self._set(item_id, **fields)
        self._event(item_id, by, "proposal_revised", {"action": new_action, "claims": claims})
        return {"accepted": True, "status": self.item(item_id)["status"]}

    # ----- the reviewer's side -----

    def view(self, item_id: str) -> dict:
        """The screen. It shows everything a decision needs, and not whether the item is a seeded test."""
        it = self.item(item_id)
        tier = self.live_tier(it)
        return {
            "item_id": it["id"], "version": it["version"], "status": it["status"], "tier": tier,
            "may_decide": self.policy["tiers"][tier]["may_decide"], "approvals_needed": self._required(it),
            "requested_by": it["requested_by"], "customer_message": it["customer_message"],
            "action": effective(it), "action_sha": action_sha(effective(it)), "claims": it["claims"] or {},
            "edited_from": it["action"] if it["final_action"] else None, "edited_by": it["edited_by"],
            "evidence": it["evidence"], "evidence_sha": it["evidence_sha"],
            "expires_at": it["expires_at"], "escalated": bool(it["escalated"]),
        }

    def claim(self, item_id: str, reviewer: str) -> dict:
        it = self.item(item_id)
        holder = self._claim_holder(it)
        if holder and holder != reviewer:
            return {"accepted": False, "refusal": "claimed_by_other", "detail": f"claimed by {holder}"}
        lease = _iso(self.clock.now + timedelta(minutes=self.policy["lease_minutes"])) \
            if "claim_lease" in self.on else None
        self._set(item_id, claimed_by=reviewer, claim_roles=self.roles(reviewer), lease_until=lease)
        self._event(item_id, reviewer, "claimed", {"lease_until": lease})
        return {"accepted": True, "lease_until": lease}

    def _claim_holder(self, it: dict) -> str | None:
        if not it["claimed_by"]:
            return None
        if it["lease_until"] is None or it["lease_until"] > self.clock.iso():
            return it["claimed_by"]
        return None

    def _required(self, it: dict, action: dict | None = None) -> int:
        """Approvals needed for `action` (default: the effective action), from its tier computed now."""
        if "two_person_rule" not in self.on:
            return 1
        tier = self.item_tier(it["action"], action or effective(it))
        return self.policy["tiers"][tier]["approvals"]

    def _authority(self, it: dict, reviewer: str, claimed_role: str | None) -> list[str]:
        if "authority_from_directory" not in self.on and claimed_role:
            return [claimed_role]
        if "authority_at_decision" not in self.on and it["claimed_by"] == reviewer and it["claim_roles"] is not None:
            return it["claim_roles"]
        return self.roles(reviewer)

    def decide(self, item_id: str, reviewer: str, decision: str, seen: dict, *, claimed_role: str | None = None,
               reason: str | None = None, edit: dict | None = None, recommendation: str | None = None) -> dict:
        """decision: approve, approve_with_edit, reject, request_changes, escalate.
        seen: the view() the reviewer decided from (its action_sha and evidence_sha are quoted)."""
        it = self.item(item_id)
        refusal, detail = self._refusal(it, reviewer, decision, seen, claimed_role, reason, edit)
        final = {**effective(it), **edit} if edit else None
        approved_sha = None
        if not refusal and decision in ("approve", "approve_with_edit"):
            approved_sha = action_sha(final or effective(it))
        self.db.execute(
            "INSERT INTO decisions (item_id, version, reviewer, decision, accepted, refusal, reason, edit,"
            " seen_action_sha, seen_evidence_sha, approved_action_sha, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, it["version"], reviewer, decision, 0 if refusal else 1, refusal,
             reason if not recommendation else f"{recommendation}: {reason}", json.dumps(edit) if edit else None,
             seen.get("action_sha"), seen.get("evidence_sha"), approved_sha, self.clock.iso()))
        if refusal:
            self._event(item_id, reviewer, "decision_refused", {"decision": decision, "refusal": refusal})
            return {"accepted": False, "refusal": refusal, "detail": detail, "status": self.item(item_id)["status"]}

        if decision in ("approve", "approve_with_edit"):
            if final:
                self._set(item_id, final_action=final, edited_by=reviewer, tier=self.item_tier(it["action"], final))
            if len(set(self._approvers(item_id))) >= self._required(self.item(item_id)):
                # Compare-and-set: only a pending item at this version becomes approved.
                self.db.execute("UPDATE items SET status = 'approved' WHERE id = ? AND status = 'pending'"
                                " AND version = ?", (item_id, it["version"]))
        elif decision == "reject":
            self._set(item_id, status="rejected")
        elif decision == "request_changes":
            self._set(item_id, status="changes_requested")
        elif decision == "escalate":
            self._escalate(item_id, reviewer, f"{reviewer}: {recommendation or 'no recommendation'} ({reason})")
        self._event(item_id, reviewer, "decided", {"decision": decision, "reason": reason})
        return {"accepted": True, "status": self.item(item_id)["status"]}

    def _refusal(self, it, reviewer, decision, seen, claimed_role, reason, edit):
        if it["status"] not in ("pending", "needs_evidence"):
            return "not_open", f"item is {it['status']}"
        if self.clock.iso() >= it["expires_at"]:
            return "expired", "the item expired"
        holder = self._claim_holder(it)
        if holder and holder != reviewer:
            return "claimed_by_other", f"claimed by {holder}"
        roles = self._authority(it, reviewer, claimed_role)
        if not roles:
            return "unknown_reviewer", f"{reviewer} is not in the directory"
        approving = decision in ("approve", "approve_with_edit")
        if edit and any(k in edit and edit[k] != effective(it)[k] for k in ("tool", "customer")):
            return "edit_not_allowed", "an edit can't change the tool or the customer"
        if approving:
            tier = self.item_tier(it["action"], {**effective(it), **(edit or {})})
            allowed = self.policy["tiers"][tier]["may_decide"]
            if not set(roles) & set(allowed):
                return "not_authorized", f"{reviewer} ({', '.join(roles)}) may not approve {tier}"
            if "requester_cannot_approve" in self.on and reviewer == it["requested_by"]:
                return "requester", f"{reviewer} raised this request"
            if it["status"] == "needs_evidence":
                return "needs_evidence", "the records don't support the proposal's claim"
        if decision == "reject" and reason not in self.policy["reject_reasons"]:
            return "reason_required", "a rejection needs a reason from the list"
        if "bind_to_action" in self.on and seen.get("action_sha") != action_sha(effective(it)):
            return "action_changed", "the action changed since you viewed it"
        if "bind_to_action" in self.on and seen.get("version") != it["version"]:
            return "version_changed", "the proposal was revised since you viewed it"
        if "bind_to_evidence" in self.on:
            current = self.evidence(it["customer"])
            if seen.get("evidence_sha") != sha(current):
                if sha(current) != it["evidence_sha"]:
                    self._reopen(it, current, "evidence changed before the decision")
                return "evidence_changed", "the records changed since you viewed them"
        return None, None

    def _escalate(self, item_id, actor, text):
        self._set(item_id, escalated=1, claimed_by=None, lease_until=None)
        self.db.execute("INSERT INTO notifications (at, to_role, item_id, text) VALUES (?,?,?,?)",
                        (self.clock.iso(), "billing_lead", item_id, text))
        self._event(item_id, actor, "escalated", {"text": text})

    def _new_version(self, it, why, data):
        """Back to the queue as a new version, the proposal as submitted: earlier approvals and edits don't count."""
        self._set(it["id"], status="pending", version=it["version"] + 1, final_action=None, edited_by=None,
                  tier=self.tier(it["action"]), claimed_by=None, lease_until=None)
        self._event(it["id"], "desk", "reopened", {"why": why, **data})

    def _reopen(self, it, current_evidence, why):
        """Back to the queue as a new version: earlier approvals don't carry over."""
        changes = _diff(it["evidence"], current_evidence)
        self._set(it["id"], status="pending", version=it["version"] + 1, evidence=current_evidence,
                  evidence_sha=sha(current_evidence), claimed_by=None, lease_until=None)
        self._event(it["id"], "desk", "reopened", {"why": why, "changes": changes})

    # ----- the executor -----

    def prepare(self, item_id: str, worker: str) -> dict:
        """The checks that run just before acting. Two workers can both pass them; commit() decides who writes."""
        it = self.item(item_id)
        if "executor_checks_decision" in self.on and it["status"] not in EXECUTABLE:
            return self._exec_refused(it, worker, "not_approved", f"item is {it['status']}")
        if "seeded_cases_inert" in self.on and it["seeded"]:
            return self._exec_refused(it, worker, "seeded", "seeded test case: never executed")
        key = f"{it['id']}:v{it['version']}"
        if "execute_once" in self.on:
            done = self.db.execute("SELECT result FROM executions WHERE key = ?", (key,)).fetchone()
            found = self.billing.refund_by_key(key) or self.billing.credit_by_key(key)
            if done or found:
                self._set(item_id, status="completed")
                self._event(item_id, worker, "already_executed", {"key": key})
                return {"ok": False, "refusal": "already_executed", "key": key}
        action = it["final_action"] if ("execute_final_version" in self.on and it["final_action"]) else it["action"]
        if action["tool"] not in TOOLS:
            return self._exec_refused(it, worker, "unknown_tool", f"{action['tool']} can't be executed")
        approvers = self._approvers_of(item_id, action)
        if "bind_to_action" in self.on and len(approvers) < self._required(it, action):
            self._new_version(it, "not enough approvals of the action to run",
                              {"approvals_of_this_action": approvers, "needed": self._required(it, action)})
            return self._exec_refused(it, worker, "action_mismatch",
                                      f"{len(approvers)} approval(s) of this action, {self._required(it, action)} needed")
        if "bind_to_evidence" in self.on and action["tool"] != "send_reply":
            current = self.evidence(it["customer"])
            if sha(current) != it["evidence_sha"]:
                self._reopen(it, current, "evidence changed after approval")
                return {"ok": False, "refusal": "evidence_changed", "changes": _diff(it["evidence"], current)}
        if "validate_at_execution" in self.on and action["tool"] != "send_reply":
            failures = self.hard_checks(action)
            if failures:
                self._set(item_id, status="refused_at_execution")
                return self._exec_refused(it, worker, "hard_check", failures[0])
        return {"ok": True, "item_id": item_id, "version": it["version"], "action": action, "approvers": approvers,
                "key": key if "execute_once" in self.on else None}

    def _exec_refused(self, it, worker, code, detail):
        self._event(it["id"], worker, "execution_refused", {"refusal": code, "detail": detail})
        return {"ok": False, "refusal": code, "detail": detail}

    def commit(self, plan: dict, worker: str) -> dict:
        if not plan["ok"]:
            return plan
        item_id, action, key = plan["item_id"], plan["action"], plan["key"]
        if "executor_checks_decision" in self.on:
            now = self.item(item_id)
            if now["version"] != plan["version"] or now["status"] not in (*EXECUTABLE, "completed"):
                self._event(item_id, worker, "execution_refused", {"refusal": "changed_after_checks"})
                return {"ok": False, "refusal": "changed_after_checks",
                        "detail": f"item is {now['status']} v{now['version']}, checked at v{plan['version']}"}
        if action["tool"] == "send_reply":
            self.billing.send(action["customer"], action["text"], source=f"review {item_id}")
            result = {"sent": action["text"]}
        elif action["tool"] == "store_credit":
            credit, created = self.billing.credit(action["customer"], action["amount"],
                                                  note=f"credit for {action['invoice_id']} ({item_id})",
                                                  idempotency_key=key, invoice_id=action["invoice_id"])
            result = {"credit": credit["id"], "created": created}
            if created:
                self._approved_by[credit["id"]] = plan["approvers"]
        else:
            try:
                refund, created = self.billing.refund(action["invoice_id"], action["amount"], key)
            except BillingUnavailable as e:
                self._set(item_id, status="execution_failed")
                self._event(item_id, worker, "execution_failed", {"error": str(e)})
                return {"ok": False, "refusal": "execution_failed", "detail": "outcome unknown to the executor"}
            result = {"refund": refund["id"], "created": created}
            if created:
                self._approved_by[refund["id"]] = plan["approvers"]
        if key is not None:
            self.db.execute("INSERT OR IGNORE INTO executions (key, item_id, result, at) VALUES (?,?,?,?)",
                            (key, item_id, json.dumps(result), self.clock.iso()))
        self._set(item_id, status="completed")
        self._event(item_id, worker, "executed", result)
        return {"ok": True, **result}

    def execute(self, item_id: str, worker: str) -> dict:
        return self.commit(self.prepare(item_id, worker), worker)

    # ----- time -----

    def tick(self) -> None:
        """The sweeper. Escalate at the SLA; at the deadline, expire, or (with the safeguard off) approve."""
        now = self.clock.iso()
        for row in self.db.execute("SELECT id FROM items WHERE status IN ('pending', 'needs_evidence')").fetchall():
            it = self.item(row["id"])
            if now >= it["expires_at"]:
                if "silence_is_not_consent" in self.on:
                    self._set(it["id"], status="expired")
                    self._event(it["id"], "desk", "expired")
                    if it["seeded"] and "seeded_cases_inert" in self.on:
                        continue
                    self.billing.send(it["customer"], "We couldn't finish reviewing your request in time, so nothing "
                                      "has been refunded. Reply to this message and we'll look at it again.",
                                      source=f"expiry {it['id']}")
                else:
                    self.db.execute(
                        "INSERT INTO decisions (item_id, version, reviewer, decision, accepted, approved_action_sha, at)"
                        " VALUES (?,?,?,?,1,?,?)", (it["id"], it["version"], "system:timeout", "approve",
                                                    action_sha(effective(it)), now))
                    self._set(it["id"], status="approved")
                    self._event(it["id"], "desk", "approved_on_timeout")
                    self.execute(it["id"], "sweeper")
            elif now >= it["sla_at"] and not it["escalated"]:
                self._escalate(it["id"], "desk", "SLA passed with no decision")

    # ----- after the fact -----

    def audit(self, item_id: str, auditor: str, verdict: str, reason: str) -> dict:
        deciders = {r["reviewer"] for r in self.db.execute(
            "SELECT reviewer FROM decisions WHERE item_id = ? AND accepted = 1", (item_id,))}
        if auditor in deciders:
            return {"accepted": False, "refusal": "not_independent"}
        self.db.execute("INSERT INTO audits (item_id, auditor, verdict, reason, at) VALUES (?,?,?,?,?)",
                        (item_id, auditor, verdict, reason, self.clock.iso()))
        return {"accepted": True}

    def seeded_metrics(self) -> dict:
        rows = self.db.execute(
            "SELECT i.id, i.seeded_expected, d.decision FROM items i JOIN decisions d ON d.item_id = i.id"
            " WHERE i.seeded = 1 AND d.accepted = 1 ORDER BY d.n").fetchall()
        expected_reject = [r for r in rows if r["seeded_expected"] == "reject"]
        caught = [r for r in expected_reject if r["decision"] in ("reject", "escalate", "request_changes")]
        return {"seeded_decided": len(rows), "should_reject": len(expected_reject), "caught": len(caught)}

    def export_labels(self) -> list[dict]:
        """With provenance: an approval is an operational decision, a reason is feedback, gold needs a process
        independent of the decision (an audit by someone else, or a seeded case's known answer)."""
        rows = []
        for d in self.db.execute("SELECT * FROM decisions WHERE accepted = 1 ORDER BY n").fetchall():
            seeded = self.item(d["item_id"])["seeded"]
            if "label_provenance" not in self.on:
                value = {"approve": "correct", "approve_with_edit": "correct"}.get(d["decision"], "wrong")
                rows.append({"item": d["item_id"], "kind": "gold", "value": value, "source": f"decision by {d['reviewer']}"})
            elif d["decision"] == "approve" and not seeded:
                rows.append({"item": d["item_id"], "kind": "operational_decision", "value": "approved",
                             "source": d["reviewer"]})
            elif not seeded:
                rows.append({"item": d["item_id"], "kind": "feedback", "value": d["decision"],
                             "reason": d["reason"], "source": d["reviewer"]})
        for a in self.db.execute("SELECT * FROM audits ORDER BY n").fetchall():
            rows.append({"item": a["item_id"], "kind": "gold", "value": a["verdict"], "reason": a["reason"],
                         "source": f"independent audit by {a['auditor']}"})
        if "label_provenance" in self.on:
            for it in self.db.execute("SELECT id, seeded_expected FROM items WHERE seeded = 1").fetchall():
                rows.append({"item": it["id"], "kind": "gold", "value": it["seeded_expected"],
                             "source": "seeded case (known answer)"})
        return rows

    # ----- what a scenario observed -----

    def observe(self) -> dict:
        items = [{k: r[k] for k in ("id", "tier", "status", "version", "escalated")}
                 for r in self.db.execute("SELECT * FROM items ORDER BY id")]
        decisions = [[r["item_id"], r["version"], r["reviewer"], r["decision"], bool(r["accepted"]), r["refusal"]]
                     for r in self.db.execute("SELECT * FROM decisions ORDER BY n")]
        return {
            "items": items,
            "decisions": decisions,
            "money": {"refunds": [[r["invoice_id"], r["amount"], self._approved_by.get(r["id"])]
                                  for r in self.billing.refunds],
                      "credits": [[c["customer"], c["amount"], self._approved_by.get(c["id"])]
                                  for c in self.billing.credits]},
            "messages": [m["text"] for m in self.billing.outbox],
            "notifications": [[n["item_id"], n["to_role"], n["text"]]
                              for n in self.db.execute("SELECT * FROM notifications ORDER BY n")],
            "labels": self.export_labels(),
            "seeded": self.seeded_metrics(),
        }

    def events(self, item_id: str | None = None) -> list[dict]:
        q = "SELECT * FROM events" + (" WHERE item_id = ?" if item_id else "") + " ORDER BY n"
        return [dict(r) for r in self.db.execute(q, (item_id,) if item_id else ())]


def effective(it: dict) -> dict:
    """The action a decision is about now: the reviewer's edit if there is one, else the proposal."""
    return it["final_action"] or it["action"]


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _diff(old: dict, new: dict) -> list[str]:
    return [f"{k}: {json.dumps(old.get(k), sort_keys=True)} -> {json.dumps(new.get(k), sort_keys=True)}"
            for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
