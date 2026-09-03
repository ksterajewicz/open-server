"""Server inventory screens: pick a server to connect, add or remove entries.

Keyboard only, btop/htop style: there is not a single clickable button in this
application, and every screen carries its own key legend.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Grid, VerticalScroll
from textual.screen import Screen
from textual.widgets import Checkbox, DataTable, Header, Input, Label, Select, Static

from ..config import InventoryError, ServerEntry, load_servers, save_servers
from ..credentials import AGENT_MODE, cache_secret, key_choices, save_secret

# The inventory table sizes itself to the terminal: Port is the only column
# with a fixed width, the rest share whatever is left, by weight.
PORT_WIDTH = 5
CELL_PADDING = 2
MIN_COLUMN_WIDTH = 4
COLUMN_WEIGHTS = (("Name", 0.22), ("Host", 0.34), ("User", 0.18), ("Key", 0.26))
COLUMN_LABELS = ("Name", "Host", "Port", "User", "Key")


def fit(text: str, width: int) -> str:
    """Trim ``text`` to ``width`` cells, marking that something was cut."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


@dataclass
class NewServer:
    """What the add form hands back: an entry plus an optional password."""

    entry: ServerEntry
    password: str | None = None
    remember: bool = False


class AddServerScreen(Screen[NewServer | None]):
    """Full-screen SSH connection form — no dialog box, no buttons."""

    # Every size is fr/auto/%, so the form fills whatever terminal it gets.
    DEFAULT_CSS = """
    AddServerScreen {
        layout: vertical;
    }
    AddServerScreen > VerticalScroll {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
    }
    AddServerScreen .section {
        width: 1fr;
        height: auto;
        color: $accent;
        text-style: bold;
    }
    AddServerScreen .row {
        grid-size: 2;
        grid-rows: auto;
        grid-columns: auto 1fr;
        grid-gutter: 0 1;
        width: 1fr;
        height: auto;
    }
    AddServerScreen .row > Label {
        width: auto;
        min-width: 9;
        height: 1;
        content-align: left middle;
    }
    AddServerScreen Input {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
        background: $boost;
    }
    AddServerScreen Input:focus {
        border: none;
        background: $surface;
        color: $text;
        text-style: bold;
    }
    /* One row per field: the stock Select/Input frames would triple that. */
    AddServerScreen Select {
        width: 1fr;
        height: 1;
    }
    AddServerScreen SelectCurrent {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
        background: $boost;
    }
    AddServerScreen Select:focus SelectCurrent {
        background: $surface;
        text-style: bold;
    }
    AddServerScreen Checkbox {
        width: 1fr;
        border: none;
        padding: 0;
        background: transparent;
    }
    AddServerScreen .legend {
        width: 1fr;
        height: 1;
        background: $panel;
        color: $text-muted;
    }
    AddServerScreen .hint {
        width: 1fr;
        height: auto;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("escape", "cancel", "Cancel"),
    ]

    LEGEND = " ^S save   Esc cancel   Tab field   Enter next   Space toggle "

    # Order matters: Enter on the last field saves the form.
    FIELD_ORDER = ("user", "host", "password", "name", "port")

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static("SSH connection", classes="section")
            yield self._row("User", Input(placeholder="deploy", id="user"))
            yield self._row("Host", Input(placeholder="10.0.0.5", id="host"))
            yield self._row(
                "Password",
                Input(placeholder="(blank: keys only)", password=True, id="password"),
            )
            yield self._row(
                "SSH key",
                Select(key_choices(), value=AGENT_MODE, allow_blank=False, id="key_ref"),
            )
            yield Checkbox("Remember password in OS keyring", id="remember")
            yield Static(
                "Unchecked: the password is kept in memory for this session only. "
                "It never goes into servers.toml.",
                classes="hint",
            )
            yield Static("Optional", classes="section")
            yield self._row("Name", Input(placeholder="(user@host)", id="name"))
            yield self._row("Port", Input(placeholder="22", id="port"))
        yield Static(self.LEGEND, classes="legend")

    @staticmethod
    def _row(label: str, widget) -> Grid:
        return Grid(Label(label), widget, classes="row")

    def on_mount(self) -> None:
        self.query_one("#user", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter walks the form; Enter on the last field saves it."""
        if event.input.id == self.FIELD_ORDER[-1]:
            self.action_save()
        else:
            self.focus_next()

    def _value(self, field: str) -> str:
        return self.query_one(f"#{field}", Input).value.strip()

    def action_save(self) -> None:
        host = self._value("host")
        if not host:
            self.notify("Host is required.", severity="error")
            self.query_one("#host", Input).focus()
            return

        port_text = self._value("port") or "22"
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            self.notify("Port must be a number between 1 and 65535.", severity="error")
            self.query_one("#port", Input).focus()
            return

        user = self._value("user") or None
        # `name` stays in the data model (existing inventories rely on it), the
        # user just no longer has to invent one.
        name = self._value("name") or (f"{user}@{host}" if user else host)

        key_ref = self.query_one("#key_ref", Select).value
        password = self.query_one("#password", Input).value or None

        self.dismiss(
            NewServer(
                entry=ServerEntry(
                    name=name,
                    host=host,
                    port=int(port_text),
                    user=user,
                    key_ref=str(key_ref) if key_ref else AGENT_MODE,
                ),
                password=password,
                remember=self.query_one("#remember", Checkbox).value,
            )
        )


class ServersScreen(Screen[ServerEntry | None]):
    """List of saved servers; picking one returns it to the app to connect."""

    DEFAULT_CSS = """
    ServersScreen {
        layout: vertical;
    }
    ServersScreen > DataTable {
        width: 1fr;
        height: 1fr;
    }
    ServersScreen .legend {
        width: 1fr;
        height: 1;
        background: $panel;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("escape", "close", "Back"),
        ("a", "add", "Add"),
        ("d", "delete", "Delete"),
        ("enter", "connect", "Connect"),
    ]

    LEGEND = " Enter connect   a add   d delete   Esc back "

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[ServerEntry] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row", zebra_stripes=True)
        yield Static(self.LEGEND, classes="legend")

    def on_mount(self) -> None:
        self._load()
        self._render_table()
        self.query_one(DataTable).focus()

    def on_resize(self) -> None:
        """Column widths follow the terminal, so nothing runs off the edge."""
        self._render_table()

    def _load(self) -> None:
        try:
            self.entries = load_servers()
        except InventoryError as error:
            self.entries = []
            self.notify(str(error), severity="error", timeout=15)

    def column_widths(self, width: int) -> dict[str, int]:
        """Split ``width`` cells between the columns: Port fixed, rest by weight."""
        usable = width - len(COLUMN_LABELS) * CELL_PADDING - PORT_WIDTH
        usable = max(usable, len(COLUMN_WEIGHTS) * MIN_COLUMN_WIDTH)

        widths = {"Port": PORT_WIDTH}
        for label, weight in COLUMN_WEIGHTS:
            widths[label] = max(MIN_COLUMN_WIDTH, int(usable * weight))
        return widths

    def _render_table(self) -> None:
        table = self.query_one(DataTable)
        widths = self.column_widths(max(table.size.width or self.size.width, 24))

        cursor = table.cursor_row
        table.clear(columns=True)
        for label in COLUMN_LABELS:
            table.add_column(label, width=widths[label], key=label)

        for entry in self.entries:
            table.add_row(
                fit(entry.name, widths["Name"]),
                fit(entry.host, widths["Host"]),
                fit(str(entry.port), widths["Port"]),
                fit(entry.user or "-", widths["User"]),
                fit(entry.key_ref.rsplit("/", 1)[-1], widths["Key"]),
            )
        if self.entries and 0 < cursor < len(self.entries):
            table.move_cursor(row=cursor)

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
        def on_result(result: NewServer | None) -> None:
            if result is None:
                return
            self.entries.append(result.entry)
            save_servers(self.entries)
            self._store_password(result)
            self._render_table()

        self.app.push_screen(AddServerScreen(), on_result)

    def _store_password(self, result: NewServer) -> None:
        """Keyring only when the user asked for it; memory otherwise."""
        if not result.password:
            return
        if not result.remember:
            cache_secret(result.entry, result.password)
            return
        try:
            save_secret(result.entry, result.password)
        except Exception as error:  # noqa: BLE001 - any backend failure lands on the user
            cache_secret(result.entry, result.password)
            self.notify(
                f"OS keyring unavailable ({error}); password kept in memory for this session only.",
                severity="warning",
                timeout=10,
            )

    def action_delete(self) -> None:
        entry = self._selected()
        if entry is None:
            return
        self.entries.remove(entry)
        save_servers(self.entries)
        self._render_table()
