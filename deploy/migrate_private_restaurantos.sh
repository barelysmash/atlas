#!/usr/bin/env bash
# Stream private RestaurantOS state to Guildenstern without touching GitHub.
# Run locally after the Atlas code release is installed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy.config
source "${SCRIPT_DIR}/deploy.config"

SOURCE_ATLAS_HOME="${1:-${HOME}/.atlas}"
SOURCE_FONDA="${SOURCE_ATLAS_HOME}/restaurantos/fonda"
SOURCE_TOKEN="${SOURCE_ATLAS_HOME}/google/gmail-token.json"
TARGET_FONDA="${TARGET_DATA}/restaurantos/fonda"
TARGET_GOOGLE="${TARGET_DATA}/google"

fail() {
    printf '[private-migrate] ERROR: %s\n' "$*" >&2
    exit 1
}

[[ -d "${SOURCE_FONDA}" ]] || fail "Source Fonda directory not found: ${SOURCE_FONDA}"
[[ -s "${SOURCE_TOKEN}" ]] || fail "Source Gmail token not found: ${SOURCE_TOKEN}"
[[ -s "${SOURCE_FONDA}/nightly-messages.jsonl" ]] || \
    fail "Source nightly message bundle is missing"

ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} test -L '${TARGET_INSTALL}'" || \
    fail "Atlas must be deployed to ${TARGET_HOST} before private state migration"

ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} \
    \"sudo install -d -o ${TARGET_USER} -g ${TARGET_USER} -m 700 \
    '${TARGET_DATA}' '${TARGET_GOOGLE}' '${TARGET_DATA}/restaurantos' '${TARGET_FONDA}'\""

copy_files=("nightly-messages.jsonl")
for optional in \
    nightly-sync-state.json \
    nightly-history.jsonl \
    nightly-manifest.json \
    operating-brief.md \
    service-date-overrides.json; do
    if [[ -f "${SOURCE_FONDA}/${optional}" ]]; then
        copy_files+=("${optional}")
    fi
done

printf '[private-migrate] Streaming %d private RestaurantOS files\n' "${#copy_files[@]}"
tar -C "${SOURCE_FONDA}" -czf - "${copy_files[@]}" | \
    ssh "${BASTION_HOST}" \
        "ssh ${TARGET_HOST} \"sudo -u ${TARGET_USER} -H tar -xzf - -C '${TARGET_FONDA}'\""

printf '[private-migrate] Streaming private Gmail OAuth token\n'
cat "${SOURCE_TOKEN}" | \
    ssh "${BASTION_HOST}" \
        "ssh ${TARGET_HOST} \"sudo -u ${TARGET_USER} -H bash -c \
        'umask 077; cat > ${TARGET_GOOGLE}/gmail-token.json'\""

ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} \
    \"sudo -u ${TARGET_USER} -H chmod 600 '${TARGET_GOOGLE}/gmail-token.json' '${TARGET_FONDA}'/*\""

TARGET_UID=$(ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} id -u ${TARGET_USER}")
SYSTEMD_ENV="XDG_RUNTIME_DIR=/run/user/${TARGET_UID} DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${TARGET_UID}/bus"

ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} sudo -u ${TARGET_USER} -H env \
    ${SYSTEMD_ENV} systemctl --user enable --now atlas-restaurantos-nightly.timer"

printf '[private-migrate] Running one live refresh on Guildenstern\n'
if ! ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} sudo -u ${TARGET_USER} -H env \
    ${SYSTEMD_ENV} systemctl --user start atlas-restaurantos-nightly.service"; then
    ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} sudo -u ${TARGET_USER} -H env \
        ${SYSTEMD_ENV} journalctl --user -u atlas-restaurantos-nightly.service \
        -n 100 --no-pager" || true
    fail "Guildenstern live refresh failed"
fi

ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} sudo -u ${TARGET_USER} -H env \
    ${SYSTEMD_ENV} systemctl --user show atlas-restaurantos-nightly.service \
    --property=Result --property=ExecMainStatus --property=ExecMainStartTimestamp \
    --no-pager"

printf '[private-migrate] Private state migrated and live refresh verified\n'
