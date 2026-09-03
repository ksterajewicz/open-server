"""Server inventory screens: pick a server to connect, add or remove entries."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label

from ..config import InventoryError, ServerEntry, load_servers, save_servers


class AddServerScreen(ModalScreen[ServerEntry | None]):
    """Form for a new inventory entry. Metadata only — never a password."""

    DEFAULT_CSS = """
    AddServerScreen {
        align: center middle;
    }
    AddServerScreen > Grid {
        grid-size: 2;
        grid-rows: auto;
        grid-columns: 12 40;
        padding: 1 2;
        width: 60;
        height: auto;
        border: thick $accent;
        background: $surface;
    }
    AddServerScreen Horizontal {
        column-span: 2;
        height: auto;
        align: right middle;
    }
    AddServerScreen Button {
        margin-left: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Grid():
            yield Label("Name")
            yield Input(placeholder="web", id="name")
            yield Label("Host")
            yield Input(placeholder="web.example.com", id="host")
            yield Label("Port")
            yield Input(placeholder="22", id="port")
            yield Label("User")
            yield Input(placeholder="deploy", id="user")
            yield Label("Key")
            yield Input(placeholder="agent", id="key_ref")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _value(self, field: str) -> str:
        return self.query_one(f"#{field}", Input).value.strip()

    def _save(self) -> None:
        name, host = self._value("name"), self._value("host")
        if not name or not host:
            self.notify("Name and host are required.", severity="error")
            return

        port_text = self._value("port") or "22"
        if not port_text.isdigit():
            self.notify("Port must be a number.", severity="error")
            return

        self.dismiss(
            ServerEntry(
                name=name,
                host=host,
                port=int(port_text),
                user=self._value("user") or None,
                key_ref=self._value("key_ref") or "agent",
            )
        )


class ServersScreen(Screen[ServerEntry | None]):
    """List of saved servers; picking one returns it to the app to connect."""

    BINDINGS = [
        ("escape", "close", "Back"),
        ("a", "add", "Add"),
        ("d", "delete", "Delete"),
        ("enter", "connect", "Connect"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Name", "Host", "Port", "User", "Key")
        self._reload()
        table.focus()

    def _reload(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        try:
            self.entries = load_servers()
        except InventoryError as error:
            self.entries = []
            self.notify(str(error), severity="error", timeout=15)
            return

        for entry in self.entries:
            table.add_row(entry.name, entry.host, str(entry.port), entry.user or "-", entry.key_ref)

    def _selected(self) -> ServerEntry | None:
        table = self.query_one(DataTable)
        if not self.entries or table.cursor_row < 0:
            return None
        return self.entries[table.cursor_row]

    def action_close(self) -> None:
        self.dismiss(None)

    def action_connect(self) -> None:
        entry = self._selected()
        if entry is not None:
            self.dismiss(entry)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """DataTable consumes Enter itself, so connect from its own message."""
        if 0 <= event.cursor_row < len(self.entries):
            self.dismiss(self.entries[event.cursor_row])

    def action_add(self) -> None:
        def on_result(entry: ServerEntry | None) -> None:
            if entry is None:
                return
            self.entries.append(entry)
            save_servers(self.entries)
            self._reload()

        self.app.push_screen(AddServerScreen(), on_result)

    def action_delete(self) -> None:
        entry = self._selected()
        if entry is None:
            return
        self.entries.remove(entry)
        save_servers(self.entries)
        self._reload()
