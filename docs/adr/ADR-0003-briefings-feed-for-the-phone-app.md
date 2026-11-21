# ADR-0003: Briefings feed for the phone app

## Status

Accepted

## Context

A separate iPhone app, Atlas briefings, shows the owner one short briefing per
service night. Its API contract was written against a mock server before anyone
looked at Atlas. Atlas already runs a read-only peer API for JARVIS
(`restaurantos serve`, `atlas-restaurantos-api.service`) with deliberate rules:
relative figures only (`FIGURES_POLICY = "relative_only"`), the API never
writes, loopback binding, standard library only, and one shared bearer token
(`ATLAS_API_TOKEN`) that opens every route. Its JARVIS routes are
`GET /v1/freshness`, `POST /v1/operating-summary` and, since upstream
`151fbf6`, `GET /v1/decisions` (a relative-only projection of JAM Decisions).

The phone is a new consumer outside the host. It needs a change feed it can
sync incrementally (stable ids, `updated_at`, deletions), a way to reach the
service, and a credential that is not the JARVIS token.

## Decision

**Relative-only briefings.** Briefings are built from `relative_summary`, never
from the dollar-bearing text of `generate_operating_brief`. Each briefing
compares the night with the same weekday a week earlier and month to date with
the aligned days of the prior month, for net sales, covers, average check,
sales per labor hour (percent changes) and labor cost share, reservation
share, comp and void rates (percentage points), and states coverage (nights in review and
missing this month) and a confidence level that follows from it. Every
briefing and every feed response carries `"figures": "relative_only"`. The
entity name is not sent in clear; the briefing id carries a short hash of it
(`brf_<date>_<8 hex>`). That hash is an identifier, not a secret: a short,
guessable name can be recovered from it by trying candidates.

**A nightly-owned briefings file.** The nightly workload owns all stored
state. After `gmail-nightly-refresh` succeeds, `restaurantos_nightly.py` runs
`restaurantos briefings-refresh`, which writes
`~/atlas-data/restaurantos/fonda/briefings.json` (mode 600, atomic replace)
next to the ledger. A briefing keeps its `updated_at` unless its content hash
changes, so an unchanged ledger leaves the file byte-for-byte as it was and
the phone neither re-downloads nor re-notifies. A night that leaves the ledger
becomes a tombstone with a new `updated_at`. New stamps are strictly later
than every stamp already in the file, which keeps the `(updated_at, id)`
change-feed order and its cursors sound. The API reads the file, re-reading
only when it changes, as `Ledger` does; until the first nightly run writes
it, the feed answers `503 briefings_unavailable` and the other routes keep
working. The file is not a readiness requirement in `deploy/workloads.toml`,
and the API unit's `ExecStart` is unchanged: `serve` defaults to
`briefings.json` next to `--history`, the file the nightly writes.

**The feed never fails the nightly unit.** The briefings step runs after the
ledger refresh and operating brief, which keep `check=True`. A non-zero exit
or an exception from `briefings-refresh` is caught and reported on one stderr
line that names the step and says the ledger refresh succeeded; the entry
point still returns 0. The phone keeps the previous briefings until the next
run.

**A damaged file heals itself.** If `briefings.json` exists but cannot be
read, is not valid JSON, or is not a briefings file, `briefings-refresh`
reports it on stderr, treats it as absent and rebuilds it from the ledger
instead of failing every night until someone deletes it. A rebuild (this, or
an operator deleting the file) assigns fresh `updated_at` values to every
briefing, so the phone re-downloads every briefing once. Each file built from
scratch gets a new random `generation`, kept by every later refresh and
carried in every cursor; a cursor from an earlier generation answers
`400 invalid_cursor`, which the app already handles by re-running its
backfill, so no phone silently misses a deletion across a rebuild. Cursors
stay valid across service restarts and token rotation, because the
generation lives in the file, not in the process.

**Refreshes are serialised.** `briefings-refresh` holds an exclusive `flock`
on `briefings.json.lock` (mode 600, standard library only) for the whole
read-compute-write, so a manual refresh during the nightly run waits instead
of both reading the same file and the later write winning. `fcntl` is
imported only when a refresh runs: no other `restaurantos` command loads the
briefings writer, so the CLI keeps working on a Windows development machine,
where `briefings-refresh` exits non-zero saying the file can only be written
on a POSIX host. There is no second locking scheme. The nightly runs the step
with a time limit of 600 seconds (`BRIEFINGS_TIMEOUT_SECONDS`), so a stuck lock
holder cannot hold the nightly unit, while a refresh that waits behind a slow
manual one still has room to finish. Before it takes the lock, a refresh
`stat()`s the ledger and requires a regular file: a missing ledger, one it may
not stat, a directory, a FIFO, socket or device is reported with its real
error and nothing is created (a FIFO is never opened, so nothing blocks).
`stat()` is used rather than `exists()` because `exists()` would report a
permission problem as a missing file.

**Partial nights.** Since upstream `151fbf6` a night with no readable nightly
e-mail can be filled from an approved Toast sales summary (`toast-approve`).
Such a *partial* night carries net sales and voids only: no labor, covers,
reservations or comps. The manifest lists them under `partial_nights`;
`restaurantos.coverage.read_partial_nights` reads them (the peer API's
`restaurantos.api.read_partial_nights` is the same function) and
`count_partial_nights` counts them per window, for `nights_partial` in
`/v1/operating-summary` and for briefings alike. A briefing whose night, or
whose week-earlier night, is partial shows `no comparison available` for
every headline that night lacks (covers, average check, sales per labor hour,
labor cost share, reservation share, comp rate) and says why in one plain
line: the night was filled from a point-of-sale summary, so only net sales
and voids are known. Net sales and void rate are compared as usual. Month to
date compares each metric over the nights that carry it (upstream's
arithmetic). The coverage section counts partial nights in both month
windows (`unknown` when the manifest has no `partial_nights` list).

**The partial-night confidence rule.** A comparison that rests on a partial
night is never High: a finding has one confidence line, and the metrics that
night lacks are either not compared (week) or compared over fewer nights
(month). So the week finding is at most Medium when either compared night is
partial, the month finding is at most Medium when a partial night falls in
either month window, and the overall level (and `confidence:` tag) is High
only when partial nights are known and none is compared or in either window.
Unknown partial nights also rule out High, like unknown coverage. Partial
nights never make a briefing Low by themselves: they are real nights with
real net sales and voids, not missing ones. A Medium rationale that a partial
night causes says `partial`; a High rationale still says only that nothing is
flagged or partial, never that a month has every night.

**One counting of flagged nights.** `restaurantos.coverage` reads the
manifest's per-night reviews (`read_reviews`) and counts flagged nights in a
window; the peer API's summaries and the briefings writer both use it, so the
two cannot drift and the nightly writer never loads the HTTP server. The
counts say only what the manifest flags: a night whose report never arrived
is not flagged, so a briefing's High confidence says "no night in either
month is flagged", not that the month has every night.

**A scoped phone token.** `ATLAS_BRIEFINGS_TOKEN` is optional, at least 24
characters, and must differ from `ATLAS_API_TOKEN`. It is accepted only on
`GET /v1/health`, `GET /v1/briefings` and `GET /v1/briefings/{id}`; on every
other path, including the JARVIS routes `/v1/freshness`,
`/v1/operating-summary` and `/v1/decisions`, it is answered
`401 unauthorized`, exactly like a wrong token, so it discloses nothing. The existing token keeps working everywhere. Tokens are
compared in constant time and never logged; configuration errors name the
variable, never its value. When the phone token is unset, the briefing routes
accept only `ATLAS_API_TOKEN`.

**Exposure through Tailscale Serve, loopback binding kept.** The service still
binds to `127.0.0.1` (`DEFAULT_HOST`, and `ATLAS_API_HOST=127.0.0.1` in the
unit with its hardening unchanged). An operator exposes only `/v1/briefings`
and `/v1/health` to the tailnet with `tailscale serve --set-path`, by hand on
the host, as `deploy/README.md` describes. No deploy runs Tailscale. JARVIS
routes (`/v1/freshness`, `/v1/operating-summary`, `/v1/decisions`) are not
mounted.

**Atlas conventions win over the app's draft contract.** Where the app's
contract and Atlas disagree (the `{"request_id", "data"}` and
`{"request_id", "error": {"code", "message"}}` envelopes, `401` before `404`,
trailing-slash tolerance, the id format, `internal_error`, `501` for methods
the server does not implement), Atlas's behaviour stands and the difference is
written down in `docs/operations/briefings-app-contract.md`, from which the
app is updated.

## Consequences

The phone holds a credential that can read briefings and nothing else; losing
the phone means rotating one token without touching JARVIS. Feed cursors are
stateless and validated structurally (no server-side cursor state, no
signature): a forged but well-formed cursor can only re-read what its bearer
may read anyway. They survive restarts and token rotation, but not a rebuild
of the file from scratch: those answer `400 invalid_cursor` and the phone
re-runs its backfill, re-downloading every briefing once.

Briefings follow the nightly schedule: a change in the ledger reaches the
phone after the next nightly run, not sooner. A ledger change touches only the
briefings whose comparison windows include the changed night.

Tombstones are kept in the file indefinitely so that any stored cursor can
still learn about a deletion; they are three small fields each.

The phone sees no absolute figure, ever. Anything the app's draft asked for
that would need one (forecasts in currency, cover counts, stock levels) is
left out and listed in the contract document.

Partial nights make some briefings say less: a week comparison against a
partial night compares net sales and void rate only, and its confidence is at
most Medium. The first refresh after the upgrade changes every briefing's
body (the new partial-night coverage lines), so the phone re-downloads each
briefing once, as for any content change.

Briefings do not include JAM Decisions. Adding a relative-only summary of
`/v1/decisions` to briefings is a possible follow-up; it would need its own
decision on scope and wording. The phone token stays unable to open
`/v1/decisions`.

## Privacy

Fixtures and tests use synthetic values and names only. A privacy test builds
briefings from a ledger of distinctive absolute values and asserts that none
of them, no window total or average, no currency symbol and no entity name
appears in any feed response. The briefings file is private host state under
`~/atlas-data` and is never part of a release.
