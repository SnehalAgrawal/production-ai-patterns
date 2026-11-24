"""Retrying a tool call: the decision belongs to the tool's retry class, not to the model or a generic retry loop.

execute_naive()     treats issue_refund like a model call: call_model retries it on a timeout
execute_by_class()  one attempt for a non-idempotent write; a timeout makes the outcome "unknown", and the executor
                    asks the service (by the caller's own reference) before anyone tries again

How to make a repeat safe on the receiving side (idempotency keys) is the next article's subject; this file only
shows what the caller can know and do.
"""

import time
from urllib.parse import quote

from http_send import post_json, timed_get
from policy import CallFailed, GiveUp, RetryBudget, call_model

RETRY_CLASS = {
    "search_help_center": "read",                 # retry like a model call
    "get_invoices": "read",
    "set_ticket_status": "idempotent_write",      # doing it twice leaves the same state
    "issue_refund": "non_idempotent_write",       # doing it twice refunds twice
}


def execute_naive(service_url, reference, amount, timeout=1.0, deadline_s=10.0):
    try:
        call_model(lambda timeout: post_json(f"{service_url}/refunds", {"reference": reference, "amount": amount},
                                             timeout),
                   deadline=time.monotonic() + deadline_s, budget=RetryBudget(), max_attempts=3, per_attempt=timeout)
        return {"status": "done", "model_sees": "refund issued"}
    except GiveUp as stop:
        return {"status": "failed", "model_sees": f"error: {stop.last}"}


def execute_by_class(tool, service_url, reference, amount, timeout=1.0):
    assert RETRY_CLASS[tool] == "non_idempotent_write"
    try:
        post_json(f"{service_url}/refunds", {"reference": reference, "amount": amount}, timeout)
        return {"status": "done", "model_sees": "refund issued"}
    except CallFailed as err:
        if err.kind == "not_sent" or (err.status is not None and err.status < 500):
            return {"status": "failed", "model_sees": f"refund not issued ({err})"}   # known not to have happened
    # Timeout, dropped connection, or 5xx: the refund may or may not have been issued. Ask before acting again.
    status, body = timed_get(f"{service_url}/refunds?reference={quote(reference)}", timeout)
    if status == 200 and body["refunds"]:
        return {"status": "done", "model_sees": "refund issued (confirmed by lookup after a timeout)"}
    if status == 200:
        return {"status": "not_applied", "model_sees": "refund not issued; safe to try again"}
    return {"status": "unknown", "model_sees": "outcome unknown; a person is checking. Do not retry."}
