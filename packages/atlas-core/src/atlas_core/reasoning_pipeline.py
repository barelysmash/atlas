from datetime import datetime

from atlas_core.blocking import block_records
from atlas_core.data_gap_engine import generate_data_gaps
from atlas_core.decision_engine import generate_decisions
from atlas_core.derived_metric_engine import derive_metrics
from atlas_core.goal import Goal
from atlas_core.insight_engine import generate_insights
from atlas_core.observation import Observation
from atlas_core.observation_engine import generate_observations
from atlas_core.operational_record import OperationalRecord
from atlas_core.reasoning_result import ReasoningResult
from atlas_core.trend_observation_engine import generate_trend_observations


class ReasoningPipeline:
    """Coordinates Atlas reasoning stages in pursuit of explicit goals.

    Atlas reasons from operational records to decisions. Rendering those
    decisions into an executive brief is not this pipeline's responsibility.

    A pipeline constructed without goals still observes, but it produces no
    insights or decisions: without a goal there is no basis on which to call
    any movement good or bad.
    """

    def __init__(self, goals: list[Goal] | None = None) -> None:
        self.goals = goals or []

    def run(
        self, record: OperationalRecord, now: datetime | None = None
    ) -> ReasoningResult:
        """Reason over a single record, without period context.

        Retained for compatibility. Prefer run_window, which can observe change
        over time.
        """
        return self._reason(generate_observations(record), now)

    def run_window(
        self, records: list[OperationalRecord], now: datetime | None = None
    ) -> ReasoningResult:
        """Reason over a window of records covering multiple periods.

        Records are first rolled up into the comparison blocks their grain
        calls for, then rates are derived from the blocked totals. Nightly data
        is therefore compared a week at a time, and a rate like sales per
        labour hour is computed from the week's totals rather than averaged
        from its own nightly values.
        """
        prepared = derive_metrics(block_records(records))

        return self._reason(generate_trend_observations(prepared), now)

    def _reason(
        self, observations: list[Observation], now: datetime | None = None
    ) -> ReasoningResult:
        insights = generate_insights(observations, self.goals, now)
        decisions = generate_decisions(insights, now)
        gaps = generate_data_gaps(observations, self.goals)

        return ReasoningResult(
            observations=observations,
            insights=insights,
            decisions=decisions,
            gaps=gaps,
        )
