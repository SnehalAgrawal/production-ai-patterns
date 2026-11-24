# 05-retries-timeouts

Companion code for **[Retries, Timeouts, and Failure Handling in AI Systems](https://snehalagrawal.com/articles/retries-timeouts-and-failure-handling-in-ai-systems/)** (Article #37).

A model call is a remote dependency. This demo puts a stand-in provider on 127.0.0.1 that fails on purpose (rejections, rate limits, overloads, hangs, slow bodies, stalled or broken streams, slow refunds) and measures what a failure policy does about each, and what the official OpenAI and Anthropic Python SDKs do by default:

1. **Which failures are retried, how many requests reach the provider, and how long the client waits between them?**
2. **What does a deadline bound, and what does a timeout passed to an HTTP client bound?** (A limit on silence, not on duration.)
3. **What happens to work the client stopped waiting for:** a generation, a stream, a refund?
4. **What do retries cost when layers stack, and what do a retry budget and jitter change?** (Fake-clock simulations of the same code.)

## What is simulated, configured, and measured

This matters for every number below.

- **Simulated:** the provider and the payment service. `standin.py` speaks just enough of OpenAI's `POST /v1/chat/completions` and Anthropic's `POST /v1/messages` (JSON and server-sent events) for their SDKs, plus `POST /refunds` and `GET /refunds?reference=`. Error bodies and headers follow each provider's documentation (fetched 2026-11-24). **No real model or provider is called**, so nothing here says how often a real provider fails, how fast it is, or whether it keeps generating or billing after a disconnect.
- **Configured:** every behaviour, timeout, deadline and attempt limit, scaled down to seconds.
- **Measured:** arrivals at the stand-in (`time.monotonic_ns()`), what it finished, sent, and noticed; what the client returned and when; the delays each SDK chose (from its own INFO log line); the headers on each SDK request.
- **Simulated with a fake clock:** `simulate.py` runs the policy code against a failing provider with no real waiting, seeded. Its numbers are properties of the policy code.

[PROTOCOL.md](PROTOCOL.md) lists the expectations (E1–E24, 54 checks) written before the first reported run.

## Run it

Part A and the simulations need Python 3.10 or later and nothing else. Part B needs the two SDKs, pinned:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-sdk.txt     # openai 3.58.0, anthropic 2.13.0, httpx2 2.16.2, ...

cd python
python -m unittest test_policy.py   # the policy with a fake clock and fake streams (12 tests)
python run.py                       # Part A, simulations, Part B for both SDKs; about 2 minutes; writes runs/ (not committed)
python report.py                    # checks the run against PROTOCOL.md; exit 1 if any expectation fails
python report.py --negative-control # two expectations changed on purpose: must exit 1
python compare.py runs/<a> runs/<b> runs/<c>   # repeat runs: stable output identical? timing ranges
```

`python run.py --skip-sdk` runs without the virtual environment (Part B is skipped). No API key is needed; the SDKs get a dummy one, and no request leaves 127.0.0.1.

## Files

| File | What it is |
|---|---|
| `python/policy.py` | The policy the article shows: `classify`, `call_model` (retries, backoff, deadline, budget), `RetryBudget`, `read_stream` (three stream clocks) |
| `python/standin.py` | The simulated provider and payment service |
| `python/http_send.py` | Part A's `http.client` client: failures become `CallFailed`, with the error code read from `error.code` (OpenAI) or `error.details.error_code` (Anthropic) |
| `python/tools.py` | The refund executors: retried like a model call, or by retry class with a lookup |
| `python/scenarios_a.py` | Part A scenarios A1–A10 |
| `python/simulate.py` | Fake-clock simulations: amplification, budgets, jitter |
| `python/sdk_probe.py` | Part B: each SDK against the stand-in |
| `python/run.py`, `report.py`, `compare.py` | Run, check against the protocol, compare repeats |
| `results/freeze.json` | SHA-256 of the protocol and code at the freeze; every run checks it |
| `results/report-run*.txt`, `results/compare.txt` | The three reported runs and their comparison |

## The runs described here

Three full runs after the freeze (`results/freeze.json`, 2026-11-24 14:56:42 UTC), 14:56–15:03 UTC on 2026-11-24:

- Python 3.12.13, macOS 26.6.2, Apple M4 Pro; other programs running (one-minute load average between 2.4 and 10.0, recorded per run).
- Part B: `openai` 3.58.0 and `anthropic` 2.13.0 on `httpx2` 2.16.2, `httpcore2` 2.16.2, `h11` 0.16.0, `anyio` 4.16.0, `pydantic` 2.14.4 (all of `requirements-sdk.txt`).
- Calibration per run: a 50 ms sleep overshot by a median of 4.5 to 9.6 ms (max 10.1 ms); a local round trip to the stand-in took a median of 0.3 to 0.5 ms (max 1.5 ms). The 0.15 s timing tolerance is about 15 times the largest of these.
- **All 54 expectations held in all three runs** (`results/report-run1.txt` to `report-run3.txt`). The stable part of the report (counts, outcomes, exception classes, versions) was identical in all three: SHA-256 `28a7ae178473d9c4aa6c1b41e67f40ad24e3ebdd38b67010e59617966133e896` (`results/compare.txt`, with every timing range).
- The negative control (E5 and E13 changed on purpose) reported 3 failures (E5, and E13 for each SDK) and exited 1 (`results/negative-control.txt`).
- One full development run before the freeze (14:54 UTC, same code apart from the frozen-file list in `run.py`) is not reported.
- An independent reviewer (a separate agent, working from a copy of this directory and the same virtual environment) ran the tests, a fourth full run (15:59 UTC), the report and the negative control: 12 tests OK, freeze matched, 54 of 54 expectations, the same stable digest, negative control exit 1.

A side effect worth knowing if you compare delays: both SDKs draw their jitter from Python's global `random`, which scenario B7 seeds (for `call_model`'s own backoff). So B7's and B12's SDK delays repeat exactly from run to run and are the same in both SDKs; B1, B5 and B6 run before the seed and vary.

## Results

Ranges are across the three runs. Counts were identical in every run.

### Part A: the policy against the stand-in

| | Scenario | Result |
|---|---|---|
| A1 | No timeout; the stand-in sends nothing for 6 s | Still waiting at 3 s; returned only when the stand-in closed the connection (6.00–6.01 s) |
| A2 | 400, 401, 429 `credit_balance_exhausted`, 429 `enforced_spend_limit_reached` | 1 attempt each, not retried |
| A2 | 429 `Retry-After: 1`, then success | 2 attempts; waited exactly 1.0 s (1.007–1.013 s in all) |
| A2 | 500 once, then success | 2 attempts (backoff 0.439 s) |
| A2 | 503 / 529 overloaded every time; connection refused | 3 attempts, then gave up |
| A2 | 200 cut off at the token limit | A success to the policy; the application's check: "unusable: cut off" |
| A3 | `Retry-After: 30` with 6 s left | 1 attempt; gave up in 1–3 ms ("no time left") |
| A4 | Hung provider, 1 s per attempt, 3 attempts | 3.43–3.44 s; with a 2 s deadline: 2.00 s, 2 attempts |
| A5 | Loop of 3 around a loop of 3, overloaded | 9 requests |
| A6 | Body in 8 pieces over 4 s | `http.client` timeout 1 s: completed in 4.03–4.06 s. `call_model` with a 2 s deadline: completed in 4.04–4.07 s |
| A7 | `read_stream` (first token 1 s, idle 0.5 s, total 3 s) | healthy: 10 chunks. Slow first token: `first_token` at 1.003–1.004 s. Stall: `idle` at 0.820–0.826 s, 3 chunks. Steady but long: `total` at 3.002–3.004 s, 12 chunks. Error event: stopped with 3 chunks. Every timeout: the stand-in sent one more chunk, saw the disconnect, stopped |
| A8 | First generation 1.5 s, client timeout 1 s, retry | Answered on attempt 2 (1.34–1.35 s); the stand-in completed 2 generations, the first 1.50–1.51 s after it arrived |
| A9 | Refund written at 0.2 s, answered at 1.5 s; executor waits 1 s | Naive: 3 refunds, model told "error". By class + lookup: 1 refund, "confirmed by lookup". No lookup: 1 refund, "unknown". Written at 1.6 s: lookup said not applied (0 refunds then), 1 refund afterwards |
| A10 | Overloaded, chat and batch policies | One record per attempt with every field; chat gave up after 2 attempts (0.40 s), batch after 4 (2.0 s) |

### Simulations (fake clock, seeded; properties of the policy code)

| Policy, 1,000 requests | Every attempt fails: provider calls | 5% fail: answered | 20% fail: answered |
|---|---|---|---|
| No retries | 1,000 | 942 | 784 |
| 3 attempts | 3,000 | 1,000 | 988 |
| 3 × 3 (two layers) | 9,000 | 1,000 | 1,000 |
| 3 × 3 × 3 (three layers) | 27,000 | 1,000 | 1,000 |
| 3 attempts + 10% budget | 1,109 | 1,000 | 867 |

100 clients failing at once, most retries in any 50 ms window: no jitter 100 and 100; SDK-style (0–25% shorter) 48 and 26; full jitter 16 and 10 (first and second retry).

### Part B: the SDKs against the stand-in

| Scenario | `openai` 3.58.0 | `anthropic` 2.13.0 |
|---|---|---|
| Overloaded every time (503 / 529) | 3 requests, retry-count 0,1,2, `InternalServerError` | 3 requests, retry-count 0,1,2, `OverloadedError` |
| Logged backoff delays (B1, B5, B6) | first 0.389–0.497 s, second 0.763–0.991 s | first 0.380–0.498 s, second 0.760–0.954 s |
| Idempotency header on any request | none | none |
| 400 | 1 request | 1 request |
| 429 `Retry-After: 1`, then success | 2 requests, waited 1.0 s | 2 requests, waited 1.0 s |
| 429 that waiting won't fix, no `Retry-After` | 3 requests, `RateLimitError` | 3 requests, `EnforcedSpendLimitReachedError` |
| No response, `timeout=1.0` | 3 requests, `APITimeoutError` after 4.30–4.42 s | 3 requests, `APITimeoutError` after 4.25–4.40 s |
| Application loop of 3 around the SDK | 9 requests | 9 requests |
| Stream, a chunk every 0.5 s for 8 s, `timeout=2.0` | completed, 16 chunks, 8.07–8.12 s | completed, 16 chunks, 8.07–8.13 s |
| Stream stalls after 3 chunks, `timeout=1.0` | 1 request, 3 chunks, `openai.APITimeoutError` at 1.32–1.33 s | 1 request, 3 chunks, `httpx2.ReadTimeout` (not wrapped) at 1.32–1.33 s |
| Error event after 3 chunks | 1 request, 3 chunks, `APIError` | 1 request, 3 chunks, `APIStatusError` |
| Connection refused | 2 retries, `APIConnectionError` | 2 retries, `APIConnectionError` |
| 429 `Retry-After: 130`, then success | 1 request, `RateLimitError` in 3–5 ms | 1 request, logged a 130 s wait, still waiting at 4 s |
| Non-streaming, `max_tokens=64000`, default timeout | (not applicable) | `ValueError` before any request |

## Limits

- The stand-in is a simulation. Status codes, bodies and headers follow the providers' documentation; timing, rates, real overload, and what a provider does after a disconnect are not reproduced. The OpenAI-shaped mid-stream error is the shape the SDK's code parses; that OpenAI sends it in that shape is not claimed.
- That the stand-in stops "generating" when the client disconnects is its own code. It shows that closing the stream reaches the other end, not that a provider stops work or billing.
- Part B is two SDK versions on one transport version. A newer release can change any row; check yours.
- Timings are from one machine with other programs running. Expect the same counts and outcomes, and timings of the same shape, not the same digits.
- A circuit breaker is described in the article but not implemented here.
- Two harness limitations, found in review after the freeze (the files are frozen, so they are documented here rather than changed): `report.py` prints the freeze status but does not fail when it doesn't match, so check the "Freeze: matches=True" line yourself; and `compare.py` labels the A1, A3, A5 and A8 timing rows all as "A:" in `results/compare.txt` (they are in that order).
- `call_model` passes the time left to `send` as its timeout. With `http.client` (and httpx) that limits each wait for data, so scenario A6 shows a 2 s deadline overrun by a slowly sent body. A hard deadline needs a wall-clock limit around `send`; `read_stream`'s total clock is one, for streams.

## Deviations

None.
