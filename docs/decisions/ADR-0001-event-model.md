# ADR-0001 — Atlas Event Model

Status: Accepted

Date: 2026-07-02

## Context

Atlas is designed as a reusable operational intelligence platform.

The system must preserve organizational knowledge, provide explainable recommendations, and support historical analysis.

Traditional CRUD applications overwrite state.

Atlas requires memory.

## Decision

Atlas will use an event-driven architecture.

Important business actions are represented as immutable events.

Examples:

- TABC_REFRESHED
- POS_IMPORTED
- MENU_CHANGED
- PRICE_CHANGED
- EXPERIMENT_STARTED
- EXPERIMENT_COMPLETED
- PLAYBOOK_UPDATED
- AI_RECOMMENDATION_ACCEPTED

Current state is produced by projecting events.

Not every raw transaction must become an event. High-volume operational data may remain in source tables while significant business actions are represented as events.

## Consequences

Benefits

- Complete history
- Explainable recommendations
- Replay capability
- Experiment tracking
- Organizational memory

Tradeoffs

- More implementation complexity
- Projection layer required
- Event schema versioning required

The benefits outweigh the costs because Atlas is designed as a long-lived decision platform rather than a simple reporting application.
