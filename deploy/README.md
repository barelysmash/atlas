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

The first code deploy installs the RestaurantOS units. If private Gmail state
has not been migrated yet, the timer is deliberately left disabled.

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
4. enables the RestaurantOS timer; and
5. runs one live refresh on Guildenstern as verification.

Do not copy the private files into this repository.

## RestaurantOS schedule

`atlas-restaurantos-nightly.timer` runs at 05:30 and 11:30
`America/Chicago` every day. The scheduled runner uses yesterday as the service
endpoint and generates a month-to-date brief against the aligned prior-month
period.

## Operations

```bash
bash deploy/deploy.sh status
bash deploy/deploy.sh run-restaurantos
bash deploy/deploy.sh logs atlas-restaurantos-nightly.service
bash deploy/deploy.sh rollback
```

After Guildenstern has completed a verified live refresh, disable the old
Windows scheduled task so there is one production writer.

## Extending Atlas

New Atlas subagents should follow the same boundary:

- code and dependencies live inside immutable releases;
- persistent state and credentials live under `~/atlas-data/<agent>/`;
- long-running agents use systemd user services;
- scheduled workflows use systemd user timers; and
- deploys never package private runtime state.
