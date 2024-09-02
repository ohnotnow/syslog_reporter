# Syslog Analysis Tool

This tool provides an automated system log analysis and resolution suggestion utility. It scans syslog files for critical issues, generates a detailed report, and optionally provides actionable resolutions for identified issues.

## Features

- **Critical Issue Identification**: Scans system logs for high-priority problems such as security breaches, service failures, resource exhaustion, network issues, and more.
- **Detailed Reports**: Generates a concise summary with specific log entries, affected hosts/services, timestamps, and potential impacts.
- **Resolution Suggestions**: Offers expert-level resolutions for identified issues, including root cause analysis, step-by-step fixes, and preventive measures.

## Installation

### Prerequisites

- Python 3.7 or higher
- OpenAI API key

### Setup

1. Clone the repository:
    ```bash
    git clone https://github.com/ohnotnow/syslog_reporter
    cd syslog_reporter
    ```

2. Create a virtual environment and activate it:

    **On MacOS and Ubuntu:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

    **On Windows:**
    ```bash
    python -m venv venv
    .\venv\Scripts\activate
    ```

3. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## Usage

You can use the tool by providing a syslog file as input. Optionally, you can enable resolution suggestions.

### Command-Line Interface

```bash
export OPENAI_API_KEY=<your_openai_api_key>
python main.py --file <path_to_syslog_file> [--resolutions]
```

- `--file`: Path to the syslog file you want to analyze. If omitted, the script will read from `stdin`.
- `--resolutions`: Include this flag to generate resolution suggestions for identified issues.
- `--dry-count`: Include this flag to get a token count for the log file and exit.
- `--remove-duplicates`: Include this flag to remove more than three copies of duplicate/similar log entries.

### Example

```bash
python main.py --file /var/log/syslog --resolutions
```

This will analyze `/var/log/syslog`, generate a report, and include suggested resolutions in the output.

To do a dry run and figure out how long your log data is, you can use the `--dry-count` flag:

```bash
$ python main.py --file /var/log/syslog --dry-count
Length: 187 lines
Tokens: 11341 tokens
```

You can also remove duplicate log entries using the `--remove-duplicates` flag to cut down on more noise:

```bash
$ python main.py --file /var/log/syslog --remove-duplicates
Length: 150 lines
Tokens: 7530 tokens
```

## Output

The tool generates a markdown report in the format `report_YYYY-MM-DD.md`, where `YYYY-MM-DD` corresponds to the date of the report generation. The report includes:

- A summary of identified critical issues.
- Example log entries.
- Affected hosts and services.
- Recommendations for further investigation and resolution (if `--resolutions` flag is used).
- The approximate cost of the API calls used for the analysis.

## Costs & Time

The following table provides _very_ approximate costs and processing times for analyzing a 1000-line log file (with the noise filtered out) using OpenAI GPT-4-Omni and GPT-4-Omni-Mini as of September 2024:

| Analysis Type | Approximate Cost (USD) | Approximate Time |
|---------------|------------------------|-------------------|
| Log report only | $0.002 | 10-15 seconds |
| Log report with resolutions | $0.01 | 15-20 seconds |

Please note that actual costs and processing times may vary depending on the specific content of your log files and any changes in API pricing.

## Filtering logs

As syslogs can fill up with repeated noise that's of no interest, you can save a lot of time and money by
filtering out common things you're not interested in.  At the top of `main.py` you'll see a list of things to ignore.
Feel free to modify this list to your liking.

```python
ignore_list = [
    "arpwatch: bogon",
    "unknown client",
    "vmmon: Hello",
    "USB disconnect",
]
```

## Notes

- The default prompts have wording in them to guide them to assume CentOS or Rocky Linux, so if you're using Ubuntu or Debian, you'll need to modify the prompts.
- Syslog output is very 'token heavy'.  The initial log scan can only handle so much data (currently about 128k tokens).  When I take a fairly random 1000 lines of syslog and filter out the noise leaving about 165 'real' lines, I get about 10,000 tokens.  You can use the `--dry-count` flag to get a token count for your log file and exit without doing the full analysis, which is handy for testing.  The `--remove-duplicates` flag can also help reduce the token count by removing more than three copies of duplicate/similar log entries.
- Remember you're passing your logs to OpenAI, so you may need to remove any sensitive information.


## License

MIT License. You can use, modify, and distribute this software under the terms of the MIT license.
