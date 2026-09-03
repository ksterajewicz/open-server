"""Identity resolution and application key handling."""

from __future__ import annotations

import stat

import pytest

from open_server import credentials
from open_server.config import ServerEntry
from open_server.credentials import resolve_identity


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "open-server"


def test_agent_mode_passes_no_identity_file():
    identity = resolve_identity(ServerEntry(name="web", host="h"))
    assert identity.key_path is None
    assert identity.ssh_args() == []


def test_app_key_is_generated_on_first_use():
    identity = resolve_identity(ServerEntry(name="web", host="h", key_ref="web-key"))

    assert identity.key_path is not None
    assert identity.key_path.exists()
    assert identity.ssh_args() == ["-i", str(identity.key_path)]

    public = identity.key_path.with_name(identity.key_path.name + ".pub")
    assert public.exists()
    assert public.read_text().startswith("ssh-ed25519 ")


def test_generated_key_is_private():
    identity = resolve_identity(ServerEntry(name="web", host="h", key_ref="web-key"))
    assert stat.S_IMODE(identity.key_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(credentials.keys_dir().stat().st_mode) == 0o700


def test_existing_key_is_reused():
    entry = ServerEntry(name="web", host="h", key_ref="web-key")
    first = resolve_identity(entry).key_path.read_bytes()
    second = resolve_identity(entry).key_path.read_bytes()
    assert first == second


def test_public_key_text_is_a_single_line():
    identity = resolve_identity(ServerEntry(name="web", host="h", key_ref="web-key"))
    text = credentials.public_key_text(identity.key_path)
    assert text.startswith("ssh-ed25519 ")
    assert "\n" not in text


def test_secrets_go_through_the_keyring(monkeypatch):
    stored = {}
    fake_keyring = type(
        "FakeKeyring",
        (),
        {
            "set_password": staticmethod(lambda s, u, p: stored.__setitem__((s, u), p)),
            "get_password": staticmethod(lambda s, u: stored.get((s, u))),
        },
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake_keyring)

    entry = ServerEntry(name="web", host="h")
    assert credentials.get_saved_secret(entry) is None
    credentials.save_secret(entry, "hunter2")
    assert credentials.get_saved_secret(entry) == "hunter2"
    assert stored == {(credentials.KEYRING_SERVICE, "web"): "hunter2"}
