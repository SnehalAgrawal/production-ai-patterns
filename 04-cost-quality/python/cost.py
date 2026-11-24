"""
Cost accounting: usage records into priced token categories, the categories of operating cost kept apart, and
the break-even between two configurations.

Three rules run through it:
  - A token category without a rate is an error, never a cost of zero. So is a category this module doesn't know
    (a typo, or a new kind of token a provider starts reporting).
  - A count that wasn't reported is an error, never 0. "Not reported" and "zero tokens" are different facts.
  - A cost category that wasn't measured stays None. Adding it to a total is an error.

Provider usage fields (both documented, and different):
  OpenAI Responses API   input_tokens INCLUDES cache reads and cache writes, broken out in input_tokens_details
                         (cached_tokens, cache_write_tokens, and cache_write_tokens_details by lifetime)
  Anthropic Messages API input_tokens counts only "tokens after the last cache breakpoint"; cache reads
                         (cache_read_input_tokens) and writes (cache_creation_input_tokens, broken down by lifetime
                         in cache_creation) are separate and must be added
Both count reasoning (thinking) tokens in output_tokens.
"""

CATEGORIES = ("input", "cache_read", "cache_write_5m", "cache_write_1h", "cache_write_30m", "cache_write_12h", "output")


def _count(record: dict, field: str) -> int:
    value = record.get(field)
    if value is None:
        raise ValueError(f"{field} was not reported")  # don't turn "not reported" into 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} is {value!r}, not a token count")
    return value


def openai_counts(usage: dict) -> dict[str, int]:
    """OpenAI Responses API usage (a plain dict) -> tokens per priced category."""
    details = usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens") or 0
    written = details.get("cache_write_tokens") or 0
    by_ttl = details.get("cache_write_tokens_details") or {}
    w30, w12 = by_ttl.get("ttl_30m_tokens") or 0, by_ttl.get("ttl_12h_tokens") or 0
    if w30 + w12 != written:
        raise ValueError("cache writes are not broken down by lifetime")  # don't guess which rate applies
    ordinary = _count(usage, "input_tokens") - cached - written
    if ordinary < 0:
        raise ValueError("cache reads and writes exceed input_tokens")
    return {"input": ordinary, "cache_read": cached, "cache_write_30m": w30, "cache_write_12h": w12,
            "output": _count(usage, "output_tokens")}  # output includes reasoning tokens


def anthropic_counts(usage: dict) -> dict[str, int]:
    """Anthropic Messages API usage (a plain dict) -> tokens per priced category."""
    written = usage.get("cache_creation_input_tokens") or 0
    by_ttl = usage.get("cache_creation") or {}
    w5m, w1h = by_ttl.get("ephemeral_5m_input_tokens") or 0, by_ttl.get("ephemeral_1h_input_tokens") or 0
    if w5m + w1h != written:
        raise ValueError("cache writes are not broken down by lifetime")
    return {"input": _count(usage, "input_tokens"), "cache_read": usage.get("cache_read_input_tokens") or 0,
            "cache_write_5m": w5m, "cache_write_1h": w1h,
            "output": _count(usage, "output_tokens")}  # output includes thinking tokens


def local_counts(call: dict) -> dict[str, int]:
    """One recorded Ollama call (01's llm.chat record) -> tokens per category. Ollama has no cache pricing."""
    return {"input": _count(call, "prompt_tokens"), "output": _count(call, "output_tokens")}


def cost_usd(counts: dict[str, int], rates: dict[str, float]) -> float:
    """Tokens per category times USD per million tokens. Unknown or unpriced categories raise."""
    unknown = [k for k in counts if k not in CATEGORIES]
    if unknown:
        raise KeyError(f"unknown token categories {unknown}")
    missing = [k for k, n in counts.items() if n and k not in rates]
    if missing:
        raise KeyError(f"no rate for {missing}")  # never price an unknown category at zero
    return sum(n * rates[k] for k, n in counts.items() if n) / 1_000_000


# ------------------------------------------------------------------------------------------- hypothetical pricing


def rates_for(scenario: dict, local_model: str) -> tuple[str, dict]:
    """(hosted model, its rates) standing in for a local model in a price scenario."""
    hosted = scenario["roles"].get(local_model)
    if hosted is None:
        raise KeyError(f"no hosted model stands in for {local_model!r} in this scenario")
    return hosted, scenario["models"][hosted]


def call_cost(call: dict, scenario: dict) -> float:
    """What one local call's token counts would cost at the stand-in hosted model's rates (hypothetical)."""
    if "model" not in call:
        raise KeyError("the call doesn't record which model made it")
    _, rates = rates_for(scenario, call["model"])
    return cost_usd(local_counts(call), rates)


def embedding_cost(tokens: int, embedding: dict) -> float:
    return cost_usd({"input": tokens}, {"input": embedding["input"]})


# ------------------------------------------------------------------------------------------- operating cost


NOT_MEASURED = None


def breakdown(inference: float, other_metered: float) -> dict:
    """
    The five categories of operating cost, kept apart. This experiment measures token counts for the first two
    (priced hypothetically); the other three are not measured here and stay None.
    """
    return {
        "inference": {"usd": inference, "kind": "hypothetical: local token counts x published rates"},
        "other_metered": {"usd": other_metered,
                          "kind": "hypothetical: query-embedding tokens (approximate count) x a published rate; "
                                  "this pipeline has no reranker or other paid API"},
        "fixed": {"usd": NOT_MEASURED, "kind": "not measured: hosting, vector storage, workers, observability"},
        "evaluation_review": {"usd": NOT_MEASURED,
                              "kind": "not measured: labelling and human verification of the replies"},
        "downstream": {"usd": NOT_MEASURED,
                       "kind": "a parameter, not a measurement: cost of handling a failed email, see break_even()"},
    }


def subtotal(costs: dict, names: list[str]) -> float:
    unmeasured = [n for n in names if costs[n]["usd"] is None]
    if unmeasured:
        raise ValueError(f"{unmeasured} were not measured and can't be added")
    return sum(costs[n]["usd"] for n in names)


def cost_per_success(spend: float, successes: int, failures: int, per_failure: float = 0.0) -> float | None:
    """(spend + handling every failure) / successes. None when nothing succeeded: the cost is unbounded."""
    if successes == 0:
        return None
    return (spend + failures * per_failure) / successes


def break_even(base_spend: float, base_failures: int, spend: float, failures: int) -> dict:
    """
    Compare a candidate configuration with the baseline on the same tasks.

    The candidate's total is spend + failures x E, where E is what handling one failed task costs downstream
    (a person's time, a follow-up, an escalation). Returns which side wins for which E:
      'dominates'   cheaper and no more failures: better at every E >= 0
      'dominated'   no cheaper and no fewer failures: worse or equal at every E >= 0
      'cheaper_but_worse'  cheaper with more failures: better only while E < threshold
      'costlier_but_better'  costlier with fewer failures: better only while E > threshold
    """
    saved, extra = base_spend - spend, failures - base_failures
    if saved >= 0 and extra <= 0:
        verdict, threshold = ("dominates" if (saved > 0 or extra < 0) else "same"), None
    elif saved <= 0 and extra >= 0:
        verdict, threshold = "dominated", None
    elif saved > 0:  # and extra > 0
        verdict, threshold = "cheaper_but_worse", saved / extra
    else:  # saved < 0 and extra < 0
        verdict, threshold = "costlier_but_better", -saved / -extra
    return {"saved": saved, "extra_failures": extra, "verdict": verdict, "threshold_per_failure": threshold}
