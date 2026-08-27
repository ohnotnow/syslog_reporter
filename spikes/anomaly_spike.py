#!/usr/bin/env python3
"""
THROWAWAY SPIKE — not production code.

Goal: prove (or disprove) that dead-simple, dependency-free anomaly detection on
RAW syslog surfaces something a sysadmin would actually care about — *before* we
commit to building it properly.

Why raw (not filtered)? Because the production denylist in agents/log_filters.py
deletes ~99% of lines, including high-volume noise like dhcpd/puppet/kernel. But
"a host's dhcpd volume tripled" is exactly the kind of signal we want, and it's
gone by the time the LLM sees anything. So we look upstream of the filter.

Two baselines that need NO history (we only have one day of logs to play with):

  1. PEER comparison   — for each program, compare each host's count against the
                         fleet. Catches "one box is doing 50x more X than its peers".
  2. TEMPORAL burst    — for each (host, program), compare each 10-min window's
                         count against that series' own typical window. Catches
                         "this thing spiked hard at 11:00".

Both use a robust z-score (median + MAD), which shrugs off the long tail of
mild .ac.uk weirdness instead of being dragged around by it.

Production would ADD a third, better baseline: day-over-day per host (persisted
to SQLite so it survives the monthly logrotate). That needs history we don't
have in a single sample file — hence it's not in this spike.

Usage:  uv run python spikes/anomaly_spike.py nov_8.log
"""

import sys
import re
import statistics
from collections import defaultdict

# --- tunables (deliberately conservative; we're ranking, not alerting yet) ---
PEER_MIN_HOSTS = 5      # only peer-compare programs seen on at least this many hosts
PEER_MIN_COUNT = 50     # ignore a (host,program) with fewer events than this
TEMPORAL_MIN_TOTAL = 50 # ignore a (host,program) series quieter than this over the day
BUCKET_MINUTES = 10     # temporal window size
TOP_N = 15              # how many of each kind to print

PROG_RE = re.compile(r'\[\d+\]$')  # strip a trailing [pid] from the program token


def parse(line):
    """Return (host, program, bucket, raw_line) or None if the line doesn't fit
    the standard 'Mon DD HH:MM:SS host program[pid]: msg' shape."""
    parts = line.split(None, 4)
    if len(parts) < 5:
        return None
    _mon, _day, tstamp, host, rest = parts
    if len(tstamp) < 5 or tstamp[2] != ':':
        return None
    program = rest.split(None, 1)[0]            # 'puppet-agent[1545710]:'
    program = program.split('[', 1)[0]          # '/usr/libexec/foo[123]:' -> '/usr/libexec/foo'
    program = PROG_RE.sub('', program).rstrip(':')
    if not program:
        return None
    minute = int(tstamp[3:5])
    bucket = f"{tstamp[:2]}:{(minute // BUCKET_MINUTES) * BUCKET_MINUTES:02d}"
    return host, program, bucket, line.rstrip("\n")


def robust_z(x, values):
    """Modified z-score. Falls back from MAD to mean-abs-dev when MAD is 0
    (common with integer counts), so a lone spike against an identical baseline
    still ranks instead of vanishing into a divide-by-zero."""
    med = statistics.median(values)
    deviations = [abs(v - med) for v in values]
    mad = statistics.median(deviations)
    if mad > 0:
        return 0.6745 * (x - med) / mad
    mean_ad = sum(deviations) / len(deviations)
    if mean_ad > 0:
        return (x - med) / (1.253 * mean_ad)
    return 0.0  # every host/window identical — nothing to see


def main(path):
    # (host, program) -> total count   |   ... -> one example raw line
    pair_count = defaultdict(int)
    pair_example = {}
    # (host, program) -> {bucket: count}
    series_buckets = defaultdict(lambda: defaultdict(int))
    series_example = {}

    parsed = skipped = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            rec = parse(line)
            if rec is None:
                skipped += 1
                continue
            parsed += 1
            host, program, bucket, raw = rec
            key = (host, program)
            pair_count[key] += 1
            pair_example.setdefault(key, raw)
            series_buckets[key][bucket] += 1
            series_example.setdefault((host, program, bucket), raw)

    print(f"parsed {parsed:,} lines  (skipped {skipped:,} non-standard)\n")

    # --- 1. PEER anomalies -------------------------------------------------
    # group host counts by program
    by_program = defaultdict(dict)  # program -> {host: count}
    for (host, program), count in pair_count.items():
        by_program[program][host] = count

    peer_hits = []
    for program, host_counts in by_program.items():
        if len(host_counts) < PEER_MIN_HOSTS:
            continue
        counts = list(host_counts.values())
        med = statistics.median(counts)
        for host, count in host_counts.items():
            if count < PEER_MIN_COUNT:
                continue
            z = robust_z(count, counts)
            if z > 0:
                peer_hits.append((z, host, program, count, med))

    peer_hits.sort(reverse=True)
    print("=" * 78)
    print("PEER ANOMALIES — a host doing far more of a program than its fleet peers")
    print("=" * 78)
    for z, host, program, count, med in peer_hits[:TOP_N]:
        print(f"  z={z:8.1f}  {host:<14} {program:<22} count={count:<8,} "
              f"fleet median={med:g}")
        print(f"            e.g. {pair_example[(host, program)][:140]}")
    print(f"  ...{len(peer_hits)} (host,program) pairs scored in total\n")

    # --- 2. TEMPORAL bursts ------------------------------------------------
    temporal_hits = []
    for (host, program), buckets in series_buckets.items():
        total = sum(buckets.values())
        if total < TEMPORAL_MIN_TOTAL:
            continue
        active = list(buckets.values())  # counts in windows where it was active
        if len(active) < 3:
            continue
        for bucket, count in buckets.items():
            z = robust_z(count, active)
            if z > 0:
                temporal_hits.append((z, host, program, bucket, count, total))

    temporal_hits.sort(reverse=True)
    print("=" * 78)
    print(f"TEMPORAL BURSTS — a host:program spiking in one {BUCKET_MINUTES}-min "
          f"window vs its own day")
    print("=" * 78)
    for z, host, program, bucket, count, total in temporal_hits[:TOP_N]:
        print(f"  z={z:8.1f}  {host:<14} {program:<22} {bucket}  "
              f"count={count:<6,} (day total={total:,})")
        print(f"            e.g. {series_example[(host, program, bucket)][:140]}")
    print(f"  ...{len(temporal_hits)} (host,program,window) buckets scored in total")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: anomaly_spike.py <syslog file>")
    main(sys.argv[1])
