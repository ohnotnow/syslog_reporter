#!/usr/bin/env python3
"""Read-only recon of an Elasticsearch cluster, for syslog_reporter.

Answers, in one copy-back report: what indices exist, which ones look
like syslog data, what fields the documents actually have, what date
range and daily volumes are present, and a few sample documents so we
can see whether host / program / message survived ingest.

Usage:
    python3 elk_recon.py --url https://elk.example.ac.uk:9200

Discovery (listing every index, grouping, picking candidates) needs
cluster-level privileges. For an account with only index-level read,
skip discovery and name the pattern(s) you can read directly:

    python3 elk_recon.py --url ... --index 'logs-*-<namespace>'

Add --since to look only at a recent window, which also skips stale or
future-dated documents (bad syslog year parsing can stamp a December
line into next year). A bare duration becomes ES date math 'now-...':

    python3 elk_recon.py --url ... --index 'logs-system.syslog-<ns>' --since 7d

Auth is either an API key (ELK_API_KEY from env/.env, or --key-file)
or a username and password (ELK_USERNAME/ELK_PASSWORD from env/.env,
or --username with an interactive password prompt). The URL can
likewise come from ELK_URL. Credentials are never printed and never
written to the report.

Every request made is read-only: GET, or POST to a _search endpoint.
The full list of endpoints hit is included at the end of the report so
it can be shown to whoever owns the cluster.

Output: elk_recon_report.txt in the current directory (also echoed to
stdout). Individual steps that fail are recorded in the report and the
rest still run. Stdlib only; no dependencies.
"""

import argparse
import base64
import getpass
import json
import os
import platform
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

REPORT_FILENAME = "elk_recon_report.txt"

# Index-name fragments that suggest syslog-ish content.
SYSLOG_HINTS = re.compile(r"syslog|filebeat|logstash|journal|beats?|messages|logs-system", re.I)

# Trailing date / rollover suffixes, stripped (repeatedly) to group
# daily indices into one family, e.g. filebeat-2026.08.02 -> filebeat.
DATE_SUFFIX = re.compile(r"[-_.](\d{4}[.\-_]\d{2}[.\-_]\d{2}|\d{4}[.\-_]\d{2}|\d{6,8}|\d+)$")

# Fields worth pulling top values for, if the mapping has them.
INTERESTING_FIELDS = [
    "host.name", "host.hostname", "host", "hostname",
    "agent.hostname", "agent.name", "beat.hostname",
    "process.name", "program", "syslog.program", "syslog.host",
    "log.syslog.appname", "log.syslog.hostname",
    "event.module", "event.dataset",
]

MAX_CANDIDATE_GROUPS = 6
MAX_FIELDS_LISTED = 150
MAX_DAY_ROWS = 40
MAX_INDEX_ROWS = 200


def log(msg):
    print(msg, file=sys.stderr)


def load_dotenv():
    """Best-effort .env loader: cwd first, then the script's directory.

    Real environment variables always win. Handles optional 'export '
    prefixes and single/double quotes. No interpolation.
    """
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    if line.startswith("export "):
                        line = line[len("export "):]
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = value
        except OSError as exc:
            log(f"warning: could not read {path}: {exc}")


def resolve_auth(args):
    """Return (Authorization header value, description) or (None, None)."""
    key = None
    if args.key_file:
        with open(args.key_file, encoding="utf-8") as fh:
            key = fh.readline().strip()
    else:
        key = os.environ.get("ELK_API_KEY", "").strip()
    if key:
        # Elasticsearch wants base64("id:api_key"). If we were handed the
        # two-part form, encode it; otherwise assume it is already encoded.
        if ":" in key:
            key = base64.b64encode(key.encode()).decode()
        return "ApiKey " + key, "api key"

    username = args.username or os.environ.get("ELK_USERNAME", "").strip()
    if not username:
        return None, None
    password = os.environ.get("ELK_PASSWORD", "").strip()
    if not password:
        password = getpass.getpass(f"Password for {username}: ")
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return "Basic " + token, f"basic auth, user {username}"


def human_bytes(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0


def index_group(name):
    base = name
    while True:
        m = DATE_SUFFIX.search(base)
        if not m:
            break
        base = base[: m.start()]
    return base or name


def flatten_properties(props, prefix=""):
    """Flatten a mappings 'properties' tree to {dotted.path: type}."""
    fields = {}
    for name, spec in sorted(props.items()):
        path = prefix + name
        if "properties" in spec:
            fields.update(flatten_properties(spec["properties"], path + "."))
        else:
            fields[path] = spec.get("type", "object")
            for sub, subspec in spec.get("fields", {}).items():
                fields[path + "." + sub] = subspec.get("type", "?") + " (multi-field)"
    return fields


class EsClient:
    def __init__(self, base_url, auth_header, timeout, insecure=False, ca_cert=None):
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.timeout = timeout
        self.requests_made = []
        if insecure:
            self.ssl_context = ssl._create_unverified_context()
        elif ca_cert:
            self.ssl_context = ssl.create_default_context(cafile=ca_cert)
        else:
            self.ssl_context = ssl.create_default_context()

    def _request(self, method, path, body=None):
        url = self.base_url + path
        self.requests_made.append(f"{method} {path}")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", self.auth_header)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as resp:
            return json.loads(resp.read().decode())

    def get(self, path):
        return self._request("GET", path)

    def search(self, index, body):
        path = "/" + urllib.parse.quote(index, safe="*,-_.") + "/_search"
        return self._request("POST", path, body)


class Report:
    def __init__(self):
        self.sections = []

    def add(self, title, text):
        self.sections.append((title, text.rstrip()))

    def error(self, title, exc):
        detail = str(exc)
        if isinstance(exc, urllib.error.HTTPError):
            try:
                detail += "\n" + exc.read().decode(errors="replace")[:2000]
            except OSError:
                pass
        self.add(title, "ERROR: " + detail)

    def render(self):
        out = []
        for title, text in self.sections:
            out.append("=" * 70)
            out.append(title)
            out.append("=" * 70)
            out.append(text)
            out.append("")
        return "\n".join(out)


def pick_time_field(fields):
    if fields.get("@timestamp") == "date":
        return "@timestamp"
    for path, ftype in fields.items():
        if ftype == "date":
            return path
    return None


def aggregatable_field(fields, path):
    """Return a terms-aggregatable version of a field path, or None."""
    ftype = fields.get(path)
    if ftype is None:
        return None
    if ftype.startswith("keyword") or ftype in ("ip", "long", "integer"):
        return path
    if fields.get(path + ".keyword", "").startswith("keyword"):
        return path + ".keyword"
    return None


def since_to_gte(value):
    """Turn a bare duration like '7d' into ES date math 'now-7d'.

    Anything else (an absolute date, or explicit date-math such as
    'now-1M/M') is passed through unchanged, so full date-math control
    is still available. Units follow Elasticsearch: s m h d w M y.
    """
    return "now-" + value if re.fullmatch(r"\d+[smhdwMy]", value) else value


def survey_cluster(es, report):
    info = es.get("/")
    version = info.get("version", {}).get("number", "?")
    report.add(
        "Cluster",
        f"cluster_name: {info.get('cluster_name', '?')}\n"
        f"version:      {version}\n"
        f"endpoint:     {es.base_url}",
    )
    return version


def survey_auth(es, report):
    try:
        auth = es.get("/_security/_authenticate")
        roles = ", ".join(auth.get("roles", [])) or "(none listed)"
        report.add(
            "Authenticated identity",
            f"username: {auth.get('username', '?')}\n"
            f"roles:    {roles}\n"
            f"realm:    {auth.get('authentication_realm', {}).get('name', '?')}",
        )
    except (urllib.error.URLError, OSError, ValueError) as exc:
        report.error("Authenticated identity (non-fatal, account may lack this endpoint)", exc)


def survey_indices(es, report):
    rows = es.get("/_cat/indices?format=json&bytes=b&h=index,docs.count,store.size,health,status")
    groups = {}
    system_count = 0
    for row in rows:
        name = row.get("index", "?")
        if name.startswith(".ds-"):
            # Data-stream backing index: group under the stream's name,
            # e.g. .ds-logs-system.syslog-default-2026.08.02-000123
            #   -> logs-system.syslog-default
            group_name = index_group(name[len(".ds-"):])
        elif name.startswith("."):
            system_count += 1
            continue
        else:
            group_name = index_group(name)
        docs = int(row.get("docs.count") or 0)
        size = int(row.get("store.size") or 0)
        g = groups.setdefault(group_name, {"indices": 0, "docs": 0, "size": 0})
        g["indices"] += 1
        g["docs"] += docs
        g["size"] += size

    lines = [f"{'group':<40} {'indices':>7} {'docs':>14} {'size':>10}"]
    for name, g in sorted(groups.items(), key=lambda kv: -kv[1]["docs"]):
        lines.append(f"{name:<40} {g['indices']:>7} {g['docs']:>14,} {human_bytes(g['size']):>10}")
    lines.append(f"\n(plus {system_count} system indices starting with '.', ignored)")
    report.add("Index families (daily indices grouped, sorted by doc count)", "\n".join(lines))

    listing = [f"{'index':<50} {'docs':>14} {'size':>10} {'health':<8}"]
    for row in sorted(rows, key=lambda r: r.get("index", ""))[:MAX_INDEX_ROWS]:
        name = row.get("index", "")
        if name.startswith(".") and not name.startswith(".ds-"):
            continue
        listing.append(
            f"{row.get('index', '?'):<50} {int(row.get('docs.count') or 0):>14,} "
            f"{human_bytes(row.get('store.size')):>10} {row.get('health', '?'):<8}"
        )
    if len(rows) > MAX_INDEX_ROWS:
        listing.append(f"... and {len(rows) - MAX_INDEX_ROWS} more")
    report.add("Full index listing", "\n".join(listing))

    try:
        aliases = es.get("/_cat/aliases?format=json&h=alias,index")
        alines = sorted(
            f"{a.get('alias', '?')} -> {a.get('index', '?')}"
            for a in aliases if not a.get("alias", "").startswith(".")
        )
        report.add("Aliases", "\n".join(alines) if alines else "(none)")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        report.error("Aliases (non-fatal)", exc)

    return groups


def survey_data_streams(es, report):
    try:
        resp = es.get("/_data_stream")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        report.error("Data streams (non-fatal, account may lack this endpoint)", exc)
        return
    streams = resp.get("data_streams", [])
    if not streams:
        report.add("Data streams", "(none visible to this account)")
        return
    lines = [f"{'data stream':<55} {'backing':>7} {'status':<8}"]
    for s in sorted(streams, key=lambda s: s.get("name", "")):
        lines.append(
            f"{s.get('name', '?'):<55} {len(s.get('indices', [])):>7} {s.get('status', '?'):<8}"
        )
    report.add("Data streams", "\n".join(lines))


def choose_candidates(groups):
    named = [g for g in groups if SYSLOG_HINTS.search(g)]
    by_volume = sorted(groups, key=lambda g: -groups[g]["docs"])
    candidates = []
    for g in named + by_volume:
        if g not in candidates and groups[g]["docs"] > 0:
            candidates.append(g)
    return candidates[:MAX_CANDIDATE_GROUPS]


def survey_group(es, report, pattern, wanted_days, since=None):
    title = f"Candidate: {pattern}"

    mapping = es.get("/" + urllib.parse.quote(pattern, safe="*-_.") + "/_mapping")
    fields = {}
    for index_body in mapping.values():
        fields.update(flatten_properties(index_body.get("mappings", {}).get("properties", {})))

    lines = [f"{len(mapping)} indices matched, {len(fields)} distinct fields\n"]
    for path, ftype in sorted(fields.items())[:MAX_FIELDS_LISTED]:
        lines.append(f"  {path}: {ftype}")
    if len(fields) > MAX_FIELDS_LISTED:
        lines.append(f"  ... and {len(fields) - MAX_FIELDS_LISTED} more")
    report.add(title + " / fields", "\n".join(lines))

    time_field = pick_time_field(fields)
    time_filter = None
    if since and time_field:
        time_filter = {"range": {time_field: {"gte": since, "lte": "now"}}}
    elif since and not time_field:
        report.add(title + " / note",
                   "--since window ignored: no date-typed field in this mapping.")

    if time_field:
        body = {
            "size": 0,
            "aggs": {
                "min_ts": {"min": {"field": time_field}},
                "max_ts": {"max": {"field": time_field}},
                "by_day": {"date_histogram": {"field": time_field, "calendar_interval": "day"}},
            },
        }
        if time_filter:
            body["query"] = time_filter
        resp = es.search(pattern, body)
        aggs = resp.get("aggregations", {})
        total = resp.get("hits", {}).get("total", {})
        total = total.get("value", total) if isinstance(total, dict) else total
        buckets = aggs.get("by_day", {}).get("buckets", [])
        dlines = [
            f"time field: {time_field}",
            f"documents:  {total:,}" if isinstance(total, int) else f"documents: {total}",
            f"earliest:   {aggs.get('min_ts', {}).get('value_as_string', '?')}",
            f"latest:     {aggs.get('max_ts', {}).get('value_as_string', '?')}",
            f"days with data: {len(buckets)}",
            "",
        ]
        shown = buckets if len(buckets) <= wanted_days else buckets[-wanted_days:]
        if len(buckets) > len(shown):
            dlines.append(f"(last {len(shown)} days shown)")
        for b in shown:
            day = str(b.get("key_as_string", "?"))[:10]
            dlines.append(f"  {day}  {b.get('doc_count', 0):>12,}")
        report.add(title + " / date coverage", "\n".join(dlines))
    else:
        report.add(title + " / date coverage", "No date-typed field found in the mapping.")

    vlines = []
    for path in INTERESTING_FIELDS:
        agg_field = aggregatable_field(fields, path)
        if not agg_field:
            continue
        try:
            vbody = {
                "size": 0,
                "aggs": {
                    "n": {"cardinality": {"field": agg_field}},
                    "top": {"terms": {"field": agg_field, "size": 10}},
                },
            }
            if time_filter:
                vbody["query"] = time_filter
            resp = es.search(pattern, vbody)
            aggs = resp.get("aggregations", {})
            n = aggs.get("n", {}).get("value", "?")
            tops = ", ".join(
                f"{b.get('key')} ({b.get('doc_count'):,})"
                for b in aggs.get("top", {}).get("buckets", [])
            )
            vlines.append(f"{agg_field}: {n} distinct\n  top: {tops}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            vlines.append(f"{agg_field}: ERROR {exc}")
    report.add(
        title + " / host- and program-shaped field values",
        "\n".join(vlines) if vlines else "None of the usual host/program field names found.",
    )

    body = {"size": 3}
    if time_field:
        body["sort"] = [{time_field: {"order": "desc"}}]
    if time_filter:
        body["query"] = time_filter
    try:
        resp = es.search(pattern, body)
    except (urllib.error.URLError, OSError, ValueError):
        resp = es.search(pattern, {"size": 3})
    slines = []
    for hit in resp.get("hits", {}).get("hits", []):
        slines.append(f"--- {hit.get('_index', '?')} ---")
        slines.append(json.dumps(hit.get("_source", {}), indent=2, sort_keys=True)[:4000])
    report.add(title + " / sample documents (newest first)", "\n".join(slines) or "(no documents)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="Elasticsearch base URL (or ELK_URL in env/.env)")
    parser.add_argument("--index", action="append", metavar="PATTERN",
                        help="survey this index pattern directly and skip cluster "
                             "discovery; repeatable. Use when the account has "
                             "index-level read but no cluster privileges "
                             "(e.g. --index 'logs-*-<namespace>')")
    parser.add_argument("--since", metavar="WINDOW",
                        help="only look at data with a timestamp in the recent "
                             "window, e.g. --since 7d (last 7 days) or --since 24h. "
                             "Filters aggregations and samples (gte now-WINDOW, "
                             "lte now), so stale and future-dated docs are skipped. "
                             "A bare duration becomes 'now-WINDOW'; an absolute date "
                             "or explicit date-math is used as-is.")
    parser.add_argument("--key-file", help="file whose first line is the API key "
                                           "(otherwise ELK_API_KEY from env/.env)")
    parser.add_argument("--username", help="basic-auth username (or ELK_USERNAME in env/.env; "
                                           "password from ELK_PASSWORD or an interactive prompt)")
    parser.add_argument("--insecure", action="store_true",
                        help="skip TLS certificate verification")
    parser.add_argument("--ca-cert", help="path to a CA certificate for a self-signed cluster")
    parser.add_argument("--timeout", type=int, default=30, help="per-request timeout, seconds")
    parser.add_argument("--days", type=int, default=MAX_DAY_ROWS,
                        help="how many day rows to show in the date-coverage table "
                             "(display only; use --since to filter the data)")
    args = parser.parse_args()

    load_dotenv()
    url = args.url or os.environ.get("ELK_URL")
    if not url:
        parser.error("no URL: pass --url or set ELK_URL")
    auth_header, auth_desc = resolve_auth(args)
    if not auth_header:
        parser.error("no credentials: set ELK_API_KEY or ELK_USERNAME/ELK_PASSWORD "
                     "(env or .env), or pass --key-file / --username")

    since_expr = since_to_gte(args.since) if args.since else None

    es = EsClient(url, auth_header, args.timeout, insecure=args.insecure, ca_cert=args.ca_cert)
    report = Report()
    report.add(
        "Recon run",
        f"generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        f"script:    elk_recon.py (read-only)\n"
        f"auth:      {auth_desc}\n"
        f"python:    {platform.python_version()} on {platform.platform()}\n"
        f"tls:       {'VERIFICATION DISABLED' if args.insecure else 'verified'}\n"
        f"window:    {since_expr + ' .. now' if since_expr else 'all timestamps'}",
    )

    log("[1/5] cluster info ...")
    try:
        survey_cluster(es, report)
    except urllib.error.HTTPError as exc:
        # We reached the cluster and auth was processed, but this account
        # can't run cluster:monitor/main. That is fine for an index-scoped
        # recon (see --index), so record it and carry on.
        report.error("Cluster (non-fatal, account may lack cluster privileges)", exc)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        report.error("Cluster", exc)
        report.add("Aborted", "Could not reach the cluster at all; nothing else was attempted.\n"
                              "Check the URL, network reachability and TLS.")
        finish(es, report, exit_code=2)

    log("[2/5] authenticated identity ...")
    survey_auth(es, report)

    if args.index:
        log(f"surveying {len(args.index)} explicit index pattern(s) (discovery skipped) ...")
        for pattern in args.index:
            log(f"      {pattern} ...")
            try:
                survey_group(es, report, pattern, args.days, since_expr)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                report.error(f"Candidate: {pattern}", exc)
        finish(es, report, exit_code=0)

    log("[3/5] index listing ...")
    try:
        groups = survey_indices(es, report)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        report.error("Index listing", exc)
        groups = {}

    log("[4/5] data streams ...")
    survey_data_streams(es, report)

    candidates = choose_candidates(groups)
    log(f"[5/5] surveying {len(candidates)} candidate index families ...")
    for group in candidates:
        pattern = group + "*"
        log(f"      {pattern} ...")
        try:
            survey_group(es, report, pattern, args.days, since_expr)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            report.error(f"Candidate: {pattern}", exc)

    finish(es, report, exit_code=0)


def finish(es, report, exit_code):
    report.add("Requests made (all read-only)", "\n".join(es.requests_made))
    text = report.render()
    with open(REPORT_FILENAME, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    log(f"\nReport written to {os.path.abspath(REPORT_FILENAME)}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
