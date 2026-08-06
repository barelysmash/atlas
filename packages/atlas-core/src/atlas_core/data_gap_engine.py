from atlas_core.data_gap import NO_DATA, SINGLE_PERIOD, DataGap
from atlas_core.goal import Goal, movement_from_delta
from atlas_core.observation import Observation

REASON_SUMMARIES = {
    NO_DATA: "no data was supplied for it",
    SINGLE_PERIOD: (
        "only one period of data was supplied, so no movement can be measured"
    ),
}


def generate_data_gaps(
    observations: list[Observation],
    goals: list[Goal] | None = None,
) -> list[DataGap]:
    """Report every goal metric that could not be evaluated.

    Together with the insights produced from the same observations, this
    accounts for every metric each goal tracks: a metric either produced an
    interpretation or produced a gap. Nothing a goal cares about is passed over
    silently.
    """
    gaps: list[DataGap] = []

    for goal in goals or []:
        for metric in goal.metrics:
            supporting = [
                observation
                for observation in observations
                if observation.has_metric(metric)
            ]

            if not supporting:
                reason = NO_DATA
            elif not any(
                movement_from_delta(
                    measured.delta if (measured := o.get_metric(metric)) else None
                )[0]
                is not None
                for o in supporting
            ):
                reason = SINGLE_PERIOD
            else:
                continue

            gaps.append(
                DataGap(
                    goal=goal.summary,
                    metric=metric,
                    reason=reason,
                    summary=(
                        f"'{goal.summary}' tracks {metric}, but "
                        f"{REASON_SUMMARIES[reason]}."
                    ),
                )
            )

    return gaps
