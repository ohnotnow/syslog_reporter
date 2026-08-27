# CLAUDE.md

A batch CLI tool that turns a noisy, org-wide syslog stream into a short,
prioritised email report for a small university sysadmin team. Deterministic
code (filters, counts, robust statistics) decides *what* is worth surfacing;
the LLM only explains findings and writes paste-ready commands. Alert fatigue
is the enemy: better to under-report with high precision than to flood.

## Start here, in this order

1. **`ant foundation`** - the project vision: what this is, what it is NOT
   (not a SIEM, not real-time, deliberately not a security tool), and the
   spirit to work in. Read it before making judgement calls.
2. **`ant recent --limit 5`** - recent decisions and the current handoff note.
   The *why* behind the design lives in ant (ADRs, pivots), and the handoff
   note is kept up to date with in-flight context that doesn't belong in git.
3. **`TECHNICAL_OVERVIEW.md`** - the *what*: pipeline diagram, directory map,
   data models, conventions, local dev commands. Read it before touching the
   pipeline; keep it updated when you change the architecture.
4. **`ait`** tracks open work (issues and epics). `ant for <issue-id>` links
   the two.

## Commands

```bash
uv sync                                          # install dependencies
uv run main.py <logfile> --debug                 # full run (costs LLM money)
uv run main.py <logfile> --no-llm                # free run: filter + detectors + store only
uv run python -m unittest discover -s tests -t . # tests (stdlib unittest, NOT pytest)
```

Sample logs (`nov_8.log`, `test_syslog.log`) and the daily ELK dumps
(`syslog-*.ndjson.gz`) are gitignored, so they exist locally but not on a
fresh clone. There is no cron wrapper any more: the dump-per-day workflow
made the old `run.sh` slicer redundant (deleted 2026-08-27).

## Conventions

- Every pipeline step is an *agent*: a class in `agents/` taking its inputs
  in `__init__` and exposing `run()`. Structured LLM output goes through
  `instructor.from_litellm(completion)` with a Pydantic `response_model`
  (see `issue_agent.py` for the pattern).
- Prompts are jinja templates in `agents/prompts/`.
- Anomaly detection is deliberately pure stdlib: no scikit-learn, no TSDB,
  history is plain SQLite. Do not add dependencies to that path without a
  conversation first.
- Models are named in LiteLLM format (`openai/gpt-4o-mini`); config comes
  from env vars / `.env` (see `Readme.md`). Never commit `.env`.
- British English throughout, including report output.
- Report markdown needs blank-line separation around headings and fences or
  email viewers render it as one blob.

## Gotchas

- `classifier.py` and `mailer.py` at the repo root are pre-pipeline leftovers:
  `classifier.py` imports modules that don't exist in the repo and nothing
  imports `mailer.py`. The real email code is `agents/emailer.py`. Don't
  mistake them for live code.
- `*.log` and `*.db` are gitignored: sample logs and the aggregate-history
  SQLite file stay local by design.
- The SMTP send path has never been tested against a real server; unit tests
  cover message assembly only.
- The baseline and temporal anomaly detectors are silent until the aggregate
  store has roughly two weeks of daily history. That is expected, not a bug.
