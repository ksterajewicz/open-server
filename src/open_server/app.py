"""The open-server application: a dashboard of live SSH panels."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from .config import ServerEntry
from .credentials import MissingKeyError
from .screens.keys import GenerateKeyScreen
from .screens.servers import ServersScreen
from .screens.update import UpdateScreen
from .widgets.dashboard import Dashboard
from .widgets.terminal_panel import TerminalPanel

# Function keys: a focused panel forwards everything else to its shell.
BINDINGS = [
    ("f2", "servers", "Servers"),
    ("f4", "close_panel", "Close"),
    ("f6", "next_panel", "Next"),
    ("f7", "generate_key", "New key"),
    ("f9", "update", "Update"),
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
        # Compact, and without the command-palette key: the legend has to fit
        # a 60-column terminal, which is the narrowest size we support.
        yield Footer(show_command_palette=False, compact=True)

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
        """Open a panel, turning a missing key file into a message, not a crash."""
        try:
            await self.dashboard.add_panel(entry)
        except MissingKeyError as error:
            self.notify(str(error), severity="error", timeout=20)
        except OSError as error:
            self.notify(f"Could not start ssh for '{entry.name}': {error}", severity="error")

    def action_generate_key(self) -> None:
        """Create an application key on purpose — nothing else ever creates one."""
        self.push_screen(GenerateKeyScreen())

    def action_update(self) -> None:
        self.push_screen(UpdateScreen())

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
