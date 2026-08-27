"""Consolidate duplicate issues across log chunks.

The issue detector works on 1000-line chunks, so one underlying problem (e.g. a
fleet-wide Puppet repo failure) gets reported several times with slightly
different wording. This agent merges those near-duplicates into one issue before
they reach the resolution step and the report — so the top-N digest shows N
*distinct* concerns. See ait syslog-reporter-UkLWZ.9.
"""
import json
from .llm import completion
from jinja2 import Environment, select_autoescape, FileSystemLoader
import instructor

from . import PROMPT_DIR
from .issue_agent import IssueList


class IssueDeduplicatorAgent:
    def __init__(self, issues: IssueList, model: str):
        self.issues = issues
        self.model = model
        self.env = Environment(
            loader=FileSystemLoader(PROMPT_DIR),
            autoescape=select_autoescape(),
        )
        self.system_prompt = self.env.get_template("issue_dedupe.j2").render()
        self.client = instructor.from_litellm(completion)

    def run(self) -> IssueList:
        # Nothing to merge with 0 or 1 issue — skip the call.
        if len(self.issues.issues) <= 1:
            return self.issues
        # Pass full fidelity (incl. complete affected_host lists) so the model can
        # merge host lists properly — the markdown view is truncated for display.
        payload = json.dumps([i.model_dump() for i in self.issues.issues], indent=2)
        return self.client.chat.completions.create(
            model=self.model,
            response_model=IssueList,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": payload},
            ],
        )
