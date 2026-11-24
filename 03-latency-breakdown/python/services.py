"""
The stand-in dependencies, in one process: a search service, a billing API, and a model that can stream.

  python services.py --variant V0-baseline --out ../runs/V0-baseline/r1

Every delay is configured (data/settings.json) and fixed per request index by the seed, so the same request gets the
same delays in every variant and every repeat. Nothing here is a real model or a real provider.

  POST /search    {"index": i}                     retrieval
  POST /invoices  {"index": i}                     the billing tool
  POST /model     {"kind": "rewrite"|"answer", "index": i, "stream": bool}

The model's final message reports its own durations, modelled on Ollama's fields (prompt_eval, eval, total): what a
provider-side timer sees, from the moment the request reached its handler to the last chunk it wrote.
"""
import argparse
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from common import DATA, NS_PER_MS, JsonLines, billing_is_slow, jitter, now_ns, sleep_until, variant_settings

ANSWER = (DATA / "answer.txt").read_text().strip()
REWRITE = "Which charges are on my two most recent invoices, and why is the second one different?"


def pieces(text: str, n: int) -> list[str]:
    size = math.ceil(len(text) / n)
    return [text[i:i + size] for i in range(0, len(text), size)]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep stderr quiet
        pass

    def do_POST(self):
        received = now_ns()
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        cfg = self.server.config
        index = body["index"]
        record = {"service": self.path.strip("/"), "index": index, "request_id": body.get("request_id"),
                  "received_ns": received}
        if self.path == "/search":
            delay = cfg["retrieval_ms"] * jitter(cfg["seed"], cfg["jitter_sigma"], "retrieval", index)
            sleep_until(received + int(delay * NS_PER_MS))
            self.reply({"chunks": ["plans", "billing"]}, record)
        elif self.path == "/invoices":
            slow = billing_is_slow(cfg, index)
            delay = cfg["billing"]["ms"] * jitter(cfg["seed"], cfg["jitter_sigma"], "billing", index)
            delay += cfg["billing"]["slow_extra_ms"] if slow else 0
            record["slow"] = slow
            sleep_until(received + int(delay * NS_PER_MS))
            self.reply({"invoices": ["INV-1001", "INV-1002"]}, record)
        elif self.path == "/model":
            self.model(body, record)
        else:
            self.send_error(404)

    def reply(self, payload: dict, record: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        record["last_write_ns"] = now_ns()
        self.server.log.write(record)

    def model(self, body: dict, record: dict) -> None:
        cfg = self.server.config
        kind, index = body["kind"], body["index"]
        m = cfg[kind]
        received = record["received_ns"]
        ttft_ns = int(m["ttft_ms"] * jitter(cfg["seed"], cfg["jitter_sigma"], kind, "ttft", index) * NS_PER_MS)
        per_token_ms = m["ms_per_output_token"] * jitter(cfg["seed"], cfg["decode_jitter_sigma"], kind, "decode", index)
        record["kind"] = kind
        if not body.get("stream"):
            decode_ns = int(m["output_tokens"] * per_token_ms * NS_PER_MS)
            sleep_until(received + ttft_ns + decode_ns)
            total_ms = (now_ns() - received) / NS_PER_MS
            self.reply({"text": REWRITE, "reported": {"total_ms": total_ms}}, record)
            return
        chunks = pieces(ANSWER, math.ceil(m["output_tokens"] / m["chunk_tokens"]))
        per_chunk_ns = int(m["chunk_tokens"] * per_token_ms * NS_PER_MS)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()  # headers go out at once, as a streaming API sends them before the first token
        first = None
        for k, text in enumerate(chunks):
            sleep_until(received + ttft_ns + k * per_chunk_ns)
            self.wfile.write((json.dumps({"text": text}) + "\n").encode())
            first = first or now_ns()
        last = now_ns()
        reported = {"prompt_eval_ms": (first - received) / NS_PER_MS, "eval_ms": (last - first) / NS_PER_MS,
                    "total_ms": (last - received) / NS_PER_MS}
        self.wfile.write((json.dumps({"done": True, "reported": reported}) + "\n").encode())
        record.update(first_write_ns=first, last_write_ns=last, reported=reported)
        self.server.log.write(record)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    server = Server(("127.0.0.1", args.port), Handler)
    server.config = variant_settings(args.variant)
    server.log = JsonLines(Path(args.out) / "services.jsonl")
    print("ready", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
