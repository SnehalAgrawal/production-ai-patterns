"""Fake-clock simulations: retry amplification across layers, what a retry budget does, and what jitter does to a
burst of retries. They run the article's call_model and RetryBudget unchanged against a simulated provider that
fails, with a fake clock, so nothing really waits. Seeded, so every run gives the same numbers.

These are simulations of the policy code, not measurements of any provider.
"""

import random

import policy
from policy import CallFailed, GiveUp, RetryBudget, call_model


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _requests(n, fail_probability, layers, attempts, budget, seed):
    """Send n requests through `layers` nested retry loops of `attempts` each; return provider calls and successes."""
    rng = random.Random(seed)
    policy.random.seed(seed)                       # backoff()'s jitter; only the clock depends on it here
    clock = FakeClock()
    calls = 0

    def provider(timeout):
        nonlocal calls
        calls += 1
        if rng.random() < fail_probability:
            raise CallFailed(status=503)
        return "ok"

    def layer(depth):
        inner = provider if depth == layers - 1 else (lambda timeout: _wrap(layer(depth + 1)))
        own_budget = budget if depth == layers - 1 else RetryBudget(ratio=1e9, capacity=1e9)  # outer layers unbudgeted
        return lambda timeout: call_model(inner, deadline=clock.now() + 1e9, budget=own_budget,
                                          max_attempts=attempts, now=clock.now, sleep=clock.sleep)

    def _wrap(fn):
        try:
            return fn(timeout=None)
        except GiveUp:
            raise CallFailed(status=503) from None  # the layer below gave up: to this layer it's just an error

    top = layer(0)
    ok = 0
    for _ in range(n):
        try:
            top(timeout=None)
            ok += 1
        except GiveUp:
            pass
    return {"provider_calls": calls, "succeeded": ok}


def amplification(n=1000, seed=7):
    """Provider calls for n user requests, under several policies and failure rates."""
    unlimited = lambda: RetryBudget(ratio=1e9, capacity=1e9)  # noqa: E731
    policies = {
        "no retries (1 attempt)": dict(layers=1, attempts=1, budget=unlimited),
        "3 attempts, one layer": dict(layers=1, attempts=3, budget=unlimited),
        "3 attempts x 2 layers": dict(layers=2, attempts=3, budget=unlimited),
        "3 attempts x 3 layers": dict(layers=3, attempts=3, budget=unlimited),
        "3 attempts + 10% retry budget": dict(layers=1, attempts=3, budget=lambda: RetryBudget(0.1, 10.0)),
    }
    results = {}
    for p in (0.05, 0.20, 1.00):
        for name, cfg in policies.items():
            r = _requests(n, p, cfg["layers"], cfg["attempts"], cfg["budget"](), seed)
            results[f"{p:.2f}|{name}"] = r
    return {"n": n, "seed": seed, "results": results}


def jitter_burst(clients=100, window_s=0.05, seed=11):
    """100 clients fail at t = 0 and schedule their first and second retries. Peak arrivals in any 50 ms window."""
    rng = random.Random(seed)
    policy.random.seed(seed)
    schemes = {
        "no jitter": lambda n: 0.5 * 2 ** n,
        "SDK-style (0-25% shorter)": lambda n: min(0.5 * 2 ** n, 8.0) * (1 - 0.25 * rng.random()),
        "full jitter": lambda n: policy.backoff(n),
    }
    out = {}
    for name, delay in schemes.items():
        for rnd in (0, 1):
            times = []
            for _ in range(clients):
                t = 0.0
                for n in range(rnd + 1):
                    t += delay(n)
                times.append(t)
            times.sort()
            peak, j = 0, 0
            for i in range(len(times)):           # largest number of arrivals within any window of window_s
                while times[i] - times[j] > window_s:
                    j += 1
                peak = max(peak, i - j + 1)
            out[f"{name}|retry {rnd + 1}"] = {"peak_in_window": peak, "first": round(times[0], 4),
                                              "last": round(times[-1], 4)}
    return {"clients": clients, "window_s": window_s, "seed": seed, "results": out}


if __name__ == "__main__":
    import json
    print(json.dumps({"amplification": amplification(), "jitter": jitter_burst()}, indent=2))
