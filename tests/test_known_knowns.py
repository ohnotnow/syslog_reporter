import tempfile
import unittest
from datetime import date
from pathlib import Path

from agents.known_knowns import KnownEntry, KnownKnowns
from agents.log_agent import LogFilterAgent


SLICE = date(2026, 8, 27)


def _knowns(*entries, log_date=SLICE):
    return KnownKnowns(list(entries), log_date)


class EntryValidationTests(unittest.TestCase):
    def test_entry_needs_match_or_program(self):
        with self.assertRaises(ValueError):
            KnownEntry(host="scopebox", reason="no matcher given")

    def test_bad_regex_fails_at_construction_not_per_line(self):
        with self.assertRaises(Exception):
            KnownEntry(host="scopebox", reason="broken", match="port [")


class ExpiryTests(unittest.TestCase):
    def entry(self, expires):
        return KnownEntry(host="scopebox", reason="microscope",
                          match="port 1234", expires=expires)

    def test_no_expiry_is_forever(self):
        self.assertEqual(len(_knowns(self.entry(None)).active), 1)

    def test_expiry_is_inclusive_of_the_slice_date(self):
        kk = _knowns(self.entry(SLICE))
        self.assertEqual(len(kk.active), 1)
        self.assertEqual(len(kk.expired), 0)

    def test_lapsed_entry_moves_to_expired(self):
        kk = _knowns(self.entry(date(2026, 8, 26)))
        self.assertEqual(len(kk.active), 0)
        self.assertEqual(len(kk.expired), 1)

    def test_expiry_judged_against_slice_date_not_today(self):
        # A backfill of an old slice should see the entry as it was then.
        kk = _knowns(self.entry(date(2026, 1, 1)), log_date=date(2025, 12, 25))
        self.assertEqual(len(kk.active), 1)


class MatchingTests(unittest.TestCase):
    def test_line_ignored_scopes_to_the_host(self):
        kk = _knowns(KnownEntry(host="scopebox", reason="microscope",
                                match="port 1234"))
        self.assertTrue(kk.line_ignored("scopebox", "widgetd[9]: retry on port 1234"))
        self.assertFalse(kk.line_ignored("otherbox", "widgetd[9]: retry on port 1234"))

    def test_host_is_an_fnmatch_pattern(self):
        kk = _knowns(KnownEntry(host="lab*", reason="lab kit", match="usb reset"))
        self.assertTrue(kk.line_ignored("lab042", "kernel: usb reset"))
        self.assertFalse(kk.line_ignored("office1", "kernel: usb reset"))

    def test_star_host_matches_everywhere(self):
        kk = _knowns(KnownEntry(host="*", reason="fleet-wide", match="widget spam"))
        self.assertTrue(kk.line_ignored("anybox", "widgetd: widget spam"))

    def test_anomaly_muted_uses_program_not_match(self):
        kk = _knowns(KnownEntry(host="mcastbox", reason="igmp eye-roll",
                                program="kernel"))
        self.assertTrue(kk.anomaly_muted("mcastbox", "kernel"))
        self.assertFalse(kk.anomaly_muted("mcastbox", "postfix/smtpd"))
        self.assertFalse(kk.anomaly_muted("otherbox", "kernel"))

    def test_match_only_entry_never_mutes_anomalies(self):
        kk = _knowns(KnownEntry(host="scopebox", reason="microscope",
                                match="port 1234"))
        self.assertFalse(kk.anomaly_muted("scopebox", "kernel"))

    def test_hits_are_counted_per_entry(self):
        entry = KnownEntry(host="scopebox", reason="microscope", match="port 1234")
        kk = _knowns(entry)
        kk.line_ignored("scopebox", "retry on port 1234")
        kk.line_ignored("scopebox", "retry on port 1234")
        kk.line_ignored("otherbox", "retry on port 1234")  # no match, no hit
        self.assertEqual(entry.hits, 2)
        self.assertEqual(kk.hit_entries(), [entry])


class FromFileTests(unittest.TestCase):
    DOC = b"""
[[known]]
host = "scopebox"
match = "port 1234"
reason = "microscope attached for the optics experiment"
added = 2026-08-27
expires = 2030-09-01

[[known]]
host = "*"
program = "kernel"
reason = "fleet-wide igmp eye-roll"
"""

    def load(self, doc, log_date=SLICE):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "known_knowns.toml"
            path.write_bytes(doc)
            return KnownKnowns.from_file(path, log_date)

    def test_parses_entries_and_toml_dates(self):
        kk = self.load(self.DOC)
        self.assertEqual(len(kk.active), 2)
        self.assertEqual(kk.active[0].expires, date(2030, 9, 1))

    def test_entries_lapse_by_slice_date(self):
        kk = self.load(self.DOC, log_date=date(2030, 9, 2))
        self.assertEqual(len(kk.active), 1)
        self.assertEqual(len(kk.expired), 1)

    def test_missing_file_means_no_entries(self):
        kk = KnownKnowns.from_file(Path("does-not-exist.toml"), SLICE)
        self.assertEqual(kk.active, [])
        self.assertEqual(kk.expired, [])

    def test_entry_without_reason_is_rejected(self):
        with self.assertRaises(ValueError):
            self.load(b'[[known]]\nhost = "scopebox"\nmatch = "port 1234"\n')


class LogFilterIntegrationTests(unittest.TestCase):
    LINES = [
        "Aug 26 14:00:05 scopebox widgetd[12]: retry on port 1234",
        "Aug 26 14:00:06 otherbox widgetd[12]: retry on port 1234",
    ]

    def test_known_lines_dropped_host_aware(self):
        kk = _knowns(KnownEntry(host="scopebox", reason="microscope",
                                match="port 1234"))
        result = LogFilterAgent(self.LINES, knowns=kk).run()
        self.assertEqual(result, [self.LINES[1]])

    def test_no_knowns_changes_nothing(self):
        self.assertEqual(LogFilterAgent(self.LINES).run(), self.LINES)


if __name__ == "__main__":
    unittest.main()
