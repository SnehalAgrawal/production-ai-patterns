"""The failure policy the article shows: classify a failed call, retry it with backoff inside one deadline and a
per-client retry budget, and read a stream with three clocks.

Standard library only. The article quotes the classifier, call_model, RetryBudget, and read_stream from this file;
run.py prints this file's SHA-256 so a later change shows.

Everything here is for a stateless model call, which has no side effect to repeat. Tool actions go through
tools.py, which decides retries by the tool's retry class instead.
"""

import asyncio
import random
import time

RETRYABLE = {408, 429, 500, 502, 503, 504, 529}
NOT_WORTH_WAITING_FOR = {  # spend caps, credit, usage limits: waiting won't fix them
    "enforced_spend_limit_reached",                                     # Anthropic: error.details.error_code
    "credit_balance_exhausted", "organization_spend_limit_exceeded",    # OpenAI: error.code
    "project_spend_limit_exceeded", "organization_usage_limit_exceeded",
}


class CallFailed(Exception):
    def __init__(self, status=None, retry_after=None, code=None, type=None, kind=None):
        super().__init__(f"status={status} type={type} code={code} kind={kind}")
        self.status = status            # None: no response at all
        self.retry_after = retry_after  # seconds, from the Retry-After header
        self.code = code                # the provider's error code, wherever that provider puts it
        self.type = type                # the provider's error type, e.g. "insufficient_quota"
        self.kind = kind                # with no response: "timeout" or "connection"


def classify(err):
    """Name the failure, for the decision and for the log."""
    if err.status is None:
        return err.kind or "no_response"                  # timeout, connection
    if err.code in NOT_WORTH_WAITING_FOR or err.type == "insufficient_quota":
        return "limit_wont_clear"                         # a 429 that waiting won't fix
    if err.status == 429:
        return "rate_limited"
    if err.status in RETRYABLE:
        return "provider_error"                           # 5xx, 529 overloaded, 408
    return "rejected"                                     # 400, 401, 403, 404, 413, ...


def worth_retrying(err):
    return classify(err) in {"timeout", "connection", "no_response", "rate_limited", "provider_error"}


def backoff(attempt, base=0.5, cap=8.0):
    # "Full jitter": a random wait between 0 and the capped exponential value.
    return random.uniform(0, min(cap, base * 2 ** attempt))


class RetryBudget:
    """Retries may be at most `ratio` of first attempts (a token bucket)."""
    def __init__(self, ratio=0.1, capacity=10.0):
        self.ratio, self.capacity, self.tokens = ratio, capacity, capacity

    def record_request(self):
        self.tokens = min(self.capacity, self.tokens + self.ratio)

    def try_spend(self):
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class GiveUp(Exception):
    """The policy stopped. `reason` says why; `last` is the last failure (None if no attempt was made)."""
    def __init__(self, reason, last=None):
        super().__init__(f"{reason}: {last}")
        self.reason, self.last = reason, last


def call_model(send, deadline, budget, max_attempts=3, per_attempt=None,
               now=time.monotonic, sleep=time.sleep, record=lambda **fields: None):
    """For a stateless model call, which has no side effect to repeat. Not for tool actions."""
    budget.record_request()
    start = now()
    for attempt in range(1, max_attempts + 1):
        remaining = deadline - now()
        if remaining <= 0:
            raise GiveUp("deadline", None)
        timeout = remaining if per_attempt is None else min(per_attempt, remaining)
        try:
            result = send(timeout=timeout)
            record(attempt=attempt, category="ok", elapsed=now() - start, timeout=timeout, delay=0.0, outcome="ok")
            return result
        except CallFailed as err:
            category, wait, outcome = classify(err), 0.0, "retry"
            if not worth_retrying(err):
                outcome = "not_retryable"
            elif attempt == max_attempts:
                outcome = "attempts_exhausted"
            else:
                wait = err.retry_after if err.retry_after is not None else backoff(attempt - 1)
                if now() + wait >= deadline:
                    outcome = "no_time_left"        # don't sleep through the deadline
                elif not budget.try_spend():
                    outcome = "budget_exhausted"    # this client is already retrying too much
            record(attempt=attempt, category=category, elapsed=now() - start, timeout=timeout,
                   delay=wait if outcome == "retry" else 0.0, outcome=outcome)
            if outcome != "retry":
                raise GiveUp(outcome, err) from err
            sleep(wait)


class StreamTimeout(Exception):
    def __init__(self, clock, partial):
        super().__init__(f"{clock} timeout after {len(partial)} chunks")
        self.clock = clock        # "first_token", "idle", or "total"
        self.partial = partial    # what had already arrived (and may already be on screen)


async def read_stream(chunks, first_token_s, idle_s, total_s):
    loop = asyncio.get_running_loop()
    end = loop.time() + total_s
    received = []
    it = chunks.__aiter__()
    try:
        while True:
            per_chunk = idle_s if received else first_token_s
            left = end - loop.time()
            wait = min(per_chunk, left)
            clock = "total" if left <= per_chunk else ("idle" if received else "first_token")
            try:
                chunk = await asyncio.wait_for(it.__anext__(), timeout=max(wait, 0))
            except StopAsyncIteration:
                return "".join(received)
            except asyncio.TimeoutError:
                raise StreamTimeout(clock, received) from None
            received.append(chunk)
    finally:
        await chunks.aclose()     # stop reading, so the model's work can be cancelled too
