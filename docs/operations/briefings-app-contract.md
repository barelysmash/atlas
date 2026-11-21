# Atlas briefings app: the contract as implemented

This is the HTTP contract the Atlas briefings iPhone app must follow against a
real Atlas server (`restaurantos serve`, `atlas-restaurantos-api.service`). It
replaces the app's draft, "Atlas Briefings API — contract v1" (round 2), which
was written against a mock server before anyone looked at Atlas. Where the
draft and Atlas's existing conventions disagreed, Atlas's conventions were
kept; every such difference is in the [deviation table](#deviations-from-the-draft)
at the end, with the reason. Update the app from that table.

`api_version` is `"1"`.

Design record: `docs/adr/ADR-0003-briefings-feed-for-the-phone-app.md`.

## 1. Transport and authentication

- **Base URL.** `https://<machine>.<tailnet>.ts.net`, no path prefix. The
  service listens on `127.0.0.1:8790` only; an operator exposes
  `/v1/briefings` and `/v1/health` (and nothing else) to the tailnet with
  Tailscale Serve, which terminates HTTPS with the machine's tailnet
  certificate (see `deploy/README.md`). Every request therefore goes over
  `https://` on the tailnet. A trailing `/` on the base URL is ignored by the
  app; the server also tolerates a trailing `/` on any path.
- **Methods.** `GET` only on the briefing routes. Requests have no body.
- **Request headers.** `Authorization: Bearer <token>` on every request,
  including `GET /v1/health`. The scheme name is case-insensitive.
  `Accept: application/json` is optional.
- **Tokens.** The app uses `ATLAS_BRIEFINGS_TOKEN`, a token of at least 24
  characters that the operator sets on the host and the user pastes into the
  app. It is accepted on `GET /v1/health`, `GET /v1/briefings` and
  `GET /v1/briefings/{id}` only; on any other path, including the JARVIS
  routes `/v1/freshness`, `/v1/operating-summary` and `/v1/decisions`, it is
  answered `401 unauthorized`. (The JARVIS token, `ATLAS_API_TOKEN`, also opens these
  routes; the phone must never hold it.) If the operator has not set
  `ATLAS_BRIEFINGS_TOKEN`, the phone's token is refused everywhere with `401`.
- **Response headers.** Every JSON response has
  `Content-Type: application/json` (no `charset` parameter; the body is always
  UTF-8 JSON), `Cache-Control: no-store` and `Content-Length`. `405` carries
  `Allow: GET`. After a `401`, `404` or `405` the server may close the
  connection.
- **Bodies.** JSON encoded as UTF-8, keys sorted. Every JSON response is an
  envelope:
  - success: `{"request_id": "<hex>", "data": <payload>}`;
  - error: `{"request_id": "<hex>", "error": {"code": "<code>", "message": "<text>"}}`.

  `request_id` is a random hex string that identifies the request in the
  server journal; quote it when reporting a problem. `message` is for logs
  only and must not be parsed.
- **Timestamps** are RFC 3339 UTC in whole seconds (`2026-11-15T11:31:02Z`).
  Accept fractional seconds too, in case that changes.
- **Dates** are service dates `YYYY-MM-DD` in the restaurant's frame
  (America/Chicago): the night a service took place, not the calendar day the
  report arrived.
- **Figures.** Every payload carries `"figures": "relative_only"`. Atlas never
  sends an absolute dollar amount, cover or guest count, labor-hour total or
  rate level, nor the restaurant's name.

## 2. Request processing order

The server evaluates a request in this order and answers with the first error
that applies:

1. Method not implemented by the HTTP server at all (anything except `GET` and
   `POST`, e.g. `PUT`, `DELETE`, `HEAD`, `OPTIONS`) → `501`, with a non-JSON
   body, before authentication. The app only sends `GET`.
2. `GET /health` (no `/v1`) → `200` liveness, no authentication. This is the
   operator's loopback check and is not mounted on the tailnet.
3. Authentication → `401 unauthorized`: the `Authorization` header is missing,
   is not `Bearer <token>`, or the token is not valid **for this path**. Any
   path that is not one of the three briefing routes (including `/nope`,
   `/v1/nope`, `/v1/briefings/a/b`) is a `401` for the phone token, so the
   server tells an unauthenticated or phone caller nothing about which routes
   exist.
4. Routing → `404 not_found` (only reachable with the JARVIS token).
5. Method on a briefing route other than `GET` (i.e. `POST`) →
   `405 method_not_allowed`, with `Allow: GET`.
6. Parameter validation, `GET /v1/briefings` only, in this order:
   1. `limit` → `400 invalid_limit`;
   2. if `cursor` is present: `cursor` → `400 invalid_cursor` (`since` is then
      ignored and not validated);
   3. otherwise `since` → `400 invalid_since`.
7. Briefings file → `503 briefings_unavailable` when the nightly run has not
   written the briefings file yet (or it cannot be read). `GET /v1/health`
   does not depend on it. Then a well-formed `cursor` issued before the file
   was rebuilt from scratch → `400 invalid_cursor` (section 7).
8. Lookup: `GET /v1/briefings/{id}` for an unknown or deleted id →
   `404 not_found`.

An unexpected server fault → `500 internal_error`.

## 3. Errors

| HTTP status | `error.code`            | When                                                                   |
| ----------- | ----------------------- | ---------------------------------------------------------------------- |
| 400         | `invalid_limit`         | `limit` is not a decimal integer in 1..100, or is repeated.            |
| 400         | `invalid_since`         | `since` is not a real `YYYY-MM-DD` date, or is repeated (no `cursor`). |
| 400         | `invalid_cursor`        | `cursor` is empty, corrupt, repeated, not issued by this server, or issued before the briefings file was rebuilt. |
| 401         | `unauthorized`          | Missing or wrong token, or a token not valid for the path.             |
| 404         | `not_found`             | Unknown route (JARVIS token only), unknown or deleted briefing.        |
| 405         | `method_not_allowed`    | `POST` to a briefing route.                                            |
| 500         | `internal_error`        | Unexpected server fault.                                               |
| 501         | (no JSON body)          | A method the server does not implement (`PUT`, `HEAD`, `OPTIONS`, ...). |
| 503         | `briefings_unavailable` | The briefings file does not exist yet or cannot be read.               |

Client rules are unchanged from the draft, with the codes above: `401` → stop
and report "unauthorized"; `5xx` and network failures → retry with backoff
(`503 briefings_unavailable` clears after the next nightly run); any other
status → do not retry; `400 invalid_cursor` for a stored cursor → discard it
and redo the `since` backfill once. Branch on the HTTP status and
`error.code`, never on `message`.

## 4. Endpoints

### `GET /v1/health`

`200`, `data`:

| Field         | Type    | Value                    |
| ------------- | ------- | ------------------------ |
| `ok`          | boolean | always `true`            |
| `name`        | string  | `"atlas-restaurantos"`   |
| `api_version` | string  | `"1"`                    |
| `figures`     | string  | `"relative_only"`        |

```json
{"data": {"api_version": "1", "figures": "relative_only", "name": "atlas-restaurantos", "ok": true}, "request_id": "9f1c..."}
```

### `GET /v1/briefings?since=YYYY-MM-DD&cursor=<string>&limit=<1..100>`

The change feed: briefings and tombstones in ascending `(updated_at, id)`
order (`updated_at` strings compare in time order; ids byte-wise). All
parameters optional; unknown parameters are ignored.

| Parameter | Format                 | Default   | Validation                                                                 |
| --------- | ---------------------- | --------- | -------------------------------------------------------------------------- |
| `limit`   | decimal integer 1..100 | `50`      | `0`, `101`, `-1`, `abc`, `1.5`, empty → `400 invalid_limit`. Checked first. |
| `since`   | `YYYY-MM-DD`           | all dates | Keeps briefings with `date >= since`. Tombstones are never filtered. Malformed or impossible (`2026-02-30`) → `400 invalid_since`. Ignored when `cursor` is present. |
| `cursor`  | opaque non-empty       | none      | A `next_cursor` from this server. Empty, corrupt, foreign or from before a rebuild of the briefings file → `400 invalid_cursor`. |

`200`, `data`:

| Field         | Type                            | Meaning                                                                 |
| ------------- | ------------------------------- | ----------------------------------------------------------------------- |
| `items`       | array of briefings / tombstones | At most `limit`, in change-feed order. May be empty.                    |
| `has_more`    | boolean                         | `true`: request again with `cursor=<next_cursor>`.                      |
| `next_cursor` | string, never null or empty     | Continuation cursor if `has_more`, otherwise the resume cursor to store. |
| `figures`     | string                          | `"relative_only"`.                                                      |

A page is shorter than `limit` only when `has_more` is `false`.

### `GET /v1/briefings/{id}`

`{id}` is the briefing id as a single URL-encoded path segment. `200` with the
same object the feed carries as `data`, or `404 not_found` for an unknown or
deleted (tombstoned) id.

## 5. Briefing JSON

Every live briefing has every field below:

| Field           | Type                 | Notes                                                                                     |
| --------------- | -------------------- | ----------------------------------------------------------------------------------------- |
| `id`            | string               | `brf_<YYYY-MM-DD>_<8 hex>`, e.g. `brf_2026-11-15_3f2a91c4`: service date plus a hash of the restaurant. Stable; opaque to clients. |
| `date`          | string `YYYY-MM-DD`  | The service night. One briefing per service night.                                         |
| `title`         | string               | E.g. `Sunday, November 15, 2026`. At most 80 characters.                                   |
| `summary`       | string               | One line, at most 160 characters.                                                          |
| `body_markdown` | string               | `morning-brief` format (section 6).                                                         |
| `tags`          | array of strings     | Always `restaurantos`, `service-night` and exactly one of `confidence:high`, `confidence:medium`, `confidence:low`; `in-review` when the night is in review. |
| `created_at`    | string, RFC 3339 UTC | When the nightly run first produced this briefing (a night that returns after a tombstone is new). |
| `updated_at`    | string, RFC 3339 UTC | Changes only when the briefing's content changes.                                           |
| `deleted`       | boolean              | Always `false` on a live briefing.                                                          |
| `figures`       | string               | Always `"relative_only"`.                                                                   |

`sections` is never sent; render `body_markdown`.

`updated_at` is assigned by the nightly run that changed the content. All
briefings changed by one run share that run's `updated_at` (the `id` breaks
the tie), and every run's stamp is at least one second later than any stamp
already issued. A nightly run that leaves a night's numbers untouched leaves
its briefing, and its `updated_at`, exactly as they were, so the app neither
re-downloads nor re-notifies.

## 6. The body

Short CommonMark (well under 250 words), in the draft's `morning-brief`
format: a `#` title (the night), an intro line, then three `##` questions,
each with one `###` finding, a `-` bullet list of evidence and exactly one
confidence line, `**Confidence:** High|Medium|Low — <rationale>`:

- **How did the night compare?** The night against the same weekday a week
  earlier, one bullet per headline metric: `Net sales`, `Covers`,
  `Average check`, `Sales per labor hour` (percent changes), and
  `Labor cost (share of sales)`, `Reservation share`, `Comp rate`,
  `Void rate` (percentage points).
- **How is the month going?** Month to date against the aligned days of the
  prior month, the same eight bullets.
- **How much weight does this bear?** Nights in review and nights missing this
  month and in the comparison days (`unknown` without a nightly manifest),
  partial nights this month and in the comparison days
  (`- Partial nights this month: <n>`, `- Partial nights, comparison days: <n>`;
  `unknown` when the manifest does not list partial nights), whether this
  night is in review, and the overall confidence, which is also the
  `confidence:` tag.

Each figure reads `up 8.2%`, `down 1.4 points`, `flat`, or
`no comparison available` when one side has no data. There are no absolute
figures, currency symbols, counts of covers, or links.

**Partial nights.** A night with no readable nightly e-mail can be filled
from an approved point-of-sale (Toast) sales summary. Such a *partial* night
carries net sales and voids only: no labor, covers, reservations or comps.
When the briefing's night, or the week-earlier night it is compared with, is
partial, the night finding reads `no comparison available` for `Covers`,
`Average check`, `Sales per labor hour`, `Labor cost (share of sales)`,
`Reservation share` and `Comp rate` (whatever the other night carries);
`Net sales` and `Void rate` are compared as usual. The finding then has one
plain line (not a bullet, its own paragraph after the bullets) that names the partial night(s)
and says why, always containing the phrases `point-of-sale summary` and
`only net sales and voids are known`, for example:

```
Tuesday, October 27 was filled from a point-of-sale summary, so only net sales and voids are known.
```

The month finding compares each metric over the nights that carry it, so a
month with partial nights still shows every metric it can compute. The app
should render the line as ordinary text; it needs no special handling.

Overall confidence: **Low** when this night is in review, there is no
week-earlier night, or 3 or more nights are missing across the two month
windows; **High** when coverage is known, no night in either month window is
in review or missing, the prior month has data, partial nights are known,
neither compared night is partial and no partial night falls in either month
window; **Medium** otherwise (including unknown coverage, unknown partial
nights, and any comparison that rests on a partial night). A comparison that
rests on a partial night is never High, and its rationale says `partial`;
partial nights alone never make a briefing Low. The same rule applies per
finding: the night finding is at most Medium when either compared night is
partial, the month finding when a partial night falls in either month window.

Confidence rests only on what the nightly manifest flags. "In review" and
"missing" count flagged nights: a night whose report arrived but has a field
flagged, or could not be read. A night whose report never arrived is not
flagged, so it is not counted anywhere. The rationales therefore say what is
known ("no night in either month is flagged or partial", "neither night is
flagged or partial"),
never that a month has every night.

## 7. Change feed: cursors, `has_more`, `since`

As in the draft:

- Cursors are opaque; store and send them verbatim.
  Pagination ends on `has_more: false`; every response has a non-empty
  `next_cursor`, even an empty first response.
- A continuation cursor keeps the `since` filter of the walk. The resume
  cursor (the `next_cursor` of a `has_more: false` page) returns everything
  created, changed or deleted after it, for any `date`.
- `since` is ignored when `cursor` is present.
- After a `since` walk the resume cursor is the feed head as it was at the
  walk's first request; a briefing changed during the walk may be returned
  again (upsert by `id`). Without `since` it is the head at the last page.
- A `since` walk includes tombstones of any date.

Cursors are stateless (the server keeps no cursor state) and survive restarts
and token rotation. They are validated structurally; a malformed one answers
`400 invalid_cursor`, and the app then redoes its backfill once, as the draft
already requires.

Each cursor also carries the generation of the briefings file it was issued
for. When the nightly host rebuilds the file from scratch (the file was
damaged, or an operator deleted it), the rebuilt file has a new generation,
and every cursor issued before the rebuild answers `400 invalid_cursor`
instead of silently skipping deletions. The backfill that follows
re-downloads every briefing once: a rebuild assigns fresh `updated_at`
values. Ids are unchanged, so the app's upsert by `id` replaces what it holds.
A cursor whose generation is missing also answers `400 invalid_cursor`, and a
briefings file with no valid generation is not a briefings file: the feed
answers `503 briefings_unavailable` until the next refresh rebuilds it.

## 8. Tombstones

When a service night leaves the ledger, its briefing becomes a tombstone,
exactly `{"id", "updated_at", "deleted": true}`. Its `updated_at` is the
stamp of the nightly run that noticed the deletion, later than every stamp
issued before. Tombstones are kept, so any stored cursor sees them.
`GET /v1/briefings/{id}` for a tombstoned id answers `404 not_found`. If the
night comes back, the same `id` reappears as a live briefing with a newer
`updated_at`.

## 9. Examples

```http
GET /v1/briefings?since=2026-11-14&limit=50 HTTP/1.1
Host: guildenstern.example-tailnet.ts.net
Authorization: Bearer <ATLAS_BRIEFINGS_TOKEN>
Accept: application/json
```

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store
```

```json
{
  "data": {
    "figures": "relative_only",
    "has_more": false,
    "items": [
      {
        "body_markdown": "# Saturday, November 14\n\nRelative figures only: changes, never amounts.\n\n## How did the night compare?\n\n### Against Saturday, November 7\n\n- Net sales: up 1.5%\n- Covers: down 22.7%\n- Average check: up 31.3%\n- Sales per labor hour: up 35.3%\n- Labor cost (share of sales): down 1.2 points\n- Reservation share: up 13.2 points\n- Comp rate: up 0.2 points\n- Void rate: down 0.2 points\n\n**Confidence:** High — neither night is flagged or partial.\n\n## How is the month going?\n\n### November 1-14 against October 1-14\n\n- Net sales: down 5.1%\n- Covers: down 5.7%\n- Average check: up 0.7%\n- Sales per labor hour: up 1.3%\n- Labor cost (share of sales): down 0.5 points\n- Reservation share: up 9.2 points\n- Comp rate: flat\n- Void rate: up 0.1 points\n\n**Confidence:** High — no night in either month is flagged or partial.\n\n## How much weight does this bear?\n\n### Data coverage\n\n- Nights in review this month: 0\n- Nights missing this month: 0\n- Nights in review, comparison days: 0\n- Nights missing, comparison days: 0\n- Partial nights this month: 0\n- Partial nights, comparison days: 0\n- This night: not flagged\n\n**Confidence:** High — no night in either month is flagged or partial.\n",
        "created_at": "2026-11-15T11:31:02Z",
        "date": "2026-11-14",
        "deleted": false,
        "figures": "relative_only",
        "id": "brf_2026-11-14_3f2a91c4",
        "summary": "Net sales up 1.5% on the week before; month to date down 5.1%. Confidence: high.",
        "tags": ["restaurantos", "service-night", "confidence:high"],
        "title": "Saturday, November 14, 2026",
        "updated_at": "2026-11-15T11:31:02Z"
      }
    ],
    "next_cursor": "eyJnIjoia3E3Um1adFcyeFBhTmM0ZSIsImgiOm51bGwsInAiOlsiMjAyNi0xMS0xNVQxMTozMTowMloiLCJicmZfMjAyNi0xMS0xNF8zZjJhOTFjNCJdLCJzIjpudWxsLCJ2IjoxfQ"
  },
  "request_id": "4e2b7c9a1d3f4b6e8a0c2d4f6b8e1a3c"
}
```

Errors:

```json
{"error": {"code": "invalid_limit", "message": "limit must be an integer 1..100"}, "request_id": "..."}
{"error": {"code": "invalid_since", "message": "since must be a date in YYYY-MM-DD form"}, "request_id": "..."}
{"error": {"code": "invalid_cursor", "message": "cursor is not a cursor issued by this server"}, "request_id": "..."}
{"error": {"code": "unauthorized", "message": "A valid bearer token is required."}, "request_id": "..."}
{"error": {"code": "not_found", "message": "No such route."}, "request_id": "..."}
{"error": {"code": "method_not_allowed", "message": "Only GET is allowed on this route."}, "request_id": "..."}
{"error": {"code": "briefings_unavailable", "message": "The briefings file does not exist yet; the nightly run builds it."}, "request_id": "..."}
{"error": {"code": "internal_error", "message": "Atlas could not complete the request."}, "request_id": "..."}
```

## Deviations from the draft

Every place the implementation differs from the app's draft contract (round 2),
and why. "Atlas convention" means an existing, deliberate rule of the peer API
that this change was not allowed to weaken.

| # | Area | Draft | As implemented | Reason |
| - | ---- | ----- | -------------- | ------ |
| 1 | Success body | The payload object itself | `{"request_id", "data": <payload>}` | Atlas convention: every response is an envelope with a request id that matches the server journal. |
| 2 | Error body | `{"error": "<code>", "message"}` | `{"request_id", "error": {"code", "message"}}` | Atlas convention; read the code from `error.code`. |
| 3 | 500 code | `internal` | `internal_error` | Atlas convention (existing code). |
| 4 | New 503 | Not listed | `503 briefings_unavailable` until the nightly run has written the briefings file | Rule: the API never writes; the nightly workload owns the file. Retryable like any 5xx. |
| 5 | Path outside `/v1/` | `404 not_found` before authentication | `401 unauthorized` without a valid token; `GET /health` (no `/v1`) is an unauthenticated liveness check returning `{"service", "status"}`, not mounted on the tailnet | Atlas convention: no route disclosure to unauthenticated callers; `/health` must keep its exact response. |
| 6 | Unknown path under `/v1/` | `404 not_found` after authentication | `401 unauthorized` for the phone token (it is not valid there); `404` only for the JARVIS token | The phone token is scoped to the briefing routes; any other path is unauthorized for it, which also discloses nothing. |
| 7 | `/v1/briefings/a/b` | `404 not_found` | `401` with the phone token, `404` with the JARVIS token | Same scoping as row 6. |
| 8 | Wrong method | `405 method_not_allowed` for any method, after authentication | `405` (with `Allow: GET`) for `POST` to a briefing route; `501` with a non-JSON body, before authentication, for methods the server does not implement (`PUT`, `DELETE`, `PATCH`, `HEAD`, `OPTIONS`) | The standard-library server answers unimplemented methods itself; adding them would change the existing routes' behaviour. The app only sends `GET`. |
| 9 | Trailing slash | `/v1/briefings/` (empty id) → `404` | A trailing `/` is ignored on every path: `/v1/briefings/` is the list, `/v1/health/` is health | Atlas convention (existing path normalisation). |
| 10 | `Content-Type` | `application/json; charset=utf-8` | `application/json` (body always UTF-8) | Atlas convention; adding `charset` only on some routes would let a caller tell routes apart before authentication. JSON is UTF-8 by definition (RFC 8259). |
| 11 | Health `data` | `{ok, name: "Mock Atlas", api_version}` | `{ok, name: "atlas-restaurantos", api_version, figures: "relative_only"}` | Real service name; Atlas responses carry the figures marker. |
| 12 | Briefing id | `brf_2026-11-15` | `brf_2026-11-15_3f2a91c4` (date plus 8 hex of a hash of the restaurant) | Stable id derived from entity and service date, without sending the restaurant's name. Ids stay opaque. |
| 13 | `figures` field | Not in the draft | `"figures": "relative_only"` on every briefing and every list page | Rule 1: relative figures only, marked on every response. Ignore it or display it. |
| 14 | `sections` | Optional array; rendered instead of the body | Never sent | Atlas produces one Markdown body; render `body_markdown`. |
| 15 | Body figures | Absolute amounts, covers, forecasts, stock levels, links (draft example) | Percent changes, percentage-point deltas, directions and night counts only; no currency, no covers, no forecast, no stock, no links | Rule 1. Anything that would need an absolute figure is left out. |
| 16 | Body questions | Free wording; "What needs attention today?", "What is coming up?" | Three fixed questions: the night, the month, and coverage | Atlas has no forecast, stock, reservation-book or review data; only the ledger. |
| 17 | Optional fields | `summary`, `body_markdown`, `tags`, `created_at`, `deleted` optional | All always present on live briefings | Stricter than the draft; no client change needed. |
| 18 | Tags | Free-form | Always `restaurantos`, `service-night`, one `confidence:<level>`; `in-review` when relevant | Lets the app show confidence without parsing Markdown. |
| 19 | `updated_at` assignment | Server-assigned when the briefing changes | Assigned by the nightly run that changed the content; one stamp per run, ties broken by `id`; at least 1 s after every earlier stamp | Rule 2: the nightly workload owns the data; the feed changes once per nightly run, not continuously. |
| 20 | Tombstone `updated_at` | At least 1 s after the newest item and not before the deletion time | The stamp of the nightly run that noticed the night left the ledger (also at least 1 s after every earlier stamp) | Same as row 19. |
| 21 | Tombstone lifetime | Not specified | Kept indefinitely; a returning night reappears live with the same id | Any stored cursor can still learn of the deletion. |
| 22 | Cursor format | Mock's base64url JSON | A different opaque base64url JSON; stateless, validated structurally, never expires; survives restarts and token rotation, but a cursor from before a from-scratch rebuild of the briefings file is `400 invalid_cursor` | No server-side cursor state (rule 2). Clients never parse cursors anyway; the app already re-runs its backfill on `invalid_cursor`. |
| 23 | Repeated parameters | Not specified | A repeated `limit`, `since` or `cursor` is `400` with that parameter's code | Unambiguous validation. |
| 24 | Authentication | One static token | `ATLAS_BRIEFINGS_TOKEN`, valid only on the three briefing routes; the JARVIS token is also accepted there; `bearer` is case-insensitive | The phone must not hold the token that opens every route. |
| 25 | Base URL and transport | `http://atlas.tailnet.ts.net:8080` (plain http on the tailnet) or a prefixed https URL | `https://<machine>.<tailnet>.ts.net` (Tailscale Serve, HTTPS on 443, no prefix); the service itself is loopback-only on `127.0.0.1:8790` | Rule 3: loopback binding stays; Tailscale Serve exposes only `/v1/briefings` and `/v1/health`. |
| 26 | Mock-only behaviour | `injected_failure`, dropped connections, CORS preflight | Not implemented; `OPTIONS` is `501` | Mock-only by the draft's own definition; CORS is not part of the contract. |
| 27 | Freshness | Briefings appear as Atlas produces them | Briefings appear after the nightly run (05:30 and 11:30 America/Chicago) for each service night in the ledger | The nightly workload builds them from the ledger. |
| 28 | Partial nights | Not in the draft | A night filled from a point-of-sale summary compares net sales and void rate only; other headlines read `no comparison available`, one plain line says why, two coverage bullets count partial nights, confidence is at most Medium | Upstream Atlas fills unreadable nights from approved Toast summaries that carry net sales and voids only; a briefing must not present a change it cannot know. |

The app needs these changes: read `data` from success bodies and `error.code`
from error bodies; treat `internal_error` and `briefings_unavailable` like
`internal` (retryable); do not expect `404` before authentication; expect
`application/json` without `charset`; accept ids with a suffix; ignore
`figures`; and use the `https://` tailnet URL and the phone token.
