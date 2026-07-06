from dataclasses import dataclass

from atlas_core.reasoning_result import ReasoningResult


@dataclass(frozen=True, slots=True)
class ExecutiveBrief:
    """Human-readable rendering of Atlas reasoning."""

    markdown: str

    @classmethod
    def from_reasoning(
        cls,
        result: ReasoningResult,
        title: str = "Executive Brief",
    ) -> "ExecutiveBrief":
        observations = "\n".join(
            f"- {observation.summary}" for observation in result.observations
        )

        insights = "\n".join(
            f"- {insight.summary}" for insight in result.insights
        )

        decisions = "\n".join(
            f"- {decision.summary}" for decision in result.decisions
        )

        markdown = (
            f"# {title}\n\n"
            "## Observations\n\n"
            f"{observations}\n\n"
            "## Insights\n\n"
            f"{insights}\n\n"
            "## Decisions\n\n"
            f"{decisions}\n"
        )

        return cls(markdown=markdown)