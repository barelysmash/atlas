#!/usr/bin/env bash
# Run on the bastion. Ship a release to Guildenstern and hand it to TARGET_USER.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy.config
source "${SCRIPT_DIR}/deploy.config"

RELEASE_NAME="${1:?Release name required}"
TARBALL="${SCRIPT_DIR}/${RELEASE_NAME}.tar.gz"
GUILD_STAGING="/tmp/atlas-handoff-${RELEASE_NAME}"
RELEASE_PATH="${TARGET_RELEASES}/${RELEASE_NAME}"

[[ -s "${TARBALL}" ]] || {
    echo "[handoff] Missing release tarball: ${TARBALL}" >&2
    exit 1
}

echo "[handoff] Shipping ${RELEASE_NAME} to ${TARGET_HOST}"
ssh "${TARGET_HOST}" "mkdir -p '${GUILD_STAGING}'"
scp -q "${TARBALL}" "${TARGET_HOST}:${GUILD_STAGING}/"

ssh -t "${TARGET_HOST}" "bash -s" <<REMOTE_SCRIPT
set -euo pipefail

sudo mkdir -p "${TARGET_RELEASES}"
sudo chown "${TARGET_USER}:${TARGET_USER}" "${TARGET_RELEASES}"

sudo mkdir -p "${RELEASE_PATH}"
sudo tar -xzf "${GUILD_STAGING}/${RELEASE_NAME}.tar.gz" \
    -C "${RELEASE_PATH}" --strip-components=1
sudo chown -R "${TARGET_USER}:${TARGET_USER}" "${RELEASE_PATH}"

sudo -u "${TARGET_USER}" -H env \
    XDG_RUNTIME_DIR="/run/user/\$(id -u "${TARGET_USER}")" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/\$(id -u "${TARGET_USER}")/bus" \
    bash -c 'cd "${RELEASE_PATH}" && bash deploy/remote_install.sh "${RELEASE_NAME}"'

rm -rf "${GUILD_STAGING}"
REMOTE_SCRIPT

echo "[handoff] ${RELEASE_NAME} installed"
