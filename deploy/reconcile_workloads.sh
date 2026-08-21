#!/usr/bin/env bash
# Reconcile one installed Atlas release's workload registry with systemd --user.

set -euo pipefail

ACTIVE_RELEASE="${1:?Active release path required}"
TARGET_DATA="${2:?Persistent Atlas data path required}"
VENV_PATH="${ACTIVE_RELEASE}/.venv"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
WORKLOAD_MANIFEST="${ACTIVE_RELEASE}/deploy/workloads.toml"
WORKLOAD_TOOL="${ACTIVE_RELEASE}/deploy/bin/workload_registry.py"
WORKLOAD_CTL=("${VENV_PATH}/bin/python" "${WORKLOAD_TOOL}" "${WORKLOAD_MANIFEST}")

"${WORKLOAD_CTL[@]}" validate >/dev/null

mkdir -p "${TARGET_DATA}"
chmod 700 "${TARGET_DATA}"
mapfile -t DATA_DIRS < <("${WORKLOAD_CTL[@]}" data-dirs)
for relative in "${DATA_DIRS[@]}"; do
    mkdir -p "${TARGET_DATA}/${relative}"
    chmod 700 "${TARGET_DATA}/${relative}"
done

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
mkdir -p "${SYSTEMD_USER_DIR}"

mapfile -t SERVICES < <("${WORKLOAD_CTL[@]}" services)
mapfile -t TIMERS < <("${WORKLOAD_CTL[@]}" timers)
REGISTERED_UNITS=("${SERVICES[@]}" "${TIMERS[@]}")

# Retire Atlas units removed from the active declarative registry.
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
        echo "[workloads] Retired undeclared unit ${unit}"
    fi
done

for unit in "${ACTIVE_RELEASE}/deploy/systemd"/*.service \
            "${ACTIVE_RELEASE}/deploy/systemd"/*.timer; do
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
    echo "[workloads] ${unit} blocked until required private state exists"
done

for service in "${READY_SERVICES[@]}"; do
    systemctl --user enable "${service}" >/dev/null
    if systemctl --user is-active --quiet "${service}"; then
        systemctl --user restart "${service}"
    else
        systemctl --user start "${service}"
    fi
    echo "[workloads] ${service} active"
done

for timer in "${READY_TIMERS[@]}"; do
    systemctl --user enable "${timer}" >/dev/null
    if systemctl --user is-active --quiet "${timer}"; then
        systemctl --user restart "${timer}"
    else
        systemctl --user start "${timer}"
    fi
    echo "[workloads] ${timer} active"
done
