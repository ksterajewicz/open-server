"""The open-server application: a dashboard of live SSH panels."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from .config import ServerEntry
from .screens.servers import ServersScreen
from .widgets.dashboard import Dashboard
from .widgets.terminal_panel import TerminalPanel

# Function keys: a focused panel forwards everything else to its shell.
BINDINGS = [
    ("f2", "servers", "Servers"),
    ("f4", "close_panel", "Close panel"),
    ("f6", "next_panel", "Next panel"),
    ("f10", "quit", "Quit"),
]


class OpenServerApp(App):
    """Many SSH sessions, one window."""

    TITLE = "open-server"
    BINDINGS = BINDINGS

    CSS = """
    Dashboard {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Dashboard()
        yield Footer()

    @property
    def dashboard(self) -> Dashboard:
        return self.query_one(Dashboard)

    def action_servers(self) -> None:
        """Open the inventory; connect to whatever the user picks."""

        def on_result(entry: ServerEntry | None) -> None:
            if entry is not None:
                self.call_later(self._connect, entry)

        self.push_screen(ServersScreen(), on_result)

    async def _connect(self, entry: ServerEntry) -> None:
        await self.dashboard.add_panel(entry)

    async def action_close_panel(self) -> None:
        panel = self.focused
        if isinstance(panel, TerminalPanel):
            await self.dashboard.close_panel(panel)

    def action_next_panel(self) -> None:
        self.dashboard.focus_next_panel()

    def action_quit(self) -> None:
        self.dashboard.close_all()
        self.exit()


def main() -> None:
    OpenServerApp().run()
