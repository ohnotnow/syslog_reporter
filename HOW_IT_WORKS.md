# How it works

Note - for a deep-dive see [TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md).

## The problem

The servers in our estate forward their system logs to a central store. That
stream is roughly half a million lines a day, and almost all of it is routine:
DHCP leases, cron jobs starting, scanners being bounced off the DNS server.
Nobody can read half a million lines, so in practice nobody reads any of them,
and the handful of lines that matter (a server running out of memory, a mail
service quietly dying, a machine overheating) scroll past unseen.

The tool turns that stream into a short morning email: the few things worth a
sysadmin's attention, each with an explanation and ready-to-paste commands to
investigate and fix. The guiding rule is that alert fatigue is the enemy. It
would rather under-report with high confidence than flood the inbox.

## The division of labour

The design splits the work in two, on purpose:

- Deterministic code decides what is worth surfacing. Filtering, counting and
  statistics: boring, testable, free to run, and incapable of making things up.
- The AI model explains those findings and writes the commands.

## A day in the life of a log line

1. Collect. A small script queries the central log store for one day of
   syslog and writes it to a compressed file, which is copied to wherever the
   tool runs. Nothing needs installing on the log server beyond that one
   script, and its access to the log store is read-only.

2. Filter. A rule list, tuned to our estate, drops the known-routine lines
   and collapses near-duplicates. On a real day this removes about 99% of the
   volume, leaving a few thousand lines that are at least unusual.

3. Find issues. The AI model reads the remaining lines in chunks and pulls
   out genuine problems, each with a severity. Duplicate sightings of the
   same problem are merged.

4. Write the fixes. For each issue the model writes a likely cause, a command
   to confirm the diagnosis, and the commands to fix it, tailored to the
   operating system of the machine involved. Every command carries a
   plain-English comment, and any command that would change a system (restart
   a service, delete files, install packages) is flagged CHANGES STATE.

5. Spot the weird. Separately, statistical checks compare every host and
   program against three yardsticks: its fleet peers, its own recent history,
   and its own habits at that time of day. This catches what no single day
   can show, such as a mail relay whose traffic dropped to 2% of its normal
   level: nothing in that day's log looks wrong on its own; the drop only
   shows against the history.

6. Report. The findings become a short digest (the email body: top issues and
   top anomalies) and a full report (an attachment with everything). It runs
   unattended overnight; the report is waiting at the start of the working
   day.

## What it costs

The deterministic stages are free and quick to run. The AI stages read only
the filtered residue and cost roughly $0.11 for a full day of estate logs at
current model prices, or about £2.50 a month as a daily job. A no-AI mode
runs the free half alone.

## What it is not

- Not a SIEM and not a security monitor. If something looks like a security
  problem (brute forcing, scanning from inside), the report says so in one
  line and leaves it to the security team, who own that. It does not
  investigate.
- Not real-time. It is a daily batch digest, not an alerting pipeline. If a
  server catches fire at 2pm, the monitoring systems page someone; this tool
  writes the considered morning-after summary.
- Not automated remediation. It changes nothing on any server. Every command
  in the report is a suggestion that a human reads, judges and pastes.

## Where the data goes

Raw logs stay on our own machines. The only data that leaves is the filtered
residue, sent to the configured AI provider's API for analysis. The provider
and model are configurable, and the reports themselves are only ever emailed
to the team.
