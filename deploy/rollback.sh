#!/usr/bin/env bash
# Roll Atlas back to the previous complete release, including its venv.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy.config
source "${SCRIPT_DIR}/deploy.config"

[[ -L "${TARGET_INSTALL}" ]] || {
    echo "[rollback] Current Atlas symlink is missing" >&2
    exit 1
}
[[ -L "${TARGET_PREVIOUS}" ]] || {
    echo "[rollback] No previous Atlas release is available" >&2
    exit 1
}

CURRENT_TARGET="$(readlink "${TARGET_INSTALL}")"
PREVIOUS_TARGET="$(readlink "${TARGET_PREVIOUS}")"

[[ -x "${PREVIOUS_TARGET}/.venv/bin/python" ]] || {
    echo "[rollback] Previous release runtime is incomplete" >&2
    exit 1
}

ln -sfn "${PREVIOUS_TARGET}" "${TARGET_INSTALL}"
ln -sfn "${CURRENT_TARGET}" "${TARGET_PREVIOUS}"

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
systemctl --user daemon-reload

for service in "${SERVICES[@]}"; do
    systemctl --user restart "${service}"
done

for timer in "${TIMERS[@]}"; do
    if systemctl --user is-enabled "${timer}" >/dev/null 2>&1; then
        systemctl --user restart "${timer}"
    fi
done

echo "[rollback] $(basename "${CURRENT_TARGET}") -> $(basename "${PREVIOUS_TARGET}")"
