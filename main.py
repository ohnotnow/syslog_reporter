import os
import sys
import argparse
import logging
import smtplib
import dotenv
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from agents import (
    ElkSourceAgent,
    LogFilterAgent,
    KnownKnowns,
    AnomalyDetectorAgent,
    AggregateStore,
    HostBaselineDetectorAgent,
    TemporalBurstDetectorAgent,
    AnomalyExplainerAgent,
    combine_anomalies,
    facts_only,
    IssueDetectorAgent,
    IssueDeduplicatorAgent,
    IssueList,
    ResolutionAgent,
    ResolutionList,
    ReportAgent,
    EmailAgent,
)

dotenv.load_dotenv()

DEFAULT_MODEL = os.getenv("SYSLOG_DEFAULT_MODEL", "openai/gpt-4o-mini")
DEFAULT_DB_PATH = os.getenv("SYSLOG_DB_PATH", "syslog_aggregates.db")
DEFAULT_KEEP_DAYS = int(os.getenv("SYSLOG_DB_KEEP_DAYS", "90"))
DEFAULT_KNOWNS_PATH = os.getenv("SYSLOG_KNOWN_KNOWNS", "known_knowns.toml")


def setup_logging(debug: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]  # Sends to stdout/stderr
    )
    log = logging.getLogger(__name__)
    return log

def main(lines: list[str], model: str = DEFAULT_MODEL, debug: bool = False,
         email_addresses: str|None = None, send_email: bool = False,
         log_date: date|None = None, db_path: str = DEFAULT_DB_PATH,
         store_enabled: bool = True, keep_days: int = DEFAULT_KEEP_DAYS,
         llm_enabled: bool = True, host_os: dict|None = None,
         knowns_path: str = DEFAULT_KNOWNS_PATH):
    log = setup_logging(debug)
    # The slice we're processing is yesterday's by default; the date keys
    # the persisted aggregates (NDJSON input overrides this from the data).
    log_date = log_date or (date.today() - timedelta(days=1))
    log.debug(f"Using model: {model}")
    log.debug(f"Original log file length: {len(lines)}")

    # Operator-acknowledged estate oddities ("that host always does that,
    # it's the microscope"): dropped from the issue path and muted on the
    # anomaly path, with a footer line in the report so suppression stays
    # visible. Expiry is judged against the slice date, so backfills of
    # historical days behave historically.
    knowns = KnownKnowns.from_file(knowns_path, log_date)
    log.info(f"Known knowns: {len(knowns.active)} active, "
             f"{len(knowns.expired)} expired ({knowns_path})")

    log.info("Filtering log file")
    log_filter = LogFilterAgent(lines, knowns=knowns)
    log.info(f"Blanket ignore: {len(log_filter.blanket_ignores)} entries "
             "from SYSLOG_BLANKET_IGNORE")
    filtered_lines = log_filter.run()
    # print("\n".join(filtered_lines))
    log.debug(f"Filtered log file length: {len(filtered_lines)}")
    # exit()
    if llm_enabled:
        # detect issues
        log.info("Detecting issues")
        issues = IssueDetectorAgent(filtered_lines, model=model).run()
        log.debug(f"Detected {len(issues.issues)} issues")

        # merge duplicate issues reported across separate log chunks
        log.info("Consolidating duplicate issues")
        issues = IssueDeduplicatorAgent(issues, model=model).run()
        log.debug(f"Consolidated to {len(issues.issues)} issues")

        # resolve issues
        log.info(f"Resolving {len(issues.issues)} issues")
        resolutions = ResolutionAgent(issues, model=model, host_os=host_os).run()
        log.debug(f"Generated {len(resolutions.resolutions)} resolutions")
    else:
        chunks = (len(filtered_lines) + 999) // 1000
        log.info(f"--no-llm: skipping issue detection ({len(filtered_lines)} "
                 f"filtered lines would have gone to the LLM in {chunks} chunk(s))")
        issues = IssueList(issues=[])
        resolutions = ResolutionList(resolutions=[])

    # detect anomalies on the RAW lines (upstream of the filter, so we still see
    # the high-volume programs the denylist removes) and explain them.
    # Three detectors feed one combined, de-duplicated list:
    #   - peer:     a host unlike its fleet peers (no history needed)
    #   - baseline: a host unlike its OWN trailing-N-day normal (needs history)
    #   - temporal: a same-time-of-day burst vs prior days (needs history)
    # The history-based two are no-ops until the SQLite store has accumulated a
    # week or two; the peer detector works from day one.
    log.info("Detecting anomalies")
    detector = AnomalyDetectorAgent(lines)
    counts, examples, host_programs = detector.aggregate()
    peer_anomalies = detector.run()
    log.debug(f"Detected {len(peer_anomalies)} peer anomalies")

    baseline_anomalies, temporal_anomalies = [], []
    if store_enabled:
        store = AggregateStore(db_path)
        written = store.write_aggregates(log_date, counts)
        store.prune(keep_days)
        log.debug(f"Persisted {written} aggregate rows for {log_date} to {db_path}")
        baseline_anomalies = HostBaselineDetectorAgent(
            counts, examples, host_programs, store, log_date).run()
        temporal_anomalies = TemporalBurstDetectorAgent(
            counts, examples, host_programs, store, log_date).run()
        store.close()
        log.debug(f"Detected {len(baseline_anomalies)} baseline and "
                  f"{len(temporal_anomalies)} temporal anomalies")
    else:
        log.debug("Aggregate store disabled (--no-store); peer detector only")

    anomalies = combine_anomalies(peer_anomalies, baseline_anomalies, temporal_anomalies)
    log.debug(f"Combined to {len(anomalies)} anomalies after de-duplication")
    # Mute known-known (host, program) pairs before the explainer, so we
    # never pay the LLM to explain something we're about to bin.
    kept = [a for a in anomalies if not knowns.anomaly_muted(a.host, a.program)]
    if len(kept) != len(anomalies):
        log.debug(f"Muted {len(anomalies) - len(kept)} known-known anomalies")
    anomalies = kept
    if host_os:
        # Replace the program-based OS guess with the real OS where the
        # source knows it (ELK dumps carry host.os.*; raw text does not).
        for a in anomalies:
            a.os_family = host_os.get(a.host, a.os_family)
    if llm_enabled:
        log.info("Explaining anomalies")
        explained_anomalies = AnomalyExplainerAgent(anomalies, model=model).run()
        log.debug(f"Explained {len(explained_anomalies)} anomalies")
    else:
        log.info("--no-llm: rendering anomalies without explanations")
        explained_anomalies = facts_only(anomalies)

    # generate the report: a short digest for the email body, and the full
    # findings as an attachment
    log.info("Generating report")
    reporter = ReportAgent(issues, resolutions, explained_anomalies,
                           llm_skipped=not llm_enabled, knowns=knowns)
    full_report = reporter.run()
    email_body = reporter.email_body()
    log.debug("Generated report")

    # While we refine things, always drop the two files to the working directory
    with open("email_body.md", "w") as f:
        f.write(email_body)
    with open("email_attachment.md", "w") as f:
        f.write(full_report)
    log.info("Wrote email_body.md and email_attachment.md")

    # Print the short digest (not the 1400-line full report) for cron logs
    print(email_body)

    if send_email:
        log.info(f"Sending email to {email_addresses}")
        EmailAgent(email_body, attachment_text=full_report,
                   recipients=email_addresses).run()
    else:
        log.info("Skipping email")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("logfile", nargs="?", default=None,
                        help="Path to the syslog file (e.g. /var/log/messages). "
                             "Omit, or pass --, to read from stdin.")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model to use (litellm format)")
    parser.add_argument("--file", type=str, default="--", help="Alternative way to pass the file; or -- for stdin")
    parser.add_argument("--format", choices=["auto", "raw", "ndjson"], default="auto",
                        help="Input format: 'raw' is rsyslog text, 'ndjson' is an "
                             "elk_dump.py dump (.gz handled). 'auto' picks ndjson "
                             "for *.ndjson / *.ndjson.gz paths, raw otherwise "
                             "(stdin is always raw).")
    parser.add_argument("--debug", action="store_true", help="Print extra debug information")
    parser.add_argument("--send-email", action="store_true", help="Email the report to the recipients")
    parser.add_argument('--recipients', required=False, help='Comma-separated list of email addresses to send the report to.')
    parser.add_argument("--date", type=str, default=None,
                        help="ISO date (YYYY-MM-DD) the log slice covers, for the "
                             "aggregate store. Defaults to yesterday.")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH,
                        help=f"SQLite aggregate store path (default {DEFAULT_DB_PATH})")
    parser.add_argument("--known-knowns", type=str, default=DEFAULT_KNOWNS_PATH,
                        help="TOML file of operator-acknowledged oddities to "
                             f"suppress (default {DEFAULT_KNOWNS_PATH}; "
                             "missing file just means none).")
    parser.add_argument("--no-store", action="store_true",
                        help="Don't persist aggregates or run the history-based "
                             "detectors (peer comparison still runs).")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip every LLM stage (issue detection, dedupe, "
                             "resolutions, anomaly explanations) so the run "
                             "costs nothing. The filter, anomaly detectors and "
                             "aggregate store still run — useful for "
                             "backfilling history or a dry run on unfamiliar data.")
    args = parser.parse_args()

    # The positional path wins; fall back to --file; "--" (or nothing) means stdin
    path = args.logfile if args.logfile else args.file
    is_ndjson = args.format == "ndjson" or (
        args.format == "auto" and path.endswith((".ndjson", ".ndjson.gz"))
    )
    log_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    if is_ndjson:
        if path == "--":
            parser.error("--format ndjson needs a file path, not stdin")
        source = ElkSourceAgent(path)
        lines = source.run()
        if source.skipped:
            print(f"warning: skipped {source.skipped} NDJSON records with no "
                  "timestamp or message", file=sys.stderr)
        # Key the aggregates off the data itself rather than assuming the
        # dump is yesterday's; an explicit --date still wins.
        log_date = log_date or source.log_date
    elif path == "--":
        lines = sys.stdin.readlines()
    else:
        with open(path, "r") as f:
            lines = f.readlines()

    recipients = args.recipients if args.recipients else None

    main(lines, args.model, args.debug, recipients, args.send_email,
         log_date=log_date, db_path=args.db, store_enabled=not args.no_store,
         llm_enabled=not args.no_llm,
         host_os=source.host_os if is_ndjson else None,
         knowns_path=args.known_knowns)
