"""Part A: the policy (policy.py) and the tool executor (tools.py) against the stand-in, in real time.
Standard library only. Every timeout and delay is configured here, scaled down (seconds, not minutes).

Each scenario returns a dict of observations; report.py checks them against PROTOCOL.md's expectations.
"""

import asyncio
import random
import socket
import threading
import time

import policy
from http_send import StreamError, open_stream, send_chat
from policy import GiveUp, RetryBudget, StreamTimeout, call_model, read_stream
from standin import StandIn, anthropic_error, openai_error
from tools import execute_by_class, execute_naive

OK = {"do": "ok"}
OVERLOADED_OPENAI = {"do": "status", "code": 503,
                     "body": openai_error("service_unavailable_error", "The model is overloaded.", "server_is_overloaded")}
OVERLOADED_ANTHROPIC = {"do": "status", "code": 529, "body": anthropic_error("overloaded_error", "Overloaded")}


def _ms(seconds):
    return round(seconds * 1000, 1)


def _wait_for(standin, predicate, limit=5.0):
    """Let the stand-in finish what it was doing (it keeps working after the client gives up)."""
    end = time.monotonic() + limit
    while time.monotonic() < end and not predicate():
        time.sleep(0.02)


def _run_policy(standin, seed, path="/v1/chat/completions", **kwargs):
    random.seed(seed)                  # backoff()'s jitter, so the delays are the same in every run
    records = []
    start = time.monotonic()
    deadline = start + kwargs.pop("deadline_s", 10.0)
    finish = None
    try:
        result = call_model(lambda timeout: send_chat(standin.url, timeout, path=path), deadline=deadline,
                            budget=kwargs.pop("budget", RetryBudget()), record=lambda **f: records.append(f), **kwargs)
        outcome = "ok"
        finish = (result.get("choices") or [{}])[0].get("finish_reason") or result.get("stop_reason")
    except GiveUp as stop:
        outcome = stop.reason
    return {"outcome": outcome, "elapsed_s": round(time.monotonic() - start, 3), "finish_reason": finish,
            "application_check": None if finish is None else ("usable" if finish in ("stop", "end_turn")
                                                               else "unusable: cut off"),
            "attempts": len(records), "categories": [r["category"] for r in records],
            "delays_s": [round(r["delay"], 3) for r in records if r["delay"]],
            "arrivals": len(standin.of("arrival", "model"))}


def a1_naive_no_timeout():
    """No timeout at all, against a provider that accepts the request and sends nothing for 6 s."""
    with StandIn(model=[{"do": "hang", "for": 6.0}]) as s:
        result = {}

        def call():
            t0 = time.monotonic()
            try:
                send_chat(s.url, timeout=None)
                result["how"] = "answer"
            except policy.CallFailed as err:
                result["how"] = err.kind
            result["ended_s"] = round(time.monotonic() - t0, 2)

        t = threading.Thread(target=call, daemon=True)
        t.start()
        t.join(3.0)
        still_waiting = t.is_alive()
        t.join(10.0)
    return {"still_waiting_at_3s": still_waiting, **result}


def _closed_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def a2_classification():
    """Each kind of failure through call_model: 3 attempts, 2 s per attempt, 10 s deadline."""
    cases = {
        "400 invalid request": [{"do": "status", "code": 400,
                                 "body": openai_error("invalid_request_error", "Unknown parameter.")}],
        "401 invalid API key": [{"do": "status", "code": 401,
                                 "body": openai_error("invalid_request_error", "Incorrect API key.", "invalid_api_key")}],
        "429 credit balance exhausted (OpenAI shape)": [{"do": "status", "code": 429, "body": openai_error(
            "insufficient_quota", "No prepaid credits remaining.", "credit_balance_exhausted")}],
        "429 spend cap reached (Anthropic shape)": [{"do": "status", "code": 429, "body": anthropic_error(
            "rate_limit_error", "You have reached your API usage limits.", "enforced_spend_limit_reached")}],
        "429 rate limit, Retry-After: 1, then success": [
            {"do": "status", "code": 429, "headers": {"Retry-After": "1"},
             "body": openai_error("rate_limit_error", "Rate limit reached for requests.")}, OK],
        "500 once, then success": [{"do": "status", "code": 500,
                                    "body": openai_error("server_error", "The server had an error.")}, OK],
        "503 overloaded, every time (OpenAI shape)": [OVERLOADED_OPENAI],
        "529 overloaded, every time (Anthropic shape)": [OVERLOADED_ANTHROPIC],
        "200, but cut off at the token limit": [{"do": "ok", "finish": "length", "text": "Your invoice for March"}],
    }
    out = {}
    for i, (name, script) in enumerate(cases.items()):
        path = "/v1/messages" if "Anthropic" in name else "/v1/chat/completions"
        with StandIn(model=script) as s:
            out[name] = _run_policy(s, seed=100 + i, path=path, max_attempts=3, per_attempt=2.0)
    # No server listening: the connection is refused before anything is sent.
    random.seed(200)
    records, port = [], _closed_port()
    start = time.monotonic()
    try:
        call_model(lambda timeout: send_chat(f"http://127.0.0.1:{port}", timeout), deadline=start + 10,
                   budget=RetryBudget(), max_attempts=3, per_attempt=2.0, record=lambda **f: records.append(f))
        outcome = "ok"
    except GiveUp as stop:
        outcome = stop.reason
    out["connection refused (nothing listening)"] = {
        "outcome": outcome, "elapsed_s": round(time.monotonic() - start, 3), "attempts": len(records),
        "categories": [r["category"] for r in records],
        "delays_s": [round(r["delay"], 3) for r in records if r["delay"]], "arrivals": None}
    return out


def a3_retry_after_beyond_deadline():
    """The provider asks for 30 s; the request has 6 s left."""
    script = [{"do": "status", "code": 429, "headers": {"Retry-After": "30"},
               "body": openai_error("rate_limit_error", "Rate limit reached for requests.")}, OK]
    with StandIn(model=script) as s:
        return _run_policy(s, seed=300, max_attempts=3, per_attempt=2.0, deadline_s=6.0)


def a4_deadline():
    """A provider that sends nothing: 1 s per attempt and 3 attempts, without and with a 2 s deadline."""
    hang = [{"do": "hang", "for": 4.0}]
    with StandIn(model=hang) as s:
        no_deadline = _run_policy(s, seed=400, max_attempts=3, per_attempt=1.0, deadline_s=1e6)
    with StandIn(model=hang) as s:
        with_deadline = _run_policy(s, seed=400, max_attempts=3, per_attempt=1.0, deadline_s=2.0)
    return {"per_attempt_only": no_deadline, "with_2s_deadline": with_deadline}


def a5_layered():
    """An application loop of 3 attempts around a client that also makes 3, on a provider that keeps failing."""
    with StandIn(model=[OVERLOADED_OPENAI]) as s:
        random.seed(500)

        def inner(timeout):
            try:
                return call_model(lambda timeout: send_chat(s.url, timeout), deadline=time.monotonic() + 30,
                                  budget=RetryBudget(), max_attempts=3, per_attempt=2.0)
            except GiveUp as stop:
                raise stop.last from None     # to the outer loop, it's the same 503

        start = time.monotonic()
        try:
            call_model(inner, deadline=start + 60, budget=RetryBudget(), max_attempts=3)
            outcome = "ok"
        except GiveUp as stop:
            outcome = stop.reason
        return {"outcome": outcome, "arrivals": len(s.of("arrival", "model")),
                "elapsed_s": round(time.monotonic() - start, 3)}


def a6_per_wait_not_total():
    """A non-streaming body sent in 8 pieces, one every 0.5 s. http.client's 1 s timeout; then a 2 s deadline."""
    trickle = [{"do": "trickle", "pieces": 8, "every": 0.5}]
    with StandIn(model=trickle) as s:
        t0 = time.monotonic()
        send_chat(s.url, timeout=1.0)
        plain = {"outcome": "ok", "elapsed_s": round(time.monotonic() - t0, 3)}
    with StandIn(model=trickle) as s:
        deadline = _run_policy(s, seed=600, max_attempts=3, deadline_s=2.0)
    return {"socket_timeout_1s": plain, "call_model_deadline_2s": deadline}


STREAMS = {
    "healthy": {"first": 0.2, "gap": 0.1, "n": 10},
    "slow first token": {"first": 2.0, "gap": 0.1, "n": 10},
    "stalls after 3 chunks": {"first": 0.1, "gap": 0.1, "n": 10, "stall_after": 3, "stall": 2.0},
    "steady but long": {"first": 0.1, "gap": 0.25, "n": 20},
    "error event after 3 chunks": {"first": 0.1, "gap": 0.1, "n": 10, "error_after": 3},
}
CLOCKS = {"first_token_s": 1.0, "idle_s": 0.5, "total_s": 3.0}


def a7_stream_clocks():
    out = {}
    for name, cfg in STREAMS.items():
        behaviour = {"do": "stream", "chunks": [f"w{i} " for i in range(cfg["n"])], "first": cfg["first"],
                     "gap": cfg["gap"]}
        for key in ("stall_after", "stall", "error_after"):
            if key in cfg:
                behaviour[key] = cfg[key]
        if "error_after" in cfg:
            behaviour["error"] = openai_error("server_error", "The model is overloaded.", "server_is_overloaded")
        with StandIn(model=[behaviour]) as s:
            t0 = time.monotonic()
            try:
                text = asyncio.run(read_stream(open_stream(s.url), **CLOCKS))
                result = {"outcome": "complete", "chunks": len(text.split())}
            except StreamTimeout as err:
                result = {"outcome": f"timeout:{err.clock}", "chunks": len(err.partial)}
            except StreamError as err:
                result = {"outcome": "error_event", "chunks": len(err.partial)}
            result["elapsed_s"] = round(time.monotonic() - t0, 3)
            _wait_for(s, lambda s=s: s.of("client_gone") or s.of("generated") or s.of("stream_error_sent"))
            gone = s.of("client_gone")
            result.update({
                "arrivals": len(s.of("arrival", "model")),
                "standin_finished_generating": bool(s.of("generated")),
                "standin_chunks_sent": len(s.of("chunk_sent")),
                "standin_saw_disconnect": bool(gone),
            })
        out[name] = result
    return out


def a8_ambiguous_model_call():
    """The first attempt takes 1.5 s to generate; the client gives up after 1 s and retries; the retry is fast."""
    with StandIn(model=[{"do": "ok", "after": 1.5}, OK]) as s:
        result = _run_policy(s, seed=800, max_attempts=3, per_attempt=1.0)
        _wait_for(s, lambda: len(s.of("generated")) >= 2)
        arrivals = s.of("arrival", "model")
        first_gen = [e for e in s.of("generated") if e["n"] == 0]
        result.update({
            "generations_completed": len(s.of("generated")),
            "first_generation_finished_after_s": round((first_gen[0]["t_ns"] - arrivals[0]["t_ns"]) / 1e9, 3)
            if first_gen else None,
        })
        return result


def a9_refund():
    """issue_refund: the payment service writes the refund at 0.2 s and answers at 1.5 s. The executor waits 1 s."""
    slow = [{"do": "refund", "commit_after": 0.2, "respond_after": 1.3}]
    out = {}
    with StandIn(refund=slow) as s:
        r = execute_naive(s.url, "case-0412-refund", 30)
        _wait_for(s, lambda: len(s.of("responded", "refund")) + len(s.of("client_gone", "refund")) >= 3)
        out["naive retry (like a model call)"] = {**r, "ledger": len(s.ledger),
                                                   "arrivals": len(s.of("arrival", "refund"))}
    with StandIn(refund=slow) as s:
        r = execute_by_class("issue_refund", s.url, "case-0412-refund", 30)
        time.sleep(1.0)
        out["by retry class, with a lookup"] = {**r, "ledger": len(s.ledger),
                                                 "arrivals": len(s.of("arrival", "refund"))}
    with StandIn(refund=slow, refund_lookup=False) as s:
        r = execute_by_class("issue_refund", s.url, "case-0412-refund", 30)
        time.sleep(1.0)
        out["by retry class, no lookup"] = {**r, "ledger": len(s.ledger),
                                             "arrivals": len(s.of("arrival", "refund"))}
    late = [{"do": "refund", "commit_after": 1.6, "respond_after": 0.4}]
    with StandIn(refund=late) as s:
        r = execute_by_class("issue_refund", s.url, "case-0412-refund", 30)
        ledger_at_answer = len(s.ledger)
        time.sleep(2.0)
        out["by retry class, lookup before the write lands"] = {
            **r, "ledger_when_executor_answered": ledger_at_answer, "ledger": len(s.ledger),
            "arrivals": len(s.of("arrival", "refund"))}
    return out


def a10_exhausted():
    """Recovery runs out: the same overloaded provider under a chat policy and a batch policy, with the record."""
    workloads = {
        "chat": {"deadline_s": 2.0, "max_attempts": 2, "per_attempt": 1.0,
                 "decision": "show a fixed message with a 'try again' button"},
        "nightly batch": {"deadline_s": 30.0, "max_attempts": 4, "per_attempt": 2.0,
                          "decision": "put the ticket back in the queue for a later run"},
    }
    out = {}
    for i, (name, cfg) in enumerate(workloads.items()):
        with StandIn(model=[OVERLOADED_OPENAI]) as s:
            random.seed(1000 + i)
            records, start = [], time.monotonic()
            deadline = start + cfg["deadline_s"]

            def record(records=records, name=name, deadline=deadline, **f):
                records.append({"request_id": f"req-{name.split()[0]}-1", "workload": name,
                                "provider": "standin (OpenAI shape)", "endpoint": "/v1/chat/completions",
                                **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in f.items()},
                                "deadline_remaining": round(deadline - time.monotonic(), 3)})
            try:
                call_model(lambda timeout: send_chat(s.url, timeout), deadline=deadline, budget=RetryBudget(),
                           max_attempts=cfg["max_attempts"], per_attempt=cfg["per_attempt"], record=record)
                final = "answered"
            except GiveUp as stop:
                final = f"gave up ({stop.reason}): {cfg['decision']}"
            out[name] = {"records": records, "final": final, "elapsed_s": round(time.monotonic() - start, 3)}
    return out


SCENARIOS = {
    "A1": a1_naive_no_timeout, "A2": a2_classification, "A3": a3_retry_after_beyond_deadline, "A4": a4_deadline,
    "A5": a5_layered, "A6": a6_per_wait_not_total, "A7": a7_stream_clocks, "A8": a8_ambiguous_model_call,
    "A9": a9_refund, "A10": a10_exhausted,
}
