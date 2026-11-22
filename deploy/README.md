# Atlas deployment on Guildenstern

Atlas uses the same two-hop host topology as JARVIS: local machine -> bastion ->
Guildenstern. Runtime services run as the unprivileged `ocelia` user through
`systemctl --user`.

## Layout

- `~/atlas-releases/atlas-YYYYMMDD-HHMMSS/`: immutable release directories
- `~/atlas`: symlink to the current release
- `~/atlas-previous`: symlink to the rollback release
- `~/atlas-data/`: persistent private state, never part of a release
- `~/.config/systemd/user/atlas-*`: user services and timers

Every release owns its own `.venv`. This keeps code and installed dependencies
atomic: rollback switches both together.

## Workload registry

`deploy/workloads.toml` is the public host contract for Atlas workloads. Each
workload declares its persistent data directories, required private readiness
files, owned systemd services, autostart services, and timers.

The registry contains paths and unit names only. It never contains credentials,
Gmail content, account identifiers, operational records, or secret values.

Deployment and rollback both reconcile systemd from the active release's
registry. Ready workloads are started/restarted, blocked workloads are disabled,
and Atlas units removed from the registry are retired.

## Privacy boundary

Release archives are built with `git archive HEAD`, so only Git-tracked files
can enter a deployment artifact. Untracked or ignored local files are excluded
by construction.

Private RestaurantOS Gmail state is transferred separately by
`migrate_private_restaurantos.sh`. It is streamed over SSH and is never written
to GitHub or included in the release archive.

Expected private target paths:

- `~/atlas-data/google/gmail-token.json`
- `~/atlas-data/restaurantos/fonda/nightly-messages.jsonl`
- `~/atlas-data/restaurantos/fonda/nightly-sync-state.json`
- `~/atlas-data/restaurantos/fonda/nightly-history.jsonl`
- `~/atlas-data/restaurantos/fonda/nightly-manifest.json`
- `~/atlas-data/restaurantos/fonda/operating-brief.md`
- `~/atlas-data/env/atlas.env` (service secrets; see `deploy/env.template`)

## One-time host prerequisite

Guildenstern already uses systemd user services for JARVIS. Atlas relies on the
same linger configuration:

```bash
sudo loginctl enable-linger ocelia
```

Python 3.12 must also be available on Guildenstern.

## Deploy code

From the Atlas repository in Git Bash or another Bash shell:

```bash
bash deploy/deploy.sh
```

A workload whose required private files do not exist is installed but left
inactive. Once its private state exists, a later deploy/rollback reconciliation
can activate it.

## Migrate private RestaurantOS state

After the code release is installed, run this once from the machine that owns
the validated private `.atlas` state:

```bash
bash deploy/migrate_private_restaurantos.sh "$HOME/.atlas"
```

The migration script:

1. verifies the local private source bundle and OAuth token;
2. streams only the required private files through the bastion to Guildenstern;
3. applies owner-only permissions;
4. runs one live refresh on Guildenstern and validates its service result; and
5. enables the RestaurantOS timer only after that refresh succeeds.

Do not copy the private files into this repository.

## RestaurantOS schedule

`atlas-restaurantos-nightly.timer` runs at 05:30 and 11:30
`America/Chicago` every day. The scheduled runner uses yesterday as the service
endpoint and generates a month-to-date brief against the aligned prior-month
period.

## RestaurantOS peer API

`atlas-restaurantos-api.service` is the surface JARVIS routes to, registered
as `atlas` in jarvis-v2's `config/agents.yaml`
(JAM `standards/agent-registration.md`). It is read-only and listens on
`127.0.0.1:8790`.

| Route | Auth | Returns |
| --- | --- | --- |
| `GET /health` | none | liveness only |
| `GET /v1/freshness` | bearer | ledger dates and counts |
| `POST /v1/operating-summary` | bearer | two periods compared |
| `GET /v1/decisions` | bearer | JAM Decisions against the goals, relative only |

These three bearer routes are the JARVIS routes: only `ATLAS_API_TOKEN` opens
them. The phone's `ATLAS_BRIEFINGS_TOKEN` gets `401` on each of them.

**Relative figures only.** The API reports percent changes, percentage-point
deltas, directions and night counts. It never returns a dollar amount, a
cover count, a labor total or a rate level, so the absolute figures in the
private ledger do not leave Guildenstern through JARVIS. The limit is
enforced here, in `restaurantos.relative_summary`, not in the adapter.

`POST /v1/operating-summary` takes an optional JSON body: `start_date`,
`end_date`, `compare_start_date`, `compare_end_date` (ISO dates, each pair
together) and `entity`. With no dates it compares month to date, through the
latest service night in the ledger, against the aligned days of the prior
month. With a window and no comparison it uses the window of equal length
just before it.

Each period in the summary also says how far to trust it, as counts of
nights: `nights_missing` (a report arrived but could not be read, so the
night is absent from the comparison) and `nights_in_review` (included, with
a field flagged), plus the review reasons. They come from the nightly
manifest and are `null` until a nightly run has written one that lists
reviews by night. `nights_partial` counts partial nights (filled from an
approved point-of-sale summary: net sales and voids only), `null` when the
manifest does not list them.

The workload is blocked until both of these exist on the host:

- `~/atlas-data/env/atlas.env`, mode 600, containing `ATLAS_API_TOKEN`
  (at least 24 characters). Create it once, by hand; no deploy writes it.
- `~/atlas-data/restaurantos/fonda/nightly-history.jsonl`

The same token goes in JARVIS's environment file as `ATLAS_API_TOKEN`.

## Briefings for the phone app (manual host steps)

The same service serves a read-only briefings feed to the Atlas briefings
iPhone app (`GET /v1/health`, `GET /v1/briefings`, `GET /v1/briefings/{id}`;
see `apps/restaurantos/README.md` and
`docs/operations/briefings-app-contract.md`). The nightly run writes
`~/atlas-data/restaurantos/fonda/briefings.json` after each successful
refresh; until the first run has written it the feed answers
`503 briefings_unavailable`, and the workload is not blocked on it. The API
unit's `ExecStart` does not name the file: `restaurantos serve` reads
`briefings.json` next to `--history` by default, which is the same file.

The briefings step is optional and never fails the nightly unit. If
`briefings-refresh` exits non-zero, cannot be started, or runs past its
600-second (ten-minute) limit (for example while waiting on a stuck refresh
lock), the nightly run prints one line on stderr naming the step and saying the ledger refresh
succeeded, and the unit still succeeds; the phone keeps the previous
briefings until the next run. Look for that line with
`bash deploy/deploy.sh logs atlas-restaurantos-nightly.service`.

A damaged `briefings.json` (unreadable, not valid JSON, or not a briefings
file) heals itself: the next refresh reports it on stderr and rebuilds the
file from the ledger. So does deleting the file by hand. A rebuild assigns
fresh `updated_at` values to every briefing, so the phone re-downloads every
briefing once; cursors the phone stored before the rebuild answer
`400 invalid_cursor`, and the app re-runs its backfill. Refreshes take an
exclusive lock on `briefings.json.lock` (mode 600, left in place), so a manual
refresh during the nightly run waits for it rather than racing it. A ledger
path that is missing, not readable, a directory or any other non-regular
file (a FIFO, for example) is reported before the lock and creates nothing.

Partial nights (filled from an approved Toast sales summary with
`restaurantos toast-approve`) carry net sales and voids only. A briefing that
compares against one says `no comparison available` for the other headlines,
explains why in one line, and is at most Medium confidence; its coverage
section counts partial nights in both month windows.

**These are manual steps an operator performs once on Guildenstern. A deploy
never performs them: it never runs `tailscale`, never edits `atlas.env` and
never changes the service's loopback binding.** The API keeps listening on
`127.0.0.1:8790` only; Tailscale Serve, on the host, forwards the two
briefing paths from the tailnet to it over HTTPS.

1. Set the phone token. Generate a second token (at least 24 characters,
   different from `ATLAS_API_TOKEN`) and add it to the private env file:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   # edit ~/atlas-data/env/atlas.env (mode 600) and set:
   #   ATLAS_BRIEFINGS_TOKEN=<the new value>
   systemctl --user restart atlas-restaurantos-api.service
   ```

   `ATLAS_BRIEFINGS_TOKEN` opens only the briefing routes. Paste it into the
   app, never into JARVIS. Leave it empty to let only `ATLAS_API_TOKEN` read
   briefings. The service refuses to start if it is shorter than 24
   characters or equal to `ATLAS_API_TOKEN`.

2. Expose ONLY the briefing routes to the tailnet. Each command mounts one
   path and proxies it to the same path on loopback; nothing else on the API
   (`/v1/freshness`, `/v1/operating-summary`, `/v1/decisions`, `/health`)
   is mounted:

   ```bash
   tailscale serve --bg --https=443 --set-path /v1/briefings http://127.0.0.1:8790/v1/briefings
   tailscale serve --bg --https=443 --set-path /v1/health http://127.0.0.1:8790/v1/health
   tailscale serve status
   ```

   `tailscale serve status` should list exactly those two paths. Use
   `tailscale serve`, never `tailscale funnel`: the feed is for the tailnet,
   not the internet. To undo, run
   `tailscale serve --https=443 --set-path /v1/briefings off` and the same for
   `/v1/health`.

3. Check it works, from another device on the tailnet (replace the host name
   with the machine's MagicDNS name):

   ```bash
   curl -sS -H "Authorization: Bearer $ATLAS_BRIEFINGS_TOKEN" \
     https://guildenstern.example-tailnet.ts.net/v1/health
   curl -sS -H "Authorization: Bearer $ATLAS_BRIEFINGS_TOKEN" \
     "https://guildenstern.example-tailnet.ts.net/v1/briefings?limit=1"
   # Must not be 200: JARVIS routes are not mounted on the tailnet.
   curl -sS -o /dev/null -w '%{http_code}\n' \
     -H "Authorization: Bearer $ATLAS_BRIEFINGS_TOKEN" \
     https://guildenstern.example-tailnet.ts.net/v1/freshness
   curl -sS -o /dev/null -w '%{http_code}\n' \
     -H "Authorization: Bearer $ATLAS_BRIEFINGS_TOKEN" \
     https://guildenstern.example-tailnet.ts.net/v1/decisions
   ```

   The first answers `200` with `"ok": true`; the second `200` with
   `"figures": "relative_only"` (or `503 briefings_unavailable` before the
   first nightly run); the third and fourth `404` from Tailscale. On the host
   itself, check the token scoping too; each of these must print `401`:

   ```bash
   curl -sS -o /dev/null -w '%{http_code}\n' \
     -H "Authorization: Bearer $ATLAS_BRIEFINGS_TOKEN" \
     http://127.0.0.1:8790/v1/freshness
   curl -sS -o /dev/null -w '%{http_code}\n' \
     -H "Authorization: Bearer $ATLAS_BRIEFINGS_TOKEN" \
     http://127.0.0.1:8790/v1/decisions
   ```

   In the app, the base URL is `https://<machine>.<tailnet>.ts.net` with no
   path.

   To rebuild the briefings file by hand (for example right after setting
   this up), run `restaurantos briefings-refresh` as shown in
   `apps/restaurantos/README.md`, as the service user.

## Operations

```bash
bash deploy/deploy.sh status
bash deploy/deploy.sh run atlas-restaurantos-nightly.service
bash deploy/deploy.sh logs atlas-restaurantos-nightly.service
bash deploy/deploy.sh logs atlas-restaurantos-api.service
bash deploy/deploy.sh rollback
```

`run-restaurantos` remains as a compatibility alias for the generic `run`
command.

## Extending Atlas

New Atlas subagents should follow the same boundary:

- code and dependencies live inside immutable releases;
- persistent state and credentials live under `~/atlas-data/<agent>/`;
- the public workload contract is added to `deploy/workloads.toml`;
- long-running agents declare autostart systemd user services;
- scheduled workflows declare systemd user timers; and
- deploys never package private runtime state.

See `docs/adr/ADR-0002-guildenstern-workload-runtime.md` for the design decision.
