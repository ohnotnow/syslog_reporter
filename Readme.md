# Syslog Analysis Tool

This tool provides an automated system log analysis and resolution suggestion utility. It scans syslog files for critical issues, generates a detailed report, and optionally provides actionable resolutions for identified issues.

## Features

- **Critical Issue Identification**: Scans system logs for high-priority problems such as security breaches, service failures, resource exhaustion, network issues, and more.
- **Detailed Reports**: Generates a concise summary with specific log entries, affected hosts/services, timestamps, and potential impacts.
- **Resolution Suggestions**: Offers expert-level resolutions for identified issues, including root cause analysis, step-by-step fixes, and preventive measures.
- **Customization**: Allows for easy customization of ignore and match lists and system prompts to tailor the analysis to specific environments or requirements.

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

You can use the tool by providing a syslog file as input. You can also pass various flags and a custom config file to override the default behaviour of the script.

### Command-Line Interface

```bash
export OPENAI_API_KEY=<your_openai_api_key>
python main.py --file <path_to_syslog_file>
```

- `--file`: Path to the syslog file you want to analyze. If omitted, the script will read from `stdin`.
- `--output-file`: Path to the output file. If omitted, the script will write to `stdout`.
- `--resolutions`: Set this flag to false to skip generating resolution suggestions for identified issues. Defaults to `True`.
- `--dry-count`: Include this flag to get a token count for the log file and exit.
- `--remove-duplicates`: Set this flag to false to skip removing more than three copies of duplicate/similar log entries. Defaults to `True`.
- `--show-log`: Set this flag to true to print the (filtered)log file to the console before processing it.
- `--config-file`: Include this flag to use a custom config file - defaults to 'prompts' (ie, `prompts.py`).
- `--overrides`: Include this flag to use a custom overrides file - defaults to 'local_overrides' (ie, `local_overrides.py`).
- `--suggestion-model`: Include this flag to use a specific model of issue resolution suggestions - defaults to `gpt-4o-mini`.
- `--issue-model`: Include this flag to use a specific model of issue identification - defaults to `gpt-4o-mini`.
### Example

```bash
python main.py --file /var/log/syslog
```

This will remove the bulk of duplicate log entries, analyze the remaining log file, generate a report, and include suggested resolutions in the output.

To do a dry run and figure out how long your log data is, you can use the `--dry-count` flag:

```bash
$ python main.py --file /var/log/syslog --dry-count --show-log
Length: 187 lines
Tokens: 11341 tokens
```

By default, the script will remove duplicate/similar log entries that occur more than three times.  This can cut out a reasonable
amount of similar-but-not-identical log entries.  You can stop this by using the `--remove-duplicates=false` flag:

```bash
$ python main.py --file /var/log/syslog
Length: 150 lines
Tokens: 7530 tokens

$ python main.py --file /var/log/syslog --remove-duplicates=false
Length: 187 lines
Tokens: 11341 tokens
```

You can also use a custom config file to override the default prompts.  For example, if you wanted to use a different set of prompts for Ubuntu you could create a file called `prompts_ubuntu.py` with your overrides and then run the tool like this:

```bash
$ python main.py --file /var/log/syslog --config-file prompts_ubuntu.py
```

The format of the file should be the same as the default prompts.py file.

You can also use a custom overrides file to override the default ignore/match lists and replacement map.  For example, if you wanted to add some additional things to ignore you could create a file called `local_overrides.py` with your overrides and then run the tool like this:

```bash
$ python main.py --file /var/log/syslog --overrides local_overrides.py
```

## Usage (Docker)

You can also run this tool using Docker. This approach ensures that all dependencies are correctly installed and isolated from your system.

### Building the Docker Image

1. Ensure you have Docker installed on your system.
2. Navigate to the directory containing the Dockerfile and run:

```bash
docker build -t syslog-reporter .
```

### Running the Docker Container

```bash
tail -500 /var/log/syslog | docker run -i --rm syslog-reporter --config-file prompts_ubuntu.py
```

**Note** - if you're using a custom config file, you'll need to mount it into the container (or rebuild the image with the custom config file).

```sh
tail -500 /var/log/syslog | docker run -i --rm -v $(pwd)/prompts_ubuntu.py:/app/prompts.py syslog-reporter
```

## Output

The tool generates a markdown report in the format `report_YYYY-MM-DD.md`, where `YYYY-MM-DD` corresponds to the date of the report generation. The report includes:

- A summary of identified critical issues.
- Example log entries.
- Affected hosts and services.
- Recommendations for further investigation and resolution (unless the `--resolutions=false` flag is used).
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
filtering out common things you're not interested in.  At the top of `prompts.py` you'll see a list of things to ignore.
Feel free to modify this list to your liking.

```python
ignore_list = [
    "arpwatch: bogon",
    "unknown client",
    "vmmon: Hello",
    "USB disconnect",
]
```

You can also set it only match certain things, by adding to the `match_list` variable.
```python
match_list = [
    "kernel",
    "nagios",
    "dhcpd",
]
```
This can be useful if you only want to report on certain things and report them to a specific person or team.  Using the `--config-file` flag you could use a custom config file for each person/team.

## Notes

- The default prompts have wording in them to guide them to assume CentOS or Rocky Linux, so if you're using Ubuntu or Debian, you'll need to modify the prompts.
- Syslog output is very 'token heavy'.  The LLM can only handle so much data (currently about 128k tokens).  When I take a fairly random 1000 lines of syslog and filter out the noise leaving about 165 'real' lines, I get about 10,000 tokens.  You can use the `--dry-count` flag to get a token count for your log file and exit without doing the full analysis, which is handy for testing.
- The script will automatically split up the log file into chunks if it's too large to process in one go.  But be aware
that this means you could accidentally send a _lot_ of tokens to OpenAI.  It's worth using the `--dry-count` flag to check
the token count before running the full analysis.
- Remember you're passing your logs to OpenAI, so you may need to remove any sensitive information.


## License

MIT License. You can use, modify, and distribute this software under the terms of the MIT license.

## Example Report (redacted with resolutions)

# Syslog Report for 2024-09-02

Here's a detailed analysis of the critical issues found in the provided syslog data:


- Issue: PulseAudio Segfaults
  - Description: Multiple instances of the PulseAudio service encountered segmentation faults due to errors in the libalsa-util.so library.
  - Example log entry: `Aug 30 11:22:57 host23 kernel: [330587.153251] pulseaudio[2836870]: segfault at 10 ip 00007f52631e71c2 sp 00007fff2486b560 error 4 in libalsa-util.so[7f52631ca000+51000]`
  - Affected host(s): **host23**
  - Affected service: **PulseAudio**
  - Timestamp/Frequency: Occurred frequently between 11:22:57 and 11:23:48 with multiple entries; approximately 3 instances.
  - Potential impact: Persistent faults may lead to the audio service being unavailable, affecting user experience on systems utilizing audio outputs.
  - Recommended action: Investigate the libalsa-util.so library for bugs; update or patch if a newer version is available. Restart PulseAudio service on the affected host.

- Issue: Nagios Check Timeouts
  - Description: Nagios check jobs for several hosts, including "host23" and "host24," timed out indicating potential network or operational issues.
  - Example log entry: `Aug 30 11:20:59 host23 nagios: Warning: Check of host 'host23' timed out after 30.01 seconds`
  - Affected host(s): **host23**, **host24**
  - Affected service: **Nagios**
  - Timestamp/Frequency: Timeouts logged at least for jobs 3979 and 3980 around 11:20 and 11:21.
  - Potential impact: Failure to monitor critical services can lead to undetected issues up to a service outage.
  - Recommended action: Check network connectivity to these hosts and ensure that the services being checked are operational. Review service logs for further diagnosis.

- Issue: Duplicate DHCP Lease
  - Description: DHCP server logs indicate multiple requests for the same IP lease, causing potential address conflicts.
  - Example log entry: `Aug 30 11:21:12 XXXXXX dhcpd[3527688]: uid lease 172.20.100.94 for client XX:XX:XX:XX:XX:XX is duplicate on sub100`
  - Affected host(s): **XXXXXX**
  - Affected service: **DHCP**
  - Timestamp/Frequency: At least three instances of duplicate leases reported at 11:21.
  - Potential impact: Duplicate IP leases may lead to connectivity issues for affected clients.
  - Recommended action: Investigate the DHCP server configuration, check for potential IP address conflicts, and resolve any overlapping DHCP ranges.

- Issue: Connect Returned Error
  - Description: Connections to a TCP socket are failing with an unhandled error.
  - Example log entry: `Aug 30 11:21:01 YYYYYY kernel: [31085335.454151] xs_tcp_setup_socket: connect returned unhandled error -107`
  - Affected host(s): **YYYYYY**
  - Affected service: **Unknown (Related to socket communication)**
  - Timestamp/Frequency: Logged once at 11:21.
  - Potential impact: Could signify issues with network resource availability, possibly impacting applications relying on this communication.
  - Recommended action: Analyze network conditions and check logs for services using this socket. Ensure that relevant services are running correctly.

Overall, the critical issues primarily revolve around service stability and network configurations. It is essential to investigate each identified area to prevent further deterioration of service availability.

## Suggestions

### PulseAudio Segfaults

Root Cause: PulseAudio crashes due to a bug in libalsa-util.so.

Fix:
1. Check for and install any available updates for alsa-lib.
   ```bash
   yum update alsa-lib
   ```
2. Restart the PulseAudio service.
   ```bash
   systemctl --user restart pulseaudio
   ```
3. Verify service operation.

Investigate: `coredumpctl list`

Prevent: Regularly update audio-related libraries and monitor for known bugs.

---

### Nagios Check Timeouts

Root Cause: Network latency or service overload causing Nagios check timeouts.

Fix:
1. Verify network connectivity to the affected hosts.
   ```bash
   ping -c 4 host23
   ```
2. Review Nagios configuration for timeout settings.
3. Investigate and resolve any network or service issues.

Investigate: `tail -n 100 /var/log/nagios/nagios.log`

Prevent: Ensure Nagios timeout parameters are aligned with network conditions.---

### Duplicate DHCP Lease

Root Cause: Overlapping IP address assignments or stale leases.

Fix:
1. Check for overlapping DHCP scope configurations.
2. Identify and remove conflicting leases from the DHCP database.
   ```bash
   dhcpd dhcpd.leases.leases
   ```
3. Restart the DHCP service to apply changes.
   ```bash
   systemctl restart dhcpd
   ```

Investigate: `dhcp-lease-list`

Prevent: Regularly audit DHCP scope configurations and active leases.

---

### Connect Returned Error

Root Cause: TCP connection error suggesting network issue or service misconfiguration.

Fix:
1. Check the status of involved network services.
2. Review logs for services tied to reported TCP connections.
3. Test connectivity using netcat.
   ```bash
   nc -zv <hostname> <port>
   ```

Investigate: `netstat -anp | grep <port>`

Prevent: Monitor network service status and employ alerting for unexpected errors.

_Cost: US$0.009_
