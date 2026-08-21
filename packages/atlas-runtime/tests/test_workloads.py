from pathlib import Path

import pytest
from atlas_runtime.workloads import (
    WorkloadRegistry,
    WorkloadSpec,
    load_workload_registry,
)


def _manifest(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_load_registry_and_resolve_activation_by_private_state(tmp_path: Path):
    manifest = _manifest(
        tmp_path / "workloads.toml",
        """
[[workloads]]
id = "restaurantos"
data_dirs = ["google", "restaurantos/fonda"]
required_private_files = [
  "google/gmail-token.json",
  "restaurantos/fonda/nightly-messages.jsonl",
]
services = ["atlas-restaurantos-nightly.service"]
timers = ["atlas-restaurantos-nightly.timer"]

[[workloads]]
id = "worker"
data_dirs = ["worker"]
services = ["atlas-worker.service"]
autostart_services = ["atlas-worker.service"]
""",
    )
    registry = load_workload_registry(manifest)

    assert registry.data_dirs == ("google", "restaurantos/fonda", "worker")
    assert registry.services == (
        "atlas-restaurantos-nightly.service",
        "atlas-worker.service",
    )
    assert registry.timers == ("atlas-restaurantos-nightly.timer",)
    assert registry.workload("restaurantos").is_ready(tmp_path) is False
    assert registry.ready_autostart_services(tmp_path) == ("atlas-worker.service",)
    assert registry.blocked_timers(tmp_path) == ("atlas-restaurantos-nightly.timer",)

    (tmp_path / "google").mkdir()
    (tmp_path / "restaurantos/fonda").mkdir(parents=True)
    (tmp_path / "google/gmail-token.json").write_text("token", encoding="utf-8")
    (tmp_path / "restaurantos/fonda/nightly-messages.jsonl").write_text(
        "{}\n", encoding="utf-8"
    )

    assert registry.workload("restaurantos").is_ready(tmp_path) is True
    assert registry.ready_timers(tmp_path) == ("atlas-restaurantos-nightly.timer",)
    assert registry.blocked_timers(tmp_path) == ()
    assert registry.blocked_autostart_services(tmp_path) == ()


def test_registry_rejects_duplicate_workload_ids():
    workload = WorkloadSpec(workload_id="worker")
    with pytest.raises(ValueError, match="duplicate workload id"):
        WorkloadRegistry((workload, workload))


def test_registry_rejects_duplicate_unit_ownership():
    first = WorkloadSpec(
        workload_id="first",
        services=("atlas-shared.service",),
    )
    second = WorkloadSpec(
        workload_id="second",
        services=("atlas-shared.service",),
    )
    with pytest.raises(ValueError, match="declared by both"):
        WorkloadRegistry((first, second))


def test_workload_rejects_unsafe_private_path():
    with pytest.raises(ValueError, match="unsafe path segment"):
        WorkloadSpec(
            workload_id="bad",
            data_dirs=("private",),
            required_private_files=("private/../secret",),
        )


def test_workload_requires_private_files_under_declared_data_dirs():
    with pytest.raises(ValueError, match="beneath a declared data directory"):
        WorkloadSpec(
            workload_id="bad",
            data_dirs=("data",),
            required_private_files=("other/token.json",),
        )


def test_workload_rejects_invalid_units_and_autostart_membership():
    with pytest.raises(ValueError, match=r"expected Atlas \.service"):
        WorkloadSpec(workload_id="bad", services=("worker.service",))

    with pytest.raises(ValueError, match="also be declared"):
        WorkloadSpec(
            workload_id="bad",
            services=("atlas-worker.service",),
            autostart_services=("atlas-other.service",),
        )

    with pytest.raises(ValueError, match="timer workloads"):
        WorkloadSpec(
            workload_id="bad",
            timers=("atlas-worker.timer",),
        )


def test_manifest_rejects_unknown_keys_and_bad_field_types(tmp_path: Path):
    unknown = _manifest(
        tmp_path / "unknown.toml",
        """
[[workloads]]
id = "worker"
magic = true
""",
    )
    with pytest.raises(ValueError, match="unknown workload keys"):
        load_workload_registry(unknown)

    bad_list = _manifest(
        tmp_path / "bad-list.toml",
        """
[[workloads]]
id = "worker"
data_dirs = "worker"
""",
    )
    with pytest.raises(ValueError, match="list of strings"):
        load_workload_registry(bad_list)


def test_manifest_rejects_missing_tables_and_bad_ids(tmp_path: Path):
    missing = _manifest(tmp_path / "missing.toml", "name = 'atlas'\n")
    with pytest.raises(ValueError, match=r"\[\[workloads\]\]"):
        load_workload_registry(missing)

    bad_id = _manifest(
        tmp_path / "bad-id.toml",
        """
[[workloads]]
id = 5
""",
    )
    with pytest.raises(ValueError, match="id must be a string"):
        load_workload_registry(bad_id)

    with pytest.raises(ValueError, match="invalid workload id"):
        WorkloadSpec(workload_id="Bad Worker")


def test_registry_requires_workloads_and_lookup_reports_missing():
    with pytest.raises(ValueError, match="at least one workload"):
        WorkloadRegistry(())

    registry = WorkloadRegistry((WorkloadSpec(workload_id="worker"),))
    with pytest.raises(KeyError):
        registry.workload("missing")


def test_workload_rejects_duplicate_values_and_non_normalized_paths():
    with pytest.raises(ValueError, match="duplicate values"):
        WorkloadSpec(workload_id="bad", data_dirs=("data", "data"))

    with pytest.raises(ValueError, match="normalized relative POSIX path"):
        WorkloadSpec(workload_id="bad", data_dirs=("/absolute",))
