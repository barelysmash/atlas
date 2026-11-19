# RestaurantOS Decisions

Atlas judges the nightly ledger against the venue's goals and emits JAM
Decisions. It runs as part of the nightly refresh; there is no separate job.

## Turning it on

Decisions are emitted only when a goals file exists:

```text
~/atlas-data/restaurantos/fonda/goals.json
```

The file is private host state. It is not in this repository and a deploy
never writes it. Without it the refresh behaves exactly as before and the
peer API answers `not_configured`.

```json
{
  "goals": [
    {
      "summary": "Grow sales",
      "priority": "high",
      "category": "atlas.marketing",
      "targets": [
        {"metric": "net_sales", "direction": "increase", "tolerance": 5}
      ]
    }
  ]
}
```

- `direction` is `increase`, `decrease` or `maintain`.
- `tolerance` is a dead band in percentage points of week-over-week change.
  Movement inside it counts as flat. Restaurants are noisy week to week; a
  band that is too tight turns ordinary variation into Decisions.
- `priority` is `high`, `medium` or `low`. A metric moving against its goal
  yields a Decision at the goal's priority; one moving with it yields a
  "sustain" Decision one step lower.
- `category` must be a category registered in JAM's glossary. The registry
  has no sales category today; `atlas.marketing` is the nearest fit.

Metrics that can be targeted: the nightly facts (`net_sales`, `guest_count`,
`labor_hours`, `labor_cost`, ...) and the rates derived from them (`splh`,
`average_check`, `labor_cost_pct`, `reservation_share`, `comp_pct`,
`void_pct`, ...).

A malformed goals file is reported in the refresh output as
`decisions_error=` and never blocks the ledger rebuild.

## How a Decision is reached

1. Only the trailing eight weeks of the ledger are considered.
2. Nights are grouped into calendar weeks. A week with fewer reported nights
   than usual is dropped for that metric, so the current week, a week with a
   missing night, and (for labor and cover metrics) a week containing a
   partial Toast night are not judged.
3. Rates are derived from each week's totals, never averaged from nightly
   rates.
4. Each goal metric is observed week over week, and as a streak when it has
   moved the same way for several weeks.
5. A movement outside the tolerance, against or with the goal, becomes a
   Decision. Every Decision requires approval; none is executed.

When a week is dropped for a metric, the comparison reaches back to the
week before it. So metrics in one run can rest on different pairs of weeks,
and their changes cannot be combined. The peer API names the weeks on every
citation (`week_of`, `compared_with_week_of`, `weeks_skipped_between`).

A week-over-week comparison does not know about holidays, weather or events.
A Decision says a metric moved against or with a goal. It does not say why.

## Outputs

`~/atlas-data/restaurantos/fonda/nightly-decisions.json` (owner-only) holds
the full JAM Decision documents, absolute figures included, plus the goal
metrics that could not be evaluated. A finding that is unchanged from the
previous run keeps its `decision_id` and `created_at`; a new week produces
new Decisions.

`GET /v1/decisions` on the peer API serves a relative-only projection for
JARVIS: direction and percent change per citation, the engine's summary,
rationale and recommendations, and how long ago the Decision first appeared.
It is built field by field and never copies an evidence statement or a metric
value from the private documents.
