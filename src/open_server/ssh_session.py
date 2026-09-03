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

# ssh prints "user@host's password:" or "Password:" — matching the common tail
# keeps this independent of the exact wording.
PASSWORD_PROMPT = "assword:"
PROMPT_TAIL_CHARS = 128


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
        password: str | None = None,
    ) -> None:
        self.entry = entry
        self.columns = columns
        self.rows = rows
        # `command` is injectable so tests can drive the PTY plumbing without ssh.
        self.command = command if command is not None else ssh_command(entry)

        # Typed into the PTY once, when ssh asks, then dropped.  It is never a
        # process argument, so it cannot show up in `ps`.
        self._password = password
        self._prompt_tail = ""

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
                self._answer_password_prompt(data)

    def _answer_password_prompt(self, data: bytes) -> None:
        """Type the password once, the first time ssh asks for it.

        The secret is dropped from the object as soon as it is written, and it
        is never appended to the raw buffer.  ssh turns terminal echo off while
        it reads the password, so the PTY does not hand it back to us either.
        """
        if self._password is None:
            return

        tail = self._prompt_tail + data.decode("utf-8", errors="replace")
        self._prompt_tail = tail[-PROMPT_TAIL_CHARS:]
        if PASSWORD_PROMPT not in self._prompt_tail.lower():
            return

        secret, self._password = self._password, None
        self._prompt_tail = ""
        try:
            os.write(self._master_fd, secret.encode("utf-8") + b"\n")
        except OSError:
            pass

    def provide_password(self, secret: str | None) -> None:
        """Arm (or disarm) the one-shot password answer before ssh prompts."""
        with self._lock:
            self._password = secret
            self._prompt_tail = ""

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
        """Tell the remote terminal its new size; a closed session ignores it."""
        self.columns = columns
        self.rows = rows
        if self._closed:
            return
        try:
            self._set_pty_size(self._master_fd, columns, rows)
        except OSError:
            # The PTY went away underneath us (the remote side hung up); the
            # panel keeps rendering its buffered output, so this is not fatal.
            return
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
