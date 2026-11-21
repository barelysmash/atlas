# Changelog

## [Unreleased]
### Added
- RestaurantOS peer API (`restaurantos serve`, `atlas-restaurantos-api.service`):
  a read-only loopback service JARVIS routes to. Relative figures only; no
  absolute dollar or cover figure is returned.
- Peer API summaries report, per period, how many nights are missing or in
  review; the nightly manifest now lists reviewed nights by date.
- Briefings feed for the Atlas briefings phone app: `GET /v1/health`,
  `GET /v1/briefings` (incremental change feed with `since`, cursors,
  `has_more` and tombstones) and `GET /v1/briefings/{id}` on the peer API.
  One relative-only Markdown briefing per service night (`"figures":
  "relative_only"`); no absolute figure is ever included.
- `restaurantos briefings-refresh` builds the briefings file
  (`restaurantos/fonda/briefings.json`) from the ledger; the nightly run
  calls it after a successful refresh. A briefing's `updated_at` changes only
  when its content does; nights that leave the ledger become tombstones.
- Optional `ATLAS_BRIEFINGS_TOKEN`: a second token for the phone, accepted
  only on the briefing routes. `ATLAS_API_TOKEN` keeps working everywhere.
- Briefings hardening: the nightly unit never fails because of the optional
  briefings step (its failure is reported on one stderr line); a damaged
  briefings file is reported and rebuilt from the ledger, under a new
  generation so cursors from before the rebuild answer `invalid_cursor` and
  the phone re-downloads every briefing once; concurrent refreshes are
  serialised by a lock on `briefings.json.lock`; the manifest reading and
  flagged-night counting are shared in `restaurantos.coverage`, so
  `briefings-refresh` no longer loads the HTTP server; confidence lines say
  only that no night is flagged. The API unit's `ExecStart` is unchanged: the
  feed reads the default `briefings.json` next to `--history`.
- Briefings generations are strict: a cursor without a generation answers
  `invalid_cursor`, and a briefings file without one answers
  `briefings_unavailable` until `briefings-refresh` rebuilds it. A refresh
  reads the ledger only once it holds the lock. The serve defaults live in
  `restaurantos.api_defaults`, shared by the CLI and the API.
- ADR-0003, `docs/operations/briefings-app-contract.md` (the app contract as
  implemented, with every deviation from the app's draft) and manual
  Tailscale Serve steps in `deploy/README.md`. The service stays on loopback.
- Briefings and partial nights (upstream `151fbf6`): a briefing for a partial
  night (filled from an approved point-of-sale summary: net sales and voids
  only), or one compared with a partial night, reads `no comparison
  available` for every headline that night lacks and says why in one line;
  the coverage section counts partial nights in both month windows; a
  comparison that rests on a partial night is at most Medium confidence.
  `read_partial_nights` and `count_partial_nights` live in
  `restaurantos.coverage`, shared with `/v1/operating-summary`'s
  `nights_partial` (`restaurantos.api.read_partial_nights` is still
  importable). The first refresh after the upgrade gives every briefing a new
  `updated_at` once (new coverage lines).
### Changed
- The phone token (`ATLAS_BRIEFINGS_TOKEN`) cannot open upstream's
  `GET /v1/decisions`, a JARVIS route; it gets `401` there like on
  `/v1/freshness` and `/v1/operating-summary`. Briefings do not include
  Decisions.
- The nightly briefings step's time limit is 600 seconds (was 300), so a
  refresh waiting behind a slow manual one is not killed early. The step
  still runs last, after upstream's ledger refresh (with `--overrides`,
  `--approved-imports` and `--goals` when present).
- `briefings-refresh` checks the ledger with `stat()` before taking its lock
  and requires a regular file: a FIFO, socket or device is reported as "not a
  regular file" (a FIFO is never opened, so nothing blocks), a directory as a
  directory, and nothing is created. It uses `stat()` rather than `exists()`
  on purpose: `stat()` raises the real error (for example `Permission
  denied`) where `exists()` would report the ledger as missing.
- Tests that need POSIX `flock` are marked explicitly with `needs_flock`
  (`apps/restaurantos/tests/_posix.py`); the suite no longer turns the
  writer's POSIX error into a skip with a hook.
### Fixed
- `python -m restaurantos` works again on hosts without `fcntl` (Windows):
  only `briefings-refresh` imports the briefings writer, which imports `fcntl`
  lazily and, without it, exits non-zero with one line saying the briefings
  file can only be written on a POSIX host.
- The nightly briefings step has a time limit; a timeout is reported on one
  stderr line and the nightly run still succeeds.
- `briefings-refresh` reports a ledger path that is a directory or cannot be
  read as such, instead of "No such file or directory".
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
