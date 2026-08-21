from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_WORKLOAD_ID = re.compile(r"^[a-z][a-z0-9-]*$")
_UNIT_NAME = re.compile(r"^atlas-[a-z0-9][a-z0-9-]*\.(service|timer)$")
_ALLOWED_KEYS = {
    "id",
    "data_dirs",
    "required_private_files",
    "services",
    "autostart_services",
    "timers",
}


def _validate_relative_path(value: str, *, label: str) -> None:
    if (
        not value
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or "\\" in value
    ):
        raise ValueError(f"{label} must be a normalized relative POSIX path: {value!r}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"{label} contains an unsafe path segment: {value!r}")


def _validate_unit(value: str, *, suffix: str) -> None:
    if not _UNIT_NAME.fullmatch(value) or not value.endswith(suffix):
        raise ValueError(f"expected Atlas {suffix} unit name, got {value!r}")


def _unique(values: tuple[str, ...], *, label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} contains duplicate values")


@dataclass(frozen=True, slots=True)
class WorkloadSpec:
    workload_id: str
    data_dirs: tuple[str, ...] = ()
    required_private_files: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    autostart_services: tuple[str, ...] = ()
    timers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _WORKLOAD_ID.fullmatch(self.workload_id):
            raise ValueError(f"invalid workload id: {self.workload_id!r}")

        _unique(self.data_dirs, label="data_dirs")
        _unique(self.required_private_files, label="required_private_files")
        _unique(self.services, label="services")
        _unique(self.autostart_services, label="autostart_services")
        _unique(self.timers, label="timers")

        for relative in self.data_dirs:
            _validate_relative_path(relative, label="data directory")
        for relative in self.required_private_files:
            _validate_relative_path(relative, label="required private file")
            if not any(
                relative.startswith(f"{directory}/") for directory in self.data_dirs
            ):
                raise ValueError(
                    "required private file must live beneath a declared "
                    f"data directory: {relative!r}"
                )

        for service in self.services:
            _validate_unit(service, suffix=".service")
        for service in self.autostart_services:
            _validate_unit(service, suffix=".service")
            if service not in self.services:
                raise ValueError(
                    "autostart service must also be declared in services: "
                    f"{service!r}"
                )
        for timer in self.timers:
            _validate_unit(timer, suffix=".timer")

        if self.timers and not self.services:
            raise ValueError("timer workloads must declare at least one service")

    def is_ready(self, data_root: str | Path) -> bool:
        root = Path(data_root)
        return all(
            (root / relative).is_file() and (root / relative).stat().st_size > 0
            for relative in self.required_private_files
        )


@dataclass(frozen=True, slots=True)
class WorkloadRegistry:
    workloads: tuple[WorkloadSpec, ...]

    def __post_init__(self) -> None:
        if not self.workloads:
            raise ValueError("workload registry must contain at least one workload")

        ids: set[str] = set()
        units: dict[str, str] = {}
        for workload in self.workloads:
            if workload.workload_id in ids:
                raise ValueError(f"duplicate workload id: {workload.workload_id}")
            ids.add(workload.workload_id)

            for unit in (*workload.services, *workload.timers):
                owner = units.get(unit)
                if owner is not None:
                    raise ValueError(
                        f"unit {unit!r} is declared by both {owner!r} and "
                        f"{workload.workload_id!r}"
                    )
                units[unit] = workload.workload_id

    @property
    def data_dirs(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    directory
                    for workload in self.workloads
                    for directory in workload.data_dirs
                }
            )
        )

    @property
    def services(self) -> tuple[str, ...]:
        return tuple(
            service for workload in self.workloads for service in workload.services
        )

    @property
    def timers(self) -> tuple[str, ...]:
        return tuple(timer for workload in self.workloads for timer in workload.timers)

    def workload(self, workload_id: str) -> WorkloadSpec:
        for workload in self.workloads:
            if workload.workload_id == workload_id:
                return workload
        raise KeyError(workload_id)

    def ready_autostart_services(self, data_root: str | Path) -> tuple[str, ...]:
        return tuple(
            service
            for workload in self.workloads
            if workload.is_ready(data_root)
            for service in workload.autostart_services
        )

    def blocked_autostart_services(self, data_root: str | Path) -> tuple[str, ...]:
        return tuple(
            service
            for workload in self.workloads
            if not workload.is_ready(data_root)
            for service in workload.autostart_services
        )

    def ready_timers(self, data_root: str | Path) -> tuple[str, ...]:
        return tuple(
            timer
            for workload in self.workloads
            if workload.is_ready(data_root)
            for timer in workload.timers
        )

    def blocked_timers(self, data_root: str | Path) -> tuple[str, ...]:
        return tuple(
            timer
            for workload in self.workloads
            if not workload.is_ready(data_root)
            for timer in workload.timers
        )


def _string_tuple(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"workload {key} must be a list of strings")
    return tuple(value)


def load_workload_registry(path: str | Path) -> WorkloadRegistry:
    with Path(path).open("rb") as handle:
        payload = tomllib.load(handle)

    raw_workloads = payload.get("workloads")
    if not isinstance(raw_workloads, list):
        raise ValueError("workload manifest requires [[workloads]] entries")

    workloads: list[WorkloadSpec] = []
    for raw in raw_workloads:
        if not isinstance(raw, dict):
            raise ValueError("each workload entry must be a TOML table")
        unknown = set(raw) - _ALLOWED_KEYS
        if unknown:
            raise ValueError(f"unknown workload keys: {sorted(unknown)!r}")

        workload_id = raw.get("id")
        if not isinstance(workload_id, str):
            raise ValueError("workload id must be a string")

        workloads.append(
            WorkloadSpec(
                workload_id=workload_id,
                data_dirs=_string_tuple(raw, "data_dirs"),
                required_private_files=_string_tuple(raw, "required_private_files"),
                services=_string_tuple(raw, "services"),
                autostart_services=_string_tuple(raw, "autostart_services"),
                timers=_string_tuple(raw, "timers"),
            )
        )

    return WorkloadRegistry(tuple(workloads))
