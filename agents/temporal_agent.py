"""Temporal burst detection WITH seasonality handling (ait .5).

The deliberately-hard one. The one-day spike showed that naive temporal bursts
are dominated by *expected* seasonality — labs full of machines rebooting at
~10:00 dump kernel boot logs every morning, which a within-day burst detector
flags every single day. Useless: it cries wolf.

The fix is to compare like with like. We score today's count in a given
time-of-day window (e.g. 10:00) against the SAME window on prior days, per
(host, program). A normal morning reboot sits right on its own 10:00 baseline
and never flags; only a 10:00 that is unusually loud *for a 10:00* surfaces.

Needs accumulated per-window history, so it is a no-op until the store holds at
least MIN_HISTORY_DAYS for a (host, program, window). Lower priority by design
— see ant ADR syslogreporter-VYQvH. Window granularity is set by
anomaly_agent.BUCKET_MINUTES.
"""
import statistics
from dataclasses import dataclass

from .anomaly_agent import guess_os_family, robust_z

LOOKBACK_DAYS = 14       # trailing window of same-time-of-day history
MIN_HISTORY_DAYS = 7     # days of that-window history needed before we score it
THRESHOLD = 3.5          # |modified z| to flag
MIN_COUNT = 30           # ignore quiet windows — a burst worth a glance is busy


@dataclass
class TemporalAnomaly:
    host: str
    program: str
    window: str                # 'HH:MM' time-of-day bucket that burst
    count: int                 # today's count in that window
    baseline_median: float     # this host's own median for that window historically
    score: float               # modified z vs the same window on prior days
    days_seen: int
    example_line: str
    os_family: str = "unknown"
    kind: str = "temporal"

    def headline(self) -> str:
        return f"Burst in the {self.window} window"

    def summary(self) -> str:
        return (f"{self.count:,} events in the {self.window} window today vs an "
                f"own median of {self.baseline_median:,.0f} for that time of day "
                f"(over {self.days_seen} days) — a burst beyond its usual rhythm.")


class TemporalBurstDetectorAgent:
    """Flag (host, program, window) counts unusual *for that time of day*."""

    def __init__(self, counts, examples, host_programs, store, log_date,
                 lookback_days=LOOKBACK_DAYS, min_history_days=MIN_HISTORY_DAYS,
                 threshold=THRESHOLD, min_count=MIN_COUNT):
        self.counts = counts
        self.examples = examples
        self.host_programs = host_programs
        self.store = store
        self.log_date = log_date
        self.lookback_days = lookback_days
        self.min_history_days = min_history_days
        self.threshold = threshold
        self.min_count = min_count

    def run(self) -> list[TemporalAnomaly]:
        history = self.store.history_window_counts(self.log_date, self.lookback_days)
        os_family = {h: guess_os_family(p) for h, p in self.host_programs.items()}

        anomalies = []
        for (host, program, window), today_count in self.counts.items():
            if today_count < self.min_count:
                continue
            population = list(history.get((host, program, window), {}).values())
            if len(population) < self.min_history_days:
                continue
            baseline_median = statistics.median(population)
            score = robust_z(today_count, population)
            if score < self.threshold:
                continue
            anomalies.append(TemporalAnomaly(
                host=host,
                program=program,
                window=window,
                count=today_count,
                baseline_median=baseline_median,
                score=score,
                days_seen=len(population),
                example_line=self.examples.get((host, program), ""),
                os_family=os_family.get(host, "unknown"),
            ))

        anomalies.sort(key=lambda a: a.score, reverse=True)
        return anomalies
