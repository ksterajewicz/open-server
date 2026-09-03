"""Generating an application SSH key — an explicit user action, never automatic.

Nothing in the application creates a key on its own: connecting to a server
whose key file is gone is an error, because a silently generated replacement
would be a key the server has never authorised.  This screen is the one place
a key comes into being, and it immediately shows the public half so the user
can put it into the server's ``authorized_keys``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Grid, VerticalScroll
from textual.screen import Screen
from textual.widgets import Header, Input, Label, Static

from ..credentials import generate_app_key, key_path_for, public_key_text

DEFAULT_KEY_NAME = "app-key"


class GenerateKeyScreen(Screen[str | None]):
    """Ask for a key name, generate the pair, show the public key to copy."""

    DEFAULT_CSS = """
    GenerateKeyScreen {
        layout: vertical;
    }
    GenerateKeyScreen > VerticalScroll {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
    }
    GenerateKeyScreen .section {
        width: 1fr;
        height: auto;
        color: $accent;
        text-style: bold;
    }
    GenerateKeyScreen .row {
        grid-size: 2;
        grid-rows: auto;
        grid-columns: auto 1fr;
        grid-gutter: 0 1;
        width: 1fr;
        height: auto;
    }
    GenerateKeyScreen .row > Label {
        width: auto;
        min-width: 10;
        height: 1;
        content-align: left middle;
    }
    GenerateKeyScreen Input {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
        background: $boost;
    }
    GenerateKeyScreen Input:focus {
        border: none;
        background: $surface;
        text-style: bold;
    }
    GenerateKeyScreen .hint {
        width: 1fr;
        height: auto;
        color: $text-muted;
    }
    GenerateKeyScreen .pubkey {
        width: 1fr;
        height: auto;
        background: $boost;
        color: $text;
    }
    GenerateKeyScreen .legend {
        width: 1fr;
        height: 1;
        background: $panel;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("ctrl+s", "generate", "Generate"),
        ("escape", "close", "Close"),
    ]

    LEGEND_FORM = " ^S generate   Esc back "
    LEGEND_DONE = " Esc back   (copy the line above into the server's authorized_keys) "

    def __init__(self) -> None:
        super().__init__()
        self.key_path = None

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static("Generate an application SSH key", classes="section")
            yield Grid(
                Label("Key name"),
                Input(placeholder=DEFAULT_KEY_NAME, id="key_name"),
                classes="row",
            )
            yield Static(
                "The private key goes to ~/.config/open-server/keys/ with 0600 "
                "permissions; the public half is shown here to paste into the "
                "server's ~/.ssh/authorized_keys.",
                classes="hint",
            )
            yield Static("", id="result", classes="section")
            yield Static("", id="pubkey", classes="pubkey")
        yield Static(self.LEGEND_FORM, id="legend", classes="legend")

    def on_mount(self) -> None:
        self.query_one("#key_name", Input).focus()

    def action_close(self) -> None:
        self.dismiss(str(self.key_path) if self.key_path else None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_generate()

    def action_generate(self) -> None:
        if self.key_path is not None:
            self.notify("Key already generated — press Esc to go back.", severity="warning")
            return

        name = self.query_one("#key_name", Input).value.strip() or DEFAULT_KEY_NAME
        if "/" in name or name.startswith("."):
            self.notify("Use a plain file name, without '/' or a leading dot.", severity="error")
            return

        target = key_path_for(name)
        try:
            self.key_path = generate_app_key(target)
            public = public_key_text(self.key_path)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error", timeout=15)
            return

        self.query_one("#result", Static).update(f"Created {self.key_path} — public key:")
        self.query_one("#pubkey", Static).update(public)
        self.query_one("#legend", Static).update(self.LEGEND_DONE)
        self.query_one("#key_name", Input).disabled = True
