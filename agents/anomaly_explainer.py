"""Turn detected peer anomalies into human-readable, OS-aware advice.

The detector (AnomalyDetectorAgent) decides *what* is weird — deterministically.
This agent's only job is to *explain*: for each anomaly it asks the LLM for
likely causes, investigation steps, and commands tailored to the host's OS
family. Detection stays cheap and deterministic; the LLM never decides what
counts as an anomaly. See ant ADR syslogreporter-VYQvH.
"""
from .llm import completion
from jinja2 import Environment, FileSystemLoader, select_autoescape
import instructor
from pydantic import BaseModel

from . import PROMPT_DIR

# Cap how many anomalies we send to the LLM — keeps cost down and the report
# focused (respect the colleagues' inboxes).
DEFAULT_MAX_EXPLAIN = 15


class AnomalyExplanation(BaseModel):
    """The LLM-generated half of an explained anomaly."""
    host: str
    program: str
    likely_causes: str
    investigation_steps: list[str]
    suggested_commands: list[str]


class AnomalyExplanationList(BaseModel):
    explanations: list[AnomalyExplanation]


class ExplainedAnomaly(BaseModel):
    """The deterministic anomaly facts merged with the LLM explanation.

    `kind`/`headline`/`detail` come from whichever detector flagged it (peer,
    baseline or temporal — they share a headline()/summary() interface), so the
    report renders all three uniformly.
    """
    host: str
    program: str
    kind: str           # peer / baseline / temporal
    headline: str       # short label, e.g. "Gone silent"
    detail: str         # the deterministic numbers sentence
    os_family: str
    example_line: str
    likely_causes: str
    investigation_steps: list[str]
    suggested_commands: list[str]

    def to_markdown(self) -> str:
        steps = "\n".join(f"- {s}" for s in self.investigation_steps) or "- (none given)"
        cmds = "\n".join(self.suggested_commands)
        cmd_block = f"```\n{cmds}\n```" if cmds else "_none given_"
        example = f"**Example:** `{self.example_line}`\n\n" if self.example_line else ""
        return (
            f"### {self.host} — {self.program}\n"
            f"**{self.headline}** ({self.os_family})\n\n"
            f"{self.detail}\n\n"
            f"{example}"
            f"**Likely causes:** {self.likely_causes}\n\n"
            f"**Investigate:**\n{steps}\n\n"
            f"**Suggested commands:**\n{cmd_block}\n"
        )


def facts_only(anomalies, max_explain: int = DEFAULT_MAX_EXPLAIN) -> list[ExplainedAnomaly]:
    """ExplainedAnomaly records built without any LLM call (--no-llm runs).

    The deterministic facts still render in the report; the advice fields say
    no explanation was generated.
    """
    return AnomalyExplainerAgent._merge(anomalies[:max_explain], [])


class AnomalyExplainerAgent:
    def __init__(self, anomalies, model, max_explain=DEFAULT_MAX_EXPLAIN):
        self.anomalies = anomalies
        self.model = model
        self.max_explain = max_explain
        self.env = Environment(
            loader=FileSystemLoader(PROMPT_DIR),
            autoescape=select_autoescape(),
        )
        self.system_prompt = self.env.get_template("anomaly_explanation.j2").render()
        self.client = instructor.from_litellm(completion)

    def run(self) -> list[ExplainedAnomaly]:
        top = self.anomalies[:self.max_explain]
        if not top:
            return []
        explanations = self._ask_llm(top)
        return self._merge(top, explanations.explanations)

    def _ask_llm(self, anomalies) -> AnomalyExplanationList:
        lines = [
            f"{i}. host={a.host} program={a.program} os_family={a.os_family} "
            f"what={a.headline()!r} detail={a.summary()!r} "
            f"example={a.example_line!r}"
            for i, a in enumerate(anomalies, 1)
        ]
        return self.client.chat.completions.create(
            model=self.model,
            response_model=AnomalyExplanationList,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": "\n".join(lines)},
            ],
        )

    @staticmethod
    def _merge(anomalies, explanations) -> list[ExplainedAnomaly]:
        """Pair each anomaly with its explanation by (host, program).

        Anomalies the LLM didn't return are still rendered, with the facts only,
        so nothing silently disappears from the report.
        """
        by_key = {(e.host, e.program): e for e in explanations}
        explained = []
        for a in anomalies:
            e = by_key.get((a.host, a.program))
            explained.append(ExplainedAnomaly(
                host=a.host,
                program=a.program,
                kind=a.kind,
                headline=a.headline(),
                detail=a.summary(),
                os_family=a.os_family,
                example_line=a.example_line,
                likely_causes=e.likely_causes if e else "(no explanation generated)",
                investigation_steps=e.investigation_steps if e else [],
                suggested_commands=e.suggested_commands if e else [],
            ))
        return explained
