from gepetto import gpt
from datetime import datetime
import re
import os
import json
from collections import defaultdict
import argparse
import sys
import tiktoken

bot = gpt.GPTModelSync()
bot.model = gpt.Model.GPT_4_OMNI_MINI.value[0]



def normalize_log_line(line):
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

    # 3. Pulseaudio segfault messages
    if 'pulseaudio' in normalized_line and 'segfault' in normalized_line:
        normalized_line = re.sub(
            r'pulseaudio.+',
            'pulseaudio segfault',
            normalized_line
        )

    if re.search(r'setroubleshoot.+SELinux', normalized_line):
        normalized_line = "setroubleshoot: SELinux"

    if "gnome" in normalized_line and "DBusError" in normalized_line:
        normalized_line = "gnome-shell DBusError"

    if re.search(r'CCMP.+REPLAY', normalized_line):
        normalized_line = "CCMP_REPLAY"

    if re.search(r'BA.+FLUSH', normalized_line):
        normalized_line = "BA_FLUSH"

    if re.search(r'FLUSH.+DEAUTH', normalized_line):
        normalized_line = "FLUSH_DEAUTH"

    if re.search(r'service=registry', normalized_line):
        normalized_line = "docker service=registry"

    if re.search(r'snap-store.+not handling', normalized_line):
        normalized_line = "snap-store not handling"

    if re.search(r'acvpndownloader_major', normalized_line):
        normalized_line = "acvpndownloader_major"

    if re.search(r'acvpndownloader_minor', normalized_line):
        normalized_line = "acvpndownloader_minor"

    if re.search(r'xrdp', normalized_line):
        normalized_line = "xrdp"

    if re.search(r'puppet-agent.+(Could not|Failed|Unable|failed)', normalized_line):
        normalized_line = "puppet-agent Error"

    if re.search(r'InRelease', normalized_line):
        normalized_line = "InRelease Error"

    if re.search(r'audit:.+DENIED', normalized_line):
        normalized_line = "audit DENIED"

    if re.search(r'(acvpnui|acwebhelper|acvpndownloader|acvpnagent)', normalized_line):
        normalized_line = "acvpnui (CISCO VPN)"

    if re.search(r'puppet.+ensure changed.+corrective', normalized_line):
        normalized_line = "puppet ensure changed corrective"

    if re.search(r'snap.+store.+error', normalized_line):
        normalized_line = "snap-store not handling error"

    if "systemd" in normalized_line and re.match(r'run.docker.runtime', normalized_line) and "Succeeded" in normalized_line:
        normalized_line = "systemd run-docker-runtime Succeeded"

    if "Started snap" in normalized_line:
        normalized_line = "Started snap"

    if re.search(r'snap.canonical.*Succeeded', normalized_line):
        normalized_line = "snap.canonical Succeeded"

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

def filter_duplicate_logs(log_lines, max_occurrences=3):
    occurrence_dict = defaultdict(int)
    filtered_logs = []

    for line in log_lines:
        normalized_line = normalize_log_line(line)

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

def scan_logfile(lines: list[str], log_scan_prompt: str, log_merge_prompt: str, line_chunk_size: int = 1000) -> tuple[list[dict], float]:
    chunks = [lines[i:i+line_chunk_size] for i in range(0, len(lines), line_chunk_size)]
    if len(chunks) > 1:
        print(f"Long log file - splitting into {len(chunks)} chunks", file=sys.stderr)
    report = ""
    total_cost = 0
    issues = []
    for chunk in chunks:
        content = "\n".join(chunk)

        messages = [
            {
                "role": "system",
                "content": log_scan_prompt
            },
            {
                "role": "user",
                "content": content
            }
        ]
        response = bot.chat(messages, model=gpt.Model.GPT_4_OMNI_MINI.value[0], temperature=0.1, json_format=True)
        message = response.message.removeprefix("```json").removeprefix("```").removesuffix("```")
        issues.extend(json.loads(message)["issues"])
        total_cost += response.cost
    if len(chunks) > 0 and len(report) < 50000:
        json_issues = {}
        for id, issue in enumerate(issues):
            json_issues[f"issue_{id + 1}"] = {
                "description": issue["description"],
                "affected_host(s)": issue["affected_host(s)"],
                "example_log_entry": issue["example_log_entry"],
                "affected_service": issue["affected_service"],
            }
        messages = [
            {
                "role": "system",
                "content": log_merge_prompt
            },
            {
                "role": "user",
                "content": json.dumps(json_issues, indent=4)
            }
        ]
        response = bot.chat(messages, model=gpt.Model.GPT_4_OMNI_MINI.value[0], temperature=0.1, json_format=True)
        message = response.message.removeprefix("```json").removeprefix("```").removesuffix("```")
        merged_issues = json.loads(message)["merged_issues"]
        total_cost += response.cost
        final_issues = {}
        # first we need to copy the issues (a list) into the final_issues dict
        for issue_id, issue in enumerate(issues):
            final_issues[f"issue_{issue_id + 1}"] = issue
        # now we remove any issue_ id's that are in the merged issues, apart from the first one in each issue_ids fields
        for merged_issue in merged_issues:
            for issue_id in merged_issue["issue_ids"][1:]:
                if issue_id in final_issues:
                    del final_issues[issue_id]
        # now we merge the issues list to overwrite the affected_host(s)
        for merged_issue in merged_issues:
            for issue_id in merged_issue["issue_ids"]:
                if issue_id in final_issues:
                    final_issues[issue_id]["affected_host(s)"] = merged_issue["affected_host(s)"]
    return final_issues, total_cost

def issue_to_report(issue: dict) -> str:
    report = f"- Issue: {issue['issue']}\n"
    report += f"  - Description: {issue['description']}\n"
    report += f"  - Example log entry: {issue['example_log_entry']}\n"
    report += f"  - Affected host(s): {issue['affected_host(s)']}\n"
    report += f"  - Affected service: {issue['affected_service']}\n"
    report += f"  - Timestamp/Frequency: {issue['timestamp/frequency']}\n"
    report += f"  - Potential impact: {issue['potential_impact']}\n"
    report += f"  - Recommended action: {issue['recommended_action']}\n\n"
    return report

def issues_list_to_report(issues: dict) -> str:
    report = ""
    for issue in issues.values():
        report += issue_to_report(issue)
    return report

def get_resolution(issue: dict, resolution_prompt: str) -> tuple[str, float]:
    # clear the original LLM recommendation so that this call can come up with it's own
    # rather than just spelling out a plan based on the original recommendation
    issue['recommended_action'] = ""
    messages = [
        {
            "role": "system",
            "content": resolution_prompt
        },
        {
            "role": "user",
            "content": issue_to_report(issue)
        }
    ]
    response = bot.chat(messages, model=gpt.Model.GPT_4_OMNI_MINI.value[0], temperature=0.1)
    suggestion = response.message.removesuffix('```').removeprefix('```json`').removeprefix('```')

    return suggestion, response.cost

def resolutions_to_report(issues: list[dict], resolution_prompt: str) -> tuple[str, float]:
    report = ""
    total_cost = 0
    for issue in issues.values():
        resolution, cost = get_resolution(issue, resolution_prompt)
        report += f"{resolution}\n\n"
        total_cost += cost
    return report, total_cost

def get_log_stats(lines, model=gpt.Model.GPT_4_OMNI_MINI.value[0]) -> tuple[int, int]:
    enc = tiktoken.encoding_for_model(model)
    return len(lines), len(enc.encode("\n".join(lines)))

def check_file_args(file, output_file):
    """
    Check if the input or output file should be stdin/stdout
    """
    if file == "":
        file = sys.stdin
    if output_file == "":
        output_file = sys.stdout
    return file, output_file

def merge_configs(config, overrides):
    mergable_lists = ["ignore_list", "match_list", "regex_ignore_list"]
    for list_name in mergable_lists:
        if hasattr(overrides, list_name):
            setattr(config, list_name, list(set(getattr(config, list_name) + getattr(overrides, list_name))))
    mergeable_dicts = ["replacement_map"]
    for dict_name in mergeable_dicts:
        if hasattr(overrides, dict_name):
            getattr(config, dict_name).update(getattr(overrides, dict_name))
    prompt_attributes = ["log_scan_prompt", "resolution_prompt", "log_merge_prompt"]
    for prompt_name in prompt_attributes:
        if hasattr(overrides, prompt_name):
            setattr(config, prompt_name, getattr(overrides, prompt_name))
    return config

def load_config(config_file, overrides):
    try:
        if config_file.endswith(".py"):
            config_file = config_file[:-3]
        config = __import__(config_file)
        if os.path.exists(overrides):
            overrides_file = overrides[:-3] if overrides.endswith(".py") else overrides
            overrides = __import__(overrides_file)
            config = merge_configs(config, overrides)
    except ImportError as e:
        print(f"Error: Failed to import config file {config_file}")
        print(e)
        sys.exit(1)
    return config

def output_final_report(report, cost, suggestions_cost, output_file):
    today_string = datetime.now().strftime("%Y-%m-%d")
    number_of_issues = len(report.split("\n- Issue:")[1:])
    final_report = f"# Log Report for {today_string} ({number_of_issues} issues)\n\n{report}\n\n"
    final_report += f"_Cost: US${cost + suggestions_cost:.3f}_\n\n"
    if output_file == sys.stdout:
        print(final_report)
    else:
        with open(output_file, 'w') as file:
            file.write(final_report)

def main(file, resolutions, dry_count, remove_duplicates, config_file, output_file, show_log, overrides):
    file, output_file = check_file_args(file, output_file)

    config = load_config(config_file, overrides)

    log_contents = read_logfile(file, config.ignore_list, config.match_list, config.replacement_map, config.regex_ignore_list)
    if len(log_contents) == 0:
        print("No log entries found")
        return

    if remove_duplicates:
        log_contents = filter_duplicate_logs(log_contents, max_occurrences=3)

    if show_log:
        print("\n".join(log_contents))

    if dry_count:
        log_length, token_length = get_log_stats(log_contents)
        print(f"Length: {log_length} lines")
        print(f"Tokens: {token_length} tokens")
        return

    issues, cost = scan_logfile(log_contents, config.log_scan_prompt, config.log_merge_prompt)
    report = issues_list_to_report(issues)
    suggestions_cost = 0
    if resolutions and not "No critical issues found" in report:
        suggestions_report, suggestions_cost = resolutions_to_report(issues, config.resolution_prompt)
        report += f"\n\n## Suggestions\n\n{suggestions_report}"

    output_final_report(report, cost, suggestions_cost, output_file)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, required=False, default="")
    parser.add_argument("--output-file", type=str, required=False, default="")
    parser.add_argument("--resolutions", action="store_true", required=False, default=True)
    parser.add_argument("--dry-count", action="store_true", required=False, default=False)
    parser.add_argument("--remove-duplicates", action="store_true", required=False, default=True)
    parser.add_argument("--config-file", type=str, required=False, default="prompts")
    parser.add_argument("--show-log", action="store_true", required=False, default=False)
    parser.add_argument("--overrides", type=str, required=False, default="local_overrides.py")
    parser.add_argument("--issue-model", type=str, required=False, default=gpt.Model.GPT_4_OMNI_MINI.value[0])
    parser.add_argument("--suggestion-model", type=str, required=False, default=gpt.Model.GPT_4_OMNI_0806.value[0])
    args = parser.parse_args()
    main(args.file, args.resolutions, args.dry_count, args.remove_duplicates, args.config_file, args.output_file, args.show_log, args.overrides)
