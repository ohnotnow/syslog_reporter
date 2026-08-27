import os
import re
from collections import defaultdict
from .log_filters import ignore_list, regex_ignore_list, normalise_map


class LogFilterAgent:
    def __init__(self, lines, knowns=None):
        self.lines = lines
        # Optional KnownKnowns (see known_knowns.py): operator-acknowledged
        # estate oddities, dropped host-aware before the general ignores.
        self.knowns = knowns
        # Estate-specific ignore substrings (hostnames, internal IPs, local
        # usernames) live in the environment, not in this public codebase:
        # SYSLOG_BLANKET_IGNORE is a comma-separated list treated exactly
        # like ignore_list entries.
        self.blanket_ignores = [
            t.strip() for t in os.getenv("SYSLOG_BLANKET_IGNORE", "").split(",")
            if t.strip()
        ]

    def run(self):
        lines = self.remove_known_lines(self.lines)
        lines = self.remove_ignored_lines(lines)
        lines = self.remove_regex_ignored_lines(lines)
        lines = self.normalise_lines(lines)
        lines = self.remove_duplicates(lines)
        return lines

    def remove_known_lines(self, lines):
        # First step so the per-entry hit counts reflect the raw line volume,
        # before the general ignores and the dedupe cap thin things out.
        if self.knowns is None:
            return lines
        kept = []
        for line in lines:
            # Syslog format: "Month Day Time hostname message"
            parts = line.split(None, 4)
            if len(parts) >= 5 and self.knowns.line_ignored(parts[3], parts[4]):
                continue
            kept.append(line)
        return kept

    def remove_ignored_lines(self, lines):
        ignores = ignore_list + self.blanket_ignores
        return [line for line in lines if not any(ignore in line for ignore in ignores)]

    def remove_regex_ignored_lines(self, lines):
        return [line for line in lines if not any(re.search(regex, line) for regex in regex_ignore_list)]

    def normalise_lines(self, lines):
        normalised_lines = []
        for line in lines:
            normalised_line = line
            for regex, replacement in normalise_map:
                if re.search(regex, normalised_line):
                    # example line: Nov  8 12:48:51 travis firefox[37746]: OnCloseSessionDone error:
                    # we want to normalise it to: Nov  8 12:48:51 travis replacement
                    parts = normalised_line.split(None, 4)
                    if len(parts) >= 5:
                        # Keep timestamp and hostname, replace message with replacement
                        normalised_line = ' '.join(parts[:4]) + ' ' + replacement
                    else:
                        # If line doesn't match expected format, use whole replacement
                        normalised_line = replacement
                    break
            normalised_lines.append(normalised_line)
        return normalised_lines

    def remove_duplicates(self, lines):
        # ignoring the syslog timestamp, remove duplicate lines
        # Dictionary to count occurrences of each unique message
        message_counts = defaultdict(int)
        result_lines = []

        for line in lines:
            # Extract message part after syslog timestamp
            # Syslog format: "Month Day Time hostname message"
            # We'll split on the first 4 whitespace-separated parts to get the message
            parts = line.split(None, 4)
            if len(parts) >= 5:
                # Everything after hostname is the message
                message = parts[4]
            else:
                # If line doesn't match expected format, use the whole line
                message = line.strip()

            # Further normalise the message part to remove kernel timestamps
            # and pids ('CRON[12345]:') that make otherwise identical
            # messages appear unique
            normalised_message = re.sub(r"\[\d+\]", "", message)

            # Only keep up to 3 occurrences of each unique message
            if message_counts[normalised_message] < 3:
                message_counts[normalised_message] += 1
                result_lines.append(line)

        return result_lines
