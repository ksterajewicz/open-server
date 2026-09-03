"""Regression test for the user-local installer."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_installer_creates_command_and_desktop_entry(tmp_path: Path) -> None:
    home = tmp_path / "home"
    fake_bin = tmp_path / "fake-bin"
    install_root = tmp_path / "install-root"
    apps_dir = tmp_path / "applications"
    config_home = tmp_path / "config"
    data_home = tmp_path / "data"

    home.mkdir()
    fake_bin.mkdir()

    write_executable(
        fake_bin / "ssh",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    write_executable(
        fake_bin / "python3",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$#" -ge 3 && "$1" == "-m" && "$2" == "venv" && "$3" == "--help" ]]; then
    exit 0
fi
if [[ "$#" -ge 3 && "$1" == "-m" && "$2" == "venv" ]]; then
    venv_dir="$3"
    mkdir -p "$venv_dir/bin"
    cat > "$venv_dir/bin/pip" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exit 0
EOF
    cat > "$venv_dir/bin/open-server" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exit 0
EOF
    chmod 755 "$venv_dir/bin/pip" "$venv_dir/bin/open-server"
    exit 0
fi
exit 1
""",
    )

    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "install" / "install.sh"
    bin_dir = home / ".local" / "bin"

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "XDG_CONFIG_HOME": str(config_home),
            "XDG_DATA_HOME": str(data_home),
            "OPEN_SERVER_DATA_DIR": str(install_root),
            "OPEN_SERVER_APPS_DIR": str(apps_dir),
        }
    )

    subprocess.run(
        ["bash", str(script_path)],
        cwd=repo_root,
        env=env,
        check=True,
    )

    launcher_path = bin_dir / "open-server"
    desktop_path = apps_dir / "open-server.desktop"
    servers_file = config_home / "open-server" / "servers.toml"

    assert launcher_path.exists()
    assert os.access(launcher_path, os.X_OK)
    assert 'exec "' in launcher_path.read_text(encoding="utf-8")

    desktop = desktop_path.read_text(encoding="utf-8")
    assert "Name=open-server" in desktop
    assert f"Exec={launcher_path}" in desktop
    assert "Terminal=true" in desktop

    assert servers_file.exists()
    assert stat.S_IMODE(servers_file.stat().st_mode) == 0o600
