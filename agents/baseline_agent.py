"""Day-over-day per-host baseline anomaly detection (ait .4).

Where the peer detector asks "is this host unlike its fleet peers?", this asks
"is this host unlike its *own* recent normal?" — scoring today's per-(host,
program) volume against that host's trailing-N-day history from the SQLite
aggregate store. It catches the things peer comparison can't: a host that has
gone loud, gone quiet, or — the one the one-day spike could never see — **gone
silent** (a box that normally chatters and today says nothing).

Needs accumulated history, so it is a no-op until the store has at least
MIN_HISTORY_DAYS of data for a series. See ant ADR syslogreporter-VYQvH.
"""
import statistics
from dataclasses import dataclass

from .anomaly_agent import collapse_to_pairs, guess_os_family, robust_z

LOOKBACK_DAYS = 14       # trailing window to build each host's own baseline from
MIN_HISTORY_DAYS = 7     # need at least this many days of history to score a series
THRESHOLD = 3.5          # |modified z| to flag (Iglewicz & Hoaglin's outlier cut)
MIN_BASELINE = 50        # ignore tiny series — a jump from 2 to 10 is just noise
MIN_SILENT_BASELINE = 100  # only call a host "silent" if it was genuinely chatty


@dataclass
class BaselineAnomaly:
    host: str
    program: str
    count: int                 # today's total for this (host, program)
    baseline_median: float     # this host's own trailing-N-day median
    score: float               # signed modified z vs own history (-ve = quieter)
    direction: str             # "louder" | "quieter" | "silent"
    days_seen: int             # how many days of history informed the baseline
    example_line: str
    os_family: str = "unknown"
    kind: str = "baseline"

    def headline(self) -> str:
        return {
            "louder": "Louder than its own baseline",
            "quieter": "Quieter than its own baseline",
            "silent": "Gone silent",
        }[self.direction]

    def summary(self) -> str:
        if self.direction == "silent":
            return (f"No events today — this host normally emits about "
                    f"{self.baseline_median:,.0f}/day of {self.program} "
                    f"(median over {self.days_seen} days). It has gone silent.")
        verb = "up from" if self.direction == "louder" else "down from"
        return (f"{self.count:,} events today, {verb} an own "
                f"{self.days_seen}-day median of {self.baseline_median:,.0f}.")


class HostBaselineDetectorAgent:
    """Score today's per-(host, program) volume against each host's own history."""

    def __init__(self, counts, examples, host_programs, store, log_date,
                 lookback_days=LOOKBACK_DAYS, min_history_days=MIN_HISTORY_DAYS,
                 threshold=THRESHOLD, min_baseline=MIN_BASELINE,
                 min_silent_baseline=MIN_SILENT_BASELINE):
        self.counts = counts
        self.examples = examples
        self.host_programs = host_programs
        self.store = store
        self.log_date = log_date
        self.lookback_days = lookback_days
        self.min_history_days = min_history_days
        self.threshold = threshold
        self.min_baseline = min_baseline
        self.min_silent_baseline = min_silent_baseline

    def run(self) -> list[BaselineAnomaly]:
        today = collapse_to_pairs(self.counts)
        history = self.store.history_pair_totals(self.log_date, self.lookback_days)
        os_family = {h: guess_os_family(p) for h, p in self.host_programs.items()}

        anomalies = []
        # Union of series seen in history or today: a series present in history
        # but absent today is exactly the "gone silent" case.
        for key in set(history) | set(today):
            host, program = key
            population = list(history.get(key, {}).values())
            if len(population) < self.min_history_days:
                continue
            baseline_median = statistics.median(population)
            today_count = today.get(key, 0)

            if today_count == 0:
                if baseline_median >= self.min_silent_baseline:
                    anomalies.append(self._make(
                        host, program, 0, baseline_median,
                        robust_z(0, population), "silent", len(population), os_family))
                continue

            if baseline_median < self.min_baseline:
                continue
            score = robust_z(today_count, population)
            if score >= self.threshold:
                direction = "louder"
            elif score <= -self.threshold:
                direction = "quieter"
            else:
                continue
            anomalies.append(self._make(
                host, program, today_count, baseline_median,
                score, direction, len(population), os_family))

        # Rank by magnitude: a host gone silent (large -ve) matters as much as
        # one gone loud (large +ve).
        anomalies.sort(key=lambda a: abs(a.score), reverse=True)
        return anomalies

    def _make(self, host, program, count, baseline_median, score, direction,
              days_seen, os_family):
        return BaselineAnomaly(
            host=host,
            program=program,
            count=count,
            baseline_median=baseline_median,
            score=score,
            direction=direction,
            days_seen=days_seen,
            example_line=self.examples.get((host, program), ""),
            os_family=os_family.get(host, "unknown"),
        )
