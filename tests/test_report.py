import unittest

from datetime import date

from agents.issue_agent import Issue, IssueList
from agents.anomaly_explainer import ExplainedAnomaly
from agents.known_knowns import KnownEntry, KnownKnowns
from agents.resolution_agent import Resolution, ResolutionList
from agents.report_agent import ReportAgent
from agents.emailer import EmailAgent


def _issue(title, severity):
    return Issue(
        issue=title, severity=severity, description=f"{title} desc",
        example_log_entry="...", affected_host=["h1"], affected_service="svc",
        timestamp_frequency="all day", potential_impact="bad",
        recommended_action=f"fix {title}",
    )


def _resolution(title):
    return Resolution(
        issue=title, root_cause=f"{title} cause",
        investigate=f"systemctl status {title}",
        fix_commands=[f"systemctl restart {title}"], notes="might just be off",
    )


def _anomaly():
    return ExplainedAnomaly(
        host="hastings", program="kernel", kind="peer",
        headline="Louder than its peers",
        detail="41,839 events vs a fleet median of 592 across peer hosts.",
        os_family="RHEL-family", example_line="pulseaudio segfault",
        likely_causes="pulseaudio is crash-looping.",
        investigation_steps=["check coredumpctl"], suggested_commands=["coredumpctl list"],
    )


class TopIssuesTests(unittest.TestCase):
    def test_sorted_by_severity_and_capped(self):
        issues = IssueList(issues=[
            _issue("a-low", "low"),
            _issue("b-critical", "critical"),
            _issue("c-medium", "medium"),
            _issue("d-high", "high"),
        ])
        top = ReportAgent(issues, ResolutionList(resolutions=[]))._top_issues(2)
        self.assertEqual([i.issue for i in top], ["b-critical", "d-high"])


class EmailBodyTests(unittest.TestCase):
    def test_body_shows_top_issues_with_commands_and_hides_the_rest(self):
        issues = IssueList(issues=[
            _issue("disk-full", "critical"),
            _issue("clock-skew", "high"),
            _issue("cosmetic-thing", "low"),
        ])
        resolutions = ResolutionList(resolutions=[
            _resolution("disk-full"), _resolution("clock-skew"),
        ])
        body = ReportAgent(issues, resolutions, [_anomaly()]).email_body(
            top_issues=2, top_anomalies=1)

        self.assertIn("disk-full", body)              # critical -> in body
        self.assertIn("clock-skew", body)             # high -> in body
        self.assertNotIn("cosmetic-thing", body)      # low, beyond top 2 -> not in body
        self.assertIn("systemctl status disk-full", body)   # investigate command shown
        self.assertIn("systemctl restart disk-full", body)  # fix command shown
        self.assertIn("```", body)                    # commands are in a code fence
        self.assertIn("of 3 issues", body)            # signals there is more
        self.assertIn("hastings", body)               # top anomaly included
        self.assertIn("coredumpctl list", body)       # anomaly command shown
        self.assertIn("email_attachment.md", body)    # points at the attachment

    def test_body_falls_back_to_recommended_action_without_resolution(self):
        issues = IssueList(issues=[_issue("orphan", "high")])
        body = ReportAgent(issues, ResolutionList(resolutions=[])).email_body()
        self.assertIn("fix orphan", body)             # recommended_action fallback

    def test_body_handles_no_issues(self):
        body = ReportAgent(IssueList(issues=[]), ResolutionList(resolutions=[]), []).email_body()
        self.assertIn("quiet day", body)


class NoLlmRunTests(unittest.TestCase):
    # A --no-llm run must never masquerade as a clean bill of health: the body
    # and the full report both say the analysis was skipped, while anomaly
    # facts from the deterministic detectors still render.
    def test_body_says_skipped_not_quiet_day(self):
        body = ReportAgent(IssueList(issues=[]), ResolutionList(resolutions=[]),
                           [_anomaly()], llm_skipped=True).email_body()
        self.assertIn("skipped", body)
        self.assertNotIn("quiet day", body)
        self.assertIn("hastings", body)               # anomaly facts still shown

    def test_full_report_says_skipped_in_issue_sections(self):
        report = ReportAgent(IssueList(issues=[]), ResolutionList(resolutions=[]),
                             [_anomaly()], llm_skipped=True).run()
        self.assertIn("--no-llm run", report)
        self.assertNotIn("No resolutions generated", report)
        self.assertIn("hastings", report)


class FormattingTests(unittest.TestCase):
    def test_host_list_truncated(self):
        issue = _issue("many-hosts", "high")
        issue.affected_host = [f"h{i}" for i in range(12)]
        self.assertIn("… and 7 more", issue.hosts_summary())

    def test_issue_markdown_has_blank_line_separation(self):
        # The blob bug: fields must be paragraph-separated, not glued together.
        md = _issue("x", "high").to_markdown()
        self.assertIn("\n\n", md)
        self.assertIn("```", md)  # example log entry fenced


class KnownKnownsFooterTests(unittest.TestCase):
    # Suppression must stay visible: a muted entry that never appears
    # anywhere is how a known known quietly becomes an unwatched fault.
    def report(self, knowns):
        return ReportAgent(IssueList(issues=[]), ResolutionList(resolutions=[]),
                           [], knowns=knowns)

    def test_fired_entries_appear_in_body_and_full_report(self):
        entry = KnownEntry(host="scopebox", reason="microscope kit",
                           match="port 1234")
        knowns = KnownKnowns([entry], date(2026, 8, 27))
        knowns.line_ignored("scopebox", "retry on port 1234")

        reporter = self.report(knowns)
        for text in (reporter.email_body(), reporter.run()):
            self.assertIn("microscope kit (scopebox) ×1", text)

    def test_expired_entries_are_flagged(self):
        entry = KnownEntry(host="scopebox", reason="microscope kit",
                           match="port 1234", expires=date(2026, 1, 1))
        reporter = self.report(KnownKnowns([entry], date(2026, 8, 27)))
        for text in (reporter.email_body(), reporter.run()):
            self.assertIn("1 known-known entry has expired", text)

    def test_silent_knowns_render_no_footer(self):
        entry = KnownEntry(host="scopebox", reason="microscope kit",
                           match="port 1234")
        reporter = self.report(KnownKnowns([entry], date(2026, 8, 27)))
        self.assertNotIn("Known knowns", reporter.email_body())
        self.assertNotIn("Known Knowns", reporter.run())

    def test_no_knowns_at_all_is_fine(self):
        reporter = self.report(None)
        self.assertNotIn("Known knowns", reporter.email_body())


class EmailAgentTests(unittest.TestCase):
    def test_build_message_attaches_full_report(self):
        agent = EmailAgent("the short body", attachment_text="the full report",
                           recipients="ops@example.com")
        agent.sender = "syslog@example.com"

        msg = agent.build_message()

        self.assertEqual(msg["Subject"], "Syslog Report")
        self.assertEqual(msg["Bcc"], "ops@example.com")
        body = msg.get_body(preferencelist=("plain",)).get_content()
        self.assertIn("the short body", body)
        attachments = list(msg.iter_attachments())
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), "email_attachment.md")
        self.assertIn("the full report", attachments[0].get_content())

    def test_build_message_without_attachment(self):
        agent = EmailAgent("body only", recipients="ops@example.com")
        agent.sender = "syslog@example.com"
        msg = agent.build_message()
        self.assertEqual(len(list(msg.iter_attachments())), 0)
        self.assertIn("body only", msg.get_content())


if __name__ == "__main__":
    unittest.main()
