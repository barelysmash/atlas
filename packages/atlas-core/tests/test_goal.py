import pytest
from atlas_core import DataGap, Goal, MetricTarget, ReasoningResult
from atlas_core.goal import DOWN, FLAT, UP, movement_from_delta


def test_create_goal():
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase")],
        priority="high",
    )

    assert goal.summary == "Grow beverage revenue."
    assert goal.metrics == ["wine_receipts"]
    assert goal.priority == "high"


def test_goal_requires_summary():
    with pytest.raises(ValueError):
        Goal.create(summary="")


def test_goal_rejects_unknown_priority():
    with pytest.raises(ValueError):
        Goal.create(summary="Grow beverage revenue.", priority="urgent")


def test_metric_target_rejects_unknown_direction():
    with pytest.raises(ValueError):
        MetricTarget("wine_receipts", "upward")


def test_goal_tracks_only_its_own_metrics():
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase")],
    )

    assert goal.tracks("wine_receipts")
    assert not goal.tracks("food_cost_pct")


def test_increase_target_favors_upward_movement():
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase")],
    )

    assert goal.is_favorable("wine_receipts", "up") is True
    assert goal.is_favorable("wine_receipts", "down") is False


def test_decrease_target_favors_downward_movement():
    goal = Goal.create(
        summary="Hold food cost under control.",
        targets=[MetricTarget("food_cost_pct", "decrease")],
    )

    assert goal.is_favorable("food_cost_pct", "down") is True
    assert goal.is_favorable("food_cost_pct", "up") is False


def test_maintain_target_favors_flat_movement():
    goal = Goal.create(
        summary="Keep labor cost stable.",
        targets=[MetricTarget("labor_cost_pct", "maintain")],
    )

    assert goal.is_favorable("labor_cost_pct", "flat") is True
    assert goal.is_favorable("labor_cost_pct", "up") is False


def test_one_goal_can_pull_metrics_in_opposite_directions():
    goal = Goal.create(
        summary="Improve beverage margin.",
        targets=[
            MetricTarget("wine_receipts", "increase"),
            MetricTarget("wine_cost_pct", "decrease"),
        ],
    )

    assert goal.is_favorable("wine_receipts", "up") is True
    assert goal.is_favorable("wine_cost_pct", "up") is False


def test_untracked_metric_cannot_be_judged():
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase")],
    )

    assert goal.is_favorable("food_cost_pct", "up") is None


def test_movement_without_direction_cannot_be_judged():
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase")],
    )

    assert goal.is_favorable("wine_receipts", None) is None


def test_maintain_target_tolerates_small_movement():
    goal = Goal.create(
        summary="Keep beer volume stable through the remodel.",
        targets=[MetricTarget("beer_receipts", "maintain", tolerance=5.0)],
    )

    assert goal.is_favorable("beer_receipts", "up", change=2.0) is True
    assert goal.is_favorable("beer_receipts", "down", change=-4.9) is True
    assert goal.is_favorable("beer_receipts", "up", change=7.0) is False


def test_movement_inside_the_band_is_not_progress():
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase", tolerance=1.0)],
    )

    assert goal.is_favorable("wine_receipts", "up", change=0.4) is False
    assert goal.is_favorable("wine_receipts", "up", change=2.0) is True


def test_tolerance_defaults_to_zero():
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase")],
    )

    assert goal.is_favorable("wine_receipts", "up", change=0.4) is True


def test_tolerance_cannot_be_negative():
    with pytest.raises(ValueError):
        MetricTarget("wine_receipts", "increase", tolerance=-1.0)


def test_a_stalled_metric_is_not_a_reversal():
    """Not moving and moving the wrong way are different situations."""
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase", tolerance=1.0)],
    )

    assert goal.assess("wine_receipts", "up", change=4.0) == "favorable"
    assert goal.assess("wine_receipts", "up", change=0.2) == "stalled"
    assert goal.assess("wine_receipts", "down", change=-4.0) == "unfavorable"


def test_a_maintain_target_has_no_stalled_state():
    """Not moving is precisely what a maintain target asked for."""
    goal = Goal.create(
        summary="Keep beer volume stable.",
        targets=[MetricTarget("beer_receipts", "maintain", tolerance=5.0)],
    )

    assert goal.assess("beer_receipts", "up", change=1.0) == "favorable"
    assert goal.assess("beer_receipts", "up", change=9.0) == "unfavorable"


def test_a_flat_rank_against_an_improve_target_is_stalled():
    goal = Goal.create(
        summary="Improve position in the Austin market.",
        targets=[MetricTarget("austin_rank", "decrease")],
    )

    assert goal.assess("austin_rank", "flat", change=0.0) == "stalled"


def test_assessment_is_none_for_untracked_metrics():
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase")],
    )

    assert goal.assess("food_cost_pct", "up", change=4.0) is None


def test_targets_are_held_immutably():
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase")],
    )

    assert isinstance(goal.targets, tuple)


@pytest.mark.parametrize(
    ("delta", "direction"), [(0.12, UP), (-0.31, DOWN), (0.0, FLAT)]
)
def test_a_delta_becomes_an_observed_direction(delta, direction):
    assert movement_from_delta(delta)[0] == direction


def test_an_absent_delta_yields_no_movement():
    assert movement_from_delta(None) == (None, None)


def test_a_delta_is_converted_from_a_fraction_to_percentage_points():
    # JAM states delta as a fraction; a tolerance is a band in points. Without
    # the conversion a twelve percent rise sits inside a five point band.
    assert movement_from_delta(0.12)[1] == pytest.approx(12.0)


def test_a_contract_delta_is_judged_against_a_points_tolerance():
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase", tolerance=5.0)],
    )
    direction, change = movement_from_delta(0.12)

    assert goal.assess("wine_receipts", direction, change) == "favorable"


def test_a_small_contract_delta_reads_as_stalled():
    goal = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase", tolerance=5.0)],
    )
    direction, change = movement_from_delta(0.02)

    assert goal.assess("wine_receipts", direction, change) == "stalled"


def test_a_result_records_what_it_could_not_evaluate():
    gap = DataGap(
        goal="Grow beverage revenue.",
        metric="wine_receipts",
        reason="no_data",
        summary="No wine receipts were reported for the period.",
    )
    result = ReasoningResult(gaps=[gap])

    assert result.gaps == [gap]


def test_a_result_has_no_gaps_by_default():
    assert ReasoningResult().gaps == []
