# Atlas Runtime

Shared host/runtime contracts for Atlas workloads.

The package defines the declarative workload registry used by Guildenstern deploys to decide which persistent data directories belong to a workload, which private files make it ready, and which systemd user services/timers should be active.

It does not orchestrate agent behavior. Workload code remains isolated in its own package/app; systemd remains the process supervisor.
