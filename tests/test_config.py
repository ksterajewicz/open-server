"""Inventory round-trip, permissions, and the no-secrets rule."""

from __future__ import annotations

import stat

import pytest

from open_server import config
from open_server.config import InventoryError, ServerEntry, load_servers, save_servers


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point the config dir at a temp directory for every test."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "open-server"


def test_load_returns_empty_when_no_file():
    assert load_servers() == []


def test_round_trip_preserves_fields():
    entries = [
        ServerEntry(name="web", host="web.example.com", port=2222, user="deploy"),
        ServerEntry(name="db", host="10.0.0.5", key_ref="db-key"),
    ]
    save_servers(entries)

    loaded = load_servers()
    assert loaded == entries


def test_saved_file_is_private():
    save_servers([ServerEntry(name="web", host="web.example.com")])
    mode = stat.S_IMODE(config.servers_file().stat().st_mode)
    assert mode == 0o600


def test_config_dir_is_private():
    save_servers([ServerEntry(name="web", host="web.example.com")])
    mode = stat.S_IMODE(config.config_dir().stat().st_mode)
    assert mode == 0o700


def test_defaults_are_applied():
    save_servers([ServerEntry(name="web", host="web.example.com")])
    entry = load_servers()[0]
    assert entry.port == 22
    assert entry.user is None
    assert entry.key_ref == "agent"


@pytest.mark.parametrize("field", ["password", "passphrase", "secret"])
def test_plaintext_secret_is_rejected(field):
    config.ensure_config_dir()
    config.servers_file().write_text(
        f'[[server]]\nname = "web"\nhost = "web.example.com"\n{field} = "hunter2"\n',
        encoding="utf-8",
    )
    with pytest.raises(InventoryError, match=field):
        load_servers()


def test_missing_required_field_is_rejected():
    config.ensure_config_dir()
    config.servers_file().write_text('[[server]]\nname = "web"\n', encoding="utf-8")
    with pytest.raises(InventoryError, match="host"):
        load_servers()


def test_installer_comments_survive_a_save():
    config.ensure_config_dir()
    config.servers_file().write_text(
        "# open-server inventory: connection metadata only, never secrets.\n",
        encoding="utf-8",
    )
    save_servers([ServerEntry(name="web", host="web.example.com")])
    assert "# open-server inventory" in config.servers_file().read_text(encoding="utf-8")


def test_target_string():
    assert ServerEntry(name="w", host="h", user="deploy").target() == "deploy@h"
    assert ServerEntry(name="w", host="h").target() == "h"
