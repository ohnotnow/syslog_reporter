from gepetto import gpt
from datetime import datetime
import re
from collections import defaultdict
import argparse
import sys
import tiktoken

bot = gpt.GPTModelSync()
bot.model = gpt.Model.GPT_4_OMNI_MINI.value[0]

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

def read_logfile(file, ignore_list) -> list[str]:
    if file == sys.stdin:
        lines = file.read().splitlines()
    else:
        with open(file, 'r') as f:
            lines = f.read().splitlines()

    lines = [line for line in lines if not any(ignore in line for ignore in ignore_list)]
    return lines

def scan_logfile(lines: list[str], log_scan_prompt: str) -> tuple[str, float]:
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
    response = bot.chat(messages, model=gpt.Model.GPT_4_OMNI_MINI.value[0], temperature=0.1)
    report = response.message
    report = report.replace("```", "")
    return report, response.cost

def get_resolutions(report_text: str, resolution_prompt: str) -> tuple[str, float]:
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
    response = bot.chat(messages, model=gpt.Model.GPT_4_OMNI_0806.value[0], temperature=0.1)
    suggestions = response.message
    suggestions = suggestions.removesuffix('```')
    suggestions = suggestions.removeprefix('```')

    return suggestions, response.cost

def get_log_stats(lines, model=gpt.Model.GPT_4_OMNI_MINI.value[0]) -> tuple[int, int]:
    enc = tiktoken.encoding_for_model(model)
    return len(lines), len(enc.encode("\n".join(lines)))

def main(file, resolutions, dry_count, remove_duplicates, config_file):
    if file == "":
        file = sys.stdin

    try:
        if config_file.endswith(".py"):
            config_file = config_file[:-3]
        config = __import__(config_file)
    except ImportError as e:
        print(f"Error: Failed to import config file {config_file}")
        print(e)
        sys.exit(1)

    log_contents = read_logfile(file, config.ignore_list)
    if remove_duplicates:
        filtered_logs = filter_duplicate_logs(log_contents, max_occurrences=3)
    else:
        filtered_logs = log_contents

    if dry_count:
        log_length, token_length = get_log_stats(filtered_logs)
        print(f"Length: {log_length} lines")
        print(f"Tokens: {token_length} tokens")
        return

    report, cost = scan_logfile(filtered_logs, config.log_scan_prompt)

    suggestions_cost = 0
    if resolutions:
        suggestions, suggestions_cost = get_resolutions(report, config.resolution_prompt)
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
    parser.add_argument("--config-file", type=str, required=False, default="prompts")
    args = parser.parse_args()
    main(args.file, args.resolutions, args.dry_count, args.remove_duplicates, args.config_file)
