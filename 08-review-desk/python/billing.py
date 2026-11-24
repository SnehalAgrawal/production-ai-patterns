"""
A simulated billing service: the system of record for invoices, payments, refunds, credits, and disputes,
plus the outbox of messages sent to customers. Nothing leaves this process.

The desk never trusts its own copy of these facts: it reads them here when it builds a review item,
again when a decision arrives, and again when it executes.
"""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


class FakeClock:
    """UTC time that only moves when a scenario moves it."""

    def __init__(self, start: str):
        self.now = datetime.fromisoformat(start.replace("Z", "+00:00"))

    def iso(self) -> str:
        return self.now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def advance(self, minutes: float = 0, hours: float = 0) -> None:
        self.now += timedelta(minutes=minutes, hours=hours)

    def set(self, iso: str) -> None:
        self.now = datetime.fromisoformat(iso.replace("Z", "+00:00"))


def cents(amount) -> int:
    return round(float(amount) * 100)


class BillingUnavailable(Exception):
    """The billing service failed. `applied` says whether it wrote the refund before failing (the caller can't tell)."""

    def __init__(self, message: str, applied: bool):
        super().__init__(message)
        self.applied = applied


class Billing:
    def __init__(self, clock: FakeClock):
        self.clock = clock
        accounts = json.loads((DATA / "accounts.json").read_text())
        self.invoices = {i["id"]: i for i in accounts["invoices"]}
        self.payments = list(accounts["payments"])
        self.disputes = copy.deepcopy(accounts["disputes"])
        self.refunds: list[dict] = []        # cash refunds written by this demo
        self.credits: list[dict] = []        # store credit written by this demo
        self.outbox: list[dict] = []         # messages sent to customers
        self.fail_next_refund: str | None = None  # None, "before_write", or "after_write"

    # ----- reads -----

    def invoice(self, invoice_id: str) -> dict | None:
        return self.invoices.get(invoice_id)

    def charges(self, invoice_id: str) -> list[dict]:
        return [p for p in self.payments
                if p["invoice"] == invoice_id and p["type"] == "charge" and p["status"] == "succeeded"]

    def refunded_cents(self, invoice_id: str) -> int:
        earlier = sum(cents(p["amount"]) for p in self.payments
                      if p["invoice"] == invoice_id and p["type"] == "refund" and p["status"] == "succeeded")
        return earlier + sum(cents(r["amount"]) for r in self.refunds if r["invoice_id"] == invoice_id)

    def credited_cents(self, invoice_id: str) -> int:
        return sum(cents(c["amount"]) for c in self.credits if c.get("invoice_id") == invoice_id)

    def left_to_refund_cents(self, invoice_id: str) -> int:
        """At most the invoice amount can be refunded or credited, minus what already was."""
        return cents(self.invoices[invoice_id]["amount"]) - self.refunded_cents(invoice_id) \
            - self.credited_cents(invoice_id)

    def open_disputes(self, invoice_id: str) -> list[dict]:
        return [d for d in self.disputes if d["invoice"] == invoice_id and d["status"] == "open"]

    def refund_by_key(self, key: str) -> dict | None:
        return next((r for r in self.refunds if r["idempotency_key"] == key), None)

    def credit_by_key(self, key: str) -> dict | None:
        return next((c for c in self.credits if c.get("idempotency_key") == key), None)

    # ----- writes -----

    def open_dispute(self, payment_id: str, reason: str) -> dict:
        payment = next(p for p in self.payments if p["id"] == payment_id)
        dispute = {"id": f"DSP-{len(self.disputes) + 1:03d}", "payment": payment_id, "invoice": payment["invoice"],
                   "reason": reason, "status": "open", "opened_at": self.clock.iso()}
        self.disputes.append(dispute)
        return dispute

    def refund(self, invoice_id: str, amount, idempotency_key: str | None) -> tuple[dict, bool]:
        """Write a refund. With a key already used, return the earlier refund instead (returns (refund, created))."""
        if idempotency_key is not None:
            existing = self.refund_by_key(idempotency_key)
            if existing is not None:
                return existing, False
        if self.fail_next_refund == "before_write":
            self.fail_next_refund = None
            raise BillingUnavailable("503 from billing", applied=False)
        refund = {"id": f"RF-{len(self.refunds) + 1:03d}", "invoice_id": invoice_id, "amount": float(amount),
                  "idempotency_key": idempotency_key, "at": self.clock.iso()}
        self.refunds.append(refund)
        if self.fail_next_refund == "after_write":
            self.fail_next_refund = None
            raise BillingUnavailable("connection reset after the refund was written", applied=True)
        return refund, True

    def credit(self, customer: str, amount, note: str, idempotency_key: str | None = None,
               invoice_id: str | None = None) -> tuple[dict, bool]:
        """Write store credit. With a key already used, return the earlier credit (returns (credit, created))."""
        if idempotency_key is not None:
            existing = self.credit_by_key(idempotency_key)
            if existing is not None:
                return existing, False
        credit = {"id": f"CR-{len(self.credits) + 1:03d}", "customer": customer, "amount": float(amount),
                  "note": note, "invoice_id": invoice_id, "idempotency_key": idempotency_key,
                  "at": self.clock.iso()}
        self.credits.append(credit)
        return credit, True

    def send(self, customer: str, text: str, source: str) -> dict:
        message = {"to": customer, "text": text, "source": source, "at": self.clock.iso()}
        self.outbox.append(message)
        return message
