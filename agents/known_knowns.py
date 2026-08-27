"""Operator-maintained 'known knowns': estate oddities the team has already
eye-rolled at ("that host always complains about TCP port 1234, it's the
microscope") and no longer wants in every report.

Entries live in a TOML file (stdlib tomllib, no new dependency) that is
gitignored by default: the content is inherently estate-identifying, so it
belongs beside the .env and the aggregate db, not in a public repo.

    [[known]]
    host = "blah"              # fnmatch pattern: "blah", "lab*", or "*"
    match = "port 1234"        # optional: regex, applied after the hostname
    program = "kernel"         # optional: fnmatch, mutes (host, program) anomalies
    reason = "microscope attached for the optics experiment"
    added = 2026-08-27
    expires = 2030-09-01       # optional: entry lapses after this slice date

Each entry needs a reason and at least one of match / program. `match` feeds
the line filter (the LLM issue path); `program` mutes the anomaly detectors,
which read the raw stream and so cannot be silenced by line filtering alone.
Expiry is judged against the date of the log slice being processed, not the
wall clock, so historical backfills behave historically. A lapsed entry simply
stops matching: the noise it covered reappears in the next digest, which is
the nudge to extend it or investigate.
"""

import fnmatch
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class KnownEntry:
    host: str
    reason: str
    match: str | None = None
    program: str | None = None
    added: date | None = None
    expires: date | None = None
    hits: int = 0
    match_re: re.Pattern | None = field(init=False, default=None, repr=False)

    def __post_init__(self):
        if not self.match and not self.program:
            raise ValueError(
                f"known-known entry for host '{self.host}' ({self.reason!r}) "
                "needs at least one of 'match' or 'program'"
            )
        # Compile eagerly so a bad regex fails loudly at startup, not
        # silently on every line.
        if self.match:
            self.match_re = re.compile(self.match)

    def is_active(self, log_date: date) -> bool:
        return self.expires is None or log_date <= self.expires

    def matches_host(self, host: str) -> bool:
        return fnmatch.fnmatchcase(host, self.host)


class KnownKnowns:
    def __init__(self, entries: list[KnownEntry] | None = None,
                 log_date: date | None = None):
        entries = entries or []
        log_date = log_date or date.today()
        self.active = [e for e in entries if e.is_active(log_date)]
        self.expired = [e for e in entries if not e.is_active(log_date)]

    @classmethod
    def from_file(cls, path: str | Path, log_date: date | None = None) -> "KnownKnowns":
        path = Path(path)
        if not path.exists():
            return cls([], log_date)
        with open(path, "rb") as f:
            data = tomllib.load(f)
        entries = []
        for raw in data.get("known", []):
            if "host" not in raw or "reason" not in raw:
                raise ValueError(
                    f"known-known entry {raw!r} in {path} needs both "
                    "'host' and 'reason'"
                )
            entries.append(KnownEntry(
                host=raw["host"],
                reason=raw["reason"],
                match=raw.get("match"),
                program=raw.get("program"),
                added=raw.get("added"),
                expires=raw.get("expires"),
            ))
        return cls(entries, log_date)

    def line_ignored(self, host: str, message: str) -> bool:
        """True if a line from `host` (message = everything after the
        hostname, i.e. program + text) matches an active entry."""
        for e in self.active:
            if e.match_re and e.matches_host(host) and e.match_re.search(message):
                e.hits += 1
                return True
        return False

    def anomaly_muted(self, host: str, program: str) -> bool:
        for e in self.active:
            if e.program and e.matches_host(host) \
                    and fnmatch.fnmatchcase(program, e.program):
                e.hits += 1
                return True
        return False

    def hit_entries(self) -> list[KnownEntry]:
        return [e for e in self.active if e.hits]
