import re
import sys
from collections import defaultdict

def normalize_log_line(line, normalise_map):
    normalized_line = line

    # Normalise the line using the local normalise_map - return early if a match/replacement is done
    for pattern, replacement in normalise_map:
        if re.search(pattern, normalized_line):
            return replacement

    # Remove timestamps at the start - handles both traditional syslog and systemd journal formats
    normalized_line = re.sub(
        r'^(?:\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2}|'
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})',
        '',
        line
    ).strip()

    # Extract hostname
    match = re.match(r'^(\S+)', normalized_line)
    hostname = match.group(1) if match else 'UNKNOWN_HOST'
    normalized_line = normalized_line[len(hostname):].strip()

    # Remove process IDs in square brackets
    normalized_line = re.sub(r'\[\d+\]', '[]', normalized_line)

    # General number normalization
    normalized_line = re.sub(r'\b\d+\b', 'N', normalized_line)

    # Normalize hexadecimal addresses
    normalized_line = re.sub(r'0x[0-9a-fA-F]+', '0xADDRESS', normalized_line)
    normalized_line = re.sub(r'(?<=\s)[0-9a-fA-F]{9,16}(?=\s|$)', 'ADDRESS', normalized_line)

    # Normalize IPv4 addresses
    normalized_line = re.sub(
        r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
        'IP_ADDR',
        normalized_line
    )

    # Handle specific patterns:

    # 1. USB Device Messages
    if 'kernel:' in normalized_line and ('input:' in normalized_line or 'hid-generic' in normalized_line):
        if 'USB HID v' in normalized_line:
            normalized_line = f'{hostname} USB HID connect'
        else:
            normalized_line = f'{hostname} USB HID disconnect'
        return normalized_line  # Return early since we have the desired format

    # 2. Docker Daemon Messages
    if 'dockerd' in normalized_line:
        # Normalize node IDs, network IDs, and timestamps
        normalized_line = re.sub(r'\([0-9a-f]{12}\)', '(NODE_ID)', normalized_line)
        normalized_line = re.sub(r'netID:[0-9a-z]{24}', 'netID:NETWORK_ID', normalized_line)
        normalized_line = re.sub(r'netPeers:N+', 'netPeers:N', normalized_line)
        normalized_line = re.sub(r'entries:N+', 'entries:N', normalized_line)
        normalized_line = re.sub(r'Queue qLen:N+', 'Queue qLen:N', normalized_line)
        normalized_line = re.sub(r'netMsg/s:N+', 'netMsg/s:N', normalized_line)
        normalized_line = re.sub(r'time="[^"]+"', 'time="TIMESTAMP"', normalized_line)
        # Simplify message
        normalized_line = f'{hostname} Docker daemon network stats'
        return normalized_line  # Return early

    # 4. AppArmor audit logs
    if 'apparmor="STATUS"' in normalized_line:
        normalized_line = re.sub(r'audit\(N\.N:N+\)', 'audit(TIMESTAMP)', normalized_line)
        normalized_line = re.sub(r'pid=N', 'pid=N', normalized_line)
        normalized_line = re.sub(r'name="[^"]+"', 'name="APP"', normalized_line)
        normalized_line = re.sub(r'profile="[^"]+"', 'profile="PROFILE"', normalized_line)
        normalized_line = re.sub(r'comm="[^"]+"', 'comm="COMMAND"', normalized_line)

    # 5. Snap-related systemd logs with UUIDs
    normalized_line = re.sub(
        r'(snap\.[\w-]+\.hook\.[a-z-]+)-[0-9a-fA-F-]{36}',
        r'\1-UUID',
        normalized_line
    )
    normalized_line = re.sub(
        r'snap\.canonical-livepatch\.canonical-livepatch-[\da-f-]+\.scope',
        'snap.canonical-livepatch.canonical-livepatch-UUID.scope',
        normalized_line
    )

    # 6. Chrome singleton socket errors
    if 'Chrome' in normalized_line and 'SingletonSocket' in normalized_line:
        normalized_line = re.sub(
            r'/tmp/\.com\.google\.Chrome\.[A-Za-z0-9]+/SingletonSocket',
            '/tmp/.com.google.Chrome.XXXXXX/SingletonSocket',
            normalized_line
        )

    # 7. Ansible logs (keep only errors)
    if 'python3' in normalized_line and 'ansible-' in normalized_line:
        if 'ERROR' in normalized_line or 'Failed' in normalized_line:
            # Keep error logs, normalize them
            parts = normalized_line.split('Invoked with')[0].strip()
            normalized_line = parts + ' ERROR_MESSAGE'
        else:
            # Skip non-error ansible logs
            return ''  # Return empty string to exclude this line

    # 8. Postfix logs
    if any(x in normalized_line for x in ['postfix/smtpd', 'postfix/cleanup', 'postfix/qmgr', 'postfix/local']):
        # Normalize queue IDs
        normalized_line = re.sub(r'\b[A-F0-9]{8,11}\b', 'QUEUE_ID', normalized_line)
        # Normalize email addresses while keeping domain
        normalized_line = re.sub(r'<[^@>]+@([^>]+)>', r'<USER@\1>', normalized_line)
        # Normalize size and delay values
        normalized_line = re.sub(r'size=N+', 'size=N', normalized_line)
        normalized_line = re.sub(r'delay=[\d.]+', 'delay=N', normalized_line)
        normalized_line = re.sub(r'delays=[\d./]+', 'delays=N', normalized_line)
        # Normalize client hostnames and IPs
        normalized_line = re.sub(r'from=<[^>]+>', 'from=ADDRESS', normalized_line)
        normalized_line = re.sub(r'to=<[^>]+>', 'to=ADDRESS', normalized_line)
        normalized_line = re.sub(
            r'(from|disconnect from|connect from) \S+\[IP_ADDR\]',
            r'\1 CLIENT_HOST[IP_ADDR]',
            normalized_line
        )
        # Normalize helo=<...>
        normalized_line = re.sub(r'helo=<[^>]+>', 'helo=<HELO>', normalized_line)
        # Normalize protocol
        normalized_line = re.sub(r'proto=\S+', 'proto=PROTOCOL', normalized_line)

    # 9. Apache/Service status logs
    if '.service' in normalized_line:
        # Normalize memory and CPU time reports
        normalized_line = re.sub(
            r'Consumed N+h N+min [\d.]+s CPU time, [\d.]+[KMGT]?B memory peak, [\d.]+[KMGT]?B memory swap peak\.',
            'Consumed CPU_TIME, MEMORY peak, SWAP peak.',
            normalized_line
        )
        # Normalize process kills
        normalized_line = re.sub(
            r'Killing process N \([^)]+\) with signal \S+\.',
            'Killing process N (PROCNAME) with signal SIGNAL.',
            normalized_line
        )

    # 10. UFW BLOCK lines
    if '[UFW BLOCK]' in normalized_line:
        parts = normalized_line.split()
        normalized_line = ' '.join([
            p for p in parts
            if not any(p.startswith(prefix + '=') for prefix in ['ID', 'MAC', 'LEN', 'TTL'])
        ])

    # 11. Service management messages
    normalized_line = re.sub(
        r'(Starting|Stopping|Stopped|Started|Deactivated|Finished) \S+\.service(?: - .*)?',
        r'\1 SERVICE',
        normalized_line
    )
    normalized_line = re.sub(r'\S+\.service: (.*)', r'SERVICE: \1', normalized_line)

    # 12. Replace specific file paths and version numbers
    normalized_line = re.sub(
        r'/usr/lib/php/\d+\.\d+/',
        '/usr/lib/php/VERSION/',
        normalized_line
    )

    # 13. Normalize 'php_invoke' messages
    normalized_line = re.sub(
        r'php_invoke \S+: already enabled for PHP N+\.\d+ \S+ sapi',
        'php_invoke MODULE: already enabled for PHP VERSION SAPI',
        normalized_line
    )

    # 14. MariaDB Access Denied logs
    if 'Access denied for user' in normalized_line:
        normalized_line = re.sub(
            r"Access denied for user '[^']+'@'[^']+'",
            "Access denied for user 'USER'@'HOST'",
            normalized_line
        )
        normalized_line = re.sub(
            r'\(using password: (YES|NO)\)',
            '(using password: YES/NO)',
            normalized_line
        )

    # 15. Firefox warnings
    if 'firefox' in normalized_line:
        normalized_line = re.sub(
            r'\[Parent N+, Main Thread\]',
            '[Parent N, Main Thread]',
            normalized_line
        )
        normalized_line = re.sub(
            r'nsSigHandlers\.cpp:N+',
            'nsSigHandlers.cpp:N',
            normalized_line
        )
        normalized_line = re.sub(
            r'session/\d+_\d+/firefox_com_\w+_\w+_\d+',
            'session/ID/firefox_com_MODULE_MODULE_ID',
            normalized_line
        )
        normalized_line = re.sub(
            r'Object does not exist at path “[^”]+”',
            'Object does not exist at path "PATH"',
            normalized_line
        )

    # 16. Kernel messages
    if 'kernel:' in normalized_line:
        # Normalize numbers in brackets
        normalized_line = re.sub(r'\[N+\.N+\]', '[N.N]', normalized_line)
        # Normalize process names with PIDs
        normalized_line = re.sub(r'(\w+)\[\d+\]:', r'\1[]:', normalized_line)
        # Normalize memory addresses
        normalized_line = re.sub(r'at ADDRESS', 'at ADDRESS', normalized_line)
        normalized_line = re.sub(r'ip ADDRESS', 'ip ADDRESS', normalized_line)
        normalized_line = re.sub(r'sp ADDRESS', 'sp ADDRESS', normalized_line)
        normalized_line = re.sub(r'in [^ ]+\[ADDRESS\+N+\]', 'in MODULE[ADDRESS+N]', normalized_line)
        # Normalize error codes
        normalized_line = re.sub(r'error N', 'error N', normalized_line)

    # 17. Clean up multiple spaces
    normalized_line = re.sub(r'\s+', ' ', normalized_line.strip())

    # Return the normalized line with the hostname
    return f'{hostname} {normalized_line}'

def filter_duplicate_logs(log_lines, max_occurrences=3, normalise_map=[]):
    occurrence_dict = defaultdict(int)
    filtered_logs = []

    for line in log_lines:
        normalized_line = normalize_log_line(line, normalise_map)

        if occurrence_dict[normalized_line] < max_occurrences:
            filtered_logs.append(line)
            occurrence_dict[normalized_line] += 1
    # final removal of some token-heavy lines
    for line in filtered_logs:
        if re.search(r'snap.+store.+error', line):
            filtered_logs.remove(line)
            truncated_line = line[:100] + "..."
            filtered_logs.append(truncated_line)
    return filtered_logs

def read_logfile(file, ignore_list, match_list, replacement_map, regex_ignore_list = []) -> list[str]:
    if file == sys.stdin:
        lines = file.read().splitlines()
    else:
        with open(file, 'r') as f:
            lines = f.read().splitlines()

    # Remove empty lines
    lines = [line for line in lines if line.strip() != ""]

    if len(ignore_list) > 0:
        # print(f"Ignoring: {ignore_list}", file=sys.stderr)
        lines = [line for line in lines if not any(ignore in line for ignore in ignore_list)]
    if len(regex_ignore_list) > 0:
        # print(f"Ignoring regex: {regex_ignore_list}", file=sys.stderr)
        lines = [line for line in lines if not any(re.search(ignore, line) for ignore in regex_ignore_list)]
    if len(match_list) > 0:
        lines = [line for line in lines if any(match in line for match in match_list)]
    lines = [line.replace(k, v) for k, v in replacement_map.items() for line in lines]
    return lines
