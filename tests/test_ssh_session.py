"""PTY plumbing tests — they drive a local shell instead of a real ssh server."""

from __future__ import annotations

import time

from open_server.config import ServerEntry
from open_server.ssh_session import SshSession, ssh_command


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def make_entry(**overrides) -> ServerEntry:
    defaults = {"name": "test", "host": "example.com", "user": "deploy"}
    defaults.update(overrides)
    return ServerEntry(**defaults)


def test_raw_output_is_captured():
    session = SshSession(make_entry(), command=["bash", "-c", "echo hi"])
    try:
        assert wait_for(lambda: any("hi" in line for line in session.raw_lines()))
    finally:
        session.close()


def test_screen_is_lazy_and_seeded_on_enable():
    session = SshSession(make_entry(), command=["bash", "-c", "echo hello; sleep 5"])
    try:
        assert wait_for(lambda: any("hello" in line for line in session.raw_lines()))
        # No emulator until a panel focuses the session.
        assert session._screen is None

        session.enable_screen()
        assert session._screen is not None
        # Output produced before focus still shows up on the emulated screen.
        assert any("hello" in line for line in session.screen_lines())

        session.disable_screen()
        assert session._screen is None
    finally:
        session.close()


def test_write_reaches_the_shell():
    session = SshSession(make_entry(), command=["bash", "--norc", "-i"])
    try:
        session.enable_screen()
        session.write(b"echo test123\n")
        assert wait_for(lambda: any("test123" in line for line in session.raw_lines()))
    finally:
        session.close()


def test_close_terminates_the_process():
    session = SshSession(make_entry(), command=["sleep", "60"])
    assert session.is_alive()
    session.close()
    assert not session.is_alive()


def test_ssh_command_uses_agent_by_default():
    command = ssh_command(make_entry())
    assert command == ["ssh", "deploy@example.com"]


def test_ssh_command_includes_non_default_port():
    command = ssh_command(make_entry(port=2222))
    assert command == ["ssh", "-p", "2222", "deploy@example.com"]


def test_ssh_command_without_user():
    command = ssh_command(make_entry(user=None))
    assert command == ["ssh", "example.com"]
