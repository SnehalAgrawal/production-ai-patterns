"""
The arithmetic of a breakdown, kept apart from the runs so it can be tested on timelines with known answers
(test_breakdown.py). Definitions: PROTOCOL.md.
"""
import math

SEGMENTS = [
    ("schedule_lag", "intended_ns", "started_ns"),
    ("connect", "started_ns", "connected_ns"),
    ("kernel_accept_queue", "connected_ns", "accepted_ns"),
    ("app_worker_queue", "accepted_ns", "dequeued_ns"),
    ("handler", "dequeued_ns", "last_write_ns"),
    ("delivery", "last_write_ns", "last_byte_ns"),
]


def nearest_rank(values: list[float], p: float) -> float:
    """The p-th percentile by nearest rank: the value at rank ceil(p/100 * N) of the sorted values."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def median(values: list[float]) -> float:
    """The median, as the nearest-rank p50 (an actual value, never an average of two)."""
    return nearest_rank(values, 50)


def segments(times: dict) -> dict[str, int]:
    """Consecutive timestamps on one clock: the segments add up to last_byte - intended by construction."""
    return {name: times[end] - times[start] for name, start, end in SEGMENTS}


def attribute(window_start: int, window_end: int, spans: list[dict]) -> tuple[dict[str, int], int]:
    """
    Critical-path attribution. Each instant of the window goes to the leaf span that was active then and ended
    last: the one the request was still waiting for. Instants no leaf covers are unattributed. Parent spans are
    ignored, so a parent and its children are never counted twice. The result adds up to the window exactly.
    """
    leaves = []
    for s in spans:
        if s.get("parent"):
            continue
        start, end = max(s["start_ns"], window_start), min(s["end_ns"], window_end)
        if end > start:
            leaves.append((start, end, s["name"]))
    cuts = sorted({window_start, window_end, *(t for leaf in leaves for t in leaf[:2])})
    attributed: dict[str, int] = {}
    unattributed = 0
    for a, b in zip(cuts, cuts[1:]):
        active = [leaf for leaf in leaves if leaf[0] <= a and leaf[1] >= b]
        if not active:
            unattributed += b - a
            continue
        name = max(active, key=lambda leaf: (leaf[1], leaf[0]))[2]
        attributed[name] = attributed.get(name, 0) + (b - a)
    return attributed, unattributed


def span_sums(spans: list[dict]) -> tuple[int, int]:
    """(naive sum of every span, parents included; sum of leaf spans)."""
    naive = sum(s["end_ns"] - s["start_ns"] for s in spans)
    leaves = sum(s["end_ns"] - s["start_ns"] for s in spans if not s.get("parent"))
    return naive, leaves


def durations_by_name(spans: list[dict]) -> dict[str, int]:
    """Each leaf span name's total duration in one request (check.sentence and send can occur several times)."""
    out: dict[str, int] = {}
    for s in spans:
        if not s.get("parent"):
            out[s["name"]] = out.get(s["name"], 0) + s["end_ns"] - s["start_ns"]
    return out
