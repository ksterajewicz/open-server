"""Server inventory: reading and writing ``servers.toml``.

This module is UI-agnostic on purpose — the TUI and any later web front end
call the same functions.  The inventory holds connection metadata only;
secrets live in the OS keyring or in key files, never in this file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import tomlkit

CONFIG_DIR_MODE = 0o700
SERVERS_FILE_MODE = 0o600

# Fields that must never appear in the inventory file.
FORBIDDEN_FIELDS = ("password", "passphrase", "secret")


class InventoryError(Exception):
    """Raised when ``servers.toml`` cannot be used as it stands."""


@dataclass
class ServerEntry:
    """One server in the inventory. Metadata only — no secrets."""

    name: str
    host: str
    port: int = 22
    user: str | None = None
    key_ref: str = "agent"

    def target(self) -> str:
        """Return the ``user@host`` (or bare host) string ssh expects."""
        return f"{self.user}@{self.host}" if self.user else self.host


def config_dir() -> Path:
    """Return the config directory, mirroring ``install/install.sh``."""
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(config_home) / "open-server"


def servers_file() -> Path:
    return config_dir() / "servers.toml"


def ensure_config_dir() -> Path:
    """Create the config directory with private permissions if missing."""
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(CONFIG_DIR_MODE)
    return directory


def load_servers() -> list[ServerEntry]:
    """Read the inventory. Returns an empty list when the file does not exist."""
    path = servers_file()
    if not path.exists():
        return []

    document = tomlkit.parse(path.read_text(encoding="utf-8"))
    entries = []
    for index, raw in enumerate(document.get("server", [])):
        entries.append(_entry_from_table(raw, index, path))
    return entries


def _entry_from_table(raw: dict, index: int, path: Path) -> ServerEntry:
    for field in FORBIDDEN_FIELDS:
        if field in raw:
            raise InventoryError(
                f"{path}: entry #{index + 1} has a '{field}' field. "
                "Secrets belong in the OS keyring, never in servers.toml — "
                "remove the field and store the secret with open-server instead."
            )

    for required in ("name", "host"):
        if required not in raw:
            raise InventoryError(f"{path}: entry #{index + 1} is missing '{required}'")

    return ServerEntry(
        name=str(raw["name"]),
        host=str(raw["host"]),
        port=int(raw.get("port", 22)),
        user=str(raw["user"]) if raw.get("user") else None,
        key_ref=str(raw.get("key_ref", "agent")),
    )


def save_servers(entries: list[ServerEntry]) -> None:
    """Write the inventory atomically, keeping the file private (0600)."""
    ensure_config_dir()
    path = servers_file()

    # Keep the installer's comment header if the file already has one.
    document = (
        tomlkit.parse(path.read_text(encoding="utf-8")) if path.exists() else tomlkit.document()
    )
    document.pop("server", None)

    tables = tomlkit.aot()
    for entry in entries:
        table = tomlkit.table()
        table["name"] = entry.name
        table["host"] = entry.host
        table["port"] = entry.port
        if entry.user:
            table["user"] = entry.user
        table["key_ref"] = entry.key_ref
        tables.append(table)
    document["server"] = tables

    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(tomlkit.dumps(document), encoding="utf-8")
    tmp_path.chmod(SERVERS_FILE_MODE)
    os.replace(tmp_path, path)
