"""Part B: the official OpenAI and Anthropic Python SDKs, pointed at the local stand-in (base_url), no real API.

Run once per SDK, in its own process, with the demo's virtual environment:

    ../.venv/bin/python sdk_probe.py openai
    ../.venv/bin/python sdk_probe.py anthropic

What it measures: how many requests each SDK sends for each kind of failure (the stand-in counts arrivals and
reads the SDK's x-stainless-retry-count header), the retry delays the SDK chose (from its own INFO log line,
"Retrying request ... in X seconds"), the gaps between arrivals, whether a retried request carries an idempotency
header, what a timeout limits on a stream, and which exception reaches the caller.

The stand-in is a simulation: it returns the error bodies and headers each provider documents, and nothing else
about a real provider is reproduced. The API key is a dummy; no request leaves 127.0.0.1.
"""

import json
import logging
import re
import sys
import threading
import time
from importlib.metadata import version

import policy
from policy import CallFailed, GiveUp, RetryBudget, call_model
from standin import StandIn, anthropic_error, openai_error

SDK = sys.argv[1] if len(sys.argv) > 1 else "openai"
OK = {"do": "ok"}


class RetryLog(logging.Handler):
    """Collects the delay from each SDK 'Retrying request ... in X seconds' INFO line."""
    def __init__(self):
        super().__init__(logging.INFO)
        self.delays = []

    def emit(self, record):
        m = re.search(r"in ([0-9.]+) seconds", record.getMessage())
        if m and record.getMessage().startswith("Retrying request"):
            self.delays.append(round(float(m.group(1)), 3))


LOG = RetryLog()
logger = logging.getLogger(SDK)
logger.setLevel(logging.INFO)
logger.addHandler(LOG)
logger.propagate = False

if SDK == "openai":
    import openai as sdk

    def client(url, **kw):
        return sdk.OpenAI(base_url=f"{url}/v1", api_key="not-a-real-key", **kw)

    def ask(c, stream=False, **kw):
        return c.chat.completions.create(model="standin", stream=stream,
                                         messages=[{"role": "user", "content": "Where is my invoice?"}], **kw)

    def text_of(event):
        return (event.choices[0].delta.content or "") if event.choices else ""

    OVERLOADED = {"do": "status", "code": 503, "body": openai_error(
        "service_unavailable_error", "The model is overloaded.", "server_is_overloaded")}
    BAD_REQUEST = {"do": "status", "code": 400, "body": openai_error("invalid_request_error", "Unknown parameter.")}
    LIMIT_WONT_CLEAR = {"do": "status", "code": 429, "body": openai_error(
        "insufficient_quota", "No prepaid credits remaining.", "credit_balance_exhausted")}

    def rate_limited(seconds):
        return {"do": "status", "code": 429, "headers": {"Retry-After": str(seconds)},
                "body": openai_error("rate_limit_error", "Rate limit reached for requests.")}
    STREAM_ERROR = openai_error("server_error", "The model is overloaded.", "server_is_overloaded")
else:
    import anthropic as sdk

    def client(url, **kw):
        return sdk.Anthropic(base_url=url, api_key="not-a-real-key", **kw)

    def ask(c, stream=False, max_tokens=256, **kw):
        return c.messages.create(model="standin", max_tokens=max_tokens, stream=stream,
                                 messages=[{"role": "user", "content": "Where is my invoice?"}], **kw)

    def text_of(event):
        return event.delta.text if event.type == "content_block_delta" else ""

    OVERLOADED = {"do": "status", "code": 529, "body": anthropic_error("overloaded_error", "Overloaded")}
    BAD_REQUEST = {"do": "status", "code": 400, "body": anthropic_error("invalid_request_error", "Unknown field.")}
    LIMIT_WONT_CLEAR = {"do": "status", "code": 429, "body": anthropic_error(
        "rate_limit_error", "You have reached your API usage limits.", "enforced_spend_limit_reached")}

    def rate_limited(seconds):
        return {"do": "status", "code": 429, "headers": {"retry-after": str(seconds)},
                "body": anthropic_error("rate_limit_error", "Number of request tokens has exceeded your limit.")}
    STREAM_ERROR = anthropic_error("overloaded_error", "Overloaded")


def observe(s, elapsed, error=None, delays=None, **extra):
    arrivals = s.of("arrival", "model")
    times = [(a["t_ns"] - arrivals[0]["t_ns"]) / 1e9 for a in arrivals]
    return {
        "arrivals": len(arrivals),
        "retry_count_headers": [a["retry_count"] for a in arrivals],
        "idempotency_headers": sorted({h for a in arrivals for h in a["idempotency_headers"]}),
        "gaps_between_arrivals_s": [round(b - a, 3) for a, b in zip(times, times[1:])],
        "sdk_logged_delays_s": delays if delays is not None else [],
        "exception": type(error).__name__ if error else None,
        "exception_module": type(error).__module__ if error else None,
        "elapsed_s": round(elapsed, 3),
        **extra,
    }


def run(script, call, **client_kw):
    """Call through a fresh client against a stand-in running `script`; return observations."""
    LOG.delays = []
    with StandIn(model=script) as s:
        c = client(s.url, **client_kw)
        start, error, extra = time.monotonic(), None, {}
        try:
            result = call(c)
            extra = result if isinstance(result, dict) else {"answered": True}
        except Exception as err:  # noqa: BLE001  (the exception class is the observation)
            error = err
            extra = getattr(err, "_observed", {})
        elapsed = time.monotonic() - start
        time.sleep(0.2)                     # let the stand-in record anything still in flight
        return observe(s, elapsed, error, list(LOG.delays), **extra)


def stream_chunks(c, **kw):
    chunks = []
    try:
        for event in ask(c, stream=True, **kw):
            if text_of(event):
                chunks.append(text_of(event))
    except Exception as err:
        err._observed = {"chunks_received": len(chunks)}
        raise
    return {"chunks_received": len(chunks)}


def stream_behaviour(n, **kw):
    return {"do": "stream", "chunks": [f"w{i} " for i in range(n)], **kw}


def b7_layered():
    """An application loop of 3 attempts (policy.call_model) around the SDK's default retries."""
    LOG.delays = []
    with StandIn(model=[OVERLOADED]) as s:
        c = client(s.url)
        policy.random.seed(700)

        def send(timeout):
            try:
                return ask(c)
            except sdk.APIStatusError as err:
                raise CallFailed(status=err.status_code) from None

        start = time.monotonic()
        try:
            call_model(send, deadline=start + 60, budget=RetryBudget(), max_attempts=3)
            error = None
        except GiveUp as stop:
            error = stop
        elapsed = time.monotonic() - start
        time.sleep(0.2)
        return observe(s, elapsed, error, list(LOG.delays))


def b4_long_retry_after():
    """429 with Retry-After: 130 (just over OpenAI's documented-in-code 120 s cap), then success."""
    LOG.delays = []
    with StandIn(model=[rate_limited(130), OK]) as s:
        c = client(s.url)
        box = {}

        def call():
            try:
                ask(c)
                box["result"] = "answered"
            except Exception as err:  # noqa: BLE001
                box["result"] = type(err).__name__
        start = time.monotonic()
        t = threading.Thread(target=call, daemon=True)
        t.start()
        t.join(4.0)
        return observe(s, time.monotonic() - start, None, list(LOG.delays), still_waiting_at_4s=t.is_alive(),
                       caller_saw=box.get("result"))


def b11_nonstreaming_guard():
    LOG.delays = []
    with StandIn(model=[OK]) as s:
        start = time.monotonic()
        try:
            ask(client(s.url), max_tokens=64000)
            error = None
        except ValueError as err:
            error = err
        return observe(s, time.monotonic() - start, error, list(LOG.delays),
                       message=str(error)[:80] if error else None)


def b12_connection_refused():
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    LOG.delays = []
    c = client(f"http://127.0.0.1:{port}")
    start, error = time.monotonic(), None
    try:
        ask(c)
    except Exception as err:  # noqa: BLE001
        error = err
    return {"arrivals": None, "sdk_logged_delays_s": list(LOG.delays),
            "exception": type(error).__name__ if error else None,
            "exception_module": type(error).__module__ if error else None,
            "elapsed_s": round(time.monotonic() - start, 3)}


def main():
    out = {"sdk": SDK, "versions": {p: version(p) for p in (SDK, "httpx2", "httpcore2", "h11", "anyio", "pydantic")},
           "python": sys.version.split()[0], "scenarios": {}}
    sc = out["scenarios"]
    sc["B1 overloaded every time (defaults)"] = run([OVERLOADED], ask)
    sc["B2 400 invalid request (defaults)"] = run([BAD_REQUEST], ask)
    sc["B3 429 with Retry-After: 1, then success"] = run([rate_limited(1), OK], ask)
    sc["B5 429 that waiting won't fix, no Retry-After"] = run([LIMIT_WONT_CLEAR], ask)
    sc["B6 no response, timeout=1.0 (defaults otherwise)"] = run([{"do": "hang", "for": 4.0}], ask, timeout=1.0)
    sc["B7 application loop of 3 around the SDK"] = b7_layered()
    sc["B8 stream, a chunk every 0.5 s for 8 s, timeout=2.0"] = run(
        [stream_behaviour(16, first=0.5, gap=0.5)], stream_chunks, timeout=2.0)
    sc["B9 stream stalls after 3 chunks, timeout=1.0"] = run(
        [stream_behaviour(10, first=0.1, gap=0.1, stall_after=3, stall=5.0)], stream_chunks, timeout=1.0)
    sc["B10 error event after 3 chunks"] = run(
        [stream_behaviour(10, first=0.1, gap=0.1, error_after=3, error=STREAM_ERROR)], stream_chunks)
    sc["B12 connection refused (defaults)"] = b12_connection_refused()
    if SDK == "anthropic":
        sc["B11 non-streaming, max_tokens=64000, default timeout"] = b11_nonstreaming_guard()
    sc["B4 429 with Retry-After: 130, then success"] = b4_long_retry_after()   # last: may leave a sleeping thread
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
