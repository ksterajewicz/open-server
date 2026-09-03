"""Entry point for the open-server TUI."""

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static


class OpenServerApp(App):
    """btop-style dashboard for managing SSH connections."""

    TITLE = "open-server"
    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("No servers configured yet.")
        yield Footer()


def main() -> None:
    OpenServerApp().run()


if __name__ == "__main__":
    main()
