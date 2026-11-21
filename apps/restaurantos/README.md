# Restaurant Plugin

Domain layer for restaurants: vocabulary, KPIs, hospitality workflows, menu engineering, beverage analytics, and benchmark logic.

Do not copy the private files into this repository.

## Briefings feed (Atlas briefings phone app)

`restaurantos serve` also serves a read-only change feed of nightly briefings
for the owner's phone. One briefing per service night in the ledger, built
from `relative_summary` only: percent changes, percentage-point deltas,
directions and night counts. Every briefing and list response carries
`"figures": "relative_only"`; no dollar amount, cover count, labor total or
rate level is ever returned.

| Route | Tokens | Returns |
| --- | --- | --- |
| `GET /v1/health` | `ATLAS_API_TOKEN` or `ATLAS_BRIEFINGS_TOKEN` | proof that URL and token work |
| `GET /v1/briefings` | `ATLAS_API_TOKEN` or `ATLAS_BRIEFINGS_TOKEN` | change feed page |
| `GET /v1/briefings/{id}` | `ATLAS_API_TOKEN` or `ATLAS_BRIEFINGS_TOKEN` | one briefing |

`ATLAS_BRIEFINGS_TOKEN` (optional, at least 24 characters, different from
`ATLAS_API_TOKEN`) is the phone's token. It opens these three routes and
nothing else; anywhere else, including the JARVIS routes `/v1/freshness`,
`/v1/operating-summary` and `/v1/decisions`, it gets `401 unauthorized`. Responses use the
service's conventions: bearer auth, `Cache-Control: no-store`, JSON with
sorted keys, `{"request_id", "data"}` on success and
`{"request_id", "error": {"code", "message"}}` on error. The full contract,
and every difference from the app's draft, is in
`docs/operations/briefings-app-contract.md`.

The API never writes. The nightly workload builds the briefings file next to
the ledger with `briefings-refresh`; it can also be rebuilt by hand:

```bash
python -m restaurantos briefings-refresh \
  --history ~/atlas-data/restaurantos/fonda/nightly-history.jsonl \
  --manifest ~/atlas-data/restaurantos/fonda/nightly-manifest.json \
  --briefings ~/atlas-data/restaurantos/fonda/briefings.json \
  --entity "<restaurant entity>"
```

It prints `briefings=`, `changed=`, `tombstones=` and `path=`. A briefing's
`updated_at` changes only when its content does, so rerunning it on an
unchanged ledger changes nothing. Until the file exists, the feed routes
answer `503 briefings_unavailable`; the other routes keep working. `serve`
reads `briefings.json` next to `--history` unless `--briefings` says
otherwise, so the API unit needs no extra argument.

If the briefings file is damaged (unreadable, not JSON, or not a briefings
file), `briefings-refresh` reports it on stderr and rebuilds it from the
ledger, as it does when the file has been deleted. A rebuild assigns fresh
`updated_at` values, so the phone re-downloads every briefing once, and
cursors issued before it answer `400 invalid_cursor` (the app then re-runs
its backfill). Concurrent refreshes are serialised by an exclusive lock on
`briefings.json.lock`. In the nightly run the step is optional and runs
last, with a 600-second limit: its failure or timeout is reported on stderr
and never fails the unit. Before taking the lock, the refresh `stat()`s the
ledger and requires a regular file; a missing ledger, a directory, a FIFO or
a path it may not stat is reported with its real error and creates nothing.

Confidence lines say only what the nightly manifest flags (for example
"no night in either month is flagged or partial"); a night whose report never arrived
is not flagged, so it is not counted.

Partial nights, filled from an approved Toast sales summary
(`restaurantos toast-approve`), carry net sales and voids only. They come
from the manifest's `partial_nights` (`restaurantos.coverage`, shared with
`/v1/operating-summary`'s `nights_partial`). A briefing for a partial night,
or one whose week-earlier night is partial, reads `no comparison available`
for covers, average check, sales per labor hour, labor cost, reservation
share and comp rate in the week finding, with one plain line saying the night
was filled from a point-of-sale summary, so only net sales and voids are
known. The coverage section adds `- Partial nights this month: <n>` and
`- Partial nights, comparison days: <n>` (`unknown` without a
`partial_nights` list). A comparison that rests on a partial night is at most
Medium confidence, never High; partial nights alone never make it Low.
Briefings do not include JAM Decisions.

### GET /v1/health

```
GET /v1/health HTTP/1.1
Authorization: Bearer <ATLAS_BRIEFINGS_TOKEN>
```

```json
{
  "data": {"api_version": "1", "figures": "relative_only", "name": "atlas-restaurantos", "ok": true},
  "request_id": "2f0c6a8e4b3d4f1a9e7c5b2d1a0f3e6c"
}
```

### GET /v1/briefings

Query parameters, all optional: `limit` (1..100, default 50), `since`
(`YYYY-MM-DD`, keeps briefings with `date >= since`; tombstones are never
filtered) and `cursor` (a `next_cursor` from an earlier response; `since` is
then ignored). Items are ordered by `(updated_at, id)`. Follow `next_cursor`
while `has_more` is `true`; store the last `next_cursor` and send it on the
next sync to get only what changed.

```
curl -sS -H "Authorization: Bearer $ATLAS_BRIEFINGS_TOKEN" \
  "http://127.0.0.1:8790/v1/briefings?since=2026-11-09&limit=2"
```

```json
{
  "data": {
    "figures": "relative_only",
    "has_more": true,
    "items": [
      {"deleted": true, "id": "brf_2026-10-31_3f2a91c4", "updated_at": "2026-11-10T11:31:02Z"},
      {
        "body_markdown": "# Monday, November 9\n\nRelative figures only: changes between periods, never amounts.\n\n## How did the night compare?\n\n### Against Monday, November 2\n\n- Net sales: up 4.3%\n- Covers: up 1.9%\n- Average check: up 2.4%\n- Labor cost (share of sales): down 0.8 points\n\n**Confidence:** High — neither night is flagged or partial.\n\n## How is the month going?\n\n...",
        "created_at": "2026-11-10T11:31:02Z",
        "date": "2026-11-09",
        "deleted": false,
        "figures": "relative_only",
        "id": "brf_2026-11-09_3f2a91c4",
        "summary": "Net sales up 4.3% on the week before; month to date down 1.2%. Confidence: medium.",
        "tags": ["restaurantos", "service-night", "confidence:medium"],
        "title": "Monday, November 9, 2026",
        "updated_at": "2026-11-10T11:31:02Z"
      }
    ],
    "next_cursor": "eyJoIjpbIjIwMjYtMTEtMTBUMTE6MzE6MDJaIiwi..."
  },
  "request_id": "7d1e0b6c2a9f4e3b8c5a1d0e9f2b4c6a"
}
```

A tombstone (the first item; it sorts first on `id`) is exactly `id`, `updated_at` and
`deleted: true`: that night left the ledger. `next_cursor` is opaque and never
empty.

### GET /v1/briefings/{id}

```
GET /v1/briefings/brf_2026-11-09_3f2a91c4 HTTP/1.1
Authorization: Bearer <ATLAS_BRIEFINGS_TOKEN>
```

```json
{
  "data": {
    "body_markdown": "# Monday, November 9\n\n...",
    "created_at": "2026-11-10T11:31:02Z",
    "date": "2026-11-09",
    "deleted": false,
    "figures": "relative_only",
    "id": "brf_2026-11-09_3f2a91c4",
    "summary": "Net sales up 4.3% on the week before; month to date down 1.2%. Confidence: medium.",
    "tags": ["restaurantos", "service-night", "confidence:medium"],
    "title": "Monday, November 9, 2026",
    "updated_at": "2026-11-10T11:31:02Z"
  },
  "request_id": "0a4c2e6b8d1f4a3c9e7b5d2f1c0e8a6b"
}
```

An unknown or deleted id answers:

```json
{"error": {"code": "not_found", "message": "No such route."}, "request_id": "5b3d1f0e2c4a4e6b8d9f7a1c3e5b0d2f"}
```
