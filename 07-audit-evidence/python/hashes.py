"""E10: why the audit record uses keyed digests, not plain hashes, for low-entropy values.

A loan ID here is "L-" plus 6 digits: 1,000,000 possible values. A plain SHA-256 of one can be
reversed by hashing every possible value. An HMAC can be matched the same way, but only by
someone who holds the key, so deleting the key ends that.
"""

import hashlib
import hmac
import secrets
import time


def candidates():
    for i in range(1_000_000):
        yield f"L-{i:06d}".encode()


def enumerate_plain(target_hex: str) -> tuple[int | None, float]:
    start = time.perf_counter()
    for attempts, c in enumerate(candidates(), 1):
        if hashlib.sha256(c).hexdigest() == target_hex:
            return attempts, time.perf_counter() - start
    return None, time.perf_counter() - start


def enumerate_keyed(target_hex: str, key: bytes, stop_at_first: bool = True) -> tuple[int, int | None, float]:
    """(matches, attempts at first match, seconds)."""
    start = time.perf_counter()
    matches, first = 0, None
    for attempts, c in enumerate(candidates(), 1):
        if hmac.new(key, c, hashlib.sha256).hexdigest() == target_hex:
            matches += 1
            first = first or attempts
            if stop_at_first:
                break
    return matches, first, time.perf_counter() - start


def experiment(loan_id: str, key: bytes) -> dict:
    plain_target = hashlib.sha256(loan_id.encode()).hexdigest()
    keyed_target = hmac.new(key, loan_id.encode(), hashlib.sha256).hexdigest()
    plain_attempts, plain_s = enumerate_plain(plain_target)
    with_key = enumerate_keyed(keyed_target, key)
    wrong_key = enumerate_keyed(keyed_target, secrets.token_bytes(32), stop_at_first=False)
    return {"space": 1_000_000,
            "plain": {"recovered": plain_attempts is not None, "attempts": plain_attempts, "seconds": plain_s},
            "keyed_with_key": {"recovered": with_key[0] > 0, "attempts": with_key[1], "seconds": with_key[2]},
            "keyed_other_key": {"matches": wrong_key[0], "seconds": wrong_key[2]}}
