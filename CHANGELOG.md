# Changelog

## [Unreleased]
### Added
- RestaurantOS peer API (`restaurantos serve`, `atlas-restaurantos-api.service`):
  a read-only loopback service JARVIS routes to. Relative figures only; no
  absolute dollar or cover figure is returned.
- Peer API summaries report, per period, how many nights are missing or in
  review; the nightly manifest now lists reviewed nights by date.
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
