# Protocol

Written before the first full run, together with `data/settings.json`. The report prints the SHA-256 of this file, the settings, and the code, so a later change shows. If anything here has to change after the first full run, the change is recorded under "Deviations" in the README; this file is not edited.

Short smoke runs (10 requests or fewer per variant) were allowed while the code was written, to find bugs. They are not reported.

## Question

When one request passes through several stages, which measurements locate the stage that makes it slow? In particular:

1. Do span durations add up to the end-to-end time, and when don't they?
2. Which number does each change move: a faster model, parallel lookups, streaming with a per-sentence check?
3. Where does waiting for a worker show up, and where is it invisible?
4. What do the mean and the percentiles say about a rare slow dependency?

## What is simulated, configured, and measured

- **Simulated:** every dependency. One local process (`services.py`) stands in for a search service, a billing API, and a model that streams its answer. Nothing calls a real model or a real provider.
- **Configured:** every delay those stand-ins add, in `data/settings.json`: the article's illustrative eight-second budget at one tenth scale, with seeded random variation (log-normal, sigma 0.1; 0.05 for the decode rate). Which requests need the billing tool, and which billing calls are slow, are fixed by the seed. The same request index gets the same delays in every variant and every repeat.
- **Measured:** timestamps taken by three separate processes on one machine (client, application, stand-in services) and everything derived from them: real overhead (local HTTP connections, request parsing, thread scheduling, sleep overshoot), the queue waits that arise from arrivals and workers, the overlap of parallel calls, and the distributions.
- **Not measured:** anything about a real model, a real provider, or a real network. The magnitudes belong to the settings, not to any production system.

## Clock

Every timestamp is `time.monotonic_ns()`. Python's documentation describes it as "a monotonic clock, i.e. a clock that cannot go backwards", and says it is the same for all processes (on macOS since Python 3.10), so timestamps from the three processes can be subtracted. Wall-clock time (`time.time()`) is not used: it "can return a lower value than a previous call if the system clock has been set back".

## The request

One request is one customer question to the support assistant (`app.py`). In the baseline:

```text
read the request → load state (in-process, configured) → rewrite (model call, not streamed)
→ retrieval (search service) → billing tool (only if the request needs it)
→ answer (model call, streamed) → check the whole answer → send it
```

## Timestamps and segments

| Timestamp | Process | Taken |
|---|---|---|
| `intended` | client | the time the open-loop schedule says the request should start |
| `started` | client | just before it opens the connection |
| `connected` | client | when `connect()` returns (the kernel completed the TCP handshake) |
| `accepted` | app | when `accept()` returns the connection |
| `dequeued` | app | when a worker takes the connection from the application's queue |
| `first_write`, `last_write` | app | the first and last write of the response |
| `first_byte`, `last_byte` | client | the first and last byte of the response received |

Consecutive timestamps give segments that add up, exactly, to the end-to-end time:

| Segment | From → to | What it is |
|---|---|---|
| schedule lag | intended → started | the client starting late (should be near 0) |
| connect | started → connected | the local TCP handshake |
| kernel accept queue | connected → accepted | the connection is complete and waits in the kernel's listen backlog until the application calls `accept()` |
| application worker queue | accepted → dequeued | the application has accepted the connection, and it waits in the application's own queue for a free worker |
| handler | dequeued → last_write | the application working on the request |
| delivery | last_write → last_byte | the last write reaching the client |

The kernel accept queue and the application worker queue are different places. The application can timestamp the second; it cannot see the first, which shows only as the difference between the client's and the application's timestamps.

**End-to-end latency:** `last_byte − intended`. Measured from the intended time, not the actual start, so a late start counts (an open-loop schedule; a client that waits for each reply before sending the next would hide queueing).

**Time to first byte received (TTFB):** `first_byte − intended`. The application sends the status line, the headers, and the first answer text in one write, so the first byte received carries answer text. There is no browser: this is not the time text is shown. The report checks, for every request, that the first byte received is in a read that contains answer text.

## Spans inside the handler

The application records spans: `read_request`, `load_state`, `rewrite`, `retrieval`, `tool`, `answer`, `check` (or `check.sentence`), and `send`; these are leaves. `lookups` is a parent span around retrieval and the tool call. The negative-control variant adds a step with no span.

- **Naive sum:** the sum of all spans, parents included.
- **Leaf sum:** the sum of leaf spans.
- **Critical-path attribution:** each instant of the handler window is assigned to the leaf span that was active at that instant and ended last (the one the request was still waiting for); an instant no leaf covers is **unattributed**. By construction the attributions and the unattributed time add up to the handler window.

## Model calls: two views

For each model call the application records when it started the call, when the first chunk arrived, and when the last arrived. The stand-in model reports its own durations in its final message, modelled on Ollama's fields: `prompt_eval_ms` (request received to first chunk written), `eval_ms` (first to last chunk written), and `total_ms`. These are what a provider-side timer would see; the difference is what it can't see.

## Variants

Every variant runs `repeats` = 3 times. Runs are ordered repeat by repeat (all variants once, then again), so a slow drift in the machine affects every variant.

| Variant | Change from the baseline | Requests |
|---|---|---|
| V0-baseline | none | 200, one every 150 ms, 8 workers |
| V1-faster-decode | the answer is generated twice as fast (0.5 ms per token instead of 1.0) | 200 |
| V2-parallel-lookups | retrieval and the billing tool run at the same time | 200 |
| V3-stream-per-sentence | each sentence is checked and sent as soon as it's complete, instead of checking the whole answer | 200 |
| V4a-burst-app-queue | 12 requests at once, 2 workers; the application accepts every connection at once and queues it | 12 |
| V4b-burst-kernel-queue | 12 requests at once, 2 workers; a worker accepts a connection only when it is free | 12 |
| V5-rare-slow-billing | 5% of billing calls take 600 ms longer | 400 |
| NC-uninstrumented-step | a 20 ms step with no span, between the lookups and the answer | 200 |

Five warm-up requests (closed loop) go first in every run and are excluded.

## Statistics

- Percentiles are **nearest-rank**: for N values sorted ascending, the p-th percentile is the value at rank ⌈p/100 × N⌉. With 200 requests, p99 is the 198th value: two values lie above it. With 400, it is the 396th: four values above. The report gives N with every percentile.
- Requests that need the billing tool (about 40%) and requests that don't are reported separately as well as together, because they are different workloads.
- Run-to-run spread: each statistic is computed per repeat, and the report gives the median of the three and their range.

## Expectations, written before the first full run

Each must hold in every repeat unless it says otherwise. "Median" is the median over requests in one run.

- **E1 (V0).** The `answer` span is the largest critical-path contributor; its median share of the handler window is between 60% and 75%. Median unattributed handler time is under 5 ms.
- **E2 (V0).** For every request, the segments add up to the end-to-end time exactly; the median kernel-accept-queue wait and median application-queue wait are each under 2 ms; the naive sum exceeds the handler window; the leaf sum does not exceed it by more than 1 ms.
- **E3 (V1 vs V0).** The median end-to-end time falls by 150 to 200 ms in each slice (configured: 175 ms). The medians of every span except `answer` change by less than 5 ms.
- **E4 (V2 vs V0).** In the tool slice, the leaf sum exceeds the handler window by a median of 20 to 40 ms (retrieval, configured 30 ms, now overlaps the tool call), and the median end-to-end time falls by 20 to 40 ms. In the no-tool slice it changes by less than 5 ms.
- **E5 (V3 vs V0).** The median TTFB falls by more than 250 ms; the median end-to-end time falls by between 0 and 50 ms.
- **E6 (V4a).** The longest application-queue wait is at least 3,000 ms; every kernel-accept-queue wait is under 10 ms; the median handler window is within 10% of V0's.
- **E7 (V4b).** The longest kernel-accept-queue wait is at least 3,000 ms; the application-queue wait is 0 by construction (reported, not tested); the median handler window is within 10% of V0's; the longest end-to-end time is within 10% of V4a's.
- **E8 (V5).** The seed makes 5 of the 400 requests' billing calls slow (counted from the seed before the first run: request indices 34, 137, 172, 249, 269). The 5 slowest requests by end-to-end time are exactly those 5; p95 is under 900 ms and p99 is at least 1,200 ms.
- **E9 (NC vs V0).** Median unattributed handler time rises by 17 to 23 ms; every leaf span's median changes by less than 5 ms.
- **E10 (repeatability).** For V0–V3, V5 and NC, the range of the three repeats' median end-to-end times is at most 10 ms in each slice.
- **E11 (two views, V0).** For every answer call, the application-observed total is at least the stand-in's reported `total_ms`, and the application-observed time to first chunk is at least its `prompt_eval_ms`. The median difference between the totals is under 5 ms.
- **E12 (TTFB).** For every request in every variant, the first byte received arrives in a read that contains answer text.

## Environment recorded with each run

Python version, platform, CPU count, load averages before and after, the number of established connections to Ollama's port 11434 before and after (other work on the machine), and the SHA-256 of this file, the settings, the answer text, and every Python file.
