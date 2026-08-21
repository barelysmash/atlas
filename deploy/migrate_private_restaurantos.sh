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

# The ordinary SSH account may not be able to traverse TARGET_USER's home.
# Validate the deployed release as the service user that actually owns/runs Atlas.
ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} \
    \"sudo -u ${TARGET_USER} -H test -L '${TARGET_INSTALL}' && \
    sudo -u ${TARGET_USER} -H test -x '${TARGET_INSTALL}/.venv/bin/python'\"" || \
    fail "Atlas runtime is not installed for ${TARGET_USER} on ${TARGET_HOST}"

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
    \"sudo -u ${TARGET_USER} -H chmod 600 '${TARGET_GOOGLE}/gmail-token.json' '${TARGET_FONDA}'/* && \
    sudo -u ${TARGET_USER} -H test -s '${TARGET_GOOGLE}/gmail-token.json' && \
    sudo -u ${TARGET_USER} -H test -s '${TARGET_FONDA}/nightly-messages.jsonl'\""

TARGET_UID=$(ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} id -u ${TARGET_USER}")
SYSTEMD_ENV="XDG_RUNTIME_DIR=/run/user/${TARGET_UID} DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${TARGET_UID}/bus"

# Verify a live refresh before enabling the persistent timer. This prevents an
# overdue Persistent=true trigger from racing the first validation run.
printf '[private-migrate] Running one live refresh on Guildenstern\n'
if ! ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} sudo -u ${TARGET_USER} -H env \
    ${SYSTEMD_ENV} systemctl --user start atlas-restaurantos-nightly.service"; then
    ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} sudo -u ${TARGET_USER} -H env \
        ${SYSTEMD_ENV} journalctl --user -u atlas-restaurantos-nightly.service \
        -n 100 --no-pager" || true
    fail "Guildenstern live refresh failed"
fi

SERVICE_STATUS=$(ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} sudo -u ${TARGET_USER} -H env \
    ${SYSTEMD_ENV} systemctl --user show atlas-restaurantos-nightly.service \
    --property=Result --property=ExecMainStatus --property=ExecMainStartTimestamp \
    --no-pager")
printf '%s\n' "${SERVICE_STATUS}"

if ! grep -qx 'Result=success' <<<"${SERVICE_STATUS}" || \
   ! grep -qx 'ExecMainStatus=0' <<<"${SERVICE_STATUS}"; then
    fail "Guildenstern refresh did not report a successful service result"
fi

printf '[private-migrate] Enabling RestaurantOS timer\n'
ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} sudo -u ${TARGET_USER} -H env \
    ${SYSTEMD_ENV} systemctl --user enable --now atlas-restaurantos-nightly.timer"

ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} sudo -u ${TARGET_USER} -H env \
    ${SYSTEMD_ENV} systemctl --user is-active --quiet atlas-restaurantos-nightly.timer" || \
    fail "RestaurantOS timer did not become active"

printf '[private-migrate] Private state migrated, live refresh verified, timer active\n'
