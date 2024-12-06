import sys
import json
from gepetto import gpt, response
import logreader
from windows_overrides import ignore_list, match_list, replacement_map, regex_ignore_list
system_prompt = """
Analyze this system log entry and respond in JSON format with the following:
1. importance: Rate importance from 0-10 where:
   - 0-2: Routine/noise (e.g., successful service starts, routine USB connections)
   - 3-5: Minor issues or warnings
   - 6-8: Significant issues requiring attention
   - 9-10: Critical issues requiring immediate action
2. reason: Brief explanation of the rating
3. suggested_regex: A simple Python regex pattern to match similar log entries (or null if not appropriate).  The regex will be used to filter the log
entries by our log filtering system so should be as simple as possible - you can ignore things like timestamps, hostnames, PID's etc.  Think more '<service>.+<some_other_text>' rather than '^\\d{{4}}-\\d{{2}}-\\d{{2}} \\d{{2}}:\\d{{2}}:\\d{{2}} <hostname> <service> .+'
4. category: One of [noise, warning, error, security, performance, hardware, network, other]

Log entry to analyze:
{line}

Respond only with valid JSON matching this structure:
{{
    "importance": <0-10>,
    "reason": "<explanation>",
    "original_line": "<original line>",
    "suggested_regex": "<regex or null>",
    "category": "<category>"
}}

Additional guidelines:
- Log lines which seem unexplained or mysterious should be rated as important so that a human can investigate them.
"""

def classify_log_line(line: str, bot: gpt.GPTModelSync) -> response.ChatResponse:
    llm_response = bot.chat(messages=[{"role": "user", "content": system_prompt.format(line=line)}], json_format=True)
    return llm_response

if __name__ == "__main__":
    bot = gpt.GPTModelSync(model=gpt.Model.GPT_4_OMNI_MINI.value[0])

    lines = logreader.read_logfile(sys.stdin, ignore_list, match_list, replacement_map, regex_ignore_list)
    noise_regex = []
    for line in lines:
        chat_response = classify_log_line(line, bot)
        print(chat_response.message)
        message = chat_response.message.replace("```json", "").replace('```', '').strip()
        try:
            decoded = json.loads(message)
            if (decoded["category"] == "noise" or decoded["importance"] < 3) and decoded["suggested_regex"]:
                noise_regex.append(decoded["suggested_regex"])
        except json.JSONDecodeError:
            print(f"Boo", file=sys.stderr)
    for reg in noise_regex:
        print(f"    r'{reg}',")
