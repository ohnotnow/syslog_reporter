from gepetto import gpt, gemini
from pydantic_ai import Agent, RunContext
from pydantic import BaseModel
from datetime import datetime
import costing
import time
import re
import os
import json
from collections import defaultdict
import argparse
import sys
import tiktoken
import logreader
import classifier
bot = gpt.GPTModelSync(model=gpt.Model.GPT_4_OMNI_MINI.value[0])
# bot = gemini.GeminiModelSync()

class Issue(BaseModel):
    issue: str = "Unknown"
    description: str = "Unknown"
    example_log_entry: str = "Unknown"
    affected_hosts: str = "Unknown"
    affected_service: str = "Unknown"
    timestamp_frequency: str = "Unknown"
    potential_impact: str = "Unknown"
    recommended_action: str = "Unknown"

class MergedIssue(BaseModel):
    issue_ids: list[str]
    affected_hosts: str = "Unknown"

class MergedIssueList(BaseModel):
    merged_issues: list[MergedIssue]

class IssueList(BaseModel):
    issues: list[Issue]

def scan_logfile(lines: list[str], log_scan_prompt: str, log_merge_prompt: str, line_chunk_size: int = 1000, model: str = gpt.Model.GPT_4_OMNI_MINI.value[0]) -> tuple[list[dict], float]:
    chunks = [lines[i:i+line_chunk_size] for i in range(0, len(lines), line_chunk_size)]
    if len(chunks) > 1:
        print(f"Long log file - splitting into {len(chunks)} chunks", file=sys.stderr)
    if not model.startswith("openai:"):
        model = f"openai:{model}"
    report = ""
    total_cost = 0
    issues = []
    final_issues = {}
    syslog_agent = Agent(
        model=model,
        result_type=IssueList,
        system_prompt=log_scan_prompt,
    )
    for chunk in chunks:
        content = "\n".join(chunk)
        response = syslog_agent.run_sync(content)
        issues.extend(response.data.issues)
        cost = costing.get_cost(model, response.cost())
        total_cost += cost
    if len(chunks) > 1 and len(report) < 50000:
        json_issues = {}
        for id, issue in enumerate(issues):
            json_issues[f"issue_{id + 1}"] = {
                "description": issue.description,
                "affected_host(s)": issue.affected_hosts,
                "example_log_entry": issue.example_log_entry,
                "affected_service": issue.affected_service,
            }
        merge_agent = Agent(
            model=model,
            result_type=MergedIssueList,
            system_prompt=log_merge_prompt,
        )
        merged_issues = merge_agent.run_sync(json.dumps(json_issues)).data.merged_issues
        cost = costing.get_cost(model, response.cost())
        total_cost += cost
        # first we need to copy the issues (a list) into the final_issues dict
        for issue_id, issue in enumerate(issues):
            final_issues[f"issue_{issue_id + 1}"] = issue
        # now we remove any issue_ id's that are in the merged issues, apart from the first one in each issue_ids fields
        for merged_issue in merged_issues:
            for issue_id in merged_issue.issue_ids[1:]:
                if issue_id in final_issues:
                    del final_issues[issue_id]
        # now we merge the issues list to overwrite the affected_host(s)
        for merged_issue in merged_issues:
            for issue_id in merged_issue.issue_ids[1:]:
                if issue_id in final_issues:
                    final_issues[issue_id]["affected_host(s)"] = merged_issue.affected_hosts
    if len(final_issues) == 0:
        # no issues were merged, so copy the original issues list into the final_issues dict
        for issue_id, issue in enumerate(issues):
            final_issues[f"issue_{issue_id + 1}"] = issue

    return final_issues, total_cost

def issue_to_report(issue: dict) -> str:
    report = f"- Issue: {issue.issue}\n"
    report += f"  - Description: {issue.description}\n"
    report += f"  - Example log entry: {issue.example_log_entry}\n"
    report += f"  - Affected host(s): {issue.affected_hosts}\n"
    report += f"  - Affected service: {issue.affected_service}\n"
    report += f"  - Timestamp/Frequency: {issue.timestamp_frequency}\n"
    report += f"  - Potential impact: {issue.potential_impact}\n"
    report += f"  - Recommended action: {issue.recommended_action}\n\n"
    return report

def issues_list_to_report(issues: dict) -> str:
    report = ""
    for issue in issues.values():
        report += issue_to_report(issue)
    return report

def get_resolution(issue: dict, resolution_prompt: str, suggestion_model: str = gpt.Model.GPT_4_OMNI_MINI.value[0]) -> tuple[str, float]:
    # clear the original LLM recommendation so that this call can come up with it's own
    # rather than just spelling out a plan based on the original recommendation
    if not suggestion_model.startswith("openai:"):
        suggestion_model = f"openai:{suggestion_model}"
    issue.recommended_action = ""
    resolution_agent = Agent(
        model=suggestion_model,
        result_type=str,
    )
    response = resolution_agent.run_sync(f"{resolution_prompt}\n\n{issue_to_report(issue)}")
    cost = costing.get_cost(suggestion_model, response.cost())
    suggestion = response.data
    suggestion = suggestion.removeprefix('```markdown').removeprefix('```').removesuffix('```')
    return suggestion, cost

def resolutions_to_report(issues: list[dict], resolution_prompt: str, suggestion_model: str = gpt.Model.GPT_4_OMNI_MINI.value[0]) -> tuple[str, float]:
    report = ""
    total_cost = 0
    for issue in issues.values():
        resolution, cost = get_resolution(issue, resolution_prompt, suggestion_model)
        report += f"{resolution}\n\n"
        total_cost += cost
    return report, total_cost

def get_log_stats(lines, model=gpt.Model.GPT_4_OMNI_MINI.value[0]) -> tuple[int, int]:
    if model.startswith("openai:"):
        model = model[len("openai:"):]
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
    mergable_lists = ["ignore_list", "match_list", "regex_ignore_list", "normalise_map"]
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

def output_final_report(report, cost, suggestions_cost, output_file, log_length, model, total_time, number_of_issues):
    today_string = datetime.now().strftime("%Y-%m-%d")
    seconds = round(total_time % 60)
    minutes = round((total_time // 60) % 60)
    final_report = f"# Log Report @ {today_string} ({number_of_issues} issues)\n\n{report}\n\n"
    final_report += f"_Cost: US${cost + suggestions_cost:.3f} for {log_length} processed lines using {model} in {minutes:02d}m {seconds:02d}s_\n\n"
    if output_file == sys.stdout:
        print(final_report)
    else:
        with open(output_file, 'w') as file:
            file.write(final_report)

def main(file, resolutions, dry_count, remove_duplicates, config_file, output_file, show_log, overrides, issue_model = gpt.Model.GPT_4_OMNI_MINI.value[0], suggestion_model = gpt.Model.GPT_4_OMNI_MINI.value[0]):
    start_time = time.time()
    file, output_file = check_file_args(file, output_file)

    config = load_config(config_file, overrides)

    log_contents = logreader.read_logfile(file, config.ignore_list, config.match_list, config.replacement_map, config.regex_ignore_list)
    if len(log_contents) == 0:
        print("No log entries found")
        return

    if remove_duplicates:
        log_contents = logreader.filter_duplicate_logs(log_contents, max_occurrences=3, normalise_map=config.normalise_map)

    if show_log:
        print("\n".join(log_contents))

    if dry_count:
        log_length, token_length = get_log_stats(log_contents, issue_model)
        print(f"Length: {log_length} lines")
        print(f"Tokens: {token_length} tokens")
        # for line in log_contents:
        #     response = classifier.classify_log_line(line, bot)
        #     print(response.message)
        #     print(response.cost)
        return

    issues, cost = scan_logfile(log_contents, config.log_scan_prompt, config.log_merge_prompt, model=issue_model)
    report = issues_list_to_report(issues)
    suggestions_cost = 0
    if resolutions and not "No critical issues found" in report:
        suggestions_report, suggestions_cost = resolutions_to_report(issues, config.resolution_prompt, suggestion_model=suggestion_model)
        report += f"\n\n## Suggestions\n\n{suggestions_report}"

    if issue_model != suggestion_model:
        used_model = f"{issue_model} (issues) and {suggestion_model} (suggestions)"
    else:
        used_model = issue_model
    end_time = time.time()
    total_time = end_time - start_time
    output_final_report(report, cost, suggestions_cost, output_file, len(log_contents), used_model, total_time, len(issues))

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
    parser.add_argument("--issue-model", type=str, required=False, default=f"openai:{gpt.Model.GPT_4_OMNI_MINI.value[0]}")
    parser.add_argument("--suggestion-model", type=str, required=False, default=f"openai:{gpt.Model.GPT_4_OMNI_1120.value[0]}")
    args = parser.parse_args()
    main(args.file, args.resolutions, args.dry_count, args.remove_duplicates, args.config_file, args.output_file, args.show_log, args.overrides, args.issue_model, args.suggestion_model)
