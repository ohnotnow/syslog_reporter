import unittest

from agents.aggregate_store import AggregateStore
from agents.baseline_agent import HostBaselineDetectorAgent


# A fortnight of slightly-jittery history around ~500/day. Real series always
# jitter, which is what gives MAD something to work with (a perfectly flat
# history has MAD 0 and robust_z reports "nothing to see").
HISTORY = [500, 510, 490, 505, 495, 515, 485, 520, 480, 502]
HISTORY_DATES = [f"2026-06-{d:02d}" for d in range(1, 1 + len(HISTORY))]
TODAY = "2026-06-13"


def _seed(store, host="boxA", program="puppet", values=HISTORY, dates=HISTORY_DATES):
    for day, n in zip(dates, values):
        store.write_aggregates(day, {(host, program, "00:00"): n})


def _today(host="boxA", program="puppet", n=None):
    """Build the (counts, examples, host_programs) triple for a single series today."""
    counts = {} if n is None else {(host, program, "00:00"): n}
    examples = {(host, program): f"Jun 13 00:00:00 {host} {program}[1]: today"}
    host_programs = {host: {program}}
    return counts, examples, host_programs


class BaselineDetectorTests(unittest.TestCase):
    def setUp(self):
        self.store = AggregateStore(":memory:")
        _seed(self.store)

    def tearDown(self):
        self.store.close()

    def test_flags_a_host_gone_loud(self):
        counts, examples, host_programs = _today(n=6000)
        anomalies = HostBaselineDetectorAgent(
            counts, examples, host_programs, self.store, TODAY).run()
        self.assertEqual(len(anomalies), 1)
        a = anomalies[0]
        self.assertEqual(a.direction, "louder")
        self.assertEqual(a.count, 6000)
        self.assertGreater(a.score, 3.5)
        self.assertEqual(a.days_seen, len(HISTORY))
        self.assertIn("Louder", a.headline())

    def test_flags_a_host_gone_silent(self):
        # No data for boxA today at all -> it has gone silent vs its own normal.
        counts, examples, host_programs = _today(n=None)
        anomalies = HostBaselineDetectorAgent(
            counts, examples, host_programs, self.store, TODAY).run()
        self.assertEqual(len(anomalies), 1)
        a = anomalies[0]
        self.assertEqual(a.direction, "silent")
        self.assertEqual(a.count, 0)
        self.assertEqual(a.headline(), "Gone silent")
        self.assertIn("gone silent", a.summary().lower())

    def test_flags_a_host_gone_quiet(self):
        counts, examples, host_programs = _today(n=40)
        anomalies = HostBaselineDetectorAgent(
            counts, examples, host_programs, self.store, TODAY).run()
        self.assertEqual([a.direction for a in anomalies], ["quieter"])
        self.assertLess(anomalies[0].score, -3.5)

    def test_stable_host_is_not_flagged(self):
        counts, examples, host_programs = _today(n=503)  # bang on its normal
        anomalies = HostBaselineDetectorAgent(
            counts, examples, host_programs, self.store, TODAY).run()
        self.assertEqual(anomalies, [])

    def test_insufficient_history_is_not_scored(self):
        store = AggregateStore(":memory:")
        _seed(store, values=HISTORY[:3], dates=HISTORY_DATES[:3])  # only 3 days
        counts, examples, host_programs = _today(n=6000)
        anomalies = HostBaselineDetectorAgent(
            counts, examples, host_programs, store, TODAY, min_history_days=7).run()
        self.assertEqual(anomalies, [])
        store.close()

    def test_tiny_series_below_min_baseline_ignored(self):
        store = AggregateStore(":memory:")
        _seed(store, values=[2, 3, 1, 2, 4, 2, 3, 1, 2, 3])  # trivial volume
        counts, examples, host_programs = _today(n=40)       # "spike" but still tiny
        anomalies = HostBaselineDetectorAgent(
            counts, examples, host_programs, store, TODAY).run()
        self.assertEqual(anomalies, [])
        store.close()


if __name__ == "__main__":
    unittest.main()
