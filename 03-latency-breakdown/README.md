# 03-latency-breakdown

Companion code for **Latency in AI Applications: Where Does the Time Actually Go?** (Article #35 on [snehalagrawal.com](https://snehalagrawal.com/articles/); link added when it's published).

A support assistant's chat request passes through several stages before the customer sees an answer:

```text
client ──► kernel accept queue ──► application worker queue ──► handler ──────────────────────────────► client
                                                                 read request, load state,
                                                                 model call 1: rewrite the question,
                                                                 retrieval, billing tool (40% of requests),
                                                                 model call 2: the answer (streamed),
                                                                 check, send
```

The demo records a timestamp at every boundary, in three separate processes, and asks:

1. **Do span durations add up to the end-to-end time, and when don't they?** Parallel calls, parent spans, and waits outside the handler break the sum. Critical-path attribution doesn't.
2. **Which number does each change move?** A faster model, parallel lookups, and streaming with a per-sentence check, each against the same baseline.
3. **Where does waiting for a worker show up?** In the application's own queue, where it can be timed, or in the kernel's listen backlog, where the application can't see it.
4. **What do the mean and the percentiles say about a rare slow dependency?**

## What is simulated, configured, and measured

This matters for every number below.

- **Simulated:** every dependency. `services.py` stands in for a search service, a billing API, and a model that streams. **No real model or provider is called**, so nothing here says how fast a real model, network, or provider is.
- **Configured:** the delays the stand-ins add (`data/settings.json`): the article's illustrative eight-second budget at one tenth scale, with seeded random variation. Which requests need the billing tool, and which billing calls are slow, are fixed by the seed, so the same request gets the same delays in every variant and repeat.
- **Measured:** timestamps from the client, the application, and the services, all on `time.monotonic_ns()` on one machine, and everything derived from them: real overhead (local HTTP connections, parsing, thread scheduling, sleep overshoot), queue waits that arise from arrivals and workers, the overlap of parallel calls, and the distributions.
- **Derived:** critical-path attribution, sums, percentiles, differences between variants (`breakdown.py`, `report.py`).

For real model timings, see the series' measured demos: [llm-inference](https://github.com/SnehalAgrawal/ai-engineering-examples/tree/main/llm-inference) (prefill, decode, prompt caching, model load, with Ollama's reported durations) and [streaming-responses](https://github.com/SnehalAgrawal/ai-engineering-examples/tree/main/streaming-responses) (time to first token, buffering proxies, check policies).

[PROTOCOL.md](PROTOCOL.md) defines every timestamp, segment, and statistic, and lists the expectations (E1-E12) written before the first full run.

## Run it

Python 3.10 or later, standard library only (no `pip install`, no model, no API key). Ports 8735 and 8736 must be free.

```bash
cd python
python -m unittest test_breakdown.py   # the arithmetic, on timelines with known answers
python run.py                          # 8 variants x 3 repeats, about 15 minutes; writes runs/ (not committed)
python report.py                       # the breakdown, comparisons, and E1-E12
```

`python run.py --variants V0-baseline V2-parallel-lookups --repeats 1` runs a subset; `python run.py --smoke 6` writes a quick test run under `runs/smoke/` (`python report.py --smoke` reads it). Change a delay in `data/settings.json` and run again to see which numbers move.

Expect the same shape of results, not the same digits: overhead, sleep accuracy and scheduling differ between machines and between runs.

## Files

| File | What it does |
|---|---|
| `data/settings.json` | every configured delay, the seed, and the variants |
| `data/answer.txt` | the answer text the stand-in model streams (7 sentences, in 35 chunks) |
| `python/services.py` | the stand-in search service, billing API, and model (one process) |
| `python/app.py` | the instrumented request path; a plain socket server with two ways of waiting for a worker |
| `python/client.py` | an open-loop client: each request starts on schedule, and latency counts from the intended start |
| `python/run.py` | starts the processes, runs every variant and repeat, records the environment |
| `python/breakdown.py` | segments, critical-path attribution, span sums, nearest-rank percentiles |
| `python/report.py` | joins the three records and prints the report; `--write` saves `results/` |
| `python/test_breakdown.py` | unit tests for `breakdown.py` |
| `results/report.txt`, `results/summary.json` | the report of the runs described below, and its statistics per repeat |

## The runs described here

- **Machine:** Python 3.12.13 (CPython), macOS 26.6.2 on arm64, 12 CPUs. Standard library only; no model.
- **Runs:** 8 variants × 3 repeats, ordered repeat by repeat, on 2026-11-24 from 18:10 to 18:23 (IST). 4,272 measured requests after the warm-ups; none failed.
- **Other work on the machine:** the 1-minute load average was 1.36 to 3.57, and at some checkpoints another program held 2 connections to the local Ollama server (this demo doesn't use it). The three repeats' medians stayed within 5.4 ms of each other in every compared variant and slice.
- **Inputs:** `PROTOCOL.md` SHA-256 `89208ade3ca2c09c…`, `data/settings.json` `44a0af5057a8bf46…`; the full hashes of every file are in [results/report.txt](results/report.txt).
- **Expectations:** 40 of 43 checks passed. E9 failed in all three repeats; see below.

## Results

All times in milliseconds, **measured on the simulated system** described above. Medians are nearest-rank; "[a-b]" is the range of the three repeats.

### 1. Span durations don't add up; boundaries do

One baseline request that used the billing tool (index 156, the one closest to its slice's median), repeat 1:

```text
                           start      end   duration
app worker queue             5.8      5.9      0.1
read_request                 5.9      6.0      0.1
load_state                   6.0     19.4     13.5
rewrite                     19.5    142.3    122.8
retrieval                  142.3    177.9     35.6
tool                       177.9    255.7     77.8
answer                     255.7    724.0    468.3
check                      724.1    758.3     34.3
send                       758.3    758.4      0.0
first and last byte received at 758.5
```

- Every request's segments (client start lag, connect, kernel accept queue, application worker queue, handler, delivery) add up exactly to its end-to-end time: all 4,272 requests (E2 tests the baseline's).
- **Baseline, tool requests (repeat 1, N=80), medians:** the handler took 752.5. Critical-path attribution: `answer` 481.5, `rewrite` 126.9, `tool` 65.7, `retrieval` 34.8, `check` 33.2, `load_state` 12.1, `read_request` 0.1, unattributed 0.2. The leaf spans added up to 752.4; adding the parent `lookups` span as well (a naive sum) gave 857.1.
- **The answer call** was 68.9% to 69.1% of the handler window (median per repeat; E1).
- **With parallel lookups,** the same request's leaf spans added up to 749.4 inside a handler of 713.9. Across tool requests, the leaf sum exceeded the handler window by a median of 34.0 to 34.7 (E4). Critical-path attribution gave the overlap to the billing call; retrieval's median attribution fell from 34.8 to 0.2.

### 2. Which number each change moves

```text
                                end-to-end, median                          first byte received, median
variant                         tool (N=80)          no tool (N=120)        all (N=200)
V0 baseline                     758.5 [758.0-759.5]  696.2 [692.6-697.7]    717.6 [714.9-718.3]
V1 faster decode                591.3 [590.7-592.8]  528.3 [526.9-528.6]    549.0 [548.8-551.3]
V2 parallel lookups             720.6 [718.4-722.9]  694.3 [692.3-696.5]    707.6 [704.8-707.9]
V3 per-sentence check, streamed 727.3 [725.4-727.8]  662.9 [662.6-664.2]    394.0 [390.2-395.0]
```

- **V1** cut end-to-end time by 165.7 to 169.1 per slice and repeat, about the 170 ms of decode it removed (E3). The first byte moved by the same amount, because the whole answer was still checked before any of it was sent. Every other span changed by less than 0.8.
- **V2** cut tool requests by 35.6 to 39.6 and changed no-tool requests by 3.9 or less (E4).
- **V3** brought the first byte forward by 323.3 to 324.7 and the last byte by only 29.5 to 33.0 (E5).

The stand-in model writes its first chunk of 10 tokens at the configured time to first token, so a 350-token answer ends 34 chunks later: about 150 + 340 = 490 ms configured, 482.6 median as the stand-in reported it.

### 3. Where waiting for a worker hides

12 requests at once, 2 workers, repeat 1, in the order the application accepted them:

```text
          accept, then queue (V4a)                        accept when free (V4b)
 #   kernel q.  app q.  handler     e2e      server view  kernel q.  app q.  handler     e2e      server view
 1     -0.3      0.1     840.7     850.5       840.8       -0.0      0.0     670.4     676.3       670.4
 2     -0.3      0.3     765.7     775.6       766.0       -0.1      0.0     782.4     788.4       782.4
 3     -0.2    766.3     780.7    1556.7      1547.0      670.8      0.0     682.5    1359.5       682.5
 4      0.0    840.7     708.9    1559.7      1549.6      782.8      0.0     708.9    1497.8       708.9
 5      0.0   1546.3     674.5    2231.6      2220.8     1353.7      0.0     672.0    2032.1       672.0
 6      0.0   1548.9     631.2    2191.4      2180.1     1492.3      0.0     629.1    2128.5       629.1
 7     -1.3   2180.5     694.3    2886.5      2874.8     2025.9      0.0     700.8    2733.5       700.8
 8      0.0   2219.9     753.9    2986.1      2973.8     2122.4      0.0     761.0    2890.1       761.0
 9      0.0   2874.8     667.4    3554.6      3542.2     2727.2      0.0     671.0    3405.2       671.0
10      0.1   2973.5     697.9    3684.7      3671.5     2884.0      0.0     698.5    3589.7       698.5
11     -0.1   3542.0     701.1    4256.4      4243.1     3398.6      0.0     693.5    4099.5       693.5
12      0.0   3671.7     689.4    4374.9      4361.1     3582.7      0.0     694.1    4284.1       694.1
```

"Server view" is what the application can time: from `accept()` to its last write. In V4a the wait is in the application's queue and in the server view; in V4b it is in the kernel's listen backlog and only the client's timestamps show it (E6, E7). The handler times are the same in both.

A kernel-accept-queue time can be slightly negative (down to -1.3 here): completing the handshake wakes both the client's `connect()` and the application's `accept()`, and whichever process runs first takes its timestamp first. Both read the same clock; the segment is simply close to zero.

### 4. A rare slow dependency

The seed made 5 of 400 requests' billing calls 600 ms slower (V5):

```text
repeat   N     mean    p50     p90     p95     p99 (rank 396)   max
1       400    726.4   714.2   778.7   793.9   1329.5           1382.3
2       400    727.7   714.6   780.9   793.1   1331.9           1383.0
3       400    729.5   715.9   781.6   797.5   1337.1           1379.3
V0 (for comparison, N=200): mean 722.9, p50 717.6, p95 790.6 (medians of the three repeats)
```

In every repeat, the 5 slowest requests were exactly the 5 with a slow billing call (E8). p95 stayed within 7 ms of the baseline's; p99 landed on a slow request. With 400 requests, only 4 values lie above the nearest-rank p99, so that p99 says no more than "at least 5 requests were slow".

### 5. Two views of one model call

The application saw the answer call's first chunk at a median of 153.7 to 153.9 and its last at 483.2 to 483.7. The stand-in model reported 152.9 to 153.0 and 482.3 to 482.7 for the same calls. The application's view was longer for every call, by a median of 0.78 to 0.89 (at most 4.86) per repeat (E11): a new local connection, the request, and the framing. Across a real network this gap would also include round trips and TLS, which this demo doesn't measure.

### The failed expectation: E9

The negative control adds a 20 ms step with no span. Median unattributed time rose by 23.9, 24.4, and 25.0 ms in the three repeats, more than the 17 to 23 ms the protocol expected, so E9 failed every time. Every instrumented span stayed within 0.82 ms of the baseline, so the extra time did appear as unattributed, as intended. The expectation got its size wrong.

A check made afterwards (post hoc, not part of the protocol) measured `time.sleep` on this machine, 60 calls each: a 10 ms sleep overshot by a median of 2.51 ms, a 20 ms sleep by 4.63 ms, and a 30 ms sleep by 3.77 ms. That matches the step taking about 24 ms. The other in-process sleeps show the same effect: `load_state`, configured with a median of 10 ms, measured a median of about 12. **Configured delays are nominal; the measured times include this overshoot.** The protocol wasn't changed.

## Limits

- Every dependency is simulated, and every magnitude comes from the settings. The results show how a breakdown behaves, not how fast any real system is.
- Everything runs on one machine over local connections: no real network, no TLS, no provider-side queue, no model.
- The client is the closest point to the user here. There is no browser, so "first byte received" isn't "first text on screen".
- One machine, one session, three repeats. Other programs were running (see above).

## Deviations

None from the protocol's code or settings after the first full run. The post-hoc sleep check is labelled as such above.
