"""Check a run against the expectations in PROTOCOL.md and print the report.

    python report.py                     the latest full run under runs/
    python report.py runs/<stamp>        a specific run
    python report.py --negative-control  the same checks with two expectations deliberately changed: must exit 1

The report has two parts. "Stable" lines hold only counts, outcomes, classes, and pass/fail, so three runs can be
compared byte for byte (compare.py). "Timings" hold the measured seconds, which vary from run to run.
Exit status: 0 if every expectation holds, 1 otherwise.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent
T = 0.15            # timing tolerance in seconds, for configured waits of 0.5 s or more (see PROTOCOL.md)

SDK_FIRST_RETRY = (0.375, 0.5)      # min(0.5 * 2**0, 8) reduced by 0-25%  (SDK source, both SDKs)
SDK_SECOND_RETRY = (0.75, 1.0)      # min(0.5 * 2**1, 8) reduced by 0-25%


def within(x, lo, hi):
    return x is not None and lo <= x <= hi


def full_jitter_ok(delays):
    return all(0 <= d <= 0.5 * 2 ** i for i, d in enumerate(delays))


def part_a_checks(a, neg):
    c = []
    a1 = a["A1"]
    c.append(("E1", "No timeout: still waiting at 3 s; returns only when the stand-in closes (6 s)",
              a1["still_waiting_at_3s"] and a1["ended_s"] >= 6.0 - T,
              f"still_waiting_at_3s={a1['still_waiting_at_3s']} how={a1['how']}"))
    a2 = a["A2"]
    want = {"400 invalid request": (1, "not_retryable"), "401 invalid API key": (1, "not_retryable"),
            "429 credit balance exhausted (OpenAI shape)": (1, "not_retryable"),
            "429 spend cap reached (Anthropic shape)": (1, "not_retryable"),
            "429 rate limit, Retry-After: 1, then success": (2, "ok"), "500 once, then success": (2, "ok"),
            "503 overloaded, every time (OpenAI shape)": (3, "attempts_exhausted"),
            "529 overloaded, every time (Anthropic shape)": (3, "attempts_exhausted"),
            "200, but cut off at the token limit": (1, "ok"),
            "connection refused (nothing listening)": (3, "attempts_exhausted")}
    for name, (attempts, outcome) in want.items():
        r = a2[name]
        ok = r["attempts"] == attempts and r["outcome"] == outcome and r["arrivals"] in (None, attempts)
        if "Retry-After: 1" in name:
            ok = ok and r["delays_s"] == [1.0] and r["elapsed_s"] >= 1.0
        elif r["delays_s"]:
            ok = ok and full_jitter_ok(r["delays_s"])
        if "cut off" in name:
            ok = ok and r["application_check"] == "unusable: cut off"
        c.append(("E2", f"Classification: {name}", ok,
                  f"attempts={r['attempts']} arrivals={r['arrivals']} outcome={r['outcome']} "
                  f"categories={','.join(r['categories'])}"
                  + (f" check={r['application_check']}" if r.get("application_check") else "")))
    a3 = a["A3"]
    c.append(("E3", "Retry-After: 30 with 6 s left: one attempt, fails at once",
              a3["attempts"] == 1 and a3["outcome"] == "no_time_left" and a3["elapsed_s"] < 0.1 + T,
              f"attempts={a3['attempts']} outcome={a3['outcome']}"))
    p, d = a["A4"]["per_attempt_only"], a["A4"]["with_2s_deadline"]
    c.append(("E4", "Hung provider, 1 s per attempt: 3 attempts and >= 3 s; with a 2 s deadline, <= 2 s",
              p["attempts"] == 3 and p["elapsed_s"] >= 3.0 and d["elapsed_s"] <= 2.0 + T
              and d["outcome"] in ("no_time_left", "deadline") and d["arrivals"] == d["attempts"],
              f"per_attempt_only attempts={p['attempts']}; with_deadline attempts={d['attempts']} "
              f"stopped_by_deadline={d['outcome'] in ('no_time_left', 'deadline')}"))
    a5 = a["A5"]
    c.append(("E5", "Application loop of 3 around a client loop of 3: 9 requests reach the provider",
              a5["arrivals"] == (3 if neg else 9), f"arrivals={a5['arrivals']} outcome={a5['outcome']}"))
    s6, d6 = a["A6"]["socket_timeout_1s"], a["A6"]["call_model_deadline_2s"]
    c.append(("E6", "Body in 8 pieces over 4 s: a 1 s socket timeout doesn't fire; a 2 s deadline passed as the "
              "per-wait timeout doesn't stop it", s6["outcome"] == "ok" and s6["elapsed_s"] >= 4.0 - T
              and d6["outcome"] == "ok" and d6["elapsed_s"] >= 4.0 - T,
              f"socket_timeout outcome={s6['outcome']}; deadline outcome={d6['outcome']} attempts={d6['attempts']}"))
    a7 = a["A7"]
    exp7 = {"healthy": ("complete", None, 10), "slow first token": ("timeout:first_token", 1.0, 0),
            "stalls after 3 chunks": ("timeout:idle", 0.8, 3), "steady but long": ("timeout:total", 3.0, None),
            "error event after 3 chunks": ("error_event", None, 3)}
    for name, (outcome, at, chunks) in exp7.items():
        r = a7[name]
        ok = r["outcome"] == outcome and r["arrivals"] == 1
        if chunks is not None:
            ok = ok and r["chunks"] == chunks
        else:
            ok = ok and 10 <= r["chunks"] <= 13
        if at is not None:
            ok = ok and within(r["elapsed_s"], at - T, at + T)
        if outcome.startswith("timeout"):
            ok = ok and r["standin_saw_disconnect"] and not r["standin_finished_generating"] \
                and r["standin_chunks_sent"] <= r["chunks"] + 2
        c.append(("E7", f"Stream clocks: {name}", ok,
                  f"outcome={r['outcome']} chunks={r['chunks']} arrivals={r['arrivals']} "
                  f"standin_disconnect={r['standin_saw_disconnect']} "
                  f"standin_finished={r['standin_finished_generating']} "
                  f"standin_sent_after_received={r['standin_chunks_sent'] - r['chunks']}"))
    a8 = a["A8"]
    c.append(("E8", "Timed out at 1 s, retried: the stand-in completed both generations, the first after 1 s",
              a8["attempts"] == 2 and a8["outcome"] == "ok" and a8["generations_completed"] == 2
              and a8["first_generation_finished_after_s"] >= 1.0,
              f"attempts={a8['attempts']} outcome={a8['outcome']} generations={a8['generations_completed']}"))
    a9 = a["A9"]
    exp9 = {"naive retry (like a model call)": ("failed", 3),
            "by retry class, with a lookup": ("done", 1),
            "by retry class, no lookup": ("unknown", 1),
            "by retry class, lookup before the write lands": ("not_applied", 1)}
    for name, (status, ledger) in exp9.items():
        r = a9[name]
        ok = r["status"] == status and r["ledger"] == ledger
        if "before the write" in name:
            ok = ok and r["ledger_when_executor_answered"] == 0
        c.append(("E9", f"Refund: {name}", ok,
                  f"status={r['status']} refunds_in_ledger={r['ledger']} requests={r['arrivals']}"))
    fields = ["request_id", "workload", "provider", "endpoint", "attempt", "category", "elapsed", "timeout",
              "delay", "outcome", "deadline_remaining"]
    a10 = a["A10"]
    for name, attempts, word in (("chat", 2, "try again"), ("nightly batch", 4, "queue")):
        r = a10[name]
        ok = len(r["records"]) == attempts and all(all(f in rec for f in fields) for rec in r["records"]) \
            and r["final"].startswith("gave up") and word in r["final"]
        c.append(("E10", f"Recovery exhausted, {name}: one record per attempt with every field; final decision",
                  ok, f"records={len(r['records'])} final={r['final']}"))
    return c


def simulation_checks(sim):
    c = []
    res = sim["amplification"]["results"]
    calls = {k.split("|")[1]: v["provider_calls"] for k, v in res.items() if k.startswith("1.00")}
    ok = (calls["no retries (1 attempt)"] == 1000 and calls["3 attempts, one layer"] == 3000
          and calls["3 attempts x 2 layers"] == 9000 and calls["3 attempts x 3 layers"] == 27000
          and calls["3 attempts + 10% retry budget"] <= 1110)
    c.append(("E11", "Total outage, 1,000 requests: 1,000 / 3,000 / 9,000 / 27,000 calls; budget <= 1,110", ok,
              " ".join(f"[{k}]={v}" for k, v in calls.items())))
    s05 = {k.split("|")[1]: v["succeeded"] for k, v in res.items() if k.startswith("0.05")}
    s20 = {k.split("|")[1]: v["succeeded"] for k, v in res.items() if k.startswith("0.20")}
    c.append(("E11", "5% failures: the budget changes no outcome; 20% failures: the budget costs successes",
              s05["3 attempts + 10% retry budget"] == s05["3 attempts, one layer"]
              and s20["3 attempts + 10% retry budget"] < s20["3 attempts, one layer"],
              f"5%: {s05['3 attempts, one layer']} vs {s05['3 attempts + 10% retry budget']}; "
              f"20%: {s20['3 attempts, one layer']} vs {s20['3 attempts + 10% retry budget']}"))
    j = sim["jitter"]["results"]
    for rnd in ("retry 1", "retry 2"):
        none, sdk, full = (j[f"{n}|{rnd}"]["peak_in_window"] for n in
                           ("no jitter", "SDK-style (0-25% shorter)", "full jitter"))
        c.append(("E12", f"Burst of 100 failures, {rnd}: peak per 50 ms, no jitter 100 > SDK-style > full jitter",
                  none == 100 and none > sdk > full, f"no_jitter={none} sdk_style={sdk} full_jitter={full}"))
    return c


def part_b_checks(sdk, b, neg):
    c, sc = [], b["scenarios"]
    tag = f"[{sdk}]"
    r = sc["B1 overloaded every time (defaults)"]
    dl = r["sdk_logged_delays_s"]
    c.append(("E13", f"{tag} Overloaded every time: 3 requests, retry-count 0,1,2, SDK delays in its ranges, "
              "no idempotency header",
              r["arrivals"] == (1 if neg else 3) and r["retry_count_headers"] == ["0", "1", "2"] and len(dl) == 2
              and within(dl[0], *SDK_FIRST_RETRY) and within(dl[1], *SDK_SECOND_RETRY)
              and all(g >= d for g, d in zip(r["gaps_between_arrivals_s"], dl)) and not r["idempotency_headers"],
              f"arrivals={r['arrivals']} retry_count={','.join(r['retry_count_headers'])} "
              f"idempotency_headers={r['idempotency_headers']} exception={r['exception']}"))
    r = sc["B2 400 invalid request (defaults)"]
    c.append(("E14", f"{tag} 400: one request", r["arrivals"] == 1,
              f"arrivals={r['arrivals']} exception={r['exception']}"))
    r = sc["B3 429 with Retry-After: 1, then success"]
    c.append(("E15", f"{tag} 429 + Retry-After: 1: two requests, the SDK waits the server's 1 s",
              r["arrivals"] == 2 and r["sdk_logged_delays_s"] == [1.0] and r["gaps_between_arrivals_s"][0] >= 1.0,
              f"arrivals={r['arrivals']} logged_delays={r['sdk_logged_delays_s']} exception={r['exception']}"))
    r = sc["B5 429 that waiting won't fix, no Retry-After"]
    c.append(("E16", f"{tag} 429 that waiting won't fix: the SDK still sends 3 requests", r["arrivals"] == 3,
              f"arrivals={r['arrivals']} exception={r['exception']}"))
    r = sc["B6 no response, timeout=1.0 (defaults otherwise)"]
    c.append(("E17", f"{tag} No response, timeout 1 s: 3 requests, >= 3 x 1 s + both delays, a timeout error",
              r["arrivals"] == 3 and r["elapsed_s"] >= 3.0 + sum(r["sdk_logged_delays_s"])
              and "Timeout" in (r["exception"] or ""),
              f"arrivals={r['arrivals']} exception={r['exception']}"))
    r = sc["B7 application loop of 3 around the SDK"]
    c.append(("E18", f"{tag} Application loop of 3 around the SDK's defaults: 9 requests", r["arrivals"] == 9,
              f"arrivals={r['arrivals']} retry_count={','.join(r['retry_count_headers'])}"))
    r = sc["B8 stream, a chunk every 0.5 s for 8 s, timeout=2.0"]
    c.append(("E19", f"{tag} Stream of 8 s, timeout 2 s: completes, no error", r["exception"] is None
              and r["chunks_received"] == 16 and r["elapsed_s"] >= 8.0 - T,
              f"chunks={r['chunks_received']} exception={r['exception']}"))
    r = sc["B9 stream stalls after 3 chunks, timeout=1.0"]
    c.append(("E20", f"{tag} Stream stalls after 3 chunks, timeout 1 s: an error after 3 chunks, not retried",
              r["arrivals"] == 1 and r["chunks_received"] == 3 and r["exception"] is not None
              and within(r["elapsed_s"], 1.3 - T, 1.3 + 2 * T),
              f"arrivals={r['arrivals']} chunks={r['chunks_received']} "
              f"exception={r['exception_module']}.{r['exception']}"))
    r = sc["B10 error event after 3 chunks"]
    c.append(("E21", f"{tag} Error event after 3 chunks (after a 200): an error after 3 chunks, not retried",
              r["arrivals"] == 1 and r["chunks_received"] == 3 and r["exception"] is not None,
              f"arrivals={r['arrivals']} chunks={r['chunks_received']} exception={r['exception']}"))
    r = sc["B12 connection refused (defaults)"]
    c.append(("E22", f"{tag} Connection refused: 2 retries in the SDK's ranges, a connection error",
              len(r["sdk_logged_delays_s"]) == 2 and within(r["sdk_logged_delays_s"][0], *SDK_FIRST_RETRY)
              and within(r["sdk_logged_delays_s"][1], *SDK_SECOND_RETRY) and r["exception"] == "APIConnectionError",
              f"retries={len(r['sdk_logged_delays_s'])} exception={r['exception']}"))
    r = sc["B4 429 with Retry-After: 130, then success"]
    if sdk == "openai":
        ok = r["arrivals"] == 1 and not r["still_waiting_at_4s"] and r["caller_saw"] == "RateLimitError"
        what = "raises at once (over its 120 s cap)"
    else:
        ok = r["arrivals"] == 1 and r["still_waiting_at_4s"] and r["sdk_logged_delays_s"] == [130.0]
        what = "waits the server's 130 s"
    c.append(("E23", f"{tag} 429 + Retry-After: 130: {what}", ok,
              f"arrivals={r['arrivals']} still_waiting_at_4s={r['still_waiting_at_4s']} "
              f"logged_delays={r['sdk_logged_delays_s']} caller_saw={r['caller_saw']}"))
    if sdk == "anthropic":
        r = sc["B11 non-streaming, max_tokens=64000, default timeout"]
        c.append(("E24", f"{tag} Non-streaming, max_tokens 64,000: ValueError before any request",
                  r["exception"] == "ValueError" and r["arrivals"] == 0,
                  f"arrivals={r['arrivals']} exception={r['exception']}"))
    return c


def timings(obs):
    lines = []
    a = obs["part_a"]
    lines.append(f"A1 naive call ended after {a['A1']['ended_s']} s ({a['A1']['how']})")
    for name, r in a["A2"].items():
        lines.append(f"A2 {name}: {r['elapsed_s']} s, delays {r['delays_s']}")
    lines.append(f"A3 {a['A3']['elapsed_s']} s")
    for k, r in a["A4"].items():
        lines.append(f"A4 {k}: {r['elapsed_s']} s, attempts {r['attempts']}, delays {r['delays_s']}")
    lines.append(f"A5 {a['A5']['elapsed_s']} s")
    for k, r in a["A6"].items():
        lines.append(f"A6 {k}: {r['elapsed_s']} s")
    for k, r in a["A7"].items():
        lines.append(f"A7 {k}: {r['elapsed_s']} s")
    lines.append(f"A8 {a['A8']['elapsed_s']} s; first generation finished {a['A8']['first_generation_finished_after_s']}"
                 f" s after it arrived")
    for k, r in a["A10"].items():
        lines.append(f"A10 {k}: {r['elapsed_s']} s; delays {[x['delay'] for x in r['records']]}")
    for sdk, b in (obs.get("part_b") or {}).items():
        for name, r in b["scenarios"].items():
            lines.append(f"[{sdk}] {name}: {r['elapsed_s']} s; delays {r['sdk_logged_delays_s']}; "
                         f"gaps {r.get('gaps_between_arrivals_s')}")
    return lines


def latest_run():
    runs = sorted(p for p in (DEMO / "runs").glob("2*") if "-" not in p.name[16:])
    return runs[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", nargs="?")
    ap.add_argument("--negative-control", action="store_true")
    args = ap.parse_args()
    run = Path(args.run) if args.run else latest_run()
    obs = json.loads((run / "observations.json").read_text())
    neg = args.negative_control

    checks = part_a_checks(obs["part_a"], neg) + simulation_checks(obs["simulation"])
    if obs.get("part_b"):
        for sdk, b in obs["part_b"].items():
            checks += part_b_checks(sdk, b, neg)

    stable = [f"{'PASS' if ok else 'FAIL'} {eid} {desc} | {detail}" for eid, desc, ok, detail in checks]
    if obs.get("part_b"):
        stable += [f"VERSIONS [{sdk}] {json.dumps(b['versions'], sort_keys=True)}" for sdk, b in obs["part_b"].items()]
    failed = [s for s in stable if s.startswith("FAIL")]
    digest = hashlib.sha256("\n".join(stable).encode()).hexdigest()

    out = [f"Run: {run.name}{'   NEGATIVE CONTROL (E5 and E13 changed on purpose)' if neg else ''}",
           f"Started {obs['started_utc']}, finished {obs['finished_utc']}",
           f"Environment: {json.dumps(obs['environment'], sort_keys=True)}",
           f"Calibration: {json.dumps(obs['calibration'], sort_keys=True)}",
           f"Freeze: matches={obs['freeze']['matches']}"
           + (f" frozen_at={obs['freeze'].get('frozen_at_utc')} changed={obs['freeze'].get('changed')}"
              if obs['freeze']['matches'] is not None else " (no manifest yet: development run)"),
           "", "== Stable ==", *stable, "", f"Stable digest: {digest}",
           f"Expectations: {len(stable) - len(failed) - sum(s.startswith('VERSIONS') for s in stable)} passed, "
           f"{len(failed)} failed", "", "== Timings (seconds; vary between runs) ==", *timings(obs)]
    text = "\n".join(out)
    print(text)
    if not neg:
        (run / "report.txt").write_text(text + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
