import unittest
from unittest.mock import patch

from agents.log_agent import LogFilterAgent


class BlanketIgnoreTests(unittest.TestCase):
    LINE = "Aug 26 14:00:05 labbox widgetd[12]: probe from 203.0.113.9"

    def test_env_entries_drop_matching_lines(self):
        with patch.dict("os.environ", {"SYSLOG_BLANKET_IGNORE": "203.0.113.9, oldprinter"}):
            self.assertEqual(LogFilterAgent([self.LINE]).run(), [])

    def test_unset_env_keeps_the_line(self):
        with patch.dict("os.environ", {"SYSLOG_BLANKET_IGNORE": ""}):
            self.assertEqual(LogFilterAgent([self.LINE]).run(), [self.LINE])

    def test_whitespace_and_empty_entries_are_ignored(self):
        with patch.dict("os.environ", {"SYSLOG_BLANKET_IGNORE": " , ,oldprinter , "}):
            agent = LogFilterAgent([])
            self.assertEqual(agent.blanket_ignores, ["oldprinter"])


class DedupeTests(unittest.TestCase):
    def test_pid_differences_do_not_defeat_the_dedupe_cap(self):
        lines = [
            f"Aug 26 0{i}:17:01 cronbox CRON[{1000 + i}]: (munin) CMD (/usr/bin/munin-cron)"
            for i in range(6)
        ]
        # a pid-varying line dedupes to the 3-copy cap like an identical one
        self.assertEqual(len(LogFilterAgent([]).remove_duplicates(lines)), 3)


class ElkEraFilterTests(unittest.TestCase):
    def filter(self, line):
        return LogFilterAgent([line]).run()

    def test_named_refused_scanner_chatter_is_dropped(self):
        for message in (
            "client @0x7f6d 167.248.133.11#31871 (1.2.3.4.in-addr.arpa): "
            "query (cache) '1.2.3.4.in-addr.arpa/MX/IN' denied",
            "client @0x7f6d 167.248.133.11#31871 (1.2.3.4.in-addr.arpa): "
            "query failed (REFUSED) for 1.2.3.4.in-addr.arpa/IN/MX at query.c:7148",
            "client @0x7f6d 1.2.3.4#5 (4.4.8.in-addr.arpa): "
            "rate limit slip REFUSED error response to 1.2.3.4/24",
        ):
            line = f"Aug 26 14:00:05 dnsbox named[32325]: {message}"
            self.assertEqual(self.filter(line), [], message)

    def test_named_servfail_is_normalised_not_dropped(self):
        line = ("Aug 26 14:00:05 dnsbox named[32325]: client @0x7f6d 10.0.0.1#31871 "
                "(x.example.com): query failed (SERVFAIL) for x.example.com/IN/A at query.c:7100")
        self.assertEqual(
            self.filter(line),
            ["Aug 26 14:00:05 dnsbox named SERVFAIL query failure"],
        )

    def test_cron_job_announcements_are_dropped(self):
        for line in (
            "Aug 26 06:25:01 dhcpbox CRON[288]: (root) CMD (/var/dhcp/check.update.needed >/dev/null 2>&1)",
            "Aug 26 06:25:01 dnsbox CROND[288]: (root) CMD (run-parts /etc/cron.hourly)",
            "Aug 26 06:25:01 gatebox crontab[132]: (root) LIST (root)",
            "Aug 26 06:25:01 scanbox CRON[301]: (CRON) info (No MTA installed, discarding output)",
        ):
            self.assertEqual(self.filter(line), [], line)

    def test_error_shaped_lines_still_survive(self):
        for line in (
            "Aug 26 14:00:05 labbox dhcpcd[884]: dhcpcd is not running",
            "Aug 26 14:00:05 dnsbox named[32325]: zone example.ac.uk/IN: "
            "refresh: could not refresh zone",
        ):
            self.assertEqual(self.filter(line), [line], line)


if __name__ == "__main__":
    unittest.main()
