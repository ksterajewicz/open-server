"""End-to-end TUI tests driven by Textual's headless harness (no real ssh)."""

from __future__ import annotations

import stat
import time

import pytest
from textual.widgets import Button, Checkbox, Input, Static

from open_server import config, credentials, updater
from open_server.app import OpenServerApp
from open_server.config import ServerEntry, save_servers
from open_server.screens import servers as servers_module
from open_server.screens.servers import AddServerScreen
from open_server.screens.update import UpdateScreen
from open_server.ssh_session import SshSession
from open_server.widgets import dashboard as dashboard_module


def real_session_factory(entry: ServerEntry, **kwargs) -> SshSession:
    """A session that builds its own ssh command, so key resolution really runs."""
    return SshSession(entry, **kwargs)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "open-server"


@pytest.fixture(autouse=True)
def fake_ssh(monkeypatch):
    """Replace ssh with a local shell so panels behave without a server."""

    def factory(entry: ServerEntry, **kwargs) -> SshSession:
        kwargs.pop("command", None)
        return SshSession(entry, command=["bash", "--norc", "-i"], **kwargs)

    monkeypatch.setattr(dashboard_module, "SshSession", factory)
    # Never touch the real OS keyring from the test suite.
    monkeypatch.setattr(dashboard_module, "get_secret", lambda entry: None)


def wait_for(predicate, timeout: float = 5.0) -> bool:
    """Wait on a background thread's work (session output) — no event loop needed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


async def wait_for_app(pilot, predicate, timeout: float = 5.0) -> bool:
    """Wait on work the Textual event loop has to run — must not block it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await pilot.pause(0.05)
    return False


async def test_app_starts_with_no_panels():
    async with OpenServerApp().run_test() as pilot:
        assert pilot.app.dashboard.panels == []


async def test_multiple_panels_run_side_by_side():
    app = OpenServerApp()
    async with app.run_test() as pilot:
        await app.dashboard.add_panel(ServerEntry(name="web", host="h1"))
        await app.dashboard.add_panel(ServerEntry(name="db", host="h2"))
        await pilot.pause()

        panels = app.dashboard.panels
        assert len(panels) == 2
        assert [panel.entry.name for panel in panels] == ["web", "db"]
        assert all(panel.session.is_alive() for panel in panels)

        app.dashboard.close_all()


async def test_only_the_focused_panel_runs_an_emulator():
    app = OpenServerApp()
    async with app.run_test() as pilot:
        first = await app.dashboard.add_panel(ServerEntry(name="web", host="h1"))
        second = await app.dashboard.add_panel(ServerEntry(name="db", host="h2"))
        await pilot.pause()

        # The newest panel takes focus, so the first one dropped its emulator.
        assert second.has_focus
        assert second.session._screen is not None
        assert first.session._screen is None

        app.dashboard.close_all()


async def test_keystrokes_reach_the_focused_shell():
    app = OpenServerApp()
    async with app.run_test() as pilot:
        panel = await app.dashboard.add_panel(ServerEntry(name="web", host="h1"))
        await pilot.pause()

        await pilot.press("e", "c", "h", "o", "space", "t", "e", "s", "t", "1", "2", "3", "enter")
        assert wait_for(lambda: any("test123" in line for line in panel.session.raw_lines()))

        app.dashboard.close_all()


async def test_f6_moves_focus_between_panels():
    app = OpenServerApp()
    async with app.run_test() as pilot:
        first = await app.dashboard.add_panel(ServerEntry(name="web", host="h1"))
        second = await app.dashboard.add_panel(ServerEntry(name="db", host="h2"))
        await pilot.pause()

        assert second.has_focus
        await pilot.press("f6")
        await pilot.pause()
        assert first.has_focus

        app.dashboard.close_all()


async def test_f4_closes_the_focused_panel_and_kills_the_process():
    app = OpenServerApp()
    async with app.run_test() as pilot:
        panel = await app.dashboard.add_panel(ServerEntry(name="web", host="h1"))
        await pilot.pause()

        await pilot.press("f4")
        await pilot.pause()

        assert app.dashboard.panels == []
        assert not panel.session.is_alive()


async def test_servers_screen_lists_saved_entries():
    save_servers([ServerEntry(name="web", host="web.example.com", user="deploy")])

    app = OpenServerApp()
    async with app.run_test() as pilot:
        await pilot.press("f2")
        await pilot.pause()

        screen = app.screen
        assert [entry.name for entry in screen.entries] == ["web"]

        await pilot.press("escape")
        await pilot.pause()


async def test_connecting_from_the_inventory_opens_a_panel():
    save_servers([ServerEntry(name="web", host="web.example.com", user="deploy")])

    app = OpenServerApp()
    async with app.run_test() as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert await wait_for_app(pilot, lambda: len(app.dashboard.panels) == 1)
        assert app.dashboard.panels[0].entry.name == "web"

        app.dashboard.close_all()


async def test_adding_a_server_persists_it():
    """The form is keyboard-only: type user, tab to host, Ctrl+S to save."""
    app = OpenServerApp()
    async with app.run_test() as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        await pilot.press("d", "e", "p", "l", "o", "y")
        await pilot.press("tab")
        await pilot.press("h", "1")
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()

        saved = config.load_servers()
        assert [(entry.name, entry.host, entry.user, entry.port) for entry in saved] == [
            ("deploy@h1", "h1", "deploy", 22)
        ]


async def test_the_form_refuses_an_entry_without_a_host():
    app = OpenServerApp()
    async with app.run_test() as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        await pilot.press("d", "e", "p", "l", "o", "y")
        await pilot.press("ctrl+s")
        await pilot.pause()

        # Still on the form, nothing written.
        assert isinstance(app.screen, AddServerScreen)
        assert config.load_servers() == []

        await pilot.press("escape")
        await pilot.pause()


async def test_a_remembered_password_goes_to_the_keyring_only(monkeypatch):
    """`remember` checked -> OS keyring; servers.toml never sees the password."""
    stored: dict[str, str] = {}
    monkeypatch.setattr(
        servers_module, "save_secret", lambda entry, secret: stored.__setitem__(entry.name, secret)
    )

    app = OpenServerApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        await pilot.press("d", "e", "p", "l", "o", "y")
        await pilot.press("tab")
        await pilot.press("h", "1")
        await pilot.press("tab")
        await pilot.press("s", "3", "c", "r", "e", "t")
        await pilot.pause()

        app.screen.query_one("#remember", Checkbox).value = True
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert stored == {"deploy@h1": "s3cret"}
    inventory = config.servers_file().read_text(encoding="utf-8")
    assert "s3cret" not in inventory
    # And the file is still loadable, i.e. the no-secrets rule was not tripped.
    assert [entry.host for entry in config.load_servers()] == ["h1"]


async def test_an_unremembered_password_stays_in_memory_only(monkeypatch):
    saved_to_keyring: list[str] = []
    monkeypatch.setattr(
        servers_module, "save_secret", lambda entry, secret: saved_to_keyring.append(secret)
    )

    app = OpenServerApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        await pilot.press("h", "o", "s", "t", "1")  # user field, then move on
        await pilot.press("tab")
        await pilot.press("h", "1")
        await pilot.press("tab")
        await pilot.press("m", "e", "m")
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert saved_to_keyring == []
    assert credentials._MEMORY_SECRETS.get("host1@h1") == "mem"
    assert "mem" not in config.servers_file().read_text(encoding="utf-8")
    credentials.forget_secret(ServerEntry(name="host1@h1", host="h1"))


async def test_the_password_field_is_masked():
    app = OpenServerApp()
    async with app.run_test() as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        assert app.screen.query_one("#password", Input).password is True

        await pilot.press("escape")
        await pilot.pause()


async def test_no_screen_in_the_app_contains_a_button():
    """Owner's rule: keyboard only, so there must be no clickable buttons."""
    app = OpenServerApp()
    async with app.run_test() as pilot:
        await app.dashboard.add_panel(ServerEntry(name="web", host="h1"))
        await pilot.pause()
        assert list(app.screen.query(Button)) == []

        await pilot.press("f2")
        await pilot.pause()
        assert list(app.screen.query(Button)) == []

        await pilot.press("a")
        await pilot.pause()
        assert list(app.screen.query(Button)) == []

        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause()

        # The two new screens are held to the same rule.
        await pilot.press("f7")
        await pilot.pause()
        assert list(app.screen.query(Button)) == []
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("f9")
        await pilot.pause()
        assert list(app.screen.query(Button)) == []
        await pilot.press("escape")
        await pilot.pause()

        app.dashboard.close_all()


# --- a missing key file is an error the user can read -----------------------


async def test_connecting_with_a_missing_key_notifies_instead_of_crashing(monkeypatch):
    """Without this you would see a traceback (or worse, a silent new key)."""
    save_servers([ServerEntry(name="web", host="h1", key_ref="gone-key")])

    # Use the real ssh_command path so resolve_identity actually runs.
    monkeypatch.setattr(dashboard_module, "SshSession", real_session_factory)

    app = OpenServerApp()
    async with app.run_test() as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert app.dashboard.panels == []
        # The placeholder is still there: the dashboard was left untouched.
        assert app.query(".placeholder")
        messages = [str(notification.message) for notification in app._notifications]
        assert any("gone-key" in message for message in messages), messages
        assert not (credentials.keys_dir() / "gone-key").exists()


# --- generating an application key on purpose -------------------------------


async def test_f7_generates_a_key_and_shows_its_public_half(isolated_config):
    app = OpenServerApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f7")
        await pilot.pause()

        await pilot.press("d", "e", "m", "o", "enter")
        await pilot.pause()

        key_path = credentials.keys_dir() / "demo"
        assert key_path.exists()
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
        assert key_path.with_name("demo.pub").exists()

        shown = str(app.screen.query_one("#pubkey", Static).content)
        assert shown.startswith("ssh-ed25519 ")
        assert shown == credentials.public_key_text(key_path)

        await pilot.press("escape")
        await pilot.pause()


async def test_a_key_is_never_created_just_by_opening_the_screen(isolated_config):
    app = OpenServerApp()
    async with app.run_test() as pilot:
        await pilot.press("f7")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert not credentials.keys_dir().exists() or list(credentials.keys_dir().iterdir()) == []


# --- the update screen ------------------------------------------------------


async def test_f9_opens_the_update_screen_and_channels_persist(monkeypatch, tmp_path):
    monkeypatch.setenv("OPEN_SERVER_DATA_DIR", str(tmp_path / "data"))

    app = OpenServerApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f9")
        await pilot.pause()

        assert isinstance(app.screen, UpdateScreen)
        assert app.screen.channel == "stable"

        await pilot.press("r")
        await pilot.pause()
        assert app.screen.channel == "rolling"
        assert updater.current_channel() == "rolling"

        state = str(app.screen.query_one("#state", Static).content)
        assert "rolling" in state

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, UpdateScreen)


async def test_the_update_screen_reports_a_failure_without_a_traceback(monkeypatch, tmp_path):
    """No checkout and no network: the user gets a sentence, not a stack trace."""
    monkeypatch.setenv("OPEN_SERVER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(updater, "REPO_URL", str(tmp_path / "nowhere"))

    app = OpenServerApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("f9")
        await pilot.pause()
        await pilot.press("u")

        assert await wait_for_app(pilot, lambda: app.screen._busy is False, timeout=30)
        messages = [str(notification.message) for notification in app._notifications]
        assert messages, "the failure should have been shown to the user"
        assert all("Traceback" not in message for message in messages)

        await pilot.press("escape")
        await pilot.pause()
