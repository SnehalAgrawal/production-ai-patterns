"""
Tests for cost.py. The provider cases are the providers' own documented examples (read 2026-11-24):

  OpenAI prompt caching guide: 12,000 input tokens, 4,000 cached, 7,000 written (3,000 with a 30-minute lifetime,
  4,000 with a 12-hour one) -> 1,000 ordinary input tokens; at $1 input, $0.10 cached, writes at 1.25x and 2.5x,
  the input costs $0.01515.
  Anthropic prompt caching guide: 100,000 tokens read from cache, 0 written, 50 after the breakpoint -> 100,050
  input tokens processed; and a usage block with cache_creation 148 (5m) + 100 (1h) = 248 written.

  python -m unittest -v test_cost
"""
import unittest

import cost


class OpenAI(unittest.TestCase):
    USAGE = {"input_tokens": 12000, "output_tokens": 0,
             "input_tokens_details": {"cached_tokens": 4000, "cache_write_tokens": 7000,
                                      "cache_write_tokens_details": {"ttl_30m_tokens": 3000, "ttl_12h_tokens": 4000}}}
    RATES = {"input": 1.0, "cache_read": 0.10, "cache_write_30m": 1.25, "cache_write_12h": 2.5, "output": 0.0}

    def test_documented_example(self):
        counts = cost.openai_counts(self.USAGE)
        self.assertEqual(counts, {"input": 1000, "cache_read": 4000, "cache_write_30m": 3000, "cache_write_12h": 4000,
                                  "output": 0})
        self.assertAlmostEqual(cost.cost_usd(counts, self.RATES), 0.01515, places=10)

    def test_writes_without_lifetimes_raise(self):
        usage = {"input_tokens": 100, "output_tokens": 1,
                 "input_tokens_details": {"cache_write_tokens": 50}}
        with self.assertRaises(ValueError):
            cost.openai_counts(usage)

    def test_no_cache_fields(self):
        self.assertEqual(cost.openai_counts({"input_tokens": 10, "output_tokens": 5})["input"], 10)


class Anthropic(unittest.TestCase):
    def test_documented_read_example(self):
        counts = cost.anthropic_counts({"input_tokens": 50, "cache_read_input_tokens": 100000,
                                        "cache_creation_input_tokens": 0, "output_tokens": 0})
        self.assertEqual(sum(v for k, v in counts.items() if k != "output"), 100050)

    def test_documented_lifetime_breakdown(self):
        usage = {"input_tokens": 2048, "cache_read_input_tokens": 1800, "cache_creation_input_tokens": 248,
                 "output_tokens": 503, "cache_creation": {"ephemeral_5m_input_tokens": 148,
                                                          "ephemeral_1h_input_tokens": 100}}
        counts = cost.anthropic_counts(usage)
        self.assertEqual((counts["cache_write_5m"], counts["cache_write_1h"]), (148, 100))
        self.assertEqual(counts["input"], 2048)  # not reduced: Anthropic's input_tokens already excludes the cache

    def test_writes_without_lifetimes_raise(self):
        with self.assertRaises(ValueError):
            cost.anthropic_counts({"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 248})


class Strictness(unittest.TestCase):
    def test_unpriced_category_raises(self):
        with self.assertRaises(KeyError):
            cost.cost_usd({"input": 10, "cache_write_1h": 5}, {"input": 1.0})

    def test_unknown_category_raises_even_at_zero(self):
        with self.assertRaises(KeyError):
            cost.cost_usd({"input": 10, "audio_input": 0}, {"input": 1.0, "audio_input": 1.0})

    def test_missing_count_is_not_zero(self):
        with self.assertRaises(ValueError):
            cost.local_counts({"prompt_tokens": None, "output_tokens": 3})
        with self.assertRaises(ValueError):
            cost.anthropic_counts({"output_tokens": 3})

    def test_unmapped_model_raises(self):
        scenario = {"roles": {"llama3.2:3b": "big"}, "models": {"big": {"input": 1.0, "output": 2.0}}}
        with self.assertRaises(KeyError):
            cost.call_cost({"model": "qwen2.5:3b", "prompt_tokens": 1, "output_tokens": 1}, scenario)
        with self.assertRaises(KeyError):
            cost.call_cost({"prompt_tokens": 1, "output_tokens": 1}, scenario)

    def test_local_call(self):
        scenario = {"roles": {"m": "big"}, "models": {"big": {"input": 2.0, "output": 10.0}}}
        self.assertAlmostEqual(cost.call_cost({"model": "m", "prompt_tokens": 1_000_000, "output_tokens": 100_000},
                                              scenario), 3.0)

    def test_unmeasured_categories_cannot_be_added(self):
        costs = cost.breakdown(1.0, 0.5)
        self.assertEqual(cost.subtotal(costs, ["inference", "other_metered"]), 1.5)
        for name in ("fixed", "evaluation_review", "downstream"):
            with self.assertRaises(ValueError):
                cost.subtotal(costs, ["inference", name])


class Decisions(unittest.TestCase):
    def test_cost_per_success(self):
        self.assertEqual(cost.cost_per_success(10.0, 4, 6), 2.5)
        self.assertEqual(cost.cost_per_success(10.0, 4, 6, per_failure=1.0), 4.0)
        self.assertIsNone(cost.cost_per_success(10.0, 0, 20))

    def test_break_even(self):
        self.assertEqual(cost.break_even(10.0, 13, 4.0, 15)["threshold_per_failure"], 3.0)
        self.assertEqual(cost.break_even(10.0, 13, 4.0, 15)["verdict"], "cheaper_but_worse")
        self.assertEqual(cost.break_even(10.0, 13, 4.0, 13)["verdict"], "dominates")
        self.assertEqual(cost.break_even(10.0, 13, 12.0, 14)["verdict"], "dominated")
        b = cost.break_even(10.0, 13, 12.0, 11)
        self.assertEqual((b["verdict"], b["threshold_per_failure"]), ("costlier_but_better", 1.0))
        self.assertEqual(cost.break_even(10.0, 13, 10.0, 13)["verdict"], "same")


if __name__ == "__main__":
    unittest.main()
