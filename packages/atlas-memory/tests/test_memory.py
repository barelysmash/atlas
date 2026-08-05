from datetime import UTC, datetime

from atlas_core import Metric, Observation
from atlas_memory import Decision, Experiment, MemoryStore, PlaybookEntry

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def _observation() -> Observation:
    return Observation(
        domain="beverage",
        subject="Casa Madero",
        summary="Wine attachment increased.",
        metrics=(Metric(name="wine_attachment", value=0.21, unit="ratio"),),
        source_ref="restaurantos://reports/beverage/weekly/2026-W30",
        observed_at=OBSERVED_AT,
    )


def test_memory_store_adds_items():
    store = MemoryStore()
    observation = _observation()
    store.add(observation)
    assert store.count() == 1
    assert store.all()[0] == observation


def test_stored_observation_is_the_contract_type():
    store = MemoryStore()
    store.add(_observation())
    stored = store.all()[0]
    assert stored.observation_id.startswith("obs_")
    assert stored.has_metric("wine_attachment")
    assert stored.observed_at == OBSERVED_AT
    assert stored.source_ref is not None


def test_memory_store_holds_several_kinds():
    store = MemoryStore()
    store.add(_observation())
    store.add(Experiment.create("Wine sampling", "Sampling lifts attachment."))
    store.add(PlaybookEntry.create("Wine sampling standard", "Offer one sample."))
    assert store.count() == 3


def test_create_experiment():
    experiment = Experiment.create(
        "Wine sampling",
        "Offering targeted samples increases wine attachment.",
    )
    assert experiment.name == "Wine sampling"
    assert experiment.hypothesis


def test_create_decision():
    decision = Decision.create(
        "Adopt wine sampling",
        "Wine attachment increased during the test.",
    )
    assert decision.summary == "Adopt wine sampling"


def test_create_playbook_entry():
    entry = PlaybookEntry.create(
        "Wine sampling standard",
        "Offer one thoughtful sample when it builds guest confidence.",
    )
    assert entry.title == "Wine sampling standard"
