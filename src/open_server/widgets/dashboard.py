"""The grid of live SSH panels — the main view of the application."""

from __future__ import annotations

import math

from textual.containers import Grid
from textual.widgets import Static

from ..config import ServerEntry
from ..credentials import get_secret
from ..ssh_session import SshSession
from .terminal_panel import TerminalPanel

PLACEHOLDER_TEXT = "No sessions yet — press F2 to pick a server."

# Below this many columns a panel stops being usable (a shell needs room), so
# the grid keeps stacking panels in one column instead of splitting further.
MIN_PANEL_WIDTH = 40

# The same rule vertically: squeezed below this many rows a panel shows only
# the tail of the output and stops being a usable shell, so the grid keeps the
# panels this tall and scrolls instead of shrinking them.
MIN_PANEL_HEIGHT = 10


class Dashboard(Grid):
    """Holds every open session; grows its grid as panels are added."""

    DEFAULT_CSS = """
    Dashboard {
        grid-size: 1;
        grid-gutter: 0;
        padding: 0;
        overflow-x: hidden;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
    }
    Dashboard > .placeholder {
        width: 1fr;
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def compose(self):
        yield Static(PLACEHOLDER_TEXT, classes="placeholder")

    @property
    def panels(self) -> list[TerminalPanel]:
        return list(self.query(TerminalPanel))

    async def add_panel(self, entry: ServerEntry) -> TerminalPanel:
        """Open a new SSH session for ``entry`` and focus its panel.

        The session is started before the placeholder goes away: if starting it
        fails (a missing key file, say), the caller sees the error and the
        dashboard is left exactly as it was.
        """
        session = SshSession(entry, password=get_secret(entry))

        await self.query(".placeholder").remove()
        panel = TerminalPanel(entry, session)
        await self.mount(panel)
        self._relayout()
        panel.focus()
        return panel

    async def close_panel(self, panel: TerminalPanel) -> None:
        """Terminate a session and drop its panel."""
        panel.close()
        await panel.remove()
        self._relayout()

        remaining = self.panels
        if remaining:
            remaining[-1].focus()
        else:
            await self.mount(Static(PLACEHOLDER_TEXT, classes="placeholder"))

    def focus_next_panel(self, step: int = 1) -> None:
        """Move focus between panels without disturbing the shells.

        The grid scrolls when there are more panels than fit, so the next panel
        may be off-screen: scroll it into view rather than moving focus to
        something the user cannot see.
        """
        panels = self.panels
        if not panels:
            return
        focused = [index for index, panel in enumerate(panels) if panel.has_focus]
        current = focused[0] if focused else -step
        target = panels[(current + step) % len(panels)]
        target.focus()
        target.scroll_visible(animate=False)

    def on_resize(self) -> None:
        """A narrower window may no longer fit the current column count."""
        self._relayout()

    def column_count(self, panels: int, width: int) -> int:
        """How many columns to use for ``panels`` panels across ``width`` cells.

        Roughly square, but never so narrow that a panel cannot hold a shell.
        """
        if panels <= 0:
            return 1
        square = max(1, math.ceil(math.sqrt(panels)))
        fits = max(1, width // MIN_PANEL_WIDTH) if width else 1
        return min(square, fits)

    def row_count(self, panels: int, columns: int) -> int:
        """How many grid rows ``panels`` panels need at ``columns`` columns."""
        if panels <= 0:
            return 1
        return max(1, math.ceil(panels / max(columns, 1)))

    def rows_that_fit(self, height: int) -> int:
        """How many panels can be stacked in ``height`` cells and stay usable."""
        return max(1, height // MIN_PANEL_HEIGHT) if height else 1

    def _relayout(self) -> None:
        """Keep the grid roughly square, within the room a panel needs.

        Once the rows no longer fit the viewport, the row height is pinned to
        ``MIN_PANEL_HEIGHT`` and the grid scrolls — the alternative is panels a
        few lines tall, where all the user sees is the tail of the output.
        """
        count = len(self.panels)
        columns = self.column_count(count, self.size.width)
        rows = self.row_count(count, columns)

        self.styles.grid_size_columns = columns
        self.styles.grid_size_rows = rows
        if rows > self.rows_that_fit(self.size.height):
            self.styles.grid_rows = str(MIN_PANEL_HEIGHT)
        else:
            self.styles.grid_rows = "1fr"

        # Re-laying out the grid resizes panels that did not move themselves, and
        # a PTY left on the old size draws the remote screen offset — so tell
        # every session its new size once the new layout is on screen.
        self.call_after_refresh(self._sync_panel_sizes)

    def _sync_panel_sizes(self) -> None:
        for panel in self.panels:
            panel.sync_size()

    def close_all(self) -> None:
        for panel in self.panels:
            panel.close()
