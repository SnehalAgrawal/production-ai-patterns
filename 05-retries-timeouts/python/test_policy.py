"""Unit tests for policy.py with a fake clock and fake streams: python -m unittest test_policy.py"""

import asyncio
import random
import unittest

import policy
from policy import CallFailed, GiveUp, RetryBudget, StreamTimeout, call_model, classify, read_stream, worth_retrying


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def failing(*errors, then="ok"):
    """A send() that raises the given errors in order, then returns `then`; counts its calls."""
    calls = []

    def send(timeout):
        calls.append(timeout)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        return then
    return send, calls


class Classify(unittest.TestCase):
    def test_categories(self):
        cases = {
            CallFailed(status=400): "rejected", CallFailed(status=401): "rejected",
            CallFailed(status=429): "rate_limited", CallFailed(status=429, code="credit_balance_exhausted"):
            "limit_wont_clear", CallFailed(status=429, code="enforced_spend_limit_reached"): "limit_wont_clear",
            CallFailed(status=429, type="insufficient_quota"): "limit_wont_clear",
            CallFailed(status=503): "provider_error", CallFailed(status=529): "provider_error",
            CallFailed(kind="timeout"): "timeout", CallFailed(kind="connection"): "connection",
        }
        for err, want in cases.items():
            self.assertEqual(classify(err), want, err)

    def test_worth_retrying(self):
        self.assertTrue(worth_retrying(CallFailed(status=503)))
        self.assertTrue(worth_retrying(CallFailed(kind="timeout")))
        self.assertFalse(worth_retrying(CallFailed(status=400)))
        self.assertFalse(worth_retrying(CallFailed(status=429, code="credit_balance_exhausted")))


class Backoff(unittest.TestCase):
    def test_full_jitter_bounds(self):
        random.seed(1)
        for attempt in range(8):
            for _ in range(200):
                self.assertTrue(0 <= policy.backoff(attempt) <= min(8.0, 0.5 * 2 ** attempt))


class Budget(unittest.TestCase):
    def test_total_outage_caps_retries(self):
        b, retries = RetryBudget(0.1, 10.0), 0
        for _ in range(1000):
            b.record_request()
            retries += b.try_spend()
        self.assertLessEqual(retries, 110)
        self.assertGreaterEqual(retries, 100)


class CallModel(unittest.TestCase):
    def test_retries_then_succeeds(self):
        clock, (send, calls) = Clock(), failing(CallFailed(status=503), CallFailed(status=503))
        self.assertEqual(call_model(send, 100, RetryBudget(), now=clock.now, sleep=clock.sleep), "ok")
        self.assertEqual(len(calls), 3)

    def test_not_retryable_stops_at_once(self):
        clock, (send, calls) = Clock(), failing(CallFailed(status=400))
        with self.assertRaises(GiveUp) as cm:
            call_model(send, 100, RetryBudget(), now=clock.now, sleep=clock.sleep)
        self.assertEqual((cm.exception.reason, len(calls)), ("not_retryable", 1))

    def test_retry_after_is_honoured(self):
        clock, (send, _) = Clock(), failing(CallFailed(status=429, retry_after=7))
        call_model(send, 100, RetryBudget(), now=clock.now, sleep=clock.sleep)
        self.assertEqual(clock.t, 7)

    def test_retry_after_beyond_deadline_fails_now(self):
        clock, (send, calls) = Clock(), failing(CallFailed(status=429, retry_after=30))
        with self.assertRaises(GiveUp) as cm:
            call_model(send, 6, RetryBudget(), now=clock.now, sleep=clock.sleep)
        self.assertEqual((cm.exception.reason, len(calls), clock.t), ("no_time_left", 1, 0))

    def test_timeout_is_what_is_left(self):
        clock, (send, calls) = Clock(), failing()
        clock.t = 4
        call_model(send, 10, RetryBudget(), per_attempt=8, now=clock.now, sleep=clock.sleep)
        self.assertEqual(calls, [6])

    def test_empty_budget_stops_retries(self):
        clock, (send, calls) = Clock(), failing(CallFailed(status=503), CallFailed(status=503))
        with self.assertRaises(GiveUp) as cm:
            call_model(send, 100, RetryBudget(0.1, 0.0), now=clock.now, sleep=clock.sleep)
        self.assertEqual((cm.exception.reason, len(calls)), ("budget_exhausted", 1))


async def fake_stream(first, gap, n, stall_after=None, stall=0.0):
    await asyncio.sleep(first)
    for i in range(n):
        if i and i == stall_after:
            await asyncio.sleep(stall)
        elif i:
            await asyncio.sleep(gap)
        yield f"w{i} "


class ReadStream(unittest.TestCase):
    def run_stream(self, gen):
        return asyncio.run(read_stream(gen, first_token_s=0.2, idle_s=0.1, total_s=0.5))

    def test_healthy(self):
        self.assertEqual(self.run_stream(fake_stream(0.01, 0.01, 5)).split(), ["w0", "w1", "w2", "w3", "w4"])

    def test_each_clock(self):
        for gen, clock, chunks in ((fake_stream(0.4, 0.01, 5), "first_token", 0),
                                   (fake_stream(0.01, 0.01, 5, stall_after=2, stall=0.3), "idle", 2),
                                   (fake_stream(0.01, 0.05, 50), "total", None)):
            with self.assertRaises(StreamTimeout) as cm:
                self.run_stream(gen)
            self.assertEqual(cm.exception.clock, clock)
            if chunks is not None:
                self.assertEqual(len(cm.exception.partial), chunks)


if __name__ == "__main__":
    unittest.main()
