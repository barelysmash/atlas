from dataclasses import dataclass, field
from typing import Any

from atlas_core.identifiers import new_recommendation_id


@dataclass(frozen=True, slots=True)
class Recommendation:
    """A proposed course of action attached to a Decision.

    ``statement`` is imperative: it says what to do. ``action_type`` names an
    executable Action the consuming application supports, and its absence
    means the recommendation is advisory only.

    ``reversible`` defaults to False deliberately, matching the contract. A
    Decision may only skip human approval when every recommendation on it can
    be undone, so the safe default is the one that requires approval.
    """

    statement: str
    action_type: str | None = None
    parameters: dict[str, Any] | None = None
    reversible: bool = False
    recommendation_id: str = field(default_factory=new_recommendation_id, compare=False)

    def __post_init__(self) -> None:
        if self.parameters is not None and self.action_type is None:
            raise ValueError(
                "parameters are arguments for an action_type; "
                "supply action_type or drop parameters"
            )
