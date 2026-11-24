"""Part A's HTTP client for the stand-in: standard library only, SDK-free.

send_chat()   one non-streaming call with http.client, translated into CallFailed on failure
open_stream() a streaming call as an async generator of text chunks (asyncio streams), closable with aclose()

http.client's `timeout` is a socket timeout: it limits connecting and each blocking read, not the whole call
(scenario A6 measures this). The deadline in call_model is passed as that per-wait timeout, which is enough for a
call that sends nothing, but not for one that sends slowly.
"""

import asyncio
import http.client
import json

from policy import CallFailed


def _error_fields(status, headers, raw):
    """Read the error code from wherever each provider puts it."""
    code = type_ = None
    try:
        body = json.loads(raw or b"{}")
        error = body.get("error") or {}
        type_ = error.get("type")
        code = error.get("code") or (error.get("details") or {}).get("error_code")  # OpenAI | Anthropic
    except (ValueError, AttributeError):
        pass
    retry_after = headers.get("retry-after")
    try:
        retry_after = float(retry_after) if retry_after is not None else None
    except ValueError:
        retry_after = None                     # an HTTP date: not used by these scenarios
    return CallFailed(status=status, retry_after=retry_after, code=code, type=type_)


def send_chat(base_url, timeout, tag=None, path="/v1/chat/completions"):
    host, port = base_url.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=timeout)
    body = json.dumps({"model": "standin", "messages": [{"role": "user", "content": "Where is my invoice?"}]})
    headers = {"Content-Type": "application/json", **({"x-demo-tag": tag} if tag else {})}
    try:
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read()
    except TimeoutError:
        raise CallFailed(kind="timeout") from None
    except (ConnectionError, http.client.RemoteDisconnected, OSError):
        raise CallFailed(kind="connection") from None
    finally:
        conn.close()
    if response.status >= 400:
        raise _error_fields(response.status, response.headers, raw)
    return json.loads(raw)


def timed_get(url, timeout):
    """A plain GET for the refund lookup: (status, parsed body)."""
    host_port, _, rest = url.removeprefix("http://").partition("/")
    host, port = host_port.split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=timeout)
    try:
        conn.request("GET", "/" + rest)
        response = conn.getresponse()
        return response.status, json.loads(response.read() or b"{}")
    finally:
        conn.close()


def post_json(url, payload, timeout):
    """A POST for the refund tool, translated into CallFailed like send_chat."""
    host_port, _, rest = url.removeprefix("http://").partition("/")
    host, port = host_port.split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=timeout)
    try:
        conn.request("POST", "/" + rest, body=json.dumps(payload), headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        raw = response.read()
    except TimeoutError:
        raise CallFailed(kind="timeout") from None
    except ConnectionRefusedError:
        raise CallFailed(kind="not_sent") from None      # the connection was refused: nothing reached the service
    except (ConnectionError, OSError):
        raise CallFailed(kind="connection") from None
    finally:
        conn.close()
    if response.status >= 400:
        raise _error_fields(response.status, response.headers, raw)
    return json.loads(raw)


class StreamError(Exception):
    def __init__(self, error, partial):
        super().__init__(f"error event after {len(partial)} chunks: {error}")
        self.error, self.partial = error, partial


async def open_stream(base_url, tag=None):
    """Yield the text of each chunk of an OpenAI-style stream from the stand-in. Closing it closes the socket."""
    host, port = base_url.removeprefix("http://").split(":")
    reader, writer = await asyncio.open_connection(host, int(port))
    received = []
    try:
        body = json.dumps({"model": "standin", "stream": True,
                           "messages": [{"role": "user", "content": "Summarise my last invoice."}]}).encode()
        head = (f"POST /v1/chat/completions HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n" + (f"x-demo-tag: {tag}\r\n" if tag else "") + "\r\n")
        writer.write(head.encode() + body)
        await writer.drain()
        while (await reader.readline()) not in (b"\r\n", b"\n", b""):
            pass                                          # status line and headers
        while True:
            line = await reader.readline()
            if not line:
                return
            if not line.startswith(b"data: "):
                continue
            data = line[6:].strip()
            if data == b"[DONE]":
                return
            event = json.loads(data)
            if "error" in event:
                raise StreamError(event["error"], received)
            text = event["choices"][0]["delta"].get("content")
            if text:
                received.append(text)
                yield text
    finally:
        writer.close()                                    # on completion, error, timeout or aclose()

