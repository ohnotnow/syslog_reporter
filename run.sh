#!/bin/bash

set -e

# check we have our syslog file argument
if [ -z "$1" ]; then
    echo "Usage: $0 <path tosyslog file> [syslog format date string in quotes]"
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

# check if we have a 2nd argument, if we do use it as the date, otherwise use yesterday
if [ -z "$2" ]; then
    # Get yesterday's date in syslog format (e.g., "Nov  8")
    filter_date=$($DATE_CMD --date="yesterday" +"%b %e")
else
    filter_date=$2
fi

export PATH=/opt/compiler/python-3.13/bin:$PATH
export LD_LIBRARY_PATH=/opt/compiler/python-3.13/lib:$LD_LIBRARY_PATH
source venv/bin/activate

# now we check the log file for *any* matches for the date string
if egrep -m 1 "$filter_date" "$SYSLOG_FILE" >/dev/null; then
    egrep "^$filter_date" "$SYSLOG_FILE" | python main.py --file=
else
    echo "No matches found for '$filter_date' in $SYSLOG_FILE"
fi
