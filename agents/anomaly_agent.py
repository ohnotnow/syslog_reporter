"""Anomaly detection over RAW syslog — peer comparison (v1).

Runs UPSTREAM of the denylist (agents/log_filters.py) so it can see the
high-volume programs the filter deletes (dhcpd, puppet, kernel, systemd).
v1 is deliberately stdlib-only: parse the program field, count per
(host, program, window), and flag hosts doing far more of a program than
their fleet peers via a robust (median/MAD) z-score.

The "compare against peers, not against global rarity" choice is the
alert-fatigue guard — a .ac.uk estate is full of one-off weirdness that is
perfectly normal. See ant ADR syslogreporter-VYQvH and ait epic
syslog-reporter-UkLWZ.
"""
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass

_PID_RE = re.compile(r"\[\d+\]$")

# Conservative defaults — we rank here; the report (later) caps length.
DEFAULT_MIN_HOSTS = 5   # only peer-compare programs seen on >= this many hosts
DEFAULT_MIN_COUNT = 50  # ignore a (host, program) quieter than this
BUCKET_MINUTES = 10     # time-window granularity for the aggregate store

# Program-name fingerprints for a rough OS-family guess. Deliberately small and
# high-confidence; ambiguous hosts fall back to "unknown" and the LLM explainer
# infers from the example log line instead.
_RHEL_HINTS = ("dnf", "yum", "rpm", "setroubleshoot", "subscription-manager", "firewalld")
_DEBIAN_HINTS = ("apt", "dpkg", "snapd", "unattended-upgrades", "ufw")


@dataclass
class PeerAnomaly:
    host: str
    program: str
    count: int
    fleet_median: float
    score: float            # robust z-score vs the fleet
    example_line: str
    os_family: str = "unknown"
    kind: str = "peer"

    # The common interface shared by every anomaly type (peer / baseline /
    # temporal) so the explainer and report can treat them uniformly. headline()
    # is the short label; summary() is the deterministic numbers sentence fed to
    # the LLM and shown in the report. See combine_anomalies().
    def headline(self) -> str:
        return "Louder than its peers"

    def summary(self) -> str:
        return (f"{self.count:,} events vs a fleet median of "
                f"{self.fleet_median:g} across peer hosts.")


def parse_line(line):
    """Return (host, program, window, raw) from a standard syslog line, else None.

    Standard shape: 'Mon DD HH:MM:SS host program[pid]: message'. The
    whitespace split mirrors LogFilterAgent in log_agent.py.
    """
    parts = line.split(None, 4)
    if len(parts) < 5:
        return None
    _mon, _day, tstamp, host, rest = parts
    if len(tstamp) < 5 or tstamp[2] != ":":
        return None
    program = rest.split(None, 1)[0]      # 'puppet-agent[1545710]:'
    program = program.split("[", 1)[0]    # drop '[pid]...' and any path's '[...]'
    program = _PID_RE.sub("", program).rstrip(":")
    if not program:
        return None
    minute = int(tstamp[3:5])
    window = f"{tstamp[:2]}:{(minute // BUCKET_MINUTES) * BUCKET_MINUTES:02d}"
    return host, program, window, line.rstrip("\n")


def robust_z(value, population):
    """Modified z-score (median + MAD).

    Falls back from MAD to mean-absolute-deviation when MAD is 0 (common with
    integer counts), so a lone spike against an otherwise-identical baseline
    still ranks instead of dividing by zero.
    """
    median = statistics.median(population)
    deviations = [abs(v - median) for v in population]
    mad = statistics.median(deviations)
    if mad > 0:
        return 0.6745 * (value - median) / mad
    mean_ad = sum(deviations) / len(deviations)
    if mean_ad > 0:
        return (value - median) / (1.253 * mean_ad)
    return 0.0  # every host identical — nothing to see


def collapse_to_pairs(counts):
    """Collapse window-keyed counts to per-(host, program) day totals.

    counts: {(host, program, window): n} -> {(host, program): total}
    Shared by the peer detector and the day-over-day baseline detector.
    """
    pairs = defaultdict(int)
    for (host, program, _window), n in counts.items():
        pairs[(host, program)] += n
    return pairs


def combine_anomalies(*lists):
    """Merge anomalies from several detectors into one ranked list.

    Each detector (peer / baseline / temporal) can flag the same (host, program)
    — alert fatigue is the enemy, so we collapse to one entry per (host, program),
    keeping the strongest signal. Scores are all modified z-scores (median/MAD),
    so their magnitudes are comparable across detectors and we can rank the union
    by |score|. (A richer "show every reason" merge is possible later; v1 keeps
    the single strongest reason — see ant ADR syslogreporter-VYQvH.)
    """
    merged = {}
    for lst in lists:
        for a in lst:
            key = (a.host, a.program)
            if key not in merged or abs(a.score) > abs(merged[key].score):
                merged[key] = a
    return sorted(merged.values(), key=lambda a: abs(a.score), reverse=True)


def guess_os_family(programs):
    """Rough RHEL-family / Debian-family / unknown guess from a host's programs."""
    progs = {p.lower() for p in programs}
    rhel = any(any(h in p for h in _RHEL_HINTS) for p in progs)
    debian = any(any(h in p for h in _DEBIAN_HINTS) for p in progs)
    if rhel and not debian:
        return "RHEL-family"
    if debian and not rhel:
        return "Debian-family"
    return "unknown"


class AnomalyDetectorAgent:
    """Peer-comparison anomaly detector (v1). Operates on RAW syslog lines."""

    def __init__(self, lines, min_hosts=DEFAULT_MIN_HOSTS, min_count=DEFAULT_MIN_COUNT):
        self.lines = lines
        self.min_hosts = min_hosts
        self.min_count = min_count
        self._aggregate = None

    def aggregate(self):
        """RAW lines -> (counts, examples, host_programs). Cached after first call.

        counts:        {(host, program, window): n}
        examples:      {(host, program): first_seen_raw_line}
        host_programs: {host: {program, ...}}  (used for the OS-family guess)

        Cached so callers that want the raw counts (the SQLite store, the
        history-based detectors) and run() don't reparse the log twice.
        """
        if self._aggregate is not None:
            return self._aggregate
        counts = defaultdict(int)
        examples = {}
        host_programs = defaultdict(set)
        for line in self.lines:
            rec = parse_line(line)
            if rec is None:
                continue
            host, program, window, raw = rec
            counts[(host, program, window)] += 1
            examples.setdefault((host, program), raw)
            host_programs[host].add(program)
        self._aggregate = (counts, examples, host_programs)
        return self._aggregate

    def run(self):
        """Return a list of PeerAnomaly, highest score first."""
        counts, examples, host_programs = self.aggregate()

        # collapse windows -> (host, program) day totals
        pair_totals = collapse_to_pairs(counts)

        # group host totals by program so each program is its own peer group
        by_program = defaultdict(dict)
        for (host, program), n in pair_totals.items():
            by_program[program][host] = n

        os_family = {h: guess_os_family(p) for h, p in host_programs.items()}

        anomalies = []
        for program, host_counts in by_program.items():
            if len(host_counts) < self.min_hosts:
                continue
            population = list(host_counts.values())
            median = statistics.median(population)
            for host, n in host_counts.items():
                if n < self.min_count:
                    continue
                score = robust_z(n, population)
                if score <= 0:
                    continue
                anomalies.append(PeerAnomaly(
                    host=host,
                    program=program,
                    count=n,
                    fleet_median=median,
                    score=score,
                    example_line=examples[(host, program)],
                    os_family=os_family.get(host, "unknown"),
                ))
        anomalies.sort(key=lambda a: a.score, reverse=True)
        return anomalies


if __name__ == "__main__":
    # Dev tool — NOT the report wiring. Eyeball the detector against a raw log.
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "--"
    fh = sys.stdin if path == "--" else open(path, encoding="utf-8", errors="replace")
    for a in AnomalyDetectorAgent(fh.readlines()).run()[:20]:
        print(f"z={a.score:8.1f}  {a.host:<14} {a.program:<22} "
              f"count={a.count:<8,} fleet median={a.fleet_median:g}  [{a.os_family}]")
        print(f"            e.g. {a.example_line[:140]}")
