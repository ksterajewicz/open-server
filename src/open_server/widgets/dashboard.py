"""The grid of live SSH panels — the main view of the application."""

from __future__ import annotations

import math

from textual.containers import Grid
from textual.widgets import Static

from ..config import ServerEntry
from ..ssh_session import SshSession
from .terminal_panel import TerminalPanel


class Dashboard(Grid):
    """Holds every open session; grows its grid as panels are added."""

    DEFAULT_CSS = """
    Dashboard {
        grid-size: 1;
        grid-gutter: 0;
    }
    Dashboard > .placeholder {
        content-align: center middle;
        color: $text-muted;
    }
    """

    def compose(self):
        yield Static(
            "No sessions yet — press F2 to pick a server.",
            classes="placeholder",
        )

    @property
    def panels(self) -> list[TerminalPanel]:
        return list(self.query(TerminalPanel))

    async def add_panel(self, entry: ServerEntry) -> TerminalPanel:
        """Open a new SSH session for ``entry`` and focus its panel."""
        await self.query(".placeholder").remove()

        session = SshSession(entry)
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
            await self.mount(
                Static("No sessions yet — press F2 to pick a server.", classes="placeholder")
            )

    def focus_next_panel(self, step: int = 1) -> None:
        """Move focus between panels without disturbing the shells."""
        panels = self.panels
        if not panels:
            return
        focused = [index for index, panel in enumerate(panels) if panel.has_focus]
        current = focused[0] if focused else -step
        panels[(current + step) % len(panels)].focus()

    def _relayout(self) -> None:
        """Keep the grid roughly square as panels come and go."""
        count = len(self.panels)
        self.styles.grid_size_columns = max(1, math.ceil(math.sqrt(count))) if count else 1

    def close_all(self) -> None:
        for panel in self.panels:
            panel.close()
