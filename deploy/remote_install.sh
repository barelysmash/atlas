#!/usr/bin/env bash
# Install one Atlas release as the unprivileged target user.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy.config
source "${SCRIPT_DIR}/deploy.config"

RELEASE_NAME="${1:?Release name required}"
RELEASE_PATH="${TARGET_RELEASES}/${RELEASE_NAME}"
VENV_PATH="${RELEASE_PATH}/.venv"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

if [[ ! -d "${RELEASE_PATH}" ]]; then
    echo "[install] Release not found: ${RELEASE_PATH}" >&2
    exit 1
fi

if ! loginctl show-user "$(whoami)" 2>/dev/null | grep -q "Linger=yes"; then
    echo "[install] WARNING: linger is not enabled for $(whoami)"
    echo "[install] An administrator must run: sudo loginctl enable-linger $(whoami)"
fi

echo "[install] Building isolated runtime for ${RELEASE_NAME}"
"${PYTHON_VERSION}" -m venv "${VENV_PATH}"
"${VENV_PATH}/bin/python" -m pip install --upgrade pip wheel --quiet

mapfile -t PROJECT_DIRS < <(
    find "${RELEASE_PATH}/packages" "${RELEASE_PATH}/apps" \
        -mindepth 2 -maxdepth 2 -name pyproject.toml -printf '%h\n' | sort
)
if [[ ${#PROJECT_DIRS[@]} -eq 0 ]]; then
    echo "[install] No installable Atlas projects found" >&2
    exit 1
fi

"${VENV_PATH}/bin/python" -m pip install --no-cache-dir "${PROJECT_DIRS[@]}" --quiet
"${VENV_PATH}/bin/python" -m restaurantos --help >/dev/null

echo "[install] Runtime verified"

# Persistent state is deliberately outside every release.
mkdir -p \
    "${TARGET_DATA}/google" \
    "${TARGET_DATA}/restaurantos/fonda" \
    "${TARGET_DATA}/logs"
chmod 700 "${TARGET_DATA}" "${TARGET_DATA}/google" "${TARGET_DATA}/restaurantos"
chmod 700 "${TARGET_DATA}/restaurantos/fonda" "${TARGET_DATA}/logs"

# Atomic release switch. The previous release remains a complete rollback target,
# including its own virtual environment.
if [[ -L "${TARGET_INSTALL}" ]]; then
    rm -f "${TARGET_PREVIOUS}"
    ln -s "$(readlink "${TARGET_INSTALL}")" "${TARGET_PREVIOUS}"
fi
ln -sfn "${RELEASE_PATH}" "${TARGET_INSTALL}"
echo "[install] ${TARGET_INSTALL} -> ${RELEASE_PATH}"

mkdir -p "${SYSTEMD_USER_DIR}"
shopt -s nullglob
for unit in "${RELEASE_PATH}/deploy/systemd"/*.service \
            "${RELEASE_PATH}/deploy/systemd"/*.timer; do
    cp "${unit}" "${SYSTEMD_USER_DIR}/"
done
shopt -u nullglob

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
systemctl --user daemon-reload

for service in "${SERVICES[@]}"; do
    systemctl --user enable --now "${service}"
done

restaurantos_ready=false
if [[ -s "${TARGET_DATA}/google/gmail-token.json" \
      && -s "${TARGET_DATA}/restaurantos/fonda/nightly-messages.jsonl" ]]; then
    restaurantos_ready=true
fi

for timer in "${TIMERS[@]}"; do
    if [[ "${timer}" == "atlas-restaurantos-nightly.timer" \
          && "${restaurantos_ready}" != true ]]; then
        systemctl --user disable --now "${timer}" >/dev/null 2>&1 || true
        echo "[install] ${timer} installed but disabled until private state is migrated"
        continue
    fi
    systemctl --user enable --now "${timer}"
    echo "[install] ${timer} enabled"
done

# Keep the current and previous releases naturally among the newest releases.
cd "${TARGET_RELEASES}"
mapfile -t OLD_RELEASES < <(ls -1dt atlas-* 2>/dev/null | tail -n +$((KEEP_RELEASES + 1)))
if [[ ${#OLD_RELEASES[@]} -gt 0 ]]; then
    rm -rf -- "${OLD_RELEASES[@]}"
fi

echo "[install] Installed ${RELEASE_NAME}"
