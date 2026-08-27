import unittest

from agents.anomaly_agent import (
    parse_line,
    robust_z,
    guess_os_family,
    combine_anomalies,
    AnomalyDetectorAgent,
    PeerAnomaly,
)
from agents.baseline_agent import BaselineAnomaly


class ParseLineTests(unittest.TestCase):
    def test_standard_line(self):
        host, program, window, raw = parse_line(
            "Nov  8 00:10:04 james puppet-agent[1545710]: Requesting catalog"
        )
        self.assertEqual(host, "james")
        self.assertEqual(program, "puppet-agent")
        self.assertEqual(window, "00:10")
        self.assertTrue(raw.endswith("Requesting catalog"))

    def test_strips_path_and_pid(self):
        rec = parse_line("Nov  8 09:14:01 box /usr/libexec/gdm-x-session[20413]: hi")
        self.assertEqual(rec[1], "/usr/libexec/gdm-x-session")

    def test_program_without_pid(self):
        rec = parse_line("Nov  8 00:00:00 hastings kernel: [123] segfault")
        self.assertEqual(rec[1], "kernel")

    def test_window_bucketing(self):
        self.assertEqual(parse_line("Nov  8 11:37:00 h prog: x")[2], "11:30")
        self.assertEqual(parse_line("Nov  8 11:00:00 h prog: x")[2], "11:00")

    def test_rejects_malformed(self):
        self.assertIsNone(parse_line("too short"))
        self.assertIsNone(parse_line(""))


class RobustZTests(unittest.TestCase):
    def test_flags_outlier(self):
        pop = [10, 11, 9, 10, 12, 500]
        self.assertGreater(robust_z(500, pop), 10)
        self.assertLess(abs(robust_z(10, pop)), 1)

    def test_identical_population_is_zero(self):
        self.assertEqual(robust_z(5, [5, 5, 5, 5]), 0.0)

    def test_mad_zero_fallback_still_ranks(self):
        # MAD is 0 (median deviation 0) but one value spikes — must rank
        # positive, not divide by zero.
        self.assertGreater(robust_z(50, [1, 1, 1, 1, 50]), 0)


class GuessOsFamilyTests(unittest.TestCase):
    def test_rhel_signals(self):
        self.assertEqual(guess_os_family({"setroubleshoot", "kernel"}), "RHEL-family")
        self.assertEqual(guess_os_family({"dnf", "sshd"}), "RHEL-family")

    def test_debian_signals(self):
        self.assertEqual(guess_os_family({"snapd-desktop-i", "kernel"}), "Debian-family")
        self.assertEqual(guess_os_family({"apt-daily", "dpkg"}), "Debian-family")

    def test_unknown_when_no_signal(self):
        self.assertEqual(guess_os_family({"sshd", "kernel", "cron"}), "unknown")

    def test_unknown_when_ambiguous(self):
        # both families present -> don't guess
        self.assertEqual(guess_os_family({"setroubleshoot", "apt"}), "unknown")


class AnomalyDetectorTests(unittest.TestCase):
    def test_flags_noisy_host(self):
        lines = []
        for i in range(5):                      # 5 quiet peers, 20 events each
            lines += [f"Nov  8 00:0{i}:00 quiet{i} sshd[1]: ok\n"] * 20
        lines += ["Nov  8 00:00:00 loud sshd[1]: flood\n"] * 2000  # the offender

        anomalies = AnomalyDetectorAgent(lines, min_hosts=5, min_count=50).run()

        self.assertTrue(anomalies, "expected at least one anomaly")
        top = anomalies[0]
        self.assertEqual(top.host, "loud")
        self.assertEqual(top.program, "sshd")
        self.assertEqual(top.count, 2000)
        self.assertIn("flood", top.example_line)

    def test_ignores_programs_below_min_hosts(self):
        # 'niche' appears on only 2 hosts -> never peer-compared, however lopsided.
        lines = ["Nov  8 00:00:00 a niche[1]: x\n"] * 1000
        lines += ["Nov  8 00:00:00 b niche[1]: x\n"] * 5

        anomalies = AnomalyDetectorAgent(lines, min_hosts=5, min_count=50).run()

        self.assertTrue(all(a.program != "niche" for a in anomalies))


class CombineAnomaliesTests(unittest.TestCase):
    def _peer(self, host, program, score):
        return PeerAnomaly(host=host, program=program, count=int(score * 100),
                           fleet_median=10, score=score, example_line="x")

    def _baseline(self, host, program, score, direction="silent"):
        return BaselineAnomaly(host=host, program=program, count=0,
                               baseline_median=500, score=score, direction=direction,
                               days_seen=10, example_line="")

    def test_dedupes_same_host_program_keeping_strongest(self):
        peer = self._peer("boxA", "sshd", 5.0)
        # same series, stronger (negative) signal from the baseline detector
        baseline = self._baseline("boxA", "sshd", -8.0)
        combined = combine_anomalies([peer], [baseline])
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0].kind, "baseline")   # |−8| beats |5|

    def test_ranks_union_by_absolute_score(self):
        combined = combine_anomalies(
            [self._peer("a", "p", 4.0), self._peer("b", "q", 9.0)],
            [self._baseline("c", "r", -6.0)],
        )
        self.assertEqual([(a.host, a.program) for a in combined],
                         [("b", "q"), ("c", "r"), ("a", "p")])

    def test_empty_in_empty_out(self):
        self.assertEqual(combine_anomalies([], [], []), [])


if __name__ == "__main__":
    unittest.main()
