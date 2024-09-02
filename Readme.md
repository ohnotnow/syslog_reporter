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

### Example

```bash
python main.py --file /var/log/syslog --resolutions
```

This will analyze `/var/log/syslog`, generate a report, and include suggested resolutions in the output.

## Output

The tool generates a markdown report in the format `report_YYYY-MM-DD.md`, where `YYYY-MM-DD` corresponds to the date of the report generation. The report includes:

- A summary of identified critical issues.
- Example log entries.
- Affected hosts and services.
- Recommendations for further investigation and resolution (if `--resolutions` flag is used).
- The approximate cost of the API calls used for the analysis.

### Filtering logs

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

## License

MIT License. You can use, modify, and distribute this software under the terms of the MIT license.
