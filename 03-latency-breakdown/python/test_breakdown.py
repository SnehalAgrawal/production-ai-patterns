"""
The breakdown arithmetic on timelines with known answers.

  python -m unittest test_breakdown.py
"""
import unittest

from breakdown import attribute, nearest_rank, segments, span_sums


def span(name, start, end, parent=False):
    return {"name": name, "start_ns": start, "end_ns": end, "parent": parent}


class Attribution(unittest.TestCase):
    def test_sequential_spans_get_their_durations(self):
        spans = [span("a", 0, 10), span("b", 10, 30), span("c", 30, 60)]
        self.assertEqual(attribute(0, 60, spans), ({"a": 10, "b": 20, "c": 30}, 0))

    def test_parallel_spans_the_longer_one_gets_the_overlap(self):
        # retrieval 0-30 and tool 0-60 in parallel, then the answer 60-100
        spans = [span("retrieval", 0, 30), span("tool", 0, 60), span("answer", 60, 100)]
        attributed, unattributed = attribute(0, 100, spans)
        self.assertEqual(attributed, {"tool": 60, "answer": 40})
        self.assertEqual(unattributed, 0)
        naive, leaves = span_sums(spans)
        self.assertEqual(leaves, 130)  # more than the 100 ns window: durations of parallel spans don't add up

    def test_parent_spans_are_not_counted_twice(self):
        spans = [span("lookups", 0, 60, parent=True), span("retrieval", 0, 30), span("tool", 30, 60)]
        self.assertEqual(attribute(0, 60, spans), ({"retrieval": 30, "tool": 30}, 0))
        naive, leaves = span_sums(spans)
        self.assertEqual((naive, leaves), (120, 60))

    def test_gaps_are_unattributed(self):
        spans = [span("a", 0, 10), span("b", 30, 40)]
        self.assertEqual(attribute(0, 50, spans), ({"a": 10, "b": 10}, 30))

    def test_spans_are_clipped_to_the_window(self):
        spans = [span("a", -5, 10), span("b", 10, 70)]
        self.assertEqual(attribute(0, 50, spans), ({"a": 10, "b": 40}, 0))

    def test_attribution_always_adds_up_to_the_window(self):
        spans = [span("a", 3, 17), span("b", 5, 9), span("c", 12, 40), span("d", 41, 44)]
        attributed, unattributed = attribute(0, 50, spans)
        self.assertEqual(sum(attributed.values()) + unattributed, 50)


class Percentiles(unittest.TestCase):
    def test_nearest_rank(self):
        values = list(range(1, 101))  # 1..100
        self.assertEqual(nearest_rank(values, 50), 50)
        self.assertEqual(nearest_rank(values, 95), 95)
        self.assertEqual(nearest_rank(values, 99), 99)
        self.assertEqual(nearest_rank(values, 100), 100)

    def test_p99_of_200_is_the_198th_value(self):
        values = list(range(1, 201))
        self.assertEqual(nearest_rank(values, 99), 198)

    def test_the_draft_articles_illustration(self):
        # 90 requests at 2 s, 8 at 6 s, 2 at 30 s
        values = [2] * 90 + [6] * 8 + [30] * 2
        self.assertEqual((nearest_rank(values, 50), nearest_rank(values, 95), nearest_rank(values, 99)), (2, 6, 30))
        self.assertAlmostEqual(sum(values) / len(values), 2.88)


class Segments(unittest.TestCase):
    def test_segments_add_up_to_end_to_end(self):
        t = {"intended_ns": 0, "started_ns": 1, "connected_ns": 3, "accepted_ns": 50, "dequeued_ns": 90,
             "last_write_ns": 900, "last_byte_ns": 902}
        parts = segments(t)
        self.assertEqual(sum(parts.values()), 902)
        self.assertEqual(parts["kernel_accept_queue"], 47)
        self.assertEqual(parts["app_worker_queue"], 40)


if __name__ == "__main__":
    unittest.main()
