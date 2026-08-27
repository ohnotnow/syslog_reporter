"""Persisted daily aggregate store — the baseline that outlives the log.

The Rocky syslog host rotates `/var/log/messages` monthly, so the raw log can
never be the long-term baseline for "is this host behaving like its own normal
this fortnight?". This module persists each day's
`(date, host, program, window, count)` aggregates to a small SQLite file on the
box (no TSDB — see ant ADR syslogreporter-VYQvH), so the history-based detectors
(baseline_agent, temporal_agent) have something to compare today against.

`AnomalyDetectorAgent.aggregate()` already produces the counts; this just writes
them and reads them back. See ait task syslog-reporter-UkLWZ.2.
"""
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta

# Keep the file small on a box that runs this daily and forever. Generous
# enough for any sensible trailing-baseline window.
DEFAULT_KEEP_DAYS = 90

_SCHEMA = """
CREATE TABLE IF NOT EXISTS aggregates (
    date    TEXT    NOT NULL,   -- ISO 'YYYY-MM-DD' the log slice covers
    host    TEXT    NOT NULL,
    program TEXT    NOT NULL,
    window  TEXT    NOT NULL,   -- 'HH:MM' time-of-day bucket (see parse_line)
    count   INTEGER NOT NULL,
    PRIMARY KEY (date, host, program, window)
);
CREATE INDEX IF NOT EXISTS idx_aggregates_series ON aggregates (host, program, date);
CREATE INDEX IF NOT EXISTS idx_aggregates_window ON aggregates (host, program, window, date);
"""


def _iso(value) -> str:
    """Normalise a date | datetime | 'YYYY-MM-DD' string to an ISO date string."""
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported date value: {value!r}")


def _as_date(value) -> date:
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"unsupported date value: {value!r}")


class AggregateStore:
    """A tiny SQLite-backed store of per-(host, program, window) daily counts."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def write_aggregates(self, log_date, counts: dict) -> int:
        """Persist a day's counts. Idempotent: re-running a day overwrites it.

        `counts` is `{(host, program, window): n}` — exactly what
        `AnomalyDetectorAgent.aggregate()` returns as its first element.
        """
        iso = _iso(log_date)
        rows = [
            (iso, host, program, window, n)
            for (host, program, window), n in counts.items()
        ]
        with self.conn:
            self.conn.executemany(
                "INSERT INTO aggregates (date, host, program, window, count) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (date, host, program, window) "
                "DO UPDATE SET count = excluded.count",
                rows,
            )
        return len(rows)

    def history_pair_totals(self, before_date, lookback_days: int) -> dict:
        """Per-(host, program) day totals over [before-lookback, before-1].

        Returns `{(host, program): {iso_date: total_count}}`. `before_date` is
        excluded so a day never sits in its own baseline.
        """
        end = _iso(before_date)
        start = _iso(_as_date(before_date) - timedelta(days=lookback_days))
        cur = self.conn.execute(
            "SELECT host, program, date, SUM(count) FROM aggregates "
            "WHERE date >= ? AND date < ? "
            "GROUP BY host, program, date",
            (start, end),
        )
        result: dict = defaultdict(dict)
        for host, program, day, total in cur:
            result[(host, program)][day] = total
        return result

    def history_window_counts(self, before_date, lookback_days: int) -> dict:
        """Per-(host, program, window) day counts over [before-lookback, before-1].

        Returns `{(host, program, window): {iso_date: count}}`. This keeps the
        time-of-day window so the temporal detector can compare like-with-like
        (10:00 today vs 10:00 on prior days) and not trip over morning reboots.
        """
        end = _iso(before_date)
        start = _iso(_as_date(before_date) - timedelta(days=lookback_days))
        cur = self.conn.execute(
            "SELECT host, program, window, date, SUM(count) FROM aggregates "
            "WHERE date >= ? AND date < ? "
            "GROUP BY host, program, window, date",
            (start, end),
        )
        result: dict = defaultdict(dict)
        for host, program, window, day, total in cur:
            result[(host, program, window)][day] = total
        return result

    def prune(self, keep_days: int = DEFAULT_KEEP_DAYS) -> int:
        """Drop rows older than `keep_days` so the file stays small. Returns rows removed."""
        cutoff = _iso(date.today() - timedelta(days=keep_days))
        with self.conn:
            cur = self.conn.execute("DELETE FROM aggregates WHERE date < ?", (cutoff,))
        return cur.rowcount
