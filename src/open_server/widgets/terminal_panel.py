"""A single terminal panel inside the dashboard.

Focused: full VT100 emulation, keystrokes go to the remote shell.
Unfocused: the cheap raw output tail, no emulator running.
"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.widget import Widget

from ..config import ServerEntry
from ..ssh_session import SshSession

REFRESH_INTERVAL = 0.05

# Keys the shell needs that Textual reports by name rather than as a character.
KEY_SEQUENCES = {
    "enter": b"\r",
    "tab": b"\t",
    "escape": b"\x1b",
    "backspace": b"\x7f",
    "delete": b"\x1b[3~",
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "insert": b"\x1b[2~",
    "space": b" ",
}


def key_to_bytes(event: events.Key) -> bytes | None:
    """Translate a Textual key event into what a PTY expects."""
    sequence = KEY_SEQUENCES.get(event.key)
    if sequence is not None:
        return sequence
    if event.character:
        return event.character.encode("utf-8")
    return None


class TerminalPanel(Widget):
    """One SSH session rendered as a panel."""

    can_focus = True

    DEFAULT_CSS = """
    TerminalPanel {
        border: round $primary-background;
        padding: 0 1;
    }
    TerminalPanel:focus {
        border: round $accent;
    }
    """

    def __init__(self, entry: ServerEntry, session: SshSession) -> None:
        super().__init__()
        self.entry = entry
        self.session = session
        self.border_title = entry.name

    def on_mount(self) -> None:
        self.set_interval(REFRESH_INTERVAL, self.refresh)

    def render(self) -> Text:
        if not self.session.is_alive() and not self.session.raw_lines():
            return Text("(session ended)", style="dim")

        height = max(self.size.height, 1)
        if self.has_focus:
            lines = self.session.screen_lines()[:height]
        else:
            lines = self.session.raw_lines(height)
        return Text("\n".join(lines))

    def on_focus(self) -> None:
        self.session.enable_screen()
        self._sync_size()

    def on_blur(self) -> None:
        self.session.disable_screen()

    def on_resize(self) -> None:
        self._sync_size()

    def _sync_size(self) -> None:
        columns = max(self.size.width, 1)
        rows = max(self.size.height, 1)
        if (columns, rows) != (self.session.columns, self.session.rows):
            self.session.resize(columns, rows)

    def on_key(self, event: events.Key) -> None:
        """Forward keystrokes to the remote shell while focused."""
        data = key_to_bytes(event)
        if data is None:
            return
        self.session.write(data)
        event.prevent_default()
        event.stop()

    def close(self) -> None:
        self.session.close()
