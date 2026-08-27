import unittest

from agents.issue_agent import Issue, IssueList
from agents.issue_dedupe_agent import IssueDeduplicatorAgent


def _issue(title):
    return Issue(
        issue=title, severity="high", description="d", example_log_entry="e",
        affected_host=["h"], affected_service="s", timestamp_frequency="t",
        potential_impact="i", recommended_action="a",
    )


class DedupeGuardTests(unittest.TestCase):
    """The merge itself is an LLM call (validated live); here we only check the
    short-circuits that must NOT call the model."""

    def test_empty_returns_same_without_llm(self):
        issues = IssueList(issues=[])
        self.assertIs(IssueDeduplicatorAgent(issues, "openai/gpt-4o-mini").run(), issues)

    def test_single_issue_returns_same_without_llm(self):
        issues = IssueList(issues=[_issue("only one")])
        self.assertIs(IssueDeduplicatorAgent(issues, "openai/gpt-4o-mini").run(), issues)


if __name__ == "__main__":
    unittest.main()
