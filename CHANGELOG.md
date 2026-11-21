# Changelog

## [Unreleased]
### Added
- RestaurantOS peer API (`restaurantos serve`, `atlas-restaurantos-api.service`):
  a read-only loopback service JARVIS routes to. Relative figures only; no
  absolute dollar or cover figure is returned.
- Peer API summaries report, per period, how many nights are missing or in
  review; the nightly manifest now lists reviewed nights by date.
- Briefings feed for the Atlas briefings phone app (ADR-0003): `GET /v1/health`,
  `GET /v1/briefings` (an incremental change feed with `since`, cursors,
  `has_more` and tombstones) and `GET /v1/briefings/{id}` on the peer API. One
  relative-only Markdown briefing per service night; no absolute figure is
  ever included. Partial nights read `no comparison available` for the
  headlines they lack and cap confidence at Medium.
- `restaurantos briefings-refresh` builds `briefings.json` next to the ledger,
  and the nightly run calls it last. The step is optional: a failure or a
  timeout is reported on one stderr line and never fails the nightly unit. A
  damaged file is rebuilt from the ledger under a new generation, so older
  cursors answer `invalid_cursor`. Writing the file needs a POSIX host; every
  other `restaurantos` command still runs without `fcntl`.
- Optional `ATLAS_BRIEFINGS_TOKEN`: a second token for the phone, accepted
  only on the briefing routes (not `/v1/freshness`, `/v1/operating-summary` or
  `/v1/decisions`). `ATLAS_API_TOKEN` keeps working everywhere.
- `restaurantos.coverage` holds the manifest reading and night counting shared
  by the API and the briefings writer; `restaurantos.api` still exports
  `read_reviews` and `read_partial_nights`.
- `docs/operations/briefings-app-contract.md` (the app contract as
  implemented) and manual Tailscale Serve steps in `deploy/README.md`. The
  service stays on loopback.
### Fixed
- Nightly reports whose figures block is typed with dashes (`LABOR- $3,500`)
  are now read; previously only the narrative covers were recovered.
- `Total in House` and `Total in Dining` (the 2026-11 template) are read as
  total and dining-room covers.
- A dated EOD report with no figures in its text is now reviewed as
  `primary_without_operational_data` instead of being skipped without a trace.

## [0.2.0] - 2026-07-02
### Added
- Atlas monorepo structure.
- Core engine package placeholders.
- Architecture, vision, and RFC documentation.
