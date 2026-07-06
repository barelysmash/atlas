from atlas_core import Observation


def test_create_observation():
    observation = Observation(
        category="operations",
        metric="wine_receipts",
        value=50000.0,
        summary="Wine receipts were $50,000.",
        evidence=["TABC June 2026"],
    )

    assert observation.category == "operations"
    assert observation.metric == "wine_receipts"
    assert observation.value == 50000.0
    assert observation.summary == "Wine receipts were $50,000."
    assert observation.evidence == ["TABC June 2026"]