"""
The support assistant's request path, instrumented at every boundary.

  python app.py --variant V0-baseline --port 8736 --services 8735 --out ../runs/V0-baseline/r1

A plain socket server, so the two places a request can wait for a worker stay apart (PROTOCOL.md):

  accept-then-queue   one thread accepts every connection at once and puts it on the application's queue;
                      a worker takes it from there. The wait is in the application's queue, and visible to it.
  accept-when-free    each worker calls accept() itself when it is free. A waiting connection stays in the
                      kernel's listen backlog, where the application can't timestamp it.

The handler records a span for every step except one: the negative control's extra step has no span on purpose.
"""
import argparse
import http.client
import json
import queue
import re
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from common import JsonLines, jitter, now_ns, variant_settings

HEADER = b"HTTP/1.0 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nConnection: close\r\n\r\n"


class Spans:
    def __init__(self):
        self.items = []

    @contextmanager
    def span(self, name: str, parent: bool = False):
        start = now_ns()
        try:
            yield
        finally:
            self.items.append({"name": name, "start_ns": start, "end_ns": now_ns(), "parent": parent})


def sleep_ms(ms: float) -> None:
    time.sleep(ms / 1000)


def post(port: int, path: str, payload: dict) -> http.client.HTTPResponse:
    """A new local connection for every call (no connection reuse), as the README states."""
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", path, json.dumps(payload), {"Content-Type": "application/json"})
    return conn.getresponse()


def call_model(port: int, payload: dict) -> dict:
    start = now_ns()
    reply = json.loads(post(port, "/model", payload).read())
    return {"start_ns": start, "end_ns": now_ns(), "reported": reply["reported"]}


def stream_model(port: int, payload: dict, on_text) -> dict:
    start = now_ns()
    response = post(port, "/model", payload)
    first = last = reported = None
    for line in iter(response.readline, b""):
        message = json.loads(line)
        if message.get("done"):
            reported = message["reported"]
            break
        last = now_ns()
        first = first or last
        on_text(message["text"])
    response.close()
    return {"start_ns": start, "first_chunk_ns": first, "last_chunk_ns": last, "end_ns": now_ns(),
            "reported": reported}


class Sender:
    """Writes the response. The status line and headers go out with the first answer text, in one write."""

    def __init__(self, conn: socket.socket):
        self.conn = conn
        self.first_write_ns = self.last_write_ns = None

    def write(self, text: str) -> None:
        data = text.encode()
        if self.first_write_ns is None:
            data = HEADER + data
        self.conn.sendall(data)
        self.last_write_ns = now_ns()
        self.first_write_ns = self.first_write_ns or self.last_write_ns


def read_request(conn: socket.socket) -> dict:
    data = b""
    while b"\r\n\r\n" not in data:
        data += conn.recv(65536)
    head, _, body = data.partition(b"\r\n\r\n")
    length = int(re.search(rb"content-length:\s*(\d+)", head, re.IGNORECASE).group(1))
    while len(body) < length:
        body += conn.recv(65536)
    return json.loads(body)


def handle(conn: socket.socket, accepted_ns: int, dequeued_ns: int, cfg: dict, services: int, log: JsonLines):
    seed, sigma = cfg["seed"], cfg["jitter_sigma"]
    sp = Spans()
    record = {"accepted_ns": accepted_ns, "dequeued_ns": dequeued_ns, "worker": threading.current_thread().name,
              "spans": sp.items, "model": {}}
    try:
        with sp.span("read_request"):
            request = read_request(conn)
        index = request["index"]
        record.update(request_id=request["request_id"], index=index, needs_tool=request["needs_tool"])
        ids = {"index": index, "request_id": request["request_id"]}

        with sp.span("load_state"):  # configured, in-process: load the conversation, check the account
            sleep_ms(cfg["load_state_ms"] * jitter(seed, sigma, "load_state", index))

        if cfg["rewrite"]["enabled"]:
            with sp.span("rewrite"):
                record["model"]["rewrite"] = call_model(services, {"kind": "rewrite", "stream": False, **ids})

        def lookup(name: str, path: str) -> None:
            with sp.span(name):
                post(services, path, ids).read()

        with sp.span("lookups", parent=True):
            steps = [("retrieval", "/search")] + ([("tool", "/invoices")] if request["needs_tool"] else [])
            if cfg["lookups"] == "parallel" and len(steps) > 1:
                threads = [threading.Thread(target=lookup, args=step) for step in steps]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            else:
                for step in steps:
                    lookup(*step)

        if cfg["uninstrumented_ms"]:
            sleep_ms(cfg["uninstrumented_ms"])  # the negative control: work with no span

        sender = Sender(conn)
        payload = {"kind": "answer", "stream": True, **ids}
        if cfg["check"]["mode"] == "whole-answer":
            parts = []
            with sp.span("answer"):
                record["model"]["answer"] = stream_model(services, payload, parts.append)
            with sp.span("check"):
                sleep_ms(cfg["check"]["whole_ms"] * jitter(seed, sigma, "check", index))
            with sp.span("send"):
                sender.write("".join(parts))
        else:
            pending = {"text": "", "n": 0}

            def release(sentence: str) -> None:
                with sp.span("check.sentence"):
                    sleep_ms(cfg["check"]["per_sentence_ms"] * jitter(seed, sigma, "check", index, pending["n"]))
                pending["n"] += 1
                with sp.span("send"):
                    sender.write(sentence)

            def on_text(text: str) -> None:
                pending["text"] += text
                while ". " in pending["text"]:
                    sentence, pending["text"] = pending["text"].split(". ", 1)
                    release(sentence + ". ")

            with sp.span("answer"):
                record["model"]["answer"] = stream_model(services, payload, on_text)
            if pending["text"]:
                release(pending["text"])

        record.update(first_write_ns=sender.first_write_ns, last_write_ns=sender.last_write_ns)
        conn.shutdown(socket.SHUT_WR)
    except Exception as error:  # recorded, never hidden: the report counts these
        record["error"] = repr(error)
    finally:
        conn.close()
        record["closed_ns"] = now_ns()
        log.write(record)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--services", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    cfg = variant_settings(args.variant)
    log = JsonLines(Path(args.out) / "app.jsonl")
    server = cfg["server"]

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", args.port))
    listener.listen(server["backlog"])

    if server["mode"] == "accept-then-queue":
        waiting: queue.Queue = queue.Queue()

        def accept_all() -> None:
            while True:
                conn, _ = listener.accept()
                waiting.put((conn, now_ns()))

        def worker() -> None:
            while True:
                conn, accepted = waiting.get()
                handle(conn, accepted, now_ns(), cfg, args.services, log)

        threading.Thread(target=accept_all, daemon=True, name="acceptor").start()
    elif server["mode"] == "accept-when-free":
        def worker() -> None:
            while True:
                conn, _ = listener.accept()
                accepted = now_ns()
                handle(conn, accepted, accepted, cfg, args.services, log)
    else:
        raise SystemExit(f"unknown server mode {server['mode']}")

    for n in range(server["workers"]):
        threading.Thread(target=worker, daemon=True, name=f"worker-{n}").start()
    print("ready", flush=True)
    threading.Event().wait()


if __name__ == "__main__":
    main()
