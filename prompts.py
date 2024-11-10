ignore_list = [
    "arpwatch: bogon",
    "unknown client",
    "vmmon: Hello",
    "USB disconnect",
    "Loading profiles",
    "Mounted snaps",
    "UFW",
    "'insightvm-",
    " insightvm-",
    "snapd.apparmor.service: Consumed",
    " 50-motd-news",
    "DHCPDISCOVER",
    "DHCPOFFER",
    "DHCPREQUEST",
    "DHCPACK",
]

regex_ignore_list = [
    r"postfix.*insightvm-",
    r'php.+already enabled',
    r'systemd.+Consumed',
    r'audit.+profile_replace',
    r'snap.+firefox',
    r'postfix.+ status=sent '
]

match_list = [
    # "nagios",
]

replacement_map = {
    "your-domain.com": "",
    "some-other-sensitive-thing": "***",
}

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
- For each issue, structure your response in JSON as follows:

{
    "issues": [
        {
            "issue": "[Brief title of the issue]",
            "description": "[Concise explanation of the problem]",
            "example_log_entry": "[Exact copy of a relevant log entry]",
            "affected_host(s)": "[Hostname(s)]",
            "affected_service": "[Service name]",
            "timestamp/frequency": "[When or how often the issue occurs]",
            "potential_impact": "[Brief description of possible consequences]",
            "recommended_action": "[Suggested next steps for investigation or resolution]"
        }
    ],
    ...
}

## Important Notes

- Always include specific examples from the log data for each issue identified
- Avoid generalizations; instead, provide concrete details and exact log entries
- If an issue affects multiple hosts, explicitly state this and provide an example from one specific host
- Ensure that your analysis is actionable by including specific hostnames, services, and timestamps
- If there are no critical issues, use the above format, but report the issues as "No critical issues found"
Remember, specific examples and exact log entries are crucial for effective troubleshooting. Prioritize providing these details in your analysis.
"""

log_merge_prompt = """
You will be given a list of Linux issues and the affected hosts.  Your task is to review the list and
return a JSON object with a series of issue ID's which refer to the same underlying issue and can be merged together.

Example Input:
```
{
    "issue_1": {
       "description": "Several hosts are timing out during Nagios checks, indicating potential connectivity issues or service unavailability.",
       "affected_host(s)": "**moody**",
       "example_log_entry": "Warning: Check of host 'moody.example.com' timed out after 30.00 seconds",
       "affected_service": "nagios",
    },
    "issue_2": {
        "description": "Hosts are reporting critical ping failures with 100% packet loss.",
        "affected_host(s)": "**brolly**",
        "example_log_entry": "Nov  8 00:00:00 puppet nagios: CURRENT HOST STATE: brolly.example.com;DOWN;HARD;10;PING CRITICAL - Packet loss = 100%",
        "affected_service": "Nagios Monitoring",
    },
    "issue_3": {
        "description": "SELinux is preventing certain operations due to permission issues on various hosts.",
        "affected_host(s)": "**little**",
        "example_log_entry": "SELinux is preventing some-command from execmem (use --p=execmem for partial execution) (18446744073709551615 enforcement) possible cause=unconfined_domain",
        "affected_service": "SELinux",
    },
    ...
}
```

Example Output:
```
{
    "merged_issues": [
        {
            "issue_ids": ["issue_1", "issue_2"],
            "affected_host(s)": "**moody**, **brolly**",
        },
        ...
    ]
}
```
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
- Issues can often have simple causes - don't over-engineer the solution.  For instance if a host is timing out when a check
from Nagios is run, it might just be that the host is switched off but someone forgot to update the nagios checks!

Remember, brevity is key. Provide only what an expert sysadmin needs to quickly address the issue.
"""
