#!/bin/bash

set -e

# check we have our syslog file argument
if [ -z "$1" ]; then
    echo "Usage: $0 <path tosyslog file>"
    exit 1
fi

SYSLOG_FILE=$1

# make sure the openai api key is set
if [ -z "$OPENAI_API_KEY" ]; then
    echo "OPENAI_API_KEY is not set"
    exit 1
fi

# Check if gdate is available; use it if so, otherwise use date (ie, avoid macos BSD date)
if command -v gdate >/dev/null 2>&1; then
    DATE_CMD="gdate"
else
    DATE_CMD="date"
fi

# Get yesterday's date in syslog format (e.g., "Nov  8")
yesterday=$($DATE_CMD --date="yesterday" +"%b %e")

export PATH=/opt/compiler/python-3.13/bin:$PATH
export LD_LIBRARY_PATH=/opt/compiler/python-3.13/lib:$LD_LIBRARY_PATH
source venv/bin/activate

# Now process the log file for yesterdays entries
egrep "^$yesterday" "$SYSLOG_FILE" | python main.py --file=
