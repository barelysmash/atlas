from atlas_core.decision import Decision
from atlas_core.decision_engine import generate_decisions
from atlas_core.insight_engine import generate_insights
from atlas_core.observation_engine import generate_observations
from atlas_core.operational_record import OperationalRecord


class ReasoningPipeline:
    """Coordinates Atlas reasoning stages."""

    def run(self, record: OperationalRecord) -> list[Decision]:
        observations = generate_observations(record)
        insights = generate_insights(observations)
        decisions = generate_decisions(insights)

        return decisions