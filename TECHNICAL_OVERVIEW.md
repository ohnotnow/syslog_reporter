# Technical Overview

Last updated: 2026-08-27

## What this is

A command-line tool that turns a noisy org-wide syslog into a short, prioritised report of genuine issues (each with paste-ready investigate/fix commands) plus a statistical anomaly check, intended as a Monday-morning email for a sysadmin team. Input is raw rsyslog text or an NDJSON dump from the org ELK cluster; a plain-language tour for non-developers lives in `HOW_IT_WORKS.md`.

For the *why* behind the design, see the `ant` notebook: foundation `syslogreporter-AkRXV`, ADR `syslogreporter-VYQvH`, pipeline note `syslogreporter-sYVTv`, the ELK-ingest ADR `syslogreporter-cwm6b`, and the current handover note `syslogreporter-7qsQV`.

## Stack

- Python 3.13+ , managed with [uv](https://docs.astral.sh/uv/)
- litellm (multi-provider LLM calls), instructor (structured output via Pydantic)
- pydantic (data models), jinja2 (prompt and report templates), python-dotenv
- Tests use the standard-library `unittest` runner (no pytest in the venv)

## Directory structure

```
main.py                     CLI entry point; wires the pipeline together
tools/
  elk_dump.py               day-bounded NDJSON dumper for the ELK cluster
                            (stdlib-only single file; runs on any python3 box)
agents/
  __init__.py               re-exports every agent; defines PROMPT_DIR
  elk_source.py             ElkSourceAgent: renders an NDJSON dump back into
                            rsyslog text lines; infers the slice date; collects
                            a {host: OS} map from host.os.* fields
  llm.py                    shared litellm completion wrapper; injects
                            SYSLOG_REASONING_EFFORT when set
  log_agent.py              LogFilterAgent (deterministic noise removal)
  log_filters.py            ignore_list / regex_ignore_list / normalise_map (edit to taste)
  known_knowns.py           KnownKnowns + KnownEntry: operator-acknowledged
                            estate oddities (TOML, gitignored); drops lines
                            host-aware and mutes (host, program) anomalies
  issue_agent.py            IssueDetectorAgent + Issue / IssueList models
  issue_dedupe_agent.py     IssueDeduplicatorAgent (merges cross-chunk duplicates)
  resolution_agent.py       ResolutionAgent + Resolution / ResolutionList models
  anomaly_agent.py          AnomalyDetectorAgent (peer) + parse_line / robust_z /
                            collapse_to_pairs / guess_os_family / combine_anomalies
  aggregate_store.py        AggregateStore (SQLite daily-aggregate persistence)
  baseline_agent.py         HostBaselineDetectorAgent + BaselineAnomaly (day-over-day)
  temporal_agent.py         TemporalBurstDetectorAgent + TemporalAnomaly (seasonality-aware)
  anomaly_explainer.py      AnomalyExplainerAgent + AnomalyExplanation / ExplainedAnomaly
  report_agent.py           ReportAgent (full report + short email digest)
  emailer.py                EmailAgent (body + attachment over SMTP)
  prompts/*.j2              jinja templates: system prompts and the report/email layouts
tests/                      unittest suite
spikes/anomaly_spike.py     throwaway proof of the anomaly approach (not wired in)
```

## Pipeline (the heart of the tool)

`main.py` runs the agents in order. Input arrives either as raw rsyslog text (file or stdin) or as an ELK NDJSON dump, selected by `--format` (auto picks ndjson for `*.ndjson(.gz)` paths); `ElkSourceAgent` renders dump documents back into classic `Mon DD HH:MM:SS host program[pid]: message` lines so every later stage sees one input shape (ADR `syslogreporter-cwm6b`). For dumps it also infers the slice date for the store and builds a `{host: "Ubuntu 22.04.5"}` map that replaces the program-based OS guess on anomalies and gives the resolution prompt a per-host OS inventory. Raw lines then feed two branches that merge at the report:

```
raw log lines
   │
   ├── LogFilterAgent ──> filtered lines ──> IssueDetectorAgent ──> IssueList
   │                                              │
   │                                       IssueDeduplicatorAgent (67 -> 30 on sample day)
   │                                              │
   │                                        ResolutionAgent ──> ResolutionList
   │                                                                │
   └── AnomalyDetectorAgent.aggregate() (RAW, no LLM)              │
                 │                                                  │
                 ├─> AggregateStore.write() ─> SQLite history ─┐    │
                 ├─> AnomalyDetectorAgent.run() ─> [PeerAnomaly]│    │
                 ├─> HostBaselineDetectorAgent ─> [Baseline] <──┤    │
                 ├─> TemporalBurstDetectorAgent ─> [Temporal] <─┘    │
                 │            │  (history-based two read SQLite)      │
                 │     combine_anomalies() ─> dedupe + rank by |score|
                 │            │                                      │
                 │     AnomalyExplainerAgent ─> [ExplainedAnomaly]   │
                 │                                     │             │
                 └─────────────────────────────────────┴─> ReportAgent <──┘
                                                        │
                              ┌─────────────────────────┴─────────────────────┐
                         email_body() (digest)                       run() (full report)
                              │                                              │
                         email_body.md                              email_attachment.md
                              └──────────── EmailAgent (optional --send-email) ┘
```

Anomaly detection runs on the RAW log, upstream of the filter, so it can see the high-volume programs the denylist removes. Everything else runs on the filtered log.

Operator-acknowledged "known knowns" (`agents/known_knowns.py`, entries in a gitignored `known_knowns.toml`) are applied in two places: `LogFilterAgent` drops matching lines host-aware before the general ignores, and `main.py` mutes matching (host, program) anomalies right after `combine_anomalies`, before the explainer spends LLM money. Suppression stays visible: the report footer lists which entries fired (with hit counts) and flags lapsed entries. Expiry compares against the slice date, not the wall clock, so backfills behave historically; a lapsed entry simply stops matching and the noise reappears, which is the nudge to extend or investigate.

Three detectors feed the anomaly branch off one shared, cached aggregate: **peer** (a host vs its fleet — no history needed), **baseline** (a host vs its *own* trailing-N-day normal, including "gone silent"), and **temporal** (a burst in a time-of-day window vs the same window on prior days — the seasonality guard that stops morning lab reboots crying wolf). The latter two read the SQLite history that `AggregateStore` accumulates daily, so they are **no-ops until ~1–2 weeks of data exist**; the peer detector works from day one. `combine_anomalies` collapses all three to one entry per (host, program), keeping the strongest signal (scores are all modified z-scores, so comparable), so a colleague never gets the same host three times.

## Data models

| Model | Defined in | Key fields |
|-------|-----------|-----------|
| `Issue` / `IssueList` | `issue_agent.py` | issue, severity (critical/high/medium/low), description, example_log_entry, affected_host[], affected_service, timestamp_frequency, potential_impact, recommended_action; `hosts_summary()` truncates long host lists |
| `Resolution` / `ResolutionList` | `resolution_agent.py` | issue (pairs to Issue by title), root_cause, investigate (one command), fix_commands[], notes |
| `PeerAnomaly` | `anomaly_agent.py` | host, program, count, fleet_median, score (robust z), example_line, os_family, kind |
| `BaselineAnomaly` | `baseline_agent.py` | host, program, count (today), baseline_median, score (signed), direction (louder/quieter/silent), days_seen, example_line, os_family, kind |
| `TemporalAnomaly` | `temporal_agent.py` | host, program, window, count, baseline_median, score, days_seen, example_line, os_family, kind |
| `ExplainedAnomaly` | `anomaly_explainer.py` | host, program, kind, headline, detail, os_family, example_line, plus likely_causes, investigation_steps[], suggested_commands[] |

Every anomaly type exposes a common `headline()` (short label) and `summary()` (the deterministic numbers sentence) so the explainer and report render all three uniformly; `combine_anomalies()` and the explainer rely on that interface. `SEVERITY_RANK` in `issue_agent.py` drives the top-N ordering for the issue digest.

## Conventions

- Every step is an *agent*: a class taking its inputs in `__init__` and exposing `run()`.
- LLM steps that need structured output use `instructor.from_litellm(completion)` with a Pydantic `response_model` (see `issue_agent.py` for the pattern), importing `completion` from `agents/llm.py` rather than litellm so cross-cutting call options (currently `SYSLOG_REASONING_EFFORT`) have one home.
- Report prompts require a one-line `#` comment above every suggested command; state-changing commands must start `# CHANGES STATE:` (see ant note `syslogreporter-C8ggs`).
- Prompts are jinja templates in `agents/prompts/` rendered with no variables (they are system prompts), except `report.j2` and `email_body.j2` which take data.
- Models are passed in LiteLLM format (e.g. `openai/gpt-4o-mini`). Default in `SYSLOG_DEFAULT_MODEL`.
- Anomaly detection is deliberately pure stdlib (no scikit-learn, no TSDB — the history store is plain SQLite). All three detectors share the robust median/MAD z-score (`robust_z`) with a mean-abs-dev fallback when MAD is zero. NB a perfectly *flat* history (every day identical) has MAD and mean-abs-dev both zero, so `robust_z` returns 0 — real series jitter, so this only bites synthetic data.
- Markdown for the report must be blank-line / heading / fenced-code separated, or it renders as one blob in a viewer.
- British English throughout.

## Configuration

Environment variables (a `.env` is read automatically; never commit it):

- `SYSLOG_DEFAULT_MODEL` default model, LiteLLM format
- `OPENAI_API_KEY` (or the key for whichever provider is used)
- `SYSLOG_SMTP_SERVER`, `SYSLOG_SMTP_SENDER`, `SYSLOG_SMTP_RECIPIENTS` for `--send-email`
- `SYSLOG_DB_PATH` SQLite aggregate-store path (default `syslog_aggregates.db`; gitignored). CLI `--db` overrides; `--no-store` skips persistence and the history-based detectors entirely
- `SYSLOG_DB_KEEP_DAYS` retention for the aggregate store; rows older than this are pruned each run (default 90)
- `SYSLOG_REASONING_EFFORT` passed as `reasoning_effort` to reasoning models via `agents/llm.py`; `none` is right for batch (gpt-5.6-class models reject `low` combined with function tools on chat completions). Unset = provider default
- `SYSLOG_BLANKET_IGNORE` comma-separated substrings appended to `ignore_list` at runtime (`LogFilterAgent.blanket_ignores`). The home for estate-identifying filter entries (hostnames, internal IPs, usernames) so the committed filter stays estate-neutral; each run logs how many entries are active, so a missing `.env` on the cron host is visible
- `SYSLOG_KNOWN_KNOWNS` path to the known-knowns TOML file (default `known_knowns.toml`, gitignored; CLI `--known-knowns` overrides; a missing file means none). Entries are estate-identifying by nature, so like the blanket ignores they live outside the public repo; each run logs how many are active/expired
- `ELK_URL`, `ELK_USERNAME`/`ELK_PASSWORD` or `ELK_API_KEY`, `ELK_INDEX` are read by `tools/elk_dump.py` only

The store is keyed by the date the log slice covers: `main.py --date YYYY-MM-DD`, defaulting to *yesterday* or, for NDJSON input, to the date found in the data. (The old `run.sh` cron wrapper that sliced a monolithic rsyslog file is gone, 2026-08-27: the dump-per-day workflow made it redundant; revisit slicing only if raw-file users turn up.) The noise filter (`agents/log_filters.py`) is meant to be edited per estate; the block comment marks the entries tuned on real ELK days (2026-08-27).

`--no-llm` skips every LLM stage (issue detection, dedupe, resolutions, anomaly explanations) so a run costs nothing; the filter, the three detectors and the store writes all still happen, and the report says the analysis was skipped rather than pretending the day was clean. Combined with `--date`/`--db` it is the backfill tool: replay a stack of historical daily slices in date order to build up baseline history for free, then do one normal run.

## Testing

- Framework: standard-library `unittest`.
- Pattern: one test module per area (`test_anomaly_agent.py`, `test_aggregate_store.py`, `test_baseline_agent.py`, `test_temporal_agent.py`, `test_anomaly_explainer.py`, `test_report.py`, `test_issue_dedupe.py`, `test_elk_source.py`, `test_log_agent.py`, `test_known_knowns.py`). Pure logic is unit-tested; LLM round-trips are validated by live runs, not mocks. The store/baseline/temporal tests seed an in-memory SQLite (`:memory:`) with synthetic history. Tests use fictional hostnames only; real estate names live solely in gitignored dumps and reports.
- NB `.gitignore` ignores `*.log` and `*.db`, so the sample logs and the aggregate-store SQLite file stay local-only: a fresh clone has neither.
- Run: `uv run python -m unittest discover -s tests -t .`

## Local development

```bash
uv sync
uv run main.py nov_8.log --model openai/gpt-4o-mini --debug   # full run on a (local-only, gitignored) sample log
uv run main.py syslog-2026-08-26.ndjson.gz --no-llm           # free run on a (gitignored) ELK dump
uv run python -m agents.anomaly_agent nov_8.log               # just eyeball the anomaly detector
```

## Outstanding work

The history-based detectors were **validated on real data on 2026-08-27**: the store was backfilled with 15 real ELK days and the baseline/temporal detectors went live on day 8 of history as designed (first genuine catch: a mail relay at 2% of its own 14-day median). Remaining tuning question on `ait` `syslog-reporter-UkLWZ.12`: temporal volume pre-dedupe looks high; review the `THRESHOLD` / `MIN_*` constants in `baseline_agent.py` / `temporal_agent.py` after a couple more weeks of history. `combine_anomalies` keeps only the single strongest reason per (host, program); a richer "show every reason" merge is a possible later refinement.

Loose ends, tracked as `ait` tasks: `--live` ELK mode is designed but parked on whitelist politics (`syslog-reporter-YHETx`); the docs-sweep/de-hardcode task `syslog-reporter-ROeNh` is half done (docs swept 2026-08-27; the estate-domain literal in `log_filters.py` remains); the SMTP send path is wired but never tested against a real server; the `Dockerfile` references python:3.9 and a non-existent `requirements.txt`; git still tracks the readme as `Readme.md` while disk and `pyproject.toml` say `README.md` (needs a `git mv`).
