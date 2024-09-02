from gepetto import gpt
from datetime import datetime
import re
from collections import defaultdict
import argparse
import sys
import tiktoken

bot = gpt.GPTModelSync()
bot.model = gpt.Model.GPT_4_OMNI_MINI.value[0]

ignore_list = [
    "arpwatch: bogon",
    "unknown client",
    "vmmon: Hello",
    "USB disconnect",
]

log_scan_prompt = """
# System Log Analysis Prompt

You are an AI assistant specializing in system log analysis. Your task is to analyze the provided syslog data and generate a concise summary of critical issues. Focus on high-priority problems that require immediate attention from system administrators.

## Analysis Steps

1. Identify critical issues such as:
   - Security breaches or attempts
   - Service failures or crashes
   - Resource exhaustion (CPU, memory, disk space)
   - Network connectivity problems
   - Authentication failures
   - Unusual system behavior

2. For each critical issue identified, provide:
   - A brief description of the problem
   - An exact copy of at least one relevant log entry that exemplifies the issue
   - The affected hostname and service (use **bold** for emphasis)
   - Timestamp or frequency of occurrence
   - Potential impact on system operations
   - If multiple hosts are affected, mention this and provide an example from one specific host

3. Highlight host-specific issues:
   - Clearly indicate when an issue is related to specific hosts
   - Provide the exact hostname(s) involved

4. Suggest possible next steps or areas for further investigation

5. If no critical issues are found, state this clearly and mention any notable patterns or trends

## Response Format

- Use a clear, bullet-point format for your analysis
- For each issue, structure your response as follows:

```
- Issue: [Brief title of the issue]
  - Description: [Concise explanation of the problem]
  - Example log entry: `[Exact copy of a relevant log entry]`
  - Affected host(s): **[Hostname(s)]**
  - Affected service: **[Service name]**
  - Timestamp/Frequency: [When or how often the issue occurs]
  - Potential impact: [Brief description of possible consequences]
  - Recommended action: [Suggested next steps for investigation or resolution]
```

## Important Notes

- Always include specific examples from the log data for each issue identified
- Avoid generalizations; instead, provide concrete details and exact log entries
- If an issue affects multiple hosts, explicitly state this and provide an example from one specific host
- Ensure that your analysis is actionable by including specific hostnames, services, and timestamps

Remember, specific examples and exact log entries are crucial for effective troubleshooting. Prioritize providing these details in your analysis.
"""

resolution_prompt = """
You are an AI assistant providing expert-level Linux system administration advice. Your task is to analyze issues identified from system logs and offer concise, actionable resolutions. Your audience consists of highly experienced Linux system administrators who require brief, direct information without extensive explanations.

## Input
You will receive a list of issues identified from system logs, including brief descriptions, example log entries, affected hosts/services, and potential impacts.

## Task
For each issue:
1. Provide a concise analysis of the root cause
2. Offer a brief, step-by-step resolution plan
3. Suggest specific Linux commands for investigation or resolution
4. If applicable, mention quick preventive measures

## Output Format
For each issue, structure your response as follows:

```
### [Issue Title]

Root Cause: [One-sentence analysis]

Fix:
1. [Concise step]
2. [Concise step]
   ```
   [Relevant command if applicable]
   ```
3. [Concise step]

Investigate: `[Single most useful investigation command]`

Prevent: [Brief prevention tip, if applicable]
```

## Guidelines:
- Assume high expertise; omit basic explanations
- Limit each section to 1-2 lines max
- Provide only the most critical commands
- Focus on immediate, practical solutions
- Mention service restarts or reboots only if absolutely necessary
- Omit general advice; focus on issue-specific information
- The primary Linux system in use is CentOS or Rocky Linux, so use their syntax and conventions unless it is clear that the system is
an alternative such as Ubuntu or Debian.

Remember, brevity is key. Provide only what an expert sysadmin needs to quickly address the issue.
"""


def normalize_log_line(line):
    # Remove timestamps and device numbers to normalize the line
    normalized_line = re.sub(r'\b\d+\b', '', line)  # Remove any numbers (timestamps, device numbers, etc.)
    normalized_line = re.sub(r'\s+', ' ', normalized_line.strip())  # Normalize whitespaces
    return normalized_line

def filter_duplicate_logs(log_lines, max_occurrences=3):
    occurrence_dict = defaultdict(int)
    filtered_logs = []

    for line in log_lines:
        normalized_line = normalize_log_line(line)

        if occurrence_dict[normalized_line] < max_occurrences:
            filtered_logs.append(line)
            occurrence_dict[normalized_line] += 1

    return filtered_logs

def read_logfile(file) -> list[str]:
    if file == sys.stdin:
        lines = file.read().splitlines()
    else:
        with open(file, 'r') as f:
            lines = f.read().splitlines()

    lines = [line for line in lines if not any(ignore in line for ignore in ignore_list)]
    return lines

def scan_logfile(lines) -> tuple[str, float]:
    content = "\n".join(lines)

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
    response = bot.chat(messages, model=gpt.Model.GPT_4_OMNI_MINI.value[0])
    report = response.message
    report = report.replace("```", "")
    return report, response.cost

def get_resolutions(report_text: str) -> tuple[str, float]:
    messages = [
        {
            "role": "system",
            "content": resolution_prompt
        },
        {
            "role": "user",
            "content": report_text
        }
    ]
    response = bot.chat(messages, model=gpt.Model.GPT_4_OMNI_0806.value[0])
    suggestions = response.message
    suggestions = suggestions.removesuffix('```')
    suggestions = suggestions.removeprefix('```')

    return suggestions, response.cost

def get_log_length(lines, model=gpt.Model.GPT_4_OMNI_MINI.value[0]) -> tuple[int, int]:
    enc = tiktoken.encoding_for_model(model)
    return len(lines), len(enc.encode("\n".join(lines)))

def main(file, resolutions, dry_count, remove_duplicates):
    if file == "":
        file = sys.stdin

    log_contents = read_logfile(file)
    if remove_duplicates:
        filtered_logs = filter_duplicate_logs(log_contents, max_occurrences=3)
    else:
        filtered_logs = log_contents

    if dry_count:
        log_length, token_length = get_log_length(filtered_logs)
        print(f"Length: {log_length} lines")
        print(f"Tokens: {token_length} tokens")
        return

    report, cost = scan_logfile(filtered_logs)

    suggestions_cost = 0
    if resolutions:
        suggestions, suggestions_cost = get_resolutions(report)
        report += f"\n\n## Suggestions\n\n{suggestions}"

    today_string = datetime.now().strftime("%Y-%m-%d")
    with open(f'report_{today_string}.md', 'w') as file:
        file.write(f"# Syslog Report for {today_string}\n\n{report}\n\n")
        file.write(f"_Cost: US${cost + suggestions_cost:.3f}_\n\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, required=False, default="")
    parser.add_argument("--resolutions", action="store_true", required=False, default=False)
    parser.add_argument("--dry-count", action="store_true", required=False, default=False)
    parser.add_argument("--remove-duplicates", action="store_true", required=False, default=False)
    args = parser.parse_args()
    main(args.file, args.resolutions, args.dry_count, args.remove_duplicates)
