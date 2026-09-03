#!/usr/bin/env bash
# Prerequisite check + config scaffold for open-server.
set -euo pipefail

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    BOLD=$'\033[1m'
    GREEN=$'\033[32m'
    RED=$'\033[31m'
    RESET=$'\033[0m'
else
    BOLD=""
    GREEN=""
    RED=""
    RESET=""
fi

info() { printf '%s\n' "${GREEN}==>${RESET} $*"; }
fail() { printf '%s\n' "${RED}error:${RESET} $*" >&2; exit 1; }

check_prereqs() {
    command -v ssh >/dev/null 2>&1 || fail "ssh (OpenSSH client) not found in PATH"
    info "found ssh: $(command -v ssh)"
}

setup_config_dir() {
    local config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
    local config_dir="$config_home/open-server"
    local servers_file="$config_dir/servers.toml"

    if [[ ! -d "$config_dir" ]]; then
        mkdir -p "$config_dir"
        chmod 700 "$config_dir"
        info "created $config_dir"
    else
        info "$config_dir already exists, leaving as is"
    fi

    if [[ ! -f "$servers_file" ]]; then
        cat > "$servers_file" <<'EOF'
# open-server inventory: connection metadata only, never secrets.
# Add entries like:
#
# [[server]]
# name = "example"
# host = "example.com"
# port = 22
# user = "deploy"
EOF
        chmod 600 "$servers_file"
        info "created starter inventory: $servers_file"
    else
        info "$servers_file already exists, leaving as is"
    fi
}

main() {
    printf '%s\n' "${BOLD}open-server installer${RESET}"
    check_prereqs
    setup_config_dir
    info "done. see README.md for next steps."
}

main "$@"
