#!/usr/bin/env bash
# Atlas deployment orchestrator. Run locally from Git Bash or Linux/macOS.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy.config
source "${SCRIPT_DIR}/deploy.config"

log() { printf '[deploy] %s\n' "$*"; }
fail() {
    printf '[deploy] ERROR: %s\n' "$*" >&2
    exit 1
}

preflight() {
    [[ -f "${LOCAL_SOURCE}/pyproject.toml" ]] || fail "Atlas pyproject.toml not found"
    [[ -f "${LOCAL_SOURCE}/apps/restaurantos/pyproject.toml" ]] || \
        fail "RestaurantOS project not found"
    command -v tar >/dev/null || fail "tar is required"
    command -v ssh >/dev/null || fail "ssh is required"
    command -v scp >/dev/null || fail "scp is required"

    ssh -o ConnectTimeout=5 -o BatchMode=yes "${BASTION_HOST}" \
        "echo connected" >/dev/null 2>&1 || \
        fail "Cannot SSH to bastion ${BASTION_HOST}"

    ssh "${BASTION_HOST}" \
        "ssh -o ConnectTimeout=5 -o BatchMode=yes ${TARGET_HOST} echo connected" \
        >/dev/null 2>&1 || fail "Bastion cannot reach ${TARGET_HOST}"

    local python_path
    python_path=$(ssh "${BASTION_HOST}" \
        "ssh ${TARGET_HOST} command -v ${PYTHON_VERSION}" 2>/dev/null || true)
    [[ -n "${python_path}" ]] || \
        fail "${PYTHON_VERSION} is not installed on ${TARGET_HOST}"

    log "Preflight passed"
}

build_release() {
    local exclude_args=(
        --exclude='.git'
        --exclude='.venv'
        --exclude='venv'
        --exclude='__pycache__'
        --exclude='*.pyc'
        --exclude='.pytest_cache'
        --exclude='.coverage'
        --exclude='*.egg-info'
        --exclude='*.log'
        --exclude='.env'
        --exclude='deploy/.env'
        --exclude='datasets/private'
    )

    tar -czf "${RELEASE_TARBALL}" \
        "${exclude_args[@]}" \
        -C "$(dirname "${LOCAL_SOURCE}")" \
        "$(basename "${LOCAL_SOURCE}")"
    log "Built ${RELEASE_TARBALL}"
}

ship_release() {
    ssh "${BASTION_HOST}" "rm -rf '${BASTION_STAGING}' && mkdir -p '${BASTION_STAGING}'"
    scp -q \
        "${RELEASE_TARBALL}" \
        "${SCRIPT_DIR}/handoff.sh" \
        "${SCRIPT_DIR}/deploy.config" \
        "${BASTION_HOST}:${BASTION_STAGING}/"
    ssh "${BASTION_HOST}" \
        "cd '${BASTION_STAGING}' && bash handoff.sh '${RELEASE_NAME}'"
    ssh "${BASTION_HOST}" "rm -rf '${BASTION_STAGING}'" || true
    rm -f "${RELEASE_TARBALL}"
}

target_uid() {
    ssh "${BASTION_HOST}" "ssh ${TARGET_HOST} id -u ${TARGET_USER}"
}

remote_user_systemctl() {
    local uid="$1"
    shift
    ssh "${BASTION_HOST}" \
        "ssh ${TARGET_HOST} sudo -u ${TARGET_USER} -H env \
         XDG_RUNTIME_DIR=/run/user/${uid} \
         DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${uid}/bus \
         systemctl --user $*"
}

status() {
    local uid
    uid=$(target_uid)

    log "Current Atlas release"
    ssh "${BASTION_HOST}" \
        "ssh ${TARGET_HOST} readlink -f '${TARGET_INSTALL}' || true"

    log "RestaurantOS timer"
    remote_user_systemctl "${uid}" status atlas-restaurantos-nightly.timer \
        --no-pager || true

    log "Last RestaurantOS service result"
    remote_user_systemctl "${uid}" show atlas-restaurantos-nightly.service \
        --property=Result --property=ExecMainStatus --property=ExecMainStartTimestamp \
        --no-pager || true
}

logs() {
    local unit="${1:-atlas-restaurantos-nightly.service}"
    local uid
    uid=$(target_uid)
    ssh -t "${BASTION_HOST}" \
        "ssh -t ${TARGET_HOST} sudo -u ${TARGET_USER} -H env \
         XDG_RUNTIME_DIR=/run/user/${uid} \
         DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${uid}/bus \
         journalctl --user -u '${unit}' -n 100 -f"
}

run_restaurantos() {
    local uid
    uid=$(target_uid)
    remote_user_systemctl "${uid}" start atlas-restaurantos-nightly.service
    status
}

rollback() {
    ssh "${BASTION_HOST}" \
        "ssh ${TARGET_HOST} sudo -u ${TARGET_USER} -H bash '${TARGET_INSTALL}/deploy/rollback.sh'"
    status
}

main() {
    case "${1:-deploy}" in
        deploy)
            preflight
            build_release
            ship_release
            status
            ;;
        status)
            status
            ;;
        logs)
            logs "${2:-atlas-restaurantos-nightly.service}"
            ;;
        run-restaurantos)
            run_restaurantos
            ;;
        rollback)
            rollback
            ;;
        *)
            cat <<'EOF'
Usage: bash deploy/deploy.sh [command]

Commands:
  deploy                 Build and deploy a new Atlas release
  status                 Show current release and RestaurantOS timer state
  logs [unit]            Follow systemd user logs
  run-restaurantos       Run RestaurantOS refresh once now
  rollback               Atomically switch to the previous release
EOF
            exit 1
            ;;
    esac
}

main "$@"
