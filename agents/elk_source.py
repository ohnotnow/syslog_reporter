"""ELK NDJSON source: turn dumped Elasticsearch syslog documents back into
classic rsyslog text lines.

The rest of the pipeline (LogFilterAgent, the anomaly detectors, the LLM
chunking) parses raw 'Mon DD HH:MM:SS host program[pid]: message' lines by
whitespace split, so rather than teach every stage a second data model we
render each ES document back into that shape and hand the pipeline what it
already understands.

Input is the NDJSON produced by tools/elk_dump.py: one JSON object per
line, flat dotted keys (@timestamp, host.name, host.hostname, process.name,
process.pid, message), optionally gzip-compressed (.gz suffix).
"""

import gzip
import json
from datetime import datetime
from zoneinfo import ZoneInfo


class ElkSourceAgent:
    def __init__(self, path, tz="Europe/London"):
        self.path = str(path)
        self.tz = ZoneInfo(tz)
        # Set by run(): the local-time date of the first line, so callers can
        # key the aggregate store off the data instead of assuming yesterday.
        self.log_date = None
        self.skipped = 0
        # Set by run() when the dump carries host.os.* fields (older dumps
        # don't): {short hostname: "Ubuntu 22.04"}. Callers can use it to
        # replace the program-based OS guess with the real OS.
        self.host_os = {}

    def run(self):
        lines = []
        opener = gzip.open if self.path.endswith(".gz") else open
        with opener(self.path, "rt", encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, 1):
                if not raw.strip():
                    continue
                try:
                    doc = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"{self.path}:{lineno}: not valid JSON ({exc}); "
                        "is this really an elk_dump.py NDJSON file?"
                    ) from exc
                rendered = self._render(doc)
                if rendered is None:
                    self.skipped += 1
                    continue
                if self.log_date is None:
                    self.log_date = self._local_time(doc["@timestamp"]).date()
                lines.append(rendered)
        return lines

    def _local_time(self, timestamp):
        return datetime.fromisoformat(timestamp).astimezone(self.tz)

    def _note_host_os(self, doc, host):
        if host in self.host_os:
            return
        name = doc.get("host.os.name")
        if not name:
            return
        version = str(doc.get("host.os.version", "")).split(" ")[0]
        self.host_os[host] = f"{name} {version}".strip()

    def _render(self, doc):
        timestamp = doc.get("@timestamp")
        message = doc.get("message")
        if not timestamp or not message:
            return None
        ts = self._local_time(timestamp)
        # Syslog pads a single-digit day with a space: 'Aug  6', not 'Aug 6'.
        stamp = f"{ts:%b} {ts.day:2d} {ts:%H:%M:%S}"
        host = doc.get("host.hostname") or str(doc.get("host.name", "unknown")).split(".")[0]
        self._note_host_os(doc, host)
        program = doc.get("process.name", "unknown")
        pid = doc.get("process.pid")
        tag = f"{program}[{pid}]:" if pid is not None else f"{program}:"
        message = str(message).replace("\n", " ").replace("\r", " ")
        return f"{stamp} {host} {tag} {message}"
