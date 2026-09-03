"""The self-update screen: pick a channel, see what is coming, pull it in.

All the real work lives in ``open_server.updater``; this screen only drives it
and prints what it says.  Git and pip run on a worker thread, because a fetch
against an unreachable network would otherwise freeze the whole interface.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, RichLog, Static

from .. import updater


class UpdateScreen(Screen[None]):
    """Channel choice, current state, and the update run itself."""

    DEFAULT_CSS = """
    UpdateScreen {
        layout: vertical;
    }
    UpdateScreen > #state {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    UpdateScreen > RichLog {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        background: $surface;
    }
    UpdateScreen .legend {
        width: 1fr;
        height: 1;
        background: $panel;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("s", "channel('stable')", "Stable"),
        ("r", "channel('rolling')", "Rolling"),
        ("u", "update", "Update"),
        ("c", "check", "Check"),
        ("enter", "restart", "Restart"),
        ("escape", "close", "Back"),
    ]

    LEGEND = " s stable   r rolling   c check   u update   Esc back "
    LEGEND_RESTART = " Enter restart now   Esc later "

    def __init__(self) -> None:
        super().__init__()
        self.channel = updater.current_channel()
        self._busy = False
        self._allow_stash = False
        self._restart_pending = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="state")
        yield RichLog(id="log", markup=False, highlight=False, wrap=True)
        yield Static(self.LEGEND, id="legend", classes="legend")

    def on_mount(self) -> None:
        self._render_state()
        self.log_line("Press c to check the selected channel, u to update.")
        self.log_line(f"Checkout: {updater.repo_dir()}")

    # --- display -----------------------------------------------------------

    def log_line(self, message: str) -> None:
        self.query_one("#log", RichLog).write(message)

    def _render_state(self, status: updater.UpdateStatus | None = None) -> None:
        lines = ["Update channel:"]
        for channel, label in updater.CHANNEL_LABELS.items():
            marker = ">" if channel == self.channel else " "
            lines.append(f" {marker} {label}")
        lines.append(f"Installed: {updater.local_state().describe()}")
        if status is not None:
            if status.error:
                lines.append(f"Remote: unknown — {status.error}")
            elif status.up_to_date():
                lines.append(f"Remote: {status.remote.describe()} — already up to date")
            else:
                behind = status.behind
                lines.append(f"Remote: {status.remote.describe()} — {behind} new commit(s)")
        self.query_one("#state", Static).update("\n".join(lines))

    def _set_legend(self, text: str) -> None:
        self.query_one("#legend", Static).update(text)

    # --- actions -----------------------------------------------------------

    def action_close(self) -> None:
        if self._busy:
            self.notify("An update is running — let it finish.", severity="warning")
            return
        self.dismiss(None)

    def action_channel(self, channel: str) -> None:
        if self._busy:
            return
        try:
            updater.set_channel(channel)
        except (updater.UpdateError, OSError) as error:
            self.notify(str(error), severity="error", timeout=10)
            return
        self.channel = channel
        self._allow_stash = False
        self._render_state()
        self.log_line(f"Channel set to {channel} (branch {updater.branch_for_channel(channel)}).")

    def action_check(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.log_line("Checking…")
        self.run_worker(self._check_worker, thread=True, exit_on_error=False)

    def action_update(self) -> None:
        if self._busy:
            return
        live = len(self.app.dashboard.panels) if hasattr(self.app, "dashboard") else 0
        if live and not self._restart_pending:
            self.log_line(f"Note: {live} SSH panel(s) are open; restarting later will close them.")
        self._busy = True
        self.log_line(f"Updating to the head of {self.channel}…")
        self.run_worker(self._update_worker, thread=True, exit_on_error=False)

    def action_restart(self) -> None:
        """Restart into the new code — and say what that costs first."""
        if not self._restart_pending or self._busy:
            return
        panels = self.app.dashboard.panels if hasattr(self.app, "dashboard") else []
        self.log_line(f"Closing {len(panels)} SSH session(s) and restarting…")
        self.app.dashboard.close_all()
        updater.restart()

    # --- worker side (runs off the event loop) ------------------------------

    def _progress(self, message: str) -> None:
        self.app.call_from_thread(self.log_line, message)

    def _check_worker(self) -> None:
        try:
            status = updater.check(self.channel, self._progress)
        except updater.UpdateError as error:
            self.app.call_from_thread(self._failed, str(error))
            return
        self.app.call_from_thread(self._checked, status)

    def _update_worker(self) -> None:
        try:
            summary = updater.update(
                self.channel, progress=self._progress, allow_stash=self._allow_stash
            )
        except updater.UpdateError as error:
            self.app.call_from_thread(self._failed, str(error))
            return
        self.app.call_from_thread(self._updated, summary)

    # --- back on the event loop --------------------------------------------

    def _checked(self, status: updater.UpdateStatus) -> None:
        self._busy = False
        self._render_state(status)
        if status.error:
            self.log_line(status.error)
        elif status.up_to_date():
            self.log_line("Already up to date.")
        else:
            self.log_line(f"{status.behind} new commit(s) waiting — press u to update.")

    def _failed(self, message: str) -> None:
        self._busy = False
        self.log_line(f"Update aborted: {message}")
        self.notify(message, severity="error", timeout=15)
        if "Confirm stashing" in message:
            self._allow_stash = True
            self.log_line("Press u again to stash those changes and continue.")

    def _updated(self, summary: str) -> None:
        self._busy = False
        self._allow_stash = False
        self._restart_pending = True
        self._render_state()
        live = len(self.app.dashboard.panels) if hasattr(self.app, "dashboard") else 0
        self.log_line(f"Updated: {summary}")
        self.log_line(
            "Restart to run the new code. This closes "
            f"{live} open SSH panel(s) — press Enter to restart now, Esc to do it later."
        )
        self._set_legend(self.LEGEND_RESTART)
