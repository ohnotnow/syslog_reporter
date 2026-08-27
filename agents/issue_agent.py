from typing import Literal
from .llm import completion
from jinja2 import Environment, PackageLoader, select_autoescape, FileSystemLoader
import instructor
from pydantic import BaseModel

from . import PROMPT_DIR

# Lower number = more urgent. Used to sort issues for the short email body.
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

class Issue(BaseModel):
    issue: str
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    description: str
    example_log_entry: str
    affected_host: list[str]
    affected_service: str
    timestamp_frequency: str
    potential_impact: str
    recommended_action: str

    def hosts_summary(self, limit: int = 5) -> str:
        """Affected hosts, truncated so long lists don't swamp the report."""
        hosts = self.affected_host
        if not hosts:
            return "n/a"
        if len(hosts) <= limit:
            return ", ".join(hosts)
        return ", ".join(hosts[:limit]) + f" … and {len(hosts) - limit} more"

    def to_markdown(self):
        return (
            f"## {self.issue}\n\n"
            f"**Severity:** {self.severity} · **Service:** {self.affected_service} · "
            f"**When:** {self.timestamp_frequency}\n\n"
            f"{self.description}\n\n"
            f"- **Affected:** {self.hosts_summary()}\n"
            f"- **Impact:** {self.potential_impact}\n"
            f"- **Recommended action:** {self.recommended_action}\n\n"
            f"**Example log entry:**\n\n"
            f"```\n{self.example_log_entry}\n```\n"
        )

class IssueList(BaseModel):
    issues: list[Issue]

    def to_markdown(self):
        return "\n".join([issue.to_markdown() for issue in self.issues]) + "\n"

class IssueDetectorAgent:
    def __init__(self, lines, model):
        self.lines = lines
        self.model = model
        self.env = Environment(
            loader=FileSystemLoader(PROMPT_DIR),
            autoescape=select_autoescape()
        )
        self.system_prompt = self.env.get_template("issue_detection.j2").render()
        self.client = instructor.from_litellm(completion)

    def run(self) -> IssueList:
        # chunk lines into 1000 line chunks
        chunks = [self.lines[i:i+1000] for i in range(0, len(self.lines), 1000)]
        issues = []
        for chunk in chunks:
            found_issues = self.client.chat.completions.create(
                model=self.model,
                response_model=IssueList,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": "\n".join(chunk)}
                ]
            )
            issues.extend(found_issues.issues)
        return IssueList(issues=issues)
