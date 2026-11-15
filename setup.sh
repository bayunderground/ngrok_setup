#!/usr/bin/env bash
# ngrok SSH tunnel setup for Raspberry Pi OS / Debian 13 arm64.
#
# Usage: sudo ./setup.sh [--dry-run] [--user NAME] {check|status|install|uninstall}
#
#   check      read-only validation of the system and project files
#   status     show the active endpoint and unit states
#   install    install project-owned files and enable project-owned units
#   uninstall  remove only project-owned files and units
#
# Test hooks (not for normal use):
#   NGROK_SSH_ROOT          prefix for system paths; when set, systemctl is skipped
#   NGROK_SSH_OS_RELEASE    path to an os-release file (default /etc/os-release)
#   NGROK_SSH_ARCH          architecture string (default: uname -m)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_PREFIX="${NGROK_SSH_ROOT:-}"
OS_RELEASE_FILE="${NGROK_SSH_OS_RELEASE:-/etc/os-release}"
DRY_RUN=0
TARGET_USER="bliss"
FAILURES=0

usage() {
    sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; FAILURES=$((FAILURES + 1)); }

check_os() {
    local id version
    id="$(. "$OS_RELEASE_FILE" && printf '%s' "${ID:-}")"
    version="$(. "$OS_RELEASE_FILE" && printf '%s' "${VERSION_ID:-}")"
    if [[ "$id" == "debian" && "$version" == "13" ]]; then
        pass "OS is Debian 13"
    else
        fail "OS must be Debian 13 (found ID=${id:-?} VERSION_ID=${version:-?})"
    fi
}

check_arch() {
    local arch="${NGROK_SSH_ARCH:-$(uname -m)}"
    if [[ "$arch" == "aarch64" || "$arch" == "arm64" ]]; then
        pass "architecture is arm64"
    else
        fail "architecture must be arm64 (found $arch)"
    fi
}

check_systemd() {
    if [[ -z "$ROOT_PREFIX" ]] && command -v systemctl >/dev/null 2>&1 \
        && [[ "$(systemctl is-system-running 2>/dev/null || true)" != "offline" ]]; then
        pass "systemd is available"
    elif [[ -n "$ROOT_PREFIX" ]]; then
        pass "systemd check skipped (test root)"
    else
        fail "systemd is not available"
    fi
}

check_networkmanager() {
    if [[ -n "$ROOT_PREFIX" ]]; then
        pass "NetworkManager check skipped (test root)"
    elif command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager; then
        pass "NetworkManager is active"
    else
        fail "NetworkManager is not active"
    fi
}

check_user() {
    if id "$TARGET_USER" >/dev/null 2>&1; then
        pass "user $TARGET_USER exists"
    else
        fail "user $TARGET_USER does not exist"
    fi
}

check_ngrok() {
    local bin="$ROOT_PREFIX/usr/local/bin/ngrok"
    if [[ -x "$bin" ]] || command -v ngrok >/dev/null 2>&1; then
        pass "ngrok is installed ($("${bin}" version 2>/dev/null || ngrok version 2>/dev/null | head -1))"
    else
        fail "ngrok is not installed"
    fi
}

check_project_files() {
    local missing=0 f
    for f in config/ngrok-ssh.yml scripts/ngrok-endpoint.py scripts/ngrok_recover.py \
        scripts/ngrok_notify_check.py dispatcher/50-ngrok-ssh \
        systemd/ngrok-ssh.service systemd/ngrok-ssh-recover.service systemd/ngrok-ssh-recover.timer; do
        [[ -f "$PROJECT_DIR/$f" ]] || { missing=1; fail "missing project file $f"; }
    done
    [[ $missing -eq 0 ]] && pass "project files are present"
}

run_check() {
    check_os
    check_arch
    check_systemd
    check_networkmanager
    check_user
    check_ngrok
    check_project_files
    if [[ $FAILURES -eq 0 ]]; then
        echo "check passed"
        return 0
    fi
    echo "check failed: $FAILURES problem(s)"
    return 1
}

run_status() {
    local state unit
    state="$(python3 "$PROJECT_DIR/scripts/ngrok-endpoint.py" --status || true)"
    echo "${state:-state=unknown}"
    if [[ -n "$ROOT_PREFIX" ]]; then
        echo "units: skipped (test root)"
        return 0
    fi
    for unit in ngrok-ssh.service ngrok-ssh-recover.timer ngrok-ssh-notify.timer; do
        echo "unit $unit: $(systemctl is-active "$unit" 2>/dev/null || true)"
    done
}

parse_args() {
    local positional=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run) DRY_RUN=1 ;;
            --user) TARGET_USER="${2:?--user needs a name}"; shift ;;
            -h|--help) usage; exit 0 ;;
            *) positional+=("$1") ;;
        esac
        shift
    done
    COMMAND="${positional[0]:-}"
    if [[ -z "$COMMAND" ]]; then
        usage
        exit 2
    fi
}

main() {
    parse_args "$@"
    case "$COMMAND" in
        check) run_check ;;
        status) run_status ;;
        install|uninstall)
            echo "error: '$COMMAND' is not implemented yet" >&2
            exit 2 ;;
        *) echo "error: unknown command '$COMMAND'" >&2; usage >&2; exit 2 ;;
    esac
}

main "$@"
