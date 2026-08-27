#!/usr/bin/env python3
"""Day-bounded NDJSON dump of syslog documents from Elasticsearch.

Pulls every document for ONE day from a syslog data stream (e.g.
'logs-system.syslog-<namespace>') and writes one trimmed JSON object
per line, keeping only the fields the syslog_reporter pipeline needs:

    @timestamp, host.name, host.hostname, process.name, process.pid, message

Usage (yesterday, the common case):

    python3 elk_dump.py --url https://elk.example.ac.uk:9200 \
        --username someuser --insecure \
        --index 'logs-system.syslog-<namespace>'

    python3 elk_dump.py ... --day 2026-08-26 --out syslog-2026-08-26.ndjson.gz

The day is bounded on BOTH sides (gte day, lt day+1, in --tz local
time), which also keeps out the future-dated documents that bad
RFC3164 year parsing can create around new year.

Pagination is a point-in-time (PIT) plus search_after, so the dump is
a consistent snapshot with no skipped or duplicated documents. The
account needs the 'read' index privilege (which includes PIT) on the
target pattern; no cluster privileges are used.

Auth and TLS conventions are the same as elk_recon.py: ELK_URL,
ELK_API_KEY or ELK_USERNAME/ELK_PASSWORD from env or a local .env, or
--key-file / --username (interactive password prompt). Credentials are
never printed. --insecure skips TLS verification, --ca-cert trusts a
local CA.

If --out ends in .gz the file is gzip-compressed (handy for scp).

This file is deliberately self-contained and stdlib-only: copy just
this one script to any box with python3 and it runs.
"""

import argparse
import base64
import getpass
import gzip
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

KEEP_FIELDS = [
    ("@timestamp",),
    ("host", "name"),
    ("host", "hostname"),
    ("host", "os", "name"),
    ("host", "os", "version"),
    ("host", "os", "family"),
    ("process", "name"),
    ("process", "pid"),
    ("message",),
]

PIT_KEEP_ALIVE = "5m"


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

    def request(self, method, path, body=None):
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


def trim(source):
    """Keep only the pipeline-relevant fields, flat with dotted keys."""
    out = {}
    for path in KEEP_FIELDS:
        value = source
        for part in path:
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        if value is not None:
            out[".".join(path)] = value
    return out


def http_detail(exc):
    detail = str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail += "\n" + exc.read().decode(errors="replace")[:2000]
        except OSError:
            pass
    return detail


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="Elasticsearch base URL (or ELK_URL in env/.env)")
    parser.add_argument("--index", default=os.environ.get("ELK_INDEX"),
                        help="index pattern or data stream to dump, e.g. "
                             "'logs-system.syslog-<namespace>' (or ELK_INDEX in env/.env)")
    parser.add_argument("--day", metavar="YYYY-MM-DD",
                        help="the day to dump (default: yesterday)")
    parser.add_argument("--tz", default="Europe/London",
                        help="timezone the day boundaries are interpreted in "
                             "(IANA name or +hh:mm offset, default Europe/London)")
    parser.add_argument("--out", metavar="FILE",
                        help="output file (default: syslog-<day>.ndjson; "
                             "a .gz suffix enables gzip compression)")
    parser.add_argument("--batch-size", type=int, default=5000,
                        help="documents per search request (max 10000)")
    parser.add_argument("--key-file", help="file whose first line is the API key "
                                           "(otherwise ELK_API_KEY from env/.env)")
    parser.add_argument("--username", help="basic-auth username (or ELK_USERNAME in env/.env; "
                                           "password from ELK_PASSWORD or an interactive prompt)")
    parser.add_argument("--insecure", action="store_true",
                        help="skip TLS certificate verification")
    parser.add_argument("--ca-cert", help="path to a CA certificate for a self-signed cluster")
    parser.add_argument("--timeout", type=int, default=60, help="per-request timeout, seconds")
    args = parser.parse_args()

    load_dotenv()
    url = args.url or os.environ.get("ELK_URL")
    if not url:
        parser.error("no URL: pass --url or set ELK_URL")
    if not args.index:
        parser.error("no index: pass --index or set ELK_INDEX")
    if not 0 < args.batch_size <= 10000:
        parser.error("--batch-size must be between 1 and 10000")
    auth_header, auth_desc = resolve_auth(args)
    if not auth_header:
        parser.error("no credentials: set ELK_API_KEY or ELK_USERNAME/ELK_PASSWORD "
                     "(env or .env), or pass --key-file / --username")

    day = args.day or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        parser.error(f"--day must be YYYY-MM-DD, got {day!r}")
    day_after = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    out_path = args.out or f"syslog-{day}.ndjson"

    query = {
        "range": {
            "@timestamp": {
                "gte": day,
                "lt": day_after,
                "format": "yyyy-MM-dd",
                "time_zone": args.tz,
            }
        }
    }

    es = EsClient(url, auth_header, args.timeout, insecure=args.insecure, ca_cert=args.ca_cert)
    log(f"dumping {args.index} for {day} ({args.tz}) as {auth_desc}")
    log(f"tls: {'VERIFICATION DISABLED' if args.insecure else 'verified'}")

    pit_path = "/" + urllib.parse.quote(args.index, safe="*,-_.") + \
               f"/_pit?keep_alive={PIT_KEEP_ALIVE}"
    try:
        pit_id = es.request("POST", pit_path)["id"]
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        log("FATAL: could not open a point-in-time on "
            f"{args.index}: {http_detail(exc)}")
        log("The account needs the 'read' index privilege on the pattern "
            "(check with GET /_security/user/_privileges).")
        sys.exit(2)

    written = 0
    total = None
    first_ts = last_ts = None
    search_after = None
    opener = gzip.open if out_path.endswith(".gz") else open
    try:
        with opener(out_path, "wt", encoding="utf-8") as fh:
            while True:
                body = {
                    "size": args.batch_size,
                    "query": query,
                    "pit": {"id": pit_id, "keep_alive": PIT_KEEP_ALIVE},
                    "sort": [{"@timestamp": "asc"}],
                    "track_total_hits": total is None,
                }
                if search_after:
                    body["search_after"] = search_after
                resp = es.request("POST", "/_search", body)
                pit_id = resp.get("pit_id", pit_id)
                if total is None:
                    total = resp.get("hits", {}).get("total", {}).get("value", 0)
                    log(f"documents in window: {total:,}")
                hits = resp.get("hits", {}).get("hits", [])
                if not hits:
                    break
                for hit in hits:
                    doc = trim(hit.get("_source", {}))
                    fh.write(json.dumps(doc, ensure_ascii=False) + "\n")
                    ts = doc.get("@timestamp")
                    if ts:
                        first_ts = first_ts or ts
                        last_ts = ts
                written += len(hits)
                search_after = hits[-1]["sort"]
                log(f"  fetched {written:,} / {total:,}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log(f"FATAL after {written:,} documents: {http_detail(exc)}")
        log(f"partial output left in {out_path}")
        sys.exit(2)
    finally:
        try:
            es.request("DELETE", "/_pit", {"id": pit_id})
        except (urllib.error.URLError, OSError, ValueError):
            log("warning: could not close the point-in-time "
                f"(it expires on its own after {PIT_KEEP_ALIVE})")

    searches = sum(1 for r in es.requests_made if r.startswith("POST /_search"))
    log(f"\nwrote {written:,} documents to {os.path.abspath(out_path)} "
        f"({os.path.getsize(out_path):,} bytes)")
    if first_ts:
        log(f"timestamps {first_ts} .. {last_ts}")
    log(f"requests: 1 PIT open, {searches} searches, 1 PIT close (all read-only)")
    if written != total:
        log(f"warning: expected {total:,} documents but wrote {written:,}")
        sys.exit(1)


if __name__ == "__main__":
    main()
