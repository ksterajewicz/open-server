"""Scaling audit: every screen is rendered at four terminal sizes and measured.

Nothing here trusts the CSS — each test reads back the regions Textual actually
laid out, so a hard-coded width or a stray padding shows up as a failure.
"""

from __future__ import annotations

import pytest
from textual.widgets import DataTable, Input, Label, Select, Static

from open_server.app import OpenServerApp
from open_server.config import ServerEntry, save_servers
from open_server.screens.servers import AddServerScreen, ServersScreen, fit
from open_server.ssh_session import SshSession
from open_server.widgets.dashboard import MIN_PANEL_HEIGHT, MIN_PANEL_WIDTH, Dashboard
from open_server.widgets.terminal_panel import TerminalPanel

SIZES = [(60, 18), (80, 24), (120, 40), (200, 50)]


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "open-server"


@pytest.fixture(autouse=True)
def fake_ssh(monkeypatch):
    from open_server.widgets import dashboard as dashboard_module

    def factory(entry: ServerEntry, **kwargs) -> SshSession:
        kwargs.pop("command", None)
        return SshSession(entry, command=["cat"], **kwargs)

    monkeypatch.setattr(dashboard_module, "SshSession", factory)
    monkeypatch.setattr(dashboard_module, "get_secret", lambda entry: None)


def horizontal_overflow(app) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Widgets whose laid-out region sticks out sideways past the screen."""
    bounds = app.screen.region
    offenders = []
    for widget in app.screen.query("*"):
        if not widget.display or not widget.region.area:
            continue
        region = widget.region
        if region.x < bounds.x or region.right > bounds.right:
            offenders.append((str(widget), tuple(region)))
    return offenders


def is_visible(app, widget) -> bool:
    """True when the widget's whole region sits inside the visible screen."""
    return app.screen.region.contains_region(widget.region) and widget.region.area > 0


# --- the add-server form ---------------------------------------------------


@pytest.mark.parametrize("size", SIZES)
async def test_form_fits_every_terminal_size(size):
    app = OpenServerApp()
    async with app.run_test(size=size) as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        assert isinstance(app.screen, AddServerScreen)
        assert horizontal_overflow(app) == []

        # The form spans the terminal instead of sitting in a fixed-width box.
        form = app.screen.query_one("#host", Input)
        assert form.region.width > size[0] // 2

        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.parametrize("size", SIZES)
async def test_form_fields_and_legend_are_visible(size):
    app = OpenServerApp()
    async with app.run_test(size=size) as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        screen = app.screen
        for field in ("user", "host", "password", "name", "port"):
            assert is_visible(app, screen.query_one(f"#{field}", Input)), field
        assert is_visible(app, screen.query_one("#key_ref", Select))

        legend = screen.query_one(".legend", Static)
        assert is_visible(app, legend)
        assert "^S save" in str(legend.content)

        # Labels keep their text at the narrowest size, too.
        labels = [str(label.content) for label in screen.query(".row > Label").results(Label)]
        assert labels == ["User", "Host", "Password", "SSH key", "Name", "Port"]

        await pilot.press("escape")
        await pilot.pause()


# --- the inventory table ---------------------------------------------------


@pytest.mark.parametrize("size", SIZES)
async def test_inventory_table_scales_to_the_terminal(size):
    save_servers(
        [
            ServerEntry(name="web", host="web.example.com", user="deploy"),
            ServerEntry(
                name="a-very-long-entry-name-for-testing",
                host="some.extremely.long.hostname.inside.a.private.network.example.org",
                port=2222,
                user="administrator-with-a-long-name",
            ),
        ]
    )

    app = OpenServerApp()
    async with app.run_test(size=size) as pilot:
        await pilot.press("f2")
        await pilot.pause()

        assert isinstance(app.screen, ServersScreen)
        assert horizontal_overflow(app) == []

        table = app.screen.query_one(DataTable)
        assert is_visible(app, table)
        assert table.row_count == 2

        widths = app.screen.column_widths(table.size.width)
        # Columns plus their cell padding stay inside the table.
        total = sum(widths.values()) + 2 * len(widths)
        assert total <= table.size.width or size[0] < 40

        assert is_visible(app, app.screen.query_one(".legend", Static))

        await pilot.press("escape")
        await pilot.pause()


def test_long_values_are_truncated_visibly():
    assert fit("short", 10) == "short"
    assert fit("web.example.com", 8) == "web.exa…"
    assert fit("x", 1) == "x"
    assert fit("abc", 1) == "…"
    assert fit("abc", 0) == ""


# --- the dashboard and its panels -----------------------------------------


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("panel_count", [1, 2, 3, 5])
async def test_panels_fit_and_match_their_pty(size, panel_count):
    app = OpenServerApp()
    async with app.run_test(size=size) as pilot:
        for index in range(panel_count):
            await app.dashboard.add_panel(ServerEntry(name=f"p{index}", host=f"h{index}"))
        # Twice: a grid that starts scrolling grows a scrollbar, and that is a
        # second layout pass which narrows the panels again.
        await pilot.pause()
        await pilot.pause()

        assert horizontal_overflow(app) == []

        for panel in app.dashboard.panels:
            columns, rows = panel.viewport()
            # The PTY is told exactly the drawable area — frame and padding
            # already subtracted — or the remote screen would be offset.
            assert (panel.session.columns, panel.session.rows) == (columns, rows)
            assert columns == panel.outer_size.width - panel.styles.gutter.width
            assert rows == panel.outer_size.height - panel.styles.gutter.height
            assert panel.region.right <= app.screen.region.right

        app.dashboard.close_all()


@pytest.mark.parametrize("size", SIZES)
async def test_panels_never_get_narrower_than_a_shell_needs(size):
    """3+ panels on a narrow terminal stack in one column instead of shrinking."""
    app = OpenServerApp()
    async with app.run_test(size=size) as pilot:
        for index in range(3):
            await app.dashboard.add_panel(ServerEntry(name=f"p{index}", host=f"h{index}"))
        await pilot.pause()

        columns = app.dashboard.styles.grid_size_columns
        if size[0] < 2 * MIN_PANEL_WIDTH:
            assert columns == 1
        for panel in app.dashboard.panels:
            assert panel.outer_size.width >= min(MIN_PANEL_WIDTH, size[0])

        app.dashboard.close_all()


@pytest.mark.parametrize("size", SIZES)
async def test_panels_never_get_shorter_than_a_shell_needs(size):
    """5 panels on a short terminal keep their height and the grid scrolls."""
    app = OpenServerApp()
    async with app.run_test(size=size) as pilot:
        for index in range(5):
            await app.dashboard.add_panel(ServerEntry(name=f"p{index}", host=f"h{index}"))
        await pilot.pause()

        for panel in app.dashboard.panels:
            assert panel.outer_size.height >= min(MIN_PANEL_HEIGHT, size[1])

        app.dashboard.close_all()


async def test_a_short_terminal_scrolls_instead_of_squashing_panels():
    """Without this, 5 panels on 60x18 leave ~3 usable lines of shell each."""
    app = OpenServerApp()
    async with app.run_test(size=(60, 18)) as pilot:
        for index in range(5):
            await app.dashboard.add_panel(ServerEntry(name=f"p{index}", host=f"h{index}"))
        await pilot.pause()

        dashboard = app.dashboard
        assert dashboard.styles.grid_size_columns == 1
        assert dashboard.styles.grid_size_rows == 5
        # More content than viewport: the grid is scrollable, not squashed.
        assert dashboard.virtual_size.height > dashboard.size.height
        assert dashboard.allow_vertical_scroll

        for panel in dashboard.panels:
            assert panel.outer_size.height >= MIN_PANEL_HEIGHT
            assert panel.session.rows == panel.viewport()[1]

        app.dashboard.close_all()


async def test_f6_scrolls_an_offscreen_panel_into_view():
    app = OpenServerApp()
    async with app.run_test(size=(60, 18)) as pilot:
        panels = []
        for index in range(5):
            panels.append(await app.dashboard.add_panel(ServerEntry(name=f"p{index}", host="h")))
        await pilot.pause()

        # Focus the last panel, then wrap around to the first one.
        panels[-1].focus()
        panels[-1].scroll_visible(animate=False)
        await pilot.pause()

        for _ in range(len(panels)):
            await pilot.press("f6")
            await pilot.pause()
            focused = [panel for panel in app.dashboard.panels if panel.has_focus]
            assert len(focused) == 1
            assert is_visible(app, focused[0]), f"{focused[0].entry.name} scrolled out of view"

        app.dashboard.close_all()


def test_row_count_rule():
    dashboard = Dashboard()
    assert dashboard.row_count(5, 1) == 5
    assert dashboard.row_count(5, 2) == 3
    assert dashboard.row_count(4, 2) == 2
    assert dashboard.row_count(0, 1) == 1
    # A 60x18 terminal holds one usable panel; a tall one holds several.
    assert dashboard.rows_that_fit(18) == 1
    assert dashboard.rows_that_fit(50) == 5
    assert dashboard.rows_that_fit(0) == 1


def test_column_count_rule():
    dashboard = Dashboard()
    # Roughly square when there is room…
    assert dashboard.column_count(4, 200) == 2
    assert dashboard.column_count(9, 200) == 3
    # …but capped by how many usable panels fit across.
    assert dashboard.column_count(9, 60) == 1
    assert dashboard.column_count(9, 100) == 2
    assert dashboard.column_count(0, 200) == 1


@pytest.mark.parametrize("size", SIZES)
async def test_dashboard_placeholder_fills_the_view(size):
    app = OpenServerApp()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        placeholder = app.query_one(".placeholder", Static)
        assert placeholder.size.width == app.query_one(Dashboard).size.width
        assert horizontal_overflow(app) == []


async def test_a_resize_relayouts_the_grid():
    """Shrinking the window must fold a wide grid back into one column."""
    app = OpenServerApp()
    async with app.run_test(size=(200, 50)) as pilot:
        for index in range(4):
            await app.dashboard.add_panel(ServerEntry(name=f"p{index}", host=f"h{index}"))
        await pilot.pause()
        assert app.dashboard.styles.grid_size_columns == 2

        await pilot.resize_terminal(60, 18)
        await pilot.pause()
        assert app.dashboard.styles.grid_size_columns == 1
        assert horizontal_overflow(app) == []

        for panel in app.dashboard.panels:
            assert isinstance(panel, TerminalPanel)
            assert (panel.session.columns, panel.session.rows) == panel.viewport()

        app.dashboard.close_all()
