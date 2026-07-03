from atlas_memory import (
    Decision,
    Experiment,
    MemoryStore,
    Observation,
    PlaybookEntry,
)


def test_memory_store_adds_items():
    store = MemoryStore()

    observation = Observation.create(
        "Wine attachment increased.",
        {"wine_attachment": 0.21},
    )

    store.add(observation)

    assert store.count() == 1
    assert store.all()[0] == observation


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