#!/usr/bin/env bash
# Install open-server into a user-local virtualenv, command wrapper, and desktop launcher.
set -euo pipefail

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    BOLD=$'\033[1m'
    GREEN=$'\033[32m'
    RED=$'\033[31m'
    YELLOW=$'\033[33m'
    RESET=$'\033[0m'
else
    BOLD=""
    GREEN=""
    RED=""
    YELLOW=""
    RESET=""
fi

info() { printf '%s\n' "${GREEN}==>${RESET} $*"; }
warn() { printf '%s\n' "${YELLOW}warning:${RESET} $*"; }
fail() { printf '%s\n' "${RED}error:${RESET} $*" >&2; exit 1; }

script_dir="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
python_bin="${PYTHON:-python3}"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
config_dir="$config_home/open-server"
servers_file="$config_dir/servers.toml"
install_root="${OPEN_SERVER_DATA_DIR:-$data_home/open-server}"
venv_dir="$install_root/.venv"
bin_dir="${OPEN_SERVER_BIN_DIR:-$HOME/.local/bin}"
launcher_path="$bin_dir/open-server"
apps_dir="${OPEN_SERVER_APPS_DIR:-$HOME/.local/share/applications}"
desktop_path="$apps_dir/open-server.desktop"

check_prereqs() {
    command -v ssh >/dev/null 2>&1 || fail "ssh (OpenSSH client) not found in PATH"
    command -v "$python_bin" >/dev/null 2>&1 || fail "$python_bin not found in PATH"
    "$python_bin" -m venv --help >/dev/null 2>&1 || fail "$python_bin does not support venv"
    info "found ssh: $(command -v ssh)"
    info "found python: $(command -v "$python_bin")"
}

setup_config_dir() {
    if [[ ! -d "$config_dir" ]]; then
        mkdir -p "$config_dir"
        chmod 700 "$config_dir"
        info "created $config_dir"
    else
        chmod 700 "$config_dir"
        info "$config_dir already exists, leaving contents as is"
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
        chmod 600 "$servers_file"
        info "$servers_file already exists, leaving contents as is"
    fi
}

install_package() {
    mkdir -p "$install_root"

    if [[ ! -d "$venv_dir" ]]; then
        "$python_bin" -m venv "$venv_dir"
        info "created virtualenv: $venv_dir"
    else
        info "$venv_dir already exists, reusing it"
    fi

    "$venv_dir/bin/pip" install --upgrade pip
    "$venv_dir/bin/pip" install --upgrade "$repo_root"
    info "installed open-server into $venv_dir"
}

install_launcher() {
    mkdir -p "$bin_dir"
    cat > "$launcher_path" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$venv_dir/bin/open-server" "\$@"
EOF
    chmod 755 "$launcher_path"
    info "installed launcher: $launcher_path"

    case ":$PATH:" in
        *":$bin_dir:"*) ;;
        *)
            warn "$bin_dir is not in PATH; the launcher command may need a new shell or PATH update"
            ;;
    esac
}

install_desktop_entry() {
    mkdir -p "$apps_dir"
    cat > "$desktop_path" <<EOF
[Desktop Entry]
Type=Application
Name=open-server
Comment=Self-hosted SSH connection manager
Exec=$launcher_path
TryExec=$launcher_path
Terminal=true
Categories=System;Utility;
StartupNotify=false
EOF
    chmod 644 "$desktop_path"
    info "installed desktop entry: $desktop_path"

    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$apps_dir" >/dev/null 2>&1 || true
    fi
}

verify_installation() {
    [[ -x "$venv_dir/bin/open-server" ]] || fail "missing venv entrypoint: $venv_dir/bin/open-server"
    [[ -x "$launcher_path" ]] || fail "missing launcher: $launcher_path"
    [[ -f "$desktop_path" ]] || fail "missing desktop entry: $desktop_path"
}

main() {
    printf '%s\n' "${BOLD}open-server installer${RESET}"
    check_prereqs
    setup_config_dir
    install_package
    install_launcher
    install_desktop_entry
    verify_installation
    info "done. launch with 'open-server' or from your applications menu."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
