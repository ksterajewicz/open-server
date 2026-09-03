"""Identity resolution and application key handling."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from open_server import credentials
from open_server.config import ServerEntry
from open_server.credentials import MissingKeyError, generate_app_key, resolve_identity


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "open-server"


def test_agent_mode_passes_no_identity_file():
    identity = resolve_identity(ServerEntry(name="web", host="h"))
    assert identity.key_path is None
    assert identity.ssh_args() == []


def test_a_missing_key_is_an_error_and_generates_nothing():
    """Owner's rule: a vanished key file must never be replaced behind the user.

    Generating one silently would hand ssh a key the server has never
    authorised — the user would see "Permission denied", not "key is gone".
    """
    entry = ServerEntry(name="web", host="h", key_ref="web-key")
    expected = credentials.keys_dir() / "web-key"

    with pytest.raises(MissingKeyError) as raised:
        resolve_identity(entry)

    assert str(expected) in str(raised.value)
    assert "web" in str(raised.value)
    assert not expected.exists()
    assert not expected.with_name("web-key.pub").exists()


def test_generating_a_key_is_an_explicit_call():
    key_path = generate_app_key(credentials.keys_dir() / "web-key")

    assert key_path.exists()
    public = key_path.with_name(key_path.name + ".pub")
    assert public.exists()
    assert public.read_text().startswith("ssh-ed25519 ")

    identity = resolve_identity(ServerEntry(name="web", host="h", key_ref="web-key"))
    assert identity.key_path == key_path
    assert identity.ssh_args() == ["-i", str(key_path)]


def test_generated_key_is_private():
    key_path = generate_app_key(credentials.keys_dir() / "web-key")
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(credentials.keys_dir().stat().st_mode) == 0o700


def test_generating_over_an_existing_key_is_refused():
    key_path = generate_app_key(credentials.keys_dir() / "web-key")
    before = key_path.read_bytes()

    with pytest.raises(FileExistsError):
        generate_app_key(key_path)
    assert key_path.read_bytes() == before


def test_existing_key_is_reused():
    generate_app_key(credentials.keys_dir() / "web-key")
    entry = ServerEntry(name="web", host="h", key_ref="web-key")
    first = resolve_identity(entry).key_path.read_bytes()
    second = resolve_identity(entry).key_path.read_bytes()
    assert first == second


def test_public_key_text_is_a_single_line():
    key_path = generate_app_key(credentials.keys_dir() / "web-key")
    text = credentials.public_key_text(key_path)
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


# --- finding the keys that are already on disk ------------------------------


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """A throwaway HOME so key scanning never sees the real ~/.ssh."""
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


def write_key(path: Path, *, with_pub: bool = False, header: bool = True) -> Path:
    body = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaAo=\n" if header else "not a key\n"
    path.write_text(body, encoding="utf-8")
    if with_pub:
        path.with_name(path.name + ".pub").write_text("ssh-ed25519 AAAA test\n", encoding="utf-8")
    return path


def test_private_keys_are_found_in_both_directories(fake_home):
    write_key(fake_home / ".ssh" / "id_ed25519", with_pub=True)
    credentials.ensure_keys_dir()
    write_key(credentials.keys_dir() / "app-key", with_pub=True)

    found = [path.name for path in credentials.list_private_keys()]
    assert found == ["id_ed25519", "app-key"]


def test_a_key_without_a_pub_is_recognised_by_its_header(fake_home):
    write_key(fake_home / ".ssh" / "lonely_key")
    assert [path.name for path in credentials.list_private_keys()] == ["lonely_key"]


def test_bookkeeping_files_are_not_keys(fake_home):
    ssh = fake_home / ".ssh"
    (ssh / "known_hosts").write_text("host ssh-rsa AAAA\n", encoding="utf-8")
    (ssh / "config").write_text("Host *\n", encoding="utf-8")
    (ssh / "authorized_keys").write_text("ssh-ed25519 AAAA me\n", encoding="utf-8")
    write_key(ssh / "id_rsa", with_pub=True)  # also drops id_rsa.pub next to it
    (ssh / "random.txt").write_text("hello\n", encoding="utf-8")
    (ssh / "binary.bin").write_bytes(b"\x00\x01\x02")

    assert [path.name for path in credentials.list_private_keys()] == ["id_rsa"]


def test_a_pub_file_alone_is_not_offered(fake_home):
    (fake_home / ".ssh" / "orphan.pub").write_text("ssh-ed25519 AAAA me\n", encoding="utf-8")
    assert credentials.list_private_keys() == []


def test_a_missing_ssh_directory_is_not_an_error(fake_home):
    (fake_home / ".ssh").rmdir()
    assert credentials.list_private_keys() == []


def test_key_choices_offer_the_agent_first(fake_home):
    write_key(fake_home / ".ssh" / "id_ed25519", with_pub=True)
    choices = credentials.key_choices()
    assert choices[0][1] == credentials.AGENT_MODE
    assert [value for _label, value in choices[1:]] == [str(fake_home / ".ssh" / "id_ed25519")]


# --- passwords --------------------------------------------------------------


def test_an_unsaved_password_lives_in_memory_only(monkeypatch):
    entry = ServerEntry(name="mem", host="h")
    monkeypatch.setattr(credentials, "get_saved_secret", lambda entry: None)

    credentials.cache_secret(entry, "hunter2")
    assert credentials.get_secret(entry) == "hunter2"
    credentials.forget_secret(entry)
    assert credentials.get_secret(entry) is None


def test_a_broken_keyring_means_no_secret(monkeypatch):
    def explode(entry):
        raise RuntimeError("no backend")

    monkeypatch.setattr(credentials, "get_saved_secret", explode)
    assert credentials.get_secret(ServerEntry(name="nowhere", host="h")) is None
