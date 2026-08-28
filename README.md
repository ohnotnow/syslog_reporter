# Syslog reporter

**Note:** this python version is unmaintained in favour of a new golang port at https://github.com/ohnotnow/syslog-reporter-go .

A command-line tool that turns a noisy, org-wide syslog into a short,
prioritised morning email: the few things actually worth a sysadmin's
attention, each with paste-ready commands to investigate and fix.

## What it does

Deterministic code does the deciding: a noise filter tuned to your estate
drops the routine 99%, and statistical checks over the raw log flag hosts
behaving unlike their peers, unlike their own recent history, or unusually
for the time of day. An LLM then does the explaining: it reads
the remaining lines, pulls out genuine issues, merges duplicates, and writes
OS-specific commands for each finding, with every state-changing command
flagged so it can't be pasted unread. A full day of logs (roughly 540k
lines) costs about $0.11 and seven minutes.

Input is a syslog text file, stdin, or an NDJSON dump pulled from an
Elasticsearch/ELK cluster with the bundled `tools/elk_dump.py`. Output is a
short digest (`email_body.md`), a full report (`email_attachment.md`), and
optionally an email with both.

For a high-level overview of how it works, see [HOW_IT_WORKS.md](HOW_IT_WORKS.md). The internals (pipeline, data models,
conventions) are in [TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md).

## Prerequisites

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/) for dependency management
- An LLM API key. OpenAI is the default, but any provider supported by
  [LiteLLM](https://docs.litellm.ai/docs/providers) works.

## Getting started

```bash
git clone https://github.com/ohnotnow/syslog_reporter
cd syslog_reporter
uv sync
```

Put your API key in the environment or a `.env` file in the project root
(never commit it):

```bash
export OPENAI_API_KEY=sk-...
export SYSLOG_DEFAULT_MODEL=openai/gpt-4o-mini   # optional, LiteLLM format
```

## Usage

```bash
uv run main.py /var/log/messages                     # a raw syslog file
tail -n 5000 /var/log/messages | uv run main.py      # or stdin
uv run main.py syslog-2026-08-26.ndjson.gz           # or an ELK dump
uv run main.py yesterday.log --no-llm                # free run, no LLM stages
```

Each run prints the digest to stdout and writes `email_body.md` and
`email_attachment.md` to the working directory. Add `--send-email` (with the
SMTP settings below) to email them. For a daily cron, point it at
yesterday's dump: `uv run main.py syslog-$(date -d yesterday +%F).ndjson.gz
--send-email`.

To pull a day of syslog out of an ELK cluster, copy `tools/elk_dump.py` (a
single stdlib-only file) to any machine that can reach the cluster and run:

```bash
python3 elk_dump.py --url https://your-elk:9200 --username you \
    --index 'logs-system.syslog-yournamespace' --day 2026-08-26 \
    --out syslog-2026-08-26.ndjson.gz
```

The dump keeps only the fields the pipeline needs (timestamp, host, OS,
program, message) and the pipeline reads the `.gz` directly.

### Command-line options

- `logfile` (positional) the log to read; omit, or pass `--`, for stdin
- `--model` the LLM, in LiteLLM format (default `openai/gpt-4o-mini`)
- `--format` input format: `auto` (default), `raw`, or `ndjson`. Auto picks
  ndjson for `*.ndjson` / `*.ndjson.gz` paths
- `--no-llm` skip every LLM stage so the run costs nothing; the filter,
  detectors and history store still run. Good for dry runs on unfamiliar
  data and for backfilling anomaly history from old days
- `--date` the ISO date the slice covers, for the history store (defaults
  to yesterday, or to the date found in an NDJSON dump)
- `--db` / `--no-store` history store path / skip persistence entirely
- `--known-knowns` path to the known-knowns TOML file (default
  `known_knowns.toml`; a missing file just means none)
- `--send-email` / `--recipients` email the report
- `--debug` extra logging
- `--file` an alternative way to pass the file path

## Configuration

Environment variables, read from the environment or `.env`:

- `SYSLOG_DEFAULT_MODEL` default model (LiteLLM format)
- `OPENAI_API_KEY` or the matching key for your provider
- `SYSLOG_REASONING_EFFORT` passed to reasoning models as
  `reasoning_effort`; `none` is the right setting for cheap batch runs
  (unset means the provider default)
- `SYSLOG_SMTP_SERVER`, `SYSLOG_SMTP_SENDER`, `SYSLOG_SMTP_RECIPIENTS` for
  `--send-email`
- `SYSLOG_DB_PATH`, `SYSLOG_DB_KEEP_DAYS` history store location (default
  `syslog_aggregates.db`, gitignored) and retention (default 90 days)
- `SYSLOG_BLANKET_IGNORE` comma-separated substrings to drop, treated like
  `ignore_list` entries. This is where estate-specific strings (internal
  hostnames, IPs, usernames) belong, so they stay out of the codebase
- `SYSLOG_KNOWN_KNOWNS` path to the known-knowns file (default
  `known_knowns.toml`)

The dump tool reads `ELK_URL`, `ELK_USERNAME`/`ELK_PASSWORD` or
`ELK_API_KEY`, and `ELK_INDEX`.

## Customising the noise filter

The filter rules live in `agents/log_filters.py` and are meant to be edited
for your estate: `ignore_list` (substring drops), `regex_ignore_list`
(regex drops) and `normalise_map` (collapse near-identical lines). Put any
entry that names your own infrastructure (a hostname, an internal IP, a
local username) in `SYSLOG_BLANKET_IGNORE` instead, so it lives in your
`.env` rather than in a public fork. The anomaly detectors read the raw
log upstream of the filter, so filtered programs are still watched for
unusual volume.

## Known knowns

Every estate has oddities the team has already shrugged at: the host that
always complains about a TCP port because a microscope is plugged into it,
the box that blocks campus multicast all day by design. Left alone they
appear in every report, and a report that keeps crying wolf stops being
read. Declare them in `known_knowns.toml` (gitignored, because its content
names your own infrastructure):

```toml
# Each [[known]] block is one entry (TOML's way of writing a list of
# dicts): repeat the header for every entry, no commas or indentation.

[[known]]
host = "scopebox"          # fnmatch pattern: "scopebox", "lab*", or "*"
match = "port 1234"        # optional: regex against the text after the hostname
reason = "microscope attached for the optics experiment"
added = 2026-08-27
expires = 2030-09-01       # optional: entry lapses after this slice date

[[known]]
host = "mcastbox"
program = "kernel"         # optional: fnmatch, mutes (host, program) anomalies
reason = "drops campus multicast all day by design"
added = 2026-08-27
```

Each entry needs a `reason` and at least one of `match` / `program`:
`match` drops matching lines from the issue path, `program` mutes that
host's anomaly detections (the detectors read the raw stream, so a line
filter alone cannot silence them). Suppression stays visible: the report
footer lists which entries fired and how often, and flags lapsed entries.
When an `expires` date passes the noise simply returns to the next digest,
which is the nudge to extend the entry or investigate. Expiry is judged
against the date of the log slice, not today, so historical backfills
behave historically.

## Example of an issue

```markdown
## 1. Sustained CPU overheating and saturation

**Severity:** critical · **Affected:** example-host

example-host repeatedly reaches near-total CPU utilization while package and core temperatures exceed thresholds and clock throttling occurs, indicating a persistent thermal and workload problem.

**Likely cause:** example-host has a persistent CPU workload combined with inadequate cooling or thermal/hypervisor contention, causing throttling and unsafe temperatures.

**Have a look:**

# Identify CPU consumers, temperatures, frequencies, throttling, and hardware errors on example-host
ssh example-host 'uptime; ps -eo pid,ppid,user,pcpu,pmem,etime,cmd --sort=-pcpu | head -30; vmstat 1 5; sensors 2>/dev/null; for f in /sys/class/thermal/thermal_zone*/temp; do echo "$f $(cat "$f")"; done; grep -iE "thermal|thrott|mce|hardware error" /var/log/messages /var/log/kern.log 2>/dev/null | tail -100'

**Try:**

# Check scheduled jobs and PCP alarm context
ssh example-host 'sudo systemctl list-timers --all; sudo crontab -l -u root; sudo journalctl -u pcp-pmie --since today --no-pager -n 100'
# Check CPU frequency, thermal zones, and virtualization metadata
ssh example-host 'lscpu; cpupower monitor 2>/dev/null | head -80; systemd-detect-virt; sudo ipmitool sdr elist 2>/dev/null | grep -Ei "temp|fan|power" || true'
# CHANGES STATE: Stop an identified runaway nonessential job before temperatures worsen
ssh example-host 'sudo systemctl stop <identified-runaway-unit>'
# CHANGES STATE: Move or disable the offending scheduled job after confirming ownership
ssh example-host 'sudo systemctl disable --now <identified-runaway-unit>'
# Recheck temperature and utilization after workload reduction
ssh example-host 'uptime; sensors 2>/dev/null; ps -eo pid,pcpu,pmem,cmd --sort=-pcpu | head -15'

_Note: Replace unit placeholders only after identifying the actual runaway unit; take example-host offline or power it down if temperatures remain beyond hardware limits._
```

## Contributing

Contributions are welcome. Fork or clone, `uv sync`, make your changes, and
run the test suite before opening a pull request:

```bash
uv run python -m unittest discover -s tests -t .
```

## Licence

Copyright (C) 2024-2026 ohnotnow

Released under the GNU Affero General Public License v3.0 (AGPL-3.0-only). See [LICENSE](LICENSE) for details.
