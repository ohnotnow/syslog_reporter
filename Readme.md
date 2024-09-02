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

## Example Report (redacted with resolutions)

# Syslog Report for 2024-09-02

Here's a detailed analysis of the critical issues found in the provided syslog data:


- Issue: PulseAudio Segfaults
  - Description: Multiple instances of the PulseAudio service encountered segmentation faults due to errors in the libalsa-util.so library.
  - Example log entry: `Aug 30 11:22:57 server-x kernel: [330587.153251] pulseaudio[2836870]: segfault at 10 ip 00007f52631e71c2 sp 00007fff2486b560 error 4 in libalsa-util.so[7f52631ca000+51000]`
  - Affected host(s): **host23**
  - Affected service: **PulseAudio**
  - Timestamp/Frequency: Occurred frequently between 11:22:57 and 11:23:48 with multiple entries; approximately 3 instances.
  - Potential impact: Persistent faults may lead to the audio service being unavailable, affecting user experience on systems utilizing audio outputs.
  - Recommended action: Investigate the libalsa-util.so library for bugs; update or patch if a newer version is available. Restart PulseAudio service on the affected host.

- Issue: Nagios Check Timeouts
  - Description: Nagios check jobs for several hosts, including "host23" and "host24," timed out indicating potential network or operational issues.
  - Example log entry: `Aug 30 11:20:59 server-x nagios: Warning: Check of host 'host23' timed out after 30.01 seconds`
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

Prevent: Ensure Nagios timeout parameters are aligned with network conditions.

---

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
