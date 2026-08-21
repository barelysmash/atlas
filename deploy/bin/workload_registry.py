from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

from atlas_runtime import load_workload_registry


def _emit(values: Iterable[str]) -> None:
    for value in values:
        print(value)


def main() -> int:
    parser = argparse.ArgumentParser(prog="atlas-workloads")
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "command",
        choices=(
            "validate",
            "workloads",
            "data-dirs",
            "services",
            "timers",
            "ready-services",
            "blocked-services",
            "ready-timers",
            "blocked-timers",
        ),
    )
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()

    registry = load_workload_registry(args.manifest)

    if args.command == "validate":
        print(f"workloads={len(registry.workloads)}")
        return 0
    if args.command == "workloads":
        _emit(workload.workload_id for workload in registry.workloads)
        return 0
    if args.command == "data-dirs":
        _emit(registry.data_dirs)
        return 0
    if args.command == "services":
        _emit(registry.services)
        return 0
    if args.command == "timers":
        _emit(registry.timers)
        return 0

    if args.data_root is None:
        parser.error(f"{args.command} requires --data-root")

    if args.command == "ready-services":
        _emit(registry.ready_autostart_services(args.data_root))
    elif args.command == "blocked-services":
        _emit(registry.blocked_autostart_services(args.data_root))
    elif args.command == "ready-timers":
        _emit(registry.ready_timers(args.data_root))
    else:
        _emit(registry.blocked_timers(args.data_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
