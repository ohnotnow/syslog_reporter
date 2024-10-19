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

def read_logfile(file, ignore_list, match_list) -> list[str]:
    if file == sys.stdin:
        lines = file.read().splitlines()
    else:
        with open(file, 'r') as f:
            lines = f.read().splitlines()

    # Remove empty lines
    lines = [line for line in lines if line.strip() != ""]

    if len(ignore_list) > 0:
        lines = [line for line in lines if not any(ignore in line for ignore in ignore_list)]
    if len(match_list) > 0:
        lines = [line for line in lines if any(match in line for match in match_list)]

    return lines

def scan_logfile(lines: list[str], log_scan_prompt: str, log_scan_review_prompt: str, line_chunk_size: int = 1000) -> tuple[str, float]:
    chunks = [lines[i:i+line_chunk_size] for i in range(0, len(lines), line_chunk_size)]
    if len(chunks) > 1:
        print(f"Long log file - splitting into {len(chunks)} chunks", file=sys.stderr)
    report = ""
    total_cost = 0
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
        response = bot.chat(messages, model=gpt.Model.GPT_4_OMNI_MINI.value[0], temperature=0.1)
        report += response.message
        report = report.replace("```", "")
        total_cost += response.cost
    if len(chunks) > 1 and len(report) < 50000:
        messages = [
            {
                "role": "system",
                "content": log_scan_review_prompt
            },
            {
                "role": "user",
                "content": report
            }
        ]
        response = bot.chat(messages, model=gpt.Model.GPT_4_OMNI_0806.value[0], temperature=0.1)
        report = response.message
        report = report.replace("```", "")
        total_cost += response.cost
    return report, total_cost

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

def check_file_args(file, output_file):
    """
    Check if the input or output file should be stdin/stdout
    """
    if file == "":
        file = sys.stdin
    if output_file == "":
        output_file = sys.stdout
    return file, output_file

def load_config(config_file):
    try:
        if config_file.endswith(".py"):
            config_file = config_file[:-3]
        config = __import__(config_file)
    except ImportError as e:
        print(f"Error: Failed to import config file {config_file}")
        print(e)
        sys.exit(1)
    return config

def output_final_report(report, cost, suggestions_cost, output_file):
    today_string = datetime.now().strftime("%Y-%m-%d")
    final_report = f"# Log Report for {today_string}\n\n{report}\n\n"
    final_report += f"_Cost: US${cost + suggestions_cost:.3f}_\n\n"
    if output_file == sys.stdout:
        print(final_report)
    else:
        with open(output_file, 'w') as file:
            file.write(final_report)

def main(file, resolutions, dry_count, remove_duplicates, config_file, output_file):
    file, output_file = check_file_args(file, output_file)

    config = load_config(config_file)

    log_contents = read_logfile(file, config.ignore_list, config.match_list)
    if len(log_contents) == 0:
        print("No log entries found")
        return

    if remove_duplicates:
        log_contents = filter_duplicate_logs(log_contents, max_occurrences=3)

    if dry_count:
        log_length, token_length = get_log_stats(log_contents)
        print(f"Length: {log_length} lines")
        print(f"Tokens: {token_length} tokens")
        return

    report, cost = scan_logfile(log_contents, config.log_scan_prompt, config.log_scan_review_prompt)

    suggestions_cost = 0
    if resolutions and not "No critical issues found" in report:
        suggestions, suggestions_cost = get_resolutions(report, config.resolution_prompt)
        report += f"\n\n## Suggestions\n\n{suggestions}"

    output_final_report(report, cost, suggestions_cost, output_file)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, required=False, default="")
    parser.add_argument("--output-file", type=str, required=False, default="")
    parser.add_argument("--resolutions", action="store_true", required=False, default=True)
    parser.add_argument("--dry-count", action="store_true", required=False, default=False)
    parser.add_argument("--remove-duplicates", action="store_true", required=False, default=True)
    parser.add_argument("--config-file", type=str, required=False, default="prompts")
    args = parser.parse_args()
    main(args.file, args.resolutions, args.dry_count, args.remove_duplicates, args.config_file, args.output_file)
