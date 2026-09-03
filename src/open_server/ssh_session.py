"""One SSH connection running in a PTY.

The session always keeps a cheap raw-output buffer (what background panels
render) and builds a full ``pyte`` VT100 screen only on demand — that lazy
screen is what a focused panel renders.  Keeping the emulator off for
background panels is the point of the hybrid rendering approach.
"""

from __future__ import annotations

import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
import threading
from collections import deque

import pyte

from .config import ServerEntry
from .credentials import resolve_identity

DEFAULT_COLUMNS = 80
DEFAULT_ROWS = 24
RAW_BUFFER_LINES = 2000
READ_CHUNK = 65536


def ssh_command(entry: ServerEntry) -> list[str]:
    """Build the ssh command line for an inventory entry."""
    identity = resolve_identity(entry)
    command = ["ssh"]
    command += identity.ssh_args()
    if entry.port != 22:
        command += ["-p", str(entry.port)]
    command.append(entry.target())
    return command


class SshSession:
    """An ssh process attached to a PTY, read by a background thread."""

    def __init__(
        self,
        entry: ServerEntry,
        columns: int = DEFAULT_COLUMNS,
        rows: int = DEFAULT_ROWS,
        command: list[str] | None = None,
    ) -> None:
        self.entry = entry
        self.columns = columns
        self.rows = rows
        # `command` is injectable so tests can drive the PTY plumbing without ssh.
        self.command = command if command is not None else ssh_command(entry)

        self._raw_lines: deque[str] = deque(maxlen=RAW_BUFFER_LINES)
        self._pending = ""
        self._screen: pyte.Screen | None = None
        self._stream: pyte.ByteStream | None = None
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._closed = False

        self._master_fd, slave_fd = pty.openpty()
        self._set_pty_size(self._master_fd, columns, rows)
        self.process = subprocess.Popen(
            self.command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=os.setsid,
            close_fds=True,
        )
        os.close(slave_fd)

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # --- reading -----------------------------------------------------------

    def _read_loop(self) -> None:
        while True:
            try:
                data = os.read(self._master_fd, READ_CHUNK)
            except OSError:
                break
            if not data:
                break
            with self._lock:
                self._append_raw(data)
                if self._stream is not None:
                    self._stream.feed(data)

    def _append_raw(self, data: bytes) -> None:
        text = self._pending + data.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._pending = lines.pop()
        for line in lines:
            self._raw_lines.append(line.rstrip("\r"))

    # --- rendering ---------------------------------------------------------

    def enable_screen(self) -> None:
        """Start full VT100 emulation (a panel gained focus)."""
        with self._lock:
            if self._screen is None:
                self._screen = pyte.Screen(self.columns, self.rows)
                self._stream = pyte.ByteStream(self._screen)
                # Seed the fresh screen with what we already buffered, so the
                # panel does not look empty on first focus.
                seeded = "\n".join(self._raw_lines) + self._pending
                self._stream.feed(seeded.encode("utf-8", errors="replace"))

    def disable_screen(self) -> None:
        """Drop the emulator (a panel lost focus); raw buffer keeps filling."""
        with self._lock:
            self._screen = None
            self._stream = None

    def screen_lines(self) -> list[str]:
        """Emulated screen contents; falls back to the raw tail if not enabled."""
        with self._lock:
            if self._screen is not None:
                return list(self._screen.display)
            return self.raw_lines(self.rows)

    def raw_lines(self, limit: int | None = None) -> list[str]:
        """Recent output lines, cheapest possible view for background panels."""
        with self._lock:
            lines = list(self._raw_lines)
            if self._pending:
                lines.append(self._pending)
        return lines[-limit:] if limit else lines

    # --- control -----------------------------------------------------------

    def write(self, data: bytes) -> None:
        """Send keystrokes to the remote shell."""
        if not self._closed:
            os.write(self._master_fd, data)

    def resize(self, columns: int, rows: int) -> None:
        self.columns = columns
        self.rows = rows
        self._set_pty_size(self._master_fd, columns, rows)
        with self._lock:
            if self._screen is not None:
                self._screen.resize(rows, columns)

    @staticmethod
    def _set_pty_size(fd: int, columns: int, rows: int) -> None:
        size = struct.pack("HHHH", rows, columns, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def close(self) -> None:
        """Terminate the ssh process and release the PTY."""
        if self._closed:
            return
        self._closed = True

        if self.is_alive():
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)

        try:
            os.close(self._master_fd)
        except OSError:
            pass
        if self._reader is not None:
            self._reader.join(timeout=1)
