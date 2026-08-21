#!/usr/bin/env bash
# Install one Atlas release as the unprivileged target user.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy.config
source "${SCRIPT_DIR}/deploy.config"

RELEASE_NAME="${1:?Release name required}"
RELEASE_PATH="${TARGET_RELEASES}/${RELEASE_NAME}"
VENV_PATH="${RELEASE_PATH}/.venv"
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
"${VENV_PATH}/bin/python" "${WORKLOAD_TOOL}" "${WORKLOAD_MANIFEST}" validate >/dev/null

echo "[install] Runtime and workload registry verified"

# Atomic release switch. The previous release remains a complete rollback target,
# including its own virtual environment.
if [[ -L "${TARGET_INSTALL}" ]]; then
    rm -f "${TARGET_PREVIOUS}"
    ln -s "$(readlink "${TARGET_INSTALL}")" "${TARGET_PREVIOUS}"
fi
ln -sfn "${RELEASE_PATH}" "${TARGET_INSTALL}"
echo "[install] ${TARGET_INSTALL} -> ${RELEASE_PATH}"

bash "${RELEASE_PATH}/deploy/reconcile_workloads.sh" \
    "${RELEASE_PATH}" "${TARGET_DATA}"

# Keep the current and previous releases naturally among the newest releases.
cd "${TARGET_RELEASES}"
mapfile -t OLD_RELEASES < <(ls -1dt atlas-* 2>/dev/null | tail -n +$((KEEP_RELEASES + 1)))
if [[ ${#OLD_RELEASES[@]} -gt 0 ]]; then
    rm -rf -- "${OLD_RELEASES[@]}"
fi

echo "[install] Installed ${RELEASE_NAME}"
