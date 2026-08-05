from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True)
class DecisionRecord:
    """A decision the organisation made, and why, kept in memory.

    This is not the Decision an engine emits. That one is a recommendation
    carrying a category, a priority, evidence, and proposed actions, specified
    by JAM and implemented in atlas_core. This one records a choice that was
    made: usually after an Experiment, often by a person, and sometimes on
    grounds the platform never saw.

    Forcing these records through the contract type would mean inventing a
    category, a priority, and evidence for decisions the engine did not make.
    Keeping them distinct and naming them accurately is the honest option.

    ``decision_id`` links back to the contract Decision when the choice
    followed one, and stays absent when it did not. That link is what makes it
    answerable later which recommendations were acted on.
    """

    id: UUID
    timestamp: datetime
    summary: str
    rationale: str
    decision_id: str | None = None

    @classmethod
    def create(
        cls,
        summary: str,
        rationale: str,
        decision_id: str | None = None,
    ) -> "DecisionRecord":
        if not summary:
            raise ValueError("summary is required")
        if not rationale:
            raise ValueError("rationale is required")
        if decision_id is not None and not decision_id.startswith("dec_"):
            raise ValueError(
                f"decision_id {decision_id!r} is not a contract decision "
                "identifier; those begin with dec_"
            )
        return cls(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            summary=summary,
            rationale=rationale,
            decision_id=decision_id,
        )

    @property
    def followed_a_recommendation(self) -> bool:
        """Whether this choice followed a Decision the platform emitted."""
        return self.decision_id is not None
