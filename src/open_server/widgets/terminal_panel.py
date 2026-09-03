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

    # Dense by design: a one-cell square border and no padding, so every cell
    # inside the frame belongs to the remote shell.
    DEFAULT_CSS = """
    TerminalPanel {
        width: 1fr;
        height: 1fr;
        border: solid $primary-background;
        border-title-align: left;
        padding: 0;
    }
    TerminalPanel:focus {
        border: solid $accent;
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

        # `self.size` is the content area — the frame and padding are already
        # subtracted — which is exactly the area the PTY is told about, so the
        # remote screen lines up cell for cell with what is drawn.
        width, height = self.viewport()
        if self.has_focus:
            lines = self.session.screen_lines()[:height]
        else:
            lines = self.session.raw_lines(height)
        # Hard-clip: a raw line longer than the panel would wrap and push the
        # rest of the output down, which looks like a corrupted screen.
        return Text("\n".join(line[:width] for line in lines), no_wrap=True, overflow="crop")

    def on_focus(self) -> None:
        self.session.enable_screen()
        self.sync_size()

    def on_blur(self) -> None:
        self.session.disable_screen()

    def on_resize(self) -> None:
        self.sync_size()

    def viewport(self) -> tuple[int, int]:
        """The drawable area in cells, frame and padding already excluded."""
        return max(self.size.width, 1), max(self.size.height, 1)

    def sync_size(self) -> None:
        """Tell the PTY the panel's current size, if it has changed."""
        columns, rows = self.viewport()
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
