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
WORKLOAD_MANIFEST="${RELEASE_PATH}/${WORKLOAD_MANIFEST_RELATIVE}"
WORKLOAD_TOOL="${RELEASE_PATH}/deploy/bin/workload_registry.py"

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

WORKLOAD_CTL=("${VENV_PATH}/bin/python" "${WORKLOAD_TOOL}" "${WORKLOAD_MANIFEST}")
"${WORKLOAD_CTL[@]}" validate >/dev/null

echo "[install] Runtime and workload registry verified"

# Persistent state is deliberately outside every release. Workloads declare only
# relative data directories; credentials and data themselves are never in Git.
mkdir -p "${TARGET_DATA}"
chmod 700 "${TARGET_DATA}"
mapfile -t DATA_DIRS < <("${WORKLOAD_CTL[@]}" data-dirs)
for relative in "${DATA_DIRS[@]}"; do
    mkdir -p "${TARGET_DATA}/${relative}"
    chmod 700 "${TARGET_DATA}/${relative}"
done

# Atomic release switch. The previous release remains a complete rollback target,
# including its own virtual environment.
if [[ -L "${TARGET_INSTALL}" ]]; then
    rm -f "${TARGET_PREVIOUS}"
    ln -s "$(readlink "${TARGET_INSTALL}")" "${TARGET_PREVIOUS}"
fi
ln -sfn "${RELEASE_PATH}" "${TARGET_INSTALL}"
echo "[install] ${TARGET_INSTALL} -> ${RELEASE_PATH}"

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
mkdir -p "${SYSTEMD_USER_DIR}"

mapfile -t SERVICES < <("${WORKLOAD_CTL[@]}" services)
mapfile -t TIMERS < <("${WORKLOAD_CTL[@]}" timers)
REGISTERED_UNITS=("${SERVICES[@]}" "${TIMERS[@]}")

# Retire Atlas units removed from the declarative registry.
shopt -s nullglob
for existing in "${SYSTEMD_USER_DIR}"/atlas-*.service \
                "${SYSTEMD_USER_DIR}"/atlas-*.timer; do
    unit="$(basename "${existing}")"
    keep=false
    for registered in "${REGISTERED_UNITS[@]}"; do
        if [[ "${unit}" == "${registered}" ]]; then
            keep=true
            break
        fi
    done
    if [[ "${keep}" != true ]]; then
        systemctl --user disable --now "${unit}" >/dev/null 2>&1 || true
        rm -f "${existing}"
        echo "[install] Retired undeclared unit ${unit}"
    fi
done

for unit in "${RELEASE_PATH}/deploy/systemd"/*.service \
            "${RELEASE_PATH}/deploy/systemd"/*.timer; do
    cp "${unit}" "${SYSTEMD_USER_DIR}/"
done
shopt -u nullglob
systemctl --user daemon-reload

mapfile -t BLOCKED_SERVICES < <(
    "${WORKLOAD_CTL[@]}" blocked-services --data-root "${TARGET_DATA}"
)
mapfile -t READY_SERVICES < <(
    "${WORKLOAD_CTL[@]}" ready-services --data-root "${TARGET_DATA}"
)
mapfile -t BLOCKED_TIMERS < <(
    "${WORKLOAD_CTL[@]}" blocked-timers --data-root "${TARGET_DATA}"
)
mapfile -t READY_TIMERS < <(
    "${WORKLOAD_CTL[@]}" ready-timers --data-root "${TARGET_DATA}"
)

for unit in "${BLOCKED_SERVICES[@]}" "${BLOCKED_TIMERS[@]}"; do
    [[ -n "${unit}" ]] || continue
    systemctl --user disable --now "${unit}" >/dev/null 2>&1 || true
    echo "[install] ${unit} blocked until required private state exists"
done

for service in "${READY_SERVICES[@]}"; do
    systemctl --user enable "${service}" >/dev/null
    if systemctl --user is-active --quiet "${service}"; then
        systemctl --user restart "${service}"
    else
        systemctl --user start "${service}"
    fi
    echo "[install] ${service} active"
done

for timer in "${READY_TIMERS[@]}"; do
    systemctl --user enable "${timer}" >/dev/null
    if systemctl --user is-active --quiet "${timer}"; then
        systemctl --user restart "${timer}"
    else
        systemctl --user start "${timer}"
    fi
    echo "[install] ${timer} active"
done

# Keep the current and previous releases naturally among the newest releases.
cd "${TARGET_RELEASES}"
mapfile -t OLD_RELEASES < <(ls -1dt atlas-* 2>/dev/null | tail -n +$((KEEP_RELEASES + 1)))
if [[ ${#OLD_RELEASES[@]} -gt 0 ]]; then
    rm -rf -- "${OLD_RELEASES[@]}"
fi

echo "[install] Installed ${RELEASE_NAME}"
