import unittest

from agents.aggregate_store import AggregateStore
from agents.temporal_agent import TemporalBurstDetectorAgent


# ~30 events in the 10:00 window every day — think a lab's morning reboot churn.
# This is exactly the "expected seasonality" the spike got swamped by.
HISTORY = [28, 32, 30, 29, 31, 27, 33, 30, 28, 32]
HISTORY_DATES = [f"2026-06-{d:02d}" for d in range(1, 1 + len(HISTORY))]
TODAY = "2026-06-13"
WINDOW = "10:00"


def _seed(store, host="lab1", program="kernel", window=WINDOW,
          values=HISTORY, dates=HISTORY_DATES):
    for day, n in zip(dates, values):
        store.write_aggregates(day, {(host, program, window): n})


def _today(host="lab1", program="kernel", window=WINDOW, n=0):
    counts = {(host, program, window): n}
    examples = {(host, program): f"Jun 13 {window}:00 {host} {program}: boot"}
    host_programs = {host: {program}}
    return counts, examples, host_programs


class TemporalDetectorTests(unittest.TestCase):
    def setUp(self):
        self.store = AggregateStore(":memory:")
        _seed(self.store)

    def tearDown(self):
        self.store.close()

    def test_flags_a_genuine_burst(self):
        counts, examples, host_programs = _today(n=2000)
        anomalies = TemporalBurstDetectorAgent(
            counts, examples, host_programs, self.store, TODAY).run()
        self.assertEqual(len(anomalies), 1)
        a = anomalies[0]
        self.assertEqual(a.window, WINDOW)
        self.assertEqual(a.count, 2000)
        self.assertGreater(a.score, 3.5)
        self.assertIn("10:00", a.headline())

    def test_routine_morning_volume_is_not_flagged(self):
        # 32 events at 10:00 is bang-on normal *for 10:00* — comparing like with
        # like is the whole point. This must NOT flag, even though 10:00 is a
        # busy time of day in absolute terms.
        counts, examples, host_programs = _today(n=32)
        anomalies = TemporalBurstDetectorAgent(
            counts, examples, host_programs, self.store, TODAY).run()
        self.assertEqual(anomalies, [])

    def test_quiet_window_below_min_count_ignored(self):
        counts, examples, host_programs = _today(n=10)  # below MIN_COUNT
        anomalies = TemporalBurstDetectorAgent(
            counts, examples, host_programs, self.store, TODAY).run()
        self.assertEqual(anomalies, [])

    def test_insufficient_history_is_not_scored(self):
        store = AggregateStore(":memory:")
        _seed(store, values=HISTORY[:3], dates=HISTORY_DATES[:3])
        counts, examples, host_programs = _today(n=2000)
        anomalies = TemporalBurstDetectorAgent(
            counts, examples, host_programs, store, TODAY, min_history_days=7).run()
        self.assertEqual(anomalies, [])
        store.close()


if __name__ == "__main__":
    unittest.main()
