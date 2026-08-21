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

if [[ -x "${PREVIOUS_TARGET}/deploy/reconcile_workloads.sh" \
      && -f "${PREVIOUS_TARGET}/deploy/workloads.toml" ]]; then
    bash "${PREVIOUS_TARGET}/deploy/reconcile_workloads.sh" \
        "${PREVIOUS_TARGET}" "${TARGET_DATA}"
else
    # Compatibility for the pre-registry Guildenstern release. This path can be
    # removed after every retained rollback release contains workloads.toml.
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
    export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
    SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

    shopt -s nullglob
    for existing in "${SYSTEMD_USER_DIR}"/atlas-*.service \
                    "${SYSTEMD_USER_DIR}"/atlas-*.timer; do
        unit="$(basename "${existing}")"
        systemctl --user disable --now "${unit}" >/dev/null 2>&1 || true
        rm -f "${existing}"
    done
    for unit in "${PREVIOUS_TARGET}/deploy/systemd"/*.service \
                "${PREVIOUS_TARGET}/deploy/systemd"/*.timer; do
        cp "${unit}" "${SYSTEMD_USER_DIR}/"
    done
    shopt -u nullglob
    systemctl --user daemon-reload

    if [[ -s "${TARGET_DATA}/google/gmail-token.json" \
          && -s "${TARGET_DATA}/restaurantos/fonda/nightly-messages.jsonl" ]]; then
        systemctl --user enable atlas-restaurantos-nightly.timer >/dev/null
        systemctl --user start atlas-restaurantos-nightly.timer
    fi
    echo "[rollback] Applied legacy RestaurantOS workload compatibility"
fi

echo "[rollback] $(basename "${CURRENT_TARGET}") -> $(basename "${PREVIOUS_TARGET}")"
