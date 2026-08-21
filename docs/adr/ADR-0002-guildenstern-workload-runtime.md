# ADR-0002: Guildenstern workload runtime

## Status

Accepted

## Context

Atlas is moving from a single RestaurantOS scheduled task to multiple independently developed workloads running on Guildenstern. Each workload may need persistent private state, long-running services, scheduled timers, or manual one-shot execution.

Encoding those details directly in deployment shell scripts would couple host operations to individual applications and create a new branch of bespoke deployment logic for every subagent.

## Decision

Atlas will use a declarative workload registry as the host/runtime contract.

Each workload declares:

- a stable workload id;
- persistent data directories relative to the shared Atlas data root;
- private files that must exist and be non-empty before the workload is considered ready;
- systemd user service units owned by the workload;
- the subset of services that should autostart; and
- systemd user timers that should be active when the workload is ready.

The registry is public configuration and never contains credentials or private data values.

Guildenstern deployment will:

1. install a complete immutable Atlas release and its per-release virtual environment;
2. validate the workload registry before switching the current-release symlink;
3. create only the declared persistent data directories under `~/atlas-data`;
4. install the active release's declared Atlas systemd units;
5. disable units removed from the registry;
6. enable or restart only workloads whose declared private readiness requirements are satisfied; and
7. use the same reconciliation path during rollback.

Systemd remains the process supervisor. The workload registry does not implement agent orchestration, routing, memory, reasoning, or inter-agent messaging.

## Consequences

Adding a new Guildenstern workload becomes a bounded change: add the application/package, declare its workload contract, add its systemd units, and provide any private state out-of-band.

Deploy and rollback share one activation algorithm, reducing drift. Removing a workload also retires its Atlas systemd units instead of leaving stale enabled processes behind.

A first deployment after this ADR retains a temporary compatibility rollback path for the pre-registry RestaurantOS release. That path can be removed once all retained rollback releases contain the workload registry.

## Privacy

Release archives continue to be built from Git-tracked files only. Persistent credentials and operational data remain outside release directories under `~/atlas-data` and are never represented by values in the workload registry.
