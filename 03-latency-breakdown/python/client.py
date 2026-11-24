"""
The client: sends the requests on an open-loop schedule and timestamps what it sees.

Each request starts at its intended time whether or not earlier replies have arrived, and its latency is measured
from that intended time. A client that waits for each reply before sending the next would send less when the server
is slow, and hide exactly the waits this demo is about.
"""
import json
import socket
import threading

from common import NS_PER_MS, JsonLines, needs_tool, now_ns, sleep_until


def one_request(port: int, request: dict, intended_ns: int, log: JsonLines, warmup: bool = False) -> None:
    record = {**request, "intended_ns": intended_ns, "warmup": warmup}
    body = json.dumps(request).encode()
    head = (f"POST /ask HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode()
    try:
        record["started_ns"] = now_ns()
        sock = socket.create_connection(("127.0.0.1", port))
        record["connected_ns"] = now_ns()  # the kernel completed the handshake; the app may not have accepted yet
        sock.sendall(head + body)
        record["sent_ns"] = now_ns()
        data, first, last, first_has_text = b"", None, None, None
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            last = now_ns()
            if first is None:
                first = last
                end = chunk.find(b"\r\n\r\n")
                first_has_text = end >= 0 and len(chunk) > end + 4
            data += chunk
        sock.close()
        status, _, text = data.partition(b"\r\n\r\n")
        record.update(first_byte_ns=first, last_byte_ns=last, first_read_has_text=first_has_text,
                      status=status.split(b"\r\n")[0].decode(), text_chars=len(text.decode()))
    except OSError as error:
        record["error"] = repr(error)
    log.write(record)


def run(port: int, cfg: dict, requests: int, run_id: str, log: JsonLines) -> None:
    # Warm-up: closed loop, every path (the billing tool included), excluded from the results.
    for w in range(cfg["warmup"]):
        one_request(port, {"request_id": f"{run_id}-warmup-{w}", "index": -(w + 1), "needs_tool": True},
                    now_ns(), log, warmup=True)

    arrival = cfg["arrival"]
    interval_ns = int(arrival.get("interval_ms", 0) * NS_PER_MS) if arrival["kind"] == "steady" else 0
    t0 = now_ns() + 100 * NS_PER_MS
    threads = []
    for i in range(requests):
        intended = t0 + i * interval_ns
        sleep_until(intended)
        request = {"request_id": f"{run_id}-{i:03d}", "index": i, "needs_tool": needs_tool(cfg, i)}
        thread = threading.Thread(target=one_request, args=(port, request, intended, log))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
