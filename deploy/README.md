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
reviews by night.

The workload is blocked until both of these exist on the host:

- `~/atlas-data/env/atlas.env`, mode 600, containing `ATLAS_API_TOKEN`
  (at least 24 characters). Create it once, by hand; no deploy writes it.
- `~/atlas-data/restaurantos/fonda/nightly-history.jsonl`

The same token goes in JARVIS's environment file as `ATLAS_API_TOKEN`.

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
