import unittest

from agents.aggregate_store import AggregateStore


class AggregateStoreTests(unittest.TestCase):
    def setUp(self):
        # In-memory DB; one connection per store keeps it alive for the test.
        self.store = AggregateStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_write_and_read_back_pair_totals(self):
        self.store.write_aggregates("2026-06-01", {
            ("hostA", "puppet", "00:00"): 100,
            ("hostA", "puppet", "00:10"): 50,   # same series, different window
            ("hostB", "sshd", "09:00"): 7,
        })
        # before_date excludes the day itself, so query a later day
        totals = self.store.history_pair_totals("2026-06-05", lookback_days=14)
        self.assertEqual(totals[("hostA", "puppet")], {"2026-06-01": 150})  # windows summed
        self.assertEqual(totals[("hostB", "sshd")], {"2026-06-01": 7})

    def test_rewrite_is_idempotent(self):
        counts = {("hostA", "puppet", "00:00"): 100}
        self.store.write_aggregates("2026-06-01", counts)
        self.store.write_aggregates("2026-06-01", counts)  # re-run same day
        totals = self.store.history_pair_totals("2026-06-05", lookback_days=14)
        self.assertEqual(totals[("hostA", "puppet")], {"2026-06-01": 100})  # not doubled

    def test_before_date_is_excluded_from_history(self):
        self.store.write_aggregates("2026-06-05", {("h", "p", "00:00"): 99})
        # Querying with before=2026-06-05 must not return that very day
        totals = self.store.history_pair_totals("2026-06-05", lookback_days=14)
        self.assertNotIn(("h", "p"), totals)

    def test_lookback_window_bounds(self):
        self.store.write_aggregates("2026-05-01", {("h", "p", "00:00"): 1})  # too old
        self.store.write_aggregates("2026-06-04", {("h", "p", "00:00"): 2})  # in window
        totals = self.store.history_pair_totals("2026-06-05", lookback_days=14)
        self.assertEqual(totals[("h", "p")], {"2026-06-04": 2})

    def test_window_counts_keep_the_window(self):
        self.store.write_aggregates("2026-06-01", {
            ("h", "p", "10:00"): 30,
            ("h", "p", "11:00"): 5,
        })
        wins = self.store.history_window_counts("2026-06-05", lookback_days=14)
        self.assertEqual(wins[("h", "p", "10:00")], {"2026-06-01": 30})
        self.assertEqual(wins[("h", "p", "11:00")], {"2026-06-01": 5})

    def test_prune_drops_old_rows(self):
        self.store.write_aggregates("2000-01-01", {("h", "p", "00:00"): 1})
        removed = self.store.prune(keep_days=30)
        self.assertEqual(removed, 1)
        self.assertEqual(self.store.history_pair_totals("2000-02-01", lookback_days=999), {})


if __name__ == "__main__":
    unittest.main()
