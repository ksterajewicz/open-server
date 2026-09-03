"""End-to-end TUI tests driven by Textual's headless harness (no real ssh)."""

from __future__ import annotations

import time

import pytest

from open_server import config
from open_server.app import OpenServerApp
from open_server.config import ServerEntry, save_servers
from open_server.ssh_session import SshSession
from open_server.widgets import dashboard as dashboard_module


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "open-server"


@pytest.fixture(autouse=True)
def fake_ssh(monkeypatch):
    """Replace ssh with a local shell so panels behave without a server."""

    def factory(entry: ServerEntry) -> SshSession:
        return SshSession(entry, command=["bash", "--norc", "-i"])

    monkeypatch.setattr(dashboard_module, "SshSession", factory)


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
    app = OpenServerApp()
    async with app.run_test() as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        await pilot.press("w", "e", "b")
        await pilot.press("tab")
        await pilot.press("h", "1")
        await pilot.pause()

        await pilot.click("#save")
        await pilot.pause()

        saved = config.load_servers()
        assert [(entry.name, entry.host) for entry in saved] == [("web", "h1")]
