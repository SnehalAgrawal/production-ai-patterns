"""Validation by level. Every check records its level, the rule, and whether it passed.

What each level establishes, and what it can't, is in PROTOCOL.md. The model's reading only *identifies*
things (which invoice, which plan, when); every amount and date that a side effect carries is computed
here from the systems of record.
"""

import json
import re
from datetime import date

READING_ENUMS = {
    "intent": {"change_plan_and_credit"},
    "target_plan": {"Basic", "Pro"},
    "effective": {"next_billing_period", "immediately"},
    "reason": {"duplicate_charge"},
}
INVOICE_ID = re.compile(r"^INV-\d{4}$")


def check(level, ok, rule, detail=None):
    out = {"level": level, "rule": rule, "ok": ok}
    if detail:
        out["detail"] = detail
    return out


def parse_reading(text):
    """Step 1's output: syntactic, then schema. Returns (reading or None, checks)."""
    try:
        reading = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [check("syntactic", False, "the output is valid JSON", e.msg)]
    checks = [check("syntactic", True, "the output is valid JSON")]
    problems = []
    if not isinstance(reading, dict):
        problems.append("not a JSON object")
    else:
        for field, allowed in READING_ENUMS.items():
            if reading.get(field) not in allowed:
                problems.append(f"{field} must be one of {', '.join(sorted(allowed))}")
        if not isinstance(reading.get("invoice"), str) or not INVOICE_ID.match(reading["invoice"]):
            problems.append("invoice must look like INV-1234")
        extra = set(reading) - set(READING_ENUMS) - {"invoice"}
        if extra:
            problems.append(f"unexpected fields: {', '.join(sorted(extra))}")
    checks.append(check("schema", not problems, "required fields, types and allowed values", "; ".join(problems)))
    return (None if problems else reading), checks


def decide(reading, email_text, org, subscription, invoice, policy, member_limit, check_dispute=False):
    """Step 2: business rules, evidence, approval. Returns (decision or None, checks); stops at the first failure."""
    checks = []

    def fail(level, rule, detail):
        checks.append(check(level, False, rule, detail))
        return None, checks

    rule = "downgrades take effect at the start of the next billing period"
    if reading["effective"] != "next_billing_period":
        return fail("business_rule", rule, f"the reading says {reading['effective']}")
    checks.append(check("business_rule", True, rule))

    rule = f"Basic allows {member_limit} members, pending invitations included"
    if reading["target_plan"] == "Basic" and subscription["members"] > member_limit:
        return fail("business_rule", rule, f"{subscription['members']} members")
    checks.append(check("business_rule", True, rule))

    inv = reading["invoice"]
    if inv not in email_text:
        return fail("evidence", "the invoice is named in the email", f"{inv} is not in the email")
    if invoice is None:
        return fail("evidence", "the invoice exists", f"{inv} not found in billing")
    if invoice["org"] != org:
        return fail("evidence", "the invoice belongs to this organization", f"{inv} belongs to another organization")
    succeeded = [c for c in invoice["charges"] if c["status"] == "succeeded"]
    if len(succeeded) < 2:
        return fail("evidence", "the invoice was charged more than once", f"{len(succeeded)} successful charge")
    if check_dispute and invoice["disputed"]:
        return fail("evidence", "the invoice is not under dispute", f"{inv} is disputed")
    checks.append(check("evidence", True, "the invoice is named, exists, is this organization's, and was charged twice"))

    amount = (len(succeeded) - 1) * invoice["amount_cents"]  # computed from billing, never from the model
    cap = policy["auto_approve_cap_cents"]
    rule = f"credits up to {money(cap)} run without a person"
    if amount > cap:
        return fail("approval", rule, f"computed credit {money(amount)}")
    checks.append(check("approval", True, rule))

    decision = {"plan": reading["target_plan"], "effective": subscription["next_period_start"], "invoice": inv,
                "amount_cents": amount, "policy_version": policy["version"]}
    return decision, checks


def parse_draft(text, facts):
    """Step 6's output: valid JSON with a subject and a body that states the recorded amount and date."""
    try:
        draft = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [check("syntactic", False, "the output is valid JSON", e.msg)]
    missing = [v for v in (facts["amount"], facts["date"]) if v not in str(draft.get("body", ""))]
    ok = isinstance(draft.get("subject"), str) and isinstance(draft.get("body"), str) and not missing
    return (draft if ok else None), [check("cross_step", ok, "the reply states the recorded amount and date",
                                           f"missing {', '.join(missing)}" if missing else None)]


def money(cents):
    return f"${cents / 100:.2f}"


def human_date(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B')} {d.year}"
