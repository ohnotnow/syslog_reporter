import unittest

from agents.anomaly_agent import PeerAnomaly
from agents.anomaly_explainer import (
    AnomalyExplainerAgent,
    AnomalyExplanation,
    ExplainedAnomaly,
    facts_only,
)
from agents.issue_agent import IssueList
from agents.resolution_agent import ResolutionList
from agents.report_agent import ReportAgent


def _anomaly(host="seal1", program="systemd", count=16875):
    return PeerAnomaly(
        host=host, program=program, count=count, fleet_median=171,
        score=83.8, example_line=f"Nov  8 00:00:13 {host} {program}[1]: restart loop",
        os_family="Debian-family",
    )


class MergeTests(unittest.TestCase):
    def test_merges_explanation_onto_facts(self):
        anomaly = _anomaly()
        explanation = AnomalyExplanation(
            host="seal1", program="systemd",
            likely_causes="A unit is stuck in a restart loop.",
            investigation_steps=["systemctl --failed"],
            suggested_commands=["journalctl -u snap.snapd-desktop-integration"],
        )

        merged = AnomalyExplainerAgent._merge([anomaly], [explanation])

        self.assertEqual(len(merged), 1)
        m = merged[0]
        self.assertEqual(m.host, "seal1")
        self.assertEqual(m.kind, "peer")
        self.assertIn("16,875", m.detail)             # deterministic fact preserved
        self.assertEqual(m.os_family, "Debian-family")
        self.assertIn("restart loop", m.likely_causes)
        self.assertEqual(m.investigation_steps, ["systemctl --failed"])

    def test_unmatched_anomaly_still_rendered_with_facts(self):
        anomaly = _anomaly(host="lonely")
        merged = AnomalyExplainerAgent._merge([anomaly], [])  # LLM returned nothing

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].host, "lonely")
        self.assertEqual(merged[0].suggested_commands, [])
        self.assertIn("no explanation", merged[0].likely_causes.lower())


class FactsOnlyTests(unittest.TestCase):
    def test_builds_explained_anomalies_without_an_llm(self):
        explained = facts_only([_anomaly(host="web1")])

        self.assertEqual(len(explained), 1)
        self.assertEqual(explained[0].host, "web1")
        self.assertEqual(explained[0].kind, "peer")
        self.assertIn("16,875", explained[0].detail)  # deterministic facts kept
        self.assertEqual(explained[0].investigation_steps, [])
        self.assertIn("no explanation", explained[0].likely_causes.lower())

    def test_caps_at_max_explain(self):
        anomalies = [_anomaly(host=f"web{i}") for i in range(5)]
        self.assertEqual(len(facts_only(anomalies, max_explain=2)), 2)


class MarkdownAndReportTests(unittest.TestCase):
    def _explained(self, **kw):
        defaults = dict(
            host="hastings", program="kernel", kind="peer",
            headline="Louder than its peers",
            detail="41,839 events vs a fleet median of 592 across peer hosts.",
            os_family="RHEL-family", example_line="pulseaudio segfault",
            likely_causes="pulseaudio is crash-looping.",
            investigation_steps=["check coredumpctl"],
            suggested_commands=["coredumpctl list"],
        )
        defaults.update(kw)
        return ExplainedAnomaly(**defaults)

    def test_explained_anomaly_markdown(self):
        md = self._explained().to_markdown()
        self.assertIn("hastings — kernel", md)
        self.assertIn("Louder than its peers", md)
        self.assertIn("41,839 events vs a fleet median of 592", md)
        self.assertIn("coredumpctl list", md)

    def test_silent_anomaly_omits_empty_example(self):
        # A host that has gone silent has no example line — don't render an
        # empty "**Example:** ``" that would just be noise.
        md = self._explained(
            kind="baseline", headline="Gone silent", example_line="",
            detail="No events today — this host normally emits about 540/day.",
        ).to_markdown()
        self.assertIn("Gone silent", md)
        self.assertNotIn("**Example:**", md)

    def test_report_includes_anomaly_section(self):
        report = ReportAgent(IssueList(issues=[]), ResolutionList(resolutions=[]),
                             [self._explained()]).run()
        self.assertIn("Unusual Activity", report)
        self.assertIn("hastings", report)

    def test_report_handles_no_anomalies(self):
        report = ReportAgent(IssueList(issues=[]), ResolutionList(resolutions=[]), []).run()
        self.assertIn("No unusual activity detected.", report)


if __name__ == "__main__":
    unittest.main()
