# Protocol

Written before the first full run. `results/freeze.json` records the SHA-256 of this file and of the code, and every run checks them, so a later change shows. If anything here has to change after the freeze, the change is recorded under "Deviations" in the README; this file is not edited.

Development runs (single scenarios, and full runs used to check the report code) were allowed before the freeze to find bugs. They are not reported.

## Question

When a model call fails, what does each part of a failure policy actually do? In particular:

1. Which failures does a policy retry, how many requests reach the provider, and how long does it wait between them?
2. What does a deadline bound, and what does a timeout passed to an HTTP client bound?
3. What happens to work the client stopped waiting for: a generation, a stream, a refund?
4. What do the official OpenAI and Anthropic Python SDKs do by default, at pinned versions?

## What is simulated, configured, and measured

- **Simulated:** the provider and the payment service. `standin.py` is one local process on 127.0.0.1 that speaks enough of two APIs for their SDKs: OpenAI-style `POST /v1/chat/completions` and Anthropic-style `POST /v1/messages`, as JSON or server-sent events, plus `POST /refunds` and `GET /refunds?reference=`. Error bodies and headers follow the shapes in each provider's documentation (fetched 2026-11-24). Nothing else about a real provider is reproduced: not its status codes in practice, its timing, its rate limits, whether it keeps generating or billing after a disconnect, or the shape of its mid-stream errors (the OpenAI-shaped one is the shape the SDK's code parses).
- **Configured:** every behaviour (which request fails how, after how long), every timeout, deadline and attempt limit, all scaled down to seconds. A 1 s timeout here stands for a production timeout of seconds or minutes.
- **Measured:** requests arriving at the stand-in, with `time.monotonic_ns()`; what the stand-in finished, sent, and noticed (disconnects); what the client returned and when; the delays the SDKs chose, from their own INFO log line ("Retrying request ... in X seconds"); the `x-stainless-retry-count` and any idempotency header on each SDK request.
- **Derived:** gaps between arrivals, counts, and the simulations below.
- **Simulated with a fake clock:** `simulate.py` runs the policy code against a provider that fails, with no real waiting, seeded. Its numbers are properties of the policy code, not of any provider.

## Timing tolerance

Configured waits here are 0.5 s or more. Each run first measures the machine: twenty 50 ms sleeps (overshoot) and twenty local round trips to the stand-in. A timing expectation holds if it is within T = 0.15 s of the configured value. The report prints the calibration, so the tolerance can be compared with the overhead it allows for.

## Part A: the policy and the tool executor against the stand-in (standard library only)

The policy is `policy.call_model`: retry only failures classified as retryable (no response, 408, 429 that waiting can fix, 5xx, 529), full-jitter backoff (a random wait between 0 and min(8, 0.5 × 2^n) seconds) unless the server sends `Retry-After`, never sleep past the deadline, at most 3 attempts unless stated. Each attempt's timeout is the smaller of the per-attempt limit and the time left. Backoff is seeded per scenario.

| | Scenario | Expected |
|---|---|---|
| E1 | No timeout, provider accepts the request and sends nothing for 6 s | Still waiting at 3 s; the call returns only when the stand-in closes the connection (≥ 6 s − T) |
| E2 | Each failure kind through the policy (3 attempts, 2 s each, 10 s deadline) | 400, 401, 429 `credit_balance_exhausted` (OpenAI shape), 429 `enforced_spend_limit_reached` (Anthropic shape, in `error.details.error_code`): 1 attempt, not retried. 429 with `Retry-After: 1` then success: 2 attempts, the wait is exactly the 1 s asked for. 500 once then success: 2 attempts. 503 `server_is_overloaded` every time, 529 `overloaded_error` every time, connection refused: 3 attempts, then give up. Every backoff within its full-jitter bound. A 200 cut off at the token limit: 1 attempt, success for the transport policy, flagged unusable by the application's check. Arrivals at the stand-in equal attempts |
| E3 | 429 with `Retry-After: 30`, 6 s left | 1 attempt; gives up at once (< 0.1 s + T) with "no time left" |
| E4 | Provider sends nothing; 1 s per attempt, 3 attempts | Without a deadline: 3 attempts, ≥ 3 s. With a 2 s deadline: ≤ 2 s + T, stopped by the deadline, arrivals equal attempts |
| E5 | An application loop of 3 attempts around a client loop of 3, provider overloaded every time | 9 requests reach the provider |
| E6 | A non-streaming body sent in 8 pieces, one every 0.5 s | `http.client` with a 1 s timeout: no timeout, completes after ≥ 4 s − T. Through `call_model` with a 2 s deadline (the time left passed as the timeout): also completes after ≥ 4 s − T |
| E7 | `read_stream` with first-token 1 s, idle 0.5 s, total 3 s, on five streams | Healthy (10 chunks): complete. First token after 2 s: `first_token` at 1 s ± T, 0 chunks. Stall after 3 chunks: `idle` at 0.8 s ± T, 3 chunks. A chunk every 0.25 s for 20 chunks: `total` at 3 s ± T, 10 to 13 chunks. Error event after 3 chunks: error, 3 chunks. One request each, never retried. For every timeout: the stand-in sees the disconnect, doesn't finish, and sends at most 2 chunks more than the client received |
| E8 | First attempt generates for 1.5 s, client timeout 1 s, retry is fast | 2 attempts, success; the stand-in completed 2 generations, the first ≥ 1 s after it arrived |
| E9 | `issue_refund`: the service writes the refund at 0.2 s and answers at 1.5 s; the executor waits 1 s | Naive (retried like a model call): status failed, 3 refunds in the ledger. By retry class, with a lookup by reference: done, 1 refund. By retry class, no lookup: unknown, 1 refund. Service writes at 1.6 s instead: the lookup at about 1 s finds nothing (not applied, 0 refunds at that moment), and the ledger then holds 1 |
| E10 | Provider overloaded every time, under a chat policy (2 s deadline, 2 attempts) and a batch policy (30 s, 4 attempts) | One record per attempt with request id, workload, provider, endpoint, attempt, category, elapsed, timeout, delay, outcome, deadline remaining; the final decision is the workload's (chat: a message with "try again"; batch: back in the queue) |

## Simulations (fake clock, seeded)

| | Simulation | Expected |
|---|---|---|
| E11 | 1,000 requests; every attempt fails | Provider calls: 1,000 with no retries, 3,000 with 3 attempts, 9,000 with 3 × 3 layers, 27,000 with 3 × 3 × 3; with 3 attempts and a 10% retry budget (token bucket, capacity 10), at most 1,000 + 10 + 0.1 × 1,000 = 1,110 |
| E11 | Same, 5% and 20% of attempts fail at random | 5%: the budget changes no outcome. 20%: the budget costs successes (fewer than with 3 attempts unbudgeted). A prediction: a 10% budget binds when failures exceed about 10% |
| E12 | 100 clients fail at the same moment and schedule two retries | Largest number of retries in any 50 ms window: 100 with no jitter, fewer with the SDK-style jitter (0–25% shorter), fewer still with full jitter, for both retries |

## Part B: the official SDKs against the stand-in

`openai` 3.58.0 and `anthropic` 2.13.0 with `httpx2` 2.16.2 (`requirements-sdk.txt` has every package), each in its own process, default client settings unless stated, a dummy API key, `base_url` set to the stand-in. The predictions come from each SDK's documentation and from its installed source (`_base_client.py`, `_constants.py`): 2 retries, delay min(0.5 × 2^n, 8) reduced by a random 0–25% unless `Retry-After` is sent, retry on connection errors, timeouts, 408, 409, 429 and ≥ 500.

| | Scenario (each SDK) | Expected |
|---|---|---|
| E13 | 503 (OpenAI) / 529 (Anthropic) overloaded every time | 3 requests, `x-stainless-retry-count` 0, 1, 2; logged delays in [0.375, 0.5] and [0.75, 1.0] s; every gap at least the logged delay; no idempotency header |
| E14 | 400 | 1 request |
| E15 | 429 with `Retry-After: 1`, then success | 2 requests, logged delay 1.0 s, gap ≥ 1 s |
| E16 | 429 that waiting won't fix (OpenAI `credit_balance_exhausted`; Anthropic `enforced_spend_limit_reached`), no `Retry-After` | 3 requests: the SDK retries it |
| E17 | Provider sends nothing, `timeout=1.0` | 3 requests; elapsed ≥ 3 × 1 s + both logged delays; a timeout exception |
| E18 | An application loop of 3 (`call_model`) around the SDK's defaults, overloaded every time | 9 requests |
| E19 | Stream: a chunk every 0.5 s for 8 s, `timeout=2.0` | Completes, 16 chunks, ≥ 8 s − T, no exception |
| E20 | Stream stalls after 3 chunks, `timeout=1.0` | 1 request, 3 chunks, an exception at about 1.3 s (between 1.3 − T and 1.3 + 2T) |
| E21 | Error event after 3 chunks, after a 200 | 1 request, 3 chunks, an exception |
| E22 | Connection refused | 2 logged retries in the ranges above; `APIConnectionError` |
| E23 | 429 with `Retry-After: 130`, then success | OpenAI: 1 request, raises `RateLimitError` at once (its code honours `Retry-After` only up to 120 s). Anthropic: 1 request, logs a 130 s delay, still waiting at 4 s (observation stopped there) |
| E24 | Anthropic only: non-streaming request with `max_tokens=64000`, default timeout | `ValueError` before any request |

## Negative control

`report.py --negative-control` runs the same checks with two expectations changed on purpose (E5 expects 3 requests instead of 9; E13 expects 1 instead of 3). It must report those failures and exit 1.

## Repeats

Three full runs after the freeze. The report's stable section (counts, outcomes, classes, pass/fail, versions) is compared by SHA-256; timings are reported as ranges across the three runs.
