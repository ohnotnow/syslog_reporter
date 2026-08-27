import gzip
import json
import os
import tempfile
import unittest
from datetime import date

from agents.elk_source import ElkSourceAgent
from agents.anomaly_agent import parse_line


def make_doc(**overrides):
    doc = {
        "@timestamp": "2026-08-26T13:00:05.000Z",
        "host.name": "dnsbox.example.ac.uk",
        "host.hostname": "dnsbox",
        "process.name": "dhcpd",
        "process.pid": 61685,
        "message": "DHCPDISCOVER from aa:bb:cc:dd:ee:ff via eth0",
    }
    doc.update(overrides)
    return doc


class ElkSourceTests(unittest.TestCase):
    def write_ndjson(self, docs, suffix=".ndjson"):
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        self.addCleanup(os.unlink, path)
        opener = gzip.open if suffix.endswith(".gz") else open
        with opener(path, "wt", encoding="utf-8") as fh:
            for doc in docs:
                fh.write(json.dumps(doc) + "\n")
        return path

    def test_renders_classic_syslog_line(self):
        path = self.write_ndjson([make_doc()])
        lines = ElkSourceAgent(path).run()
        # 13:00 UTC on Aug 26 is 14:00 in Europe/London (BST)
        self.assertEqual(
            lines,
            ["Aug 26 14:00:05 dnsbox dhcpd[61685]: "
             "DHCPDISCOVER from aa:bb:cc:dd:ee:ff via eth0"],
        )

    def test_rendered_line_satisfies_pipeline_parser(self):
        path = self.write_ndjson([make_doc()])
        host, program, window, _raw = parse_line(ElkSourceAgent(path).run()[0])
        self.assertEqual(host, "dnsbox")
        self.assertEqual(program, "dhcpd")
        self.assertEqual(window, "14:00")

    def test_offset_timestamps_and_single_digit_day_padding(self):
        doc = make_doc(**{"@timestamp": "2026-08-06T09:15:00.000+01:00"})
        path = self.write_ndjson([doc])
        lines = ElkSourceAgent(path).run()
        self.assertTrue(lines[0].startswith("Aug  6 09:15:00 dnsbox"))

    def test_no_pid_renders_bare_program_tag(self):
        doc = make_doc()
        del doc["process.pid"]
        path = self.write_ndjson([doc])
        self.assertIn(" dhcpd: DHCPDISCOVER", ElkSourceAgent(path).run()[0])

    def test_reads_gzip(self):
        path = self.write_ndjson([make_doc()], suffix=".ndjson.gz")
        self.assertEqual(len(ElkSourceAgent(path).run()), 1)

    def test_infers_log_date_from_first_line_local_time(self):
        # 23:30 UTC on the 25th is 00:30 on the 26th in Europe/London
        doc = make_doc(**{"@timestamp": "2026-08-25T23:30:00.000Z"})
        agent = ElkSourceAgent(self.write_ndjson([doc]))
        agent.run()
        self.assertEqual(agent.log_date, date(2026, 8, 26))

    def test_skips_and_counts_docs_without_message_or_timestamp(self):
        no_message = make_doc()
        del no_message["message"]
        no_timestamp = make_doc()
        del no_timestamp["@timestamp"]
        path = self.write_ndjson([no_message, no_timestamp, make_doc()])
        agent = ElkSourceAgent(path)
        self.assertEqual(len(agent.run()), 1)
        self.assertEqual(agent.skipped, 2)

    def test_falls_back_to_short_form_of_host_name(self):
        doc = make_doc(**{"host.hostname": ""})
        path = self.write_ndjson([doc])
        self.assertIn(" dnsbox dhcpd", ElkSourceAgent(path).run()[0])

    def test_collects_host_os_map_when_dump_carries_os_fields(self):
        with_os = make_doc(**{
            "host.os.name": "Ubuntu",
            "host.os.version": "22.04.1 LTS (Jammy Jellyfish)",
            "host.os.family": "debian",
        })
        without_os = make_doc(**{"host.hostname": "oldbox"})
        agent = ElkSourceAgent(self.write_ndjson([with_os, without_os]))
        agent.run()
        self.assertEqual(agent.host_os, {"dnsbox": "Ubuntu 22.04.1"})

    def test_host_os_empty_for_pre_os_dumps(self):
        agent = ElkSourceAgent(self.write_ndjson([make_doc()]))
        agent.run()
        self.assertEqual(agent.host_os, {})

    def test_newlines_in_message_are_flattened(self):
        doc = make_doc(message="line one\nline two")
        path = self.write_ndjson([doc])
        lines = ElkSourceAgent(path).run()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith("line one line two"))

    def test_non_json_input_raises_with_line_number(self):
        fd, path = tempfile.mkstemp(suffix=".ndjson")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Aug 26 14:00:05 dnsbox dhcpd[1]: raw text, not JSON\n")
        with self.assertRaises(ValueError) as ctx:
            ElkSourceAgent(path).run()
        self.assertIn(":1:", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
