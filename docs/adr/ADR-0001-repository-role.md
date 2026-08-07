# ADR-0001: Repository Role

Status: Accepted
Date: 2026-08-06

## Context

JAM conformance requires a repository to declare its platform role, and to
state what it owns and what it does not. Atlas had neither, so its boundaries
lived in the heads of whoever had worked on it most recently.

Naming what a repository does not own matters more than naming what it does.
Ownership tends to expand quietly: a reasoning engine that renders a report is
one commit away from owning presentation, and nothing stops it if nothing was
written down.

## Decision

Atlas is the **operational intelligence engine** of the BarelySmash platform.

> Operational intelligence for BarelySmash: observes operational records,
> interprets them against declared goals, and emits Decisions.

### Atlas owns

- **Operational records.** `OperationalRecord` is Atlas's internal
  vocabulary for a measurement: its grain, its aggregation, and how records
  roll up into comparable blocks.
- **Observation.** Turning records into measurement events, including
  period-over-period change and streaks.
- **Interpretation.** Assessing movement against declared goals, and
  producing Insights with a confidence that scales with corroborating
  evidence.
- **Recommendation.** Producing Decisions from interpretations, with a
  category, a priority, and reversibility stated per recommendation.
- **Reporting what it could not evaluate.** A goal metric with no data is
  named rather than passed over, because silence is indistinguishable from
  nothing being wrong.

### Atlas does not own

- **The contracts.** JAM defines Observation, Insight, Decision, and
  DecisionState. Atlas implements them and vendors the schemas it validates
  against under `packages/atlas-core/tests/contracts/`, pinned to a JAM
  release. Atlas does not extend a contract; it proposes changes to JAM.
- **The decision category registry.** JAM's `glossary/` is authoritative.
  Atlas emits categories from it.
- **Synthesis and orchestration.** JARVIS decides what to surface, to whom,
  and when. JARVIS is never a source of a Decision, and Atlas never
  addresses a consumer directly.
- **Decision lifecycle.** Whether a Decision was accepted, executed, or
  rejected belongs to the consumer as DecisionState. Atlas emits and does
  not track.
- **Trading.** Friday's domain. Atlas emits no `friday.*` category.
- **Presentation.** `ExecutiveBrief` renders a result as markdown for
  convenience. A brief is not a Decision, nothing may parse one, and any
  real presentation layer belongs to the application.

## Consequences

A change that would have Atlas track what happened to a Decision, define a new
contract field, or address a consumer directly is out of scope for this
repository and needs a JAM change or a different one.

The boundary is only partly enforced. The contract test proves Atlas emits
documents JAM accepts; nothing yet proves Atlas does not reach past the
boundaries above.

## Exceptions

JAM conformance asks that deviations be recorded with their scope and
remediation. Atlas carries four.

**RestaurantOS shares this repository.** `apps/restaurantos` is an
application, not part of the engine, and the manifest has one repository type.
It reaches into `atlas_core` through a relative `pythonpath` and would be a
separate repository if it were larger. *Temporary; remediation is extraction.*

**`Goal.category` is validated for shape, not membership.** Atlas checks that
a category matches `^atlas\.[a-z][a-z0-9_]*$` but does not carry JAM's
category registry, so an unregistered but well-formed value passes locally and
fails in JAM's validator. *Temporary; remediation is vendoring
`decision-categories.json` beside the schemas already pinned under
`tests/contracts/`.*

**Two mechanisms resolve cross-package imports.** Each package declares the
sibling source it needs on `pytest`'s `pythonpath`, so a bare `pytest` works
with no install, and CI additionally installs every package editable so mypy
can resolve the same imports. Both are needed: `pytest` does not read an
install, and mypy does not read `pythonpath`. *Permanent, and worth revisiting
if a third mechanism appears.*
