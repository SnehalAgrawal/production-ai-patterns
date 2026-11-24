"""A simulated model provider and a simulated refund service, on 127.0.0.1. Standard library only.

This is a simulation. It speaks just enough of two APIs for their official Python SDKs to talk to it:

  POST /v1/chat/completions   OpenAI-style chat completion, JSON or server-sent events
  POST /v1/messages           Anthropic-style message, JSON or server-sent events
  POST /refunds               a payment service that issues a refund (writes to a ledger)
  GET  /refunds?reference=R   look a refund up by the caller's own reference

Each request gets the next behaviour from a script the scenario sets: answer (after a configured "generation"
time), fail with a status and a provider-shaped error body, hang, stream with configured gaps, stalls or an error
event, or send a body slowly. Nothing here says how a real provider behaves: the error bodies follow the shapes in
each provider's documentation, and the behaviours are the ones a scenario asks for.

Every arrival, completed generation, chunk, disconnect, and ledger write is recorded with time.monotonic_ns().
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def now_ns():
    return time.monotonic_ns()


def openai_error(type_, message, code=None):
    return {"error": {"message": message, "type": type_, "param": None, "code": code}}


def anthropic_error(type_, message, error_code=None):
    error = {"type": type_, "message": message}
    if error_code:
        error["details"] = {"error_code": error_code}
    return {"type": "error", "error": error, "request_id": "req_standin"}


def _completion(api, text, finish="stop"):
    if api == "openai":
        return {"id": "chatcmpl-standin", "object": "chat.completion", "created": 0, "model": "standin",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 10, "completion_tokens": len(text.split()), "total_tokens": 10}}
    return {"id": "msg_standin", "type": "message", "role": "assistant", "model": "standin",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn" if finish == "stop" else "max_tokens", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": len(text.split())}}


def _sse_events(api, chunks):
    """(prefix events, one event per chunk, suffix events) as bytes, in each API's streaming format."""
    def ev(name, data):
        head = f"event: {name}\n" if name else ""
        return (head + "data: " + json.dumps(data) + "\n\n").encode()
    if api == "openai":
        def chunk(c):
            return ev(None, {"id": "chatcmpl-standin", "object": "chat.completion.chunk", "created": 0,
                             "model": "standin", "choices": [{"index": 0, "delta": {"content": c},
                                                              "finish_reason": None}]})
        prefix = []
        suffix = [ev(None, {"id": "chatcmpl-standin", "object": "chat.completion.chunk", "created": 0,
                            "model": "standin", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
                  b"data: [DONE]\n\n"]
        return prefix, [chunk(c) for c in chunks], suffix
    start = {"type": "message_start", "message": {**_completion("anthropic", ""), "content": []}}
    prefix = [ev("message_start", start),
              ev("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "text", "text": ""}})]
    body = [ev("content_block_delta", {"type": "content_block_delta", "index": 0,
                                       "delta": {"type": "text_delta", "text": c}}) for c in chunks]
    suffix = [ev("content_block_stop", {"type": "content_block_stop", "index": 0}),
              ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn",
                                                                      "stop_sequence": None},
                                   "usage": {"output_tokens": len(chunks)}}),
              ev("message_stop", {"type": "message_stop"})]
    return prefix, body, suffix


def _stream_error(api, error):
    if api == "openai":
        return ("data: " + json.dumps(error) + "\n\n").encode()
    return ("event: error\ndata: " + json.dumps(error) + "\n\n").encode()


class StandIn:
    """Start with `with StandIn(model=[...], refund=[...]) as s:`; read s.events afterwards.

    `model` and `refund` are lists of behaviours, one per arrival; the last one repeats.
    `refund_lookup=False` makes GET /refunds return 404, as for a service with no way to look a refund up.
    """

    def __init__(self, model=None, refund=None, refund_lookup=True):
        self.scripts = {"model": list(model or [{"do": "ok"}]), "refund": list(refund or [{"do": "refund"}])}
        self.counts = {"model": 0, "refund": 0}
        self.refund_lookup = refund_lookup
        self.events, self.ledger = [], []
        self.lock = threading.Lock()
        standin = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                standin._handle(self, "POST")

            def do_GET(self):
                standin._handle(self, "GET")

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def record(self, **fields):
        with self.lock:
            self.events.append({"t_ns": now_ns(), **fields})

    def of(self, event, family=None):
        return [e for e in self.events if e["event"] == event and (family is None or e.get("family") == family)]

    def _next(self, family):
        with self.lock:
            n = self.counts[family]
            self.counts[family] += 1
            script = self.scripts[family]
            return n, script[min(n, len(script) - 1)]

    # ---- request handling -------------------------------------------------------------------------------------

    def _handle(self, h, method):
        url = urlparse(h.path)
        length = int(h.headers.get("Content-Length") or 0)
        body = json.loads(h.rfile.read(length) or b"{}") if method == "POST" else {}
        if url.path == "/refunds":
            return self._refund(h, method, url, body)
        api = "openai" if url.path.endswith("/chat/completions") else "anthropic"
        n, b = self._next("model")
        idem = sorted(k for k in h.headers.keys() if "idempotency" in k.lower())
        self.record(event="arrival", family="model", n=n, api=api, path=url.path, behaviour=b["do"],
                    retry_count=h.headers.get("x-stainless-retry-count"), tag=h.headers.get("x-demo-tag"),
                    idempotency_headers=idem, stream=bool(body.get("stream")))
        try:
            getattr(self, "_do_" + b["do"])(h, api, n, b)
        except (BrokenPipeError, ConnectionResetError):
            self.record(event="client_gone", family="model", n=n, at="write")

    def _send_json(self, h, code, payload, headers=None):
        data = json.dumps(payload).encode()
        h.send_response(code)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(data)
        h.wfile.flush()

    def _do_ok(self, h, api, n, b):
        time.sleep(b.get("after", 0.0))       # the "generation", which runs whether or not the client still waits
        self.record(event="generated", family="model", n=n)
        self._send_json(h, 200, _completion(api, b.get("text", "Your invoice is attached."), b.get("finish", "stop")))
        self.record(event="responded", family="model", n=n)

    def _do_status(self, h, api, n, b):
        self._send_json(h, b["code"], b["body"], b.get("headers"))
        self.record(event="responded", family="model", n=n, status=b["code"])

    def _do_hang(self, h, api, n, b):
        time.sleep(b.get("for", 30.0))         # accept the request, send nothing, then close
        self.record(event="closed_without_response", family="model", n=n)

    def _do_trickle(self, h, api, n, b):
        """A non-streaming response whose body arrives a few bytes at a time."""
        data = json.dumps(_completion(api, b.get("text", "Your invoice is attached."))).encode()
        pieces = b["pieces"]
        size = -(-len(data) // pieces)
        h.send_response(200)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.flush()
        for i in range(pieces):
            time.sleep(b["every"])
            h.wfile.write(data[i * size:(i + 1) * size])
            h.wfile.flush()
        self.record(event="responded", family="model", n=n)

    def _do_stream(self, h, api, n, b):
        chunks = b["chunks"]
        prefix, body, suffix = _sse_events(api, chunks)
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-cache")
        h.end_headers()                        # HTTP/1.0: the body ends when the connection closes
        for piece in prefix:
            h.wfile.write(piece)
        h.wfile.flush()
        time.sleep(b.get("first", 0.0))        # time to first token
        for i, piece in enumerate(body):
            if i and b.get("stall_after") == i:
                time.sleep(b["stall"])         # a stall in the middle of the stream
            elif i:
                time.sleep(b.get("gap", 0.0))
            if b.get("error_after") == i:
                h.wfile.write(_stream_error(api, b["error"]))
                h.wfile.flush()
                self.record(event="stream_error_sent", family="model", n=n, after_chunks=i)
                return
            try:
                h.wfile.write(piece)
                h.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                self.record(event="client_gone", family="model", n=n, at="chunk", chunks_sent=i)
                return                         # stop "generating": the stand-in cancels on disconnect
            self.record(event="chunk_sent", family="model", n=n, index=i)
        for piece in suffix:
            h.wfile.write(piece)
        h.wfile.flush()
        self.record(event="generated", family="model", n=n)
        self.record(event="responded", family="model", n=n)

    # ---- the refund service -------------------------------------------------------------------------------------

    def _refund(self, h, method, url, body):
        if method == "GET":
            reference = parse_qs(url.query).get("reference", [""])[0]
            self.record(event="lookup", family="refund", reference=reference)
            if not self.refund_lookup:
                return self._send_json(h, 404, {"error": "not supported"})
            with self.lock:
                found = [r for r in self.ledger if r["reference"] == reference]
            return self._send_json(h, 200, {"refunds": found})
        n, b = self._next("refund")
        self.record(event="arrival", family="refund", n=n, reference=body.get("reference"))
        time.sleep(b.get("commit_after", 0.0))
        with self.lock:                        # the refund is issued here, before the reply is sent
            self.ledger.append({"refund_id": f"rf_{len(self.ledger) + 1}", "reference": body.get("reference"),
                                "amount": body.get("amount")})
        self.record(event="ledger_write", family="refund", n=n)
        time.sleep(b.get("respond_after", 0.0))
        try:
            self._send_json(h, 200, {"status": "refunded", "refund_id": self.ledger[-1]["refund_id"]})
            self.record(event="responded", family="refund", n=n)
        except (BrokenPipeError, ConnectionResetError):
            self.record(event="client_gone", family="refund", n=n, at="write")
