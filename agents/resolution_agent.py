from agents.issue_agent import IssueList
from .llm import completion
from jinja2 import Environment, select_autoescape, FileSystemLoader
import instructor
from pydantic import BaseModel

from . import PROMPT_DIR


class Resolution(BaseModel):
    issue: str                  # echoed back verbatim, so it pairs to its Issue
    root_cause: str
    investigate: str            # one paste-ready diagnostic command
    fix_commands: list[str]     # ordered, paste-ready shell commands
    notes: str = ""             # optional one-line caveat

    def to_markdown(self) -> str:
        fixes = "\n".join(self.fix_commands) if self.fix_commands else "# (no commands suggested)"
        md = (
            f"### {self.issue}\n\n"
            f"**Root cause:** {self.root_cause}\n\n"
            f"**Investigate:**\n\n```\n{self.investigate}\n```\n\n"
            f"**Fix:**\n\n```\n{fixes}\n```\n"
        )
        if self.notes:
            md += f"\n**Note:** {self.notes}\n"
        return md


class ResolutionList(BaseModel):
    resolutions: list[Resolution]

    def to_markdown(self) -> str:
        if not self.resolutions:
            return "No resolutions generated.\n"
        return "\n".join(r.to_markdown() for r in self.resolutions) + "\n"

    def by_issue(self) -> dict:
        """Map issue title -> Resolution, for pairing with issues in the report."""
        return {r.issue: r for r in self.resolutions}


class ResolutionAgent:
    def __init__(self, issues: IssueList, model: str, host_os: dict | None = None):
        self.issues = issues
        self.model = model
        self.env = Environment(
            loader=FileSystemLoader(PROMPT_DIR),
            autoescape=select_autoescape()
        )
        self.system_prompt = self.env.get_template("resolution.j2").render(host_os=host_os)
        self.client = instructor.from_litellm(completion)

    def run(self) -> ResolutionList:
        if not self.issues.issues:
            return ResolutionList(resolutions=[])
        return self.client.chat.completions.create(
            model=self.model,
            response_model=ResolutionList,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.issues.to_markdown()},
            ],
        )
