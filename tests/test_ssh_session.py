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


# --- the password prompt ----------------------------------------------------

# Stands in for ssh: prints a password prompt with echo off (as ssh does) and
# writes whatever it was given to a file, so the test can check it arrived.
FAKE_SSH = (
    'stty -echo; printf "%s" "deploy@example.com\'s password: "; '
    'read -r secret; stty echo; printf "%s" "$secret" > "$1"; echo AUTHENTICATED'
)


def test_the_password_is_typed_into_the_pty_when_ssh_asks(tmp_path):
    sink = tmp_path / "typed"
    session = SshSession(
        make_entry(),
        command=["bash", "-c", FAKE_SSH, "fake-ssh", str(sink)],
        password="hunter2",
    )
    try:
        assert wait_for(lambda: any("AUTHENTICATED" in line for line in session.raw_lines()))
        assert sink.read_text() == "hunter2"

        # It is gone from the object as soon as it was used…
        assert session._password is None
        # …it never entered the raw buffer that panels render…
        assert not any("hunter2" in line for line in session.raw_lines())
        # …and it was never a process argument, so `ps` could not show it.
        assert not any("hunter2" in argument for argument in session.command)
    finally:
        session.close()


def test_no_password_means_nothing_is_typed(tmp_path):
    sink = tmp_path / "typed"
    session = SshSession(
        make_entry(),
        command=["bash", "-c", FAKE_SSH, "fake-ssh", str(sink)],
    )
    try:
        assert wait_for(lambda: any("password" in line for line in session.raw_lines()))
        time.sleep(0.3)
        assert not sink.exists()
    finally:
        session.close()


def test_the_password_is_typed_only_once(tmp_path):
    """A second prompt must not get the password again — ssh asks up to 3 times."""
    sink = tmp_path / "typed"
    script = (
        'stty -echo; printf "password: "; read -r a; printf "%s\\n" "$a" > "$1"; '
        'printf "password: "; read -r b; printf "%s\\n" "$b" >> "$1"; echo DONE'
    )
    session = SshSession(
        make_entry(),
        command=["bash", "-c", script, "fake-ssh", str(sink)],
        password="hunter2",
    )
    try:
        # Answer the first prompt automatically, then type the second by hand.
        assert wait_for(lambda: sink.exists() and sink.read_text().splitlines())
        session.write(b"typed-by-hand\n")
        assert wait_for(lambda: any("DONE" in line for line in session.raw_lines()))
        lines = sink.read_text().splitlines()
        assert lines[0] == "hunter2"
        assert "hunter2" not in lines[1:]
    finally:
        session.close()


def test_provide_password_arms_the_answer_before_the_prompt(tmp_path):
    sink = tmp_path / "typed"
    session = SshSession(
        make_entry(),
        command=["bash", "-c", "sleep 0.3; " + FAKE_SSH, "fake-ssh", str(sink)],
    )
    try:
        session.provide_password("late-secret")
        assert wait_for(lambda: any("AUTHENTICATED" in line for line in session.raw_lines()))
        assert sink.read_text() == "late-secret"
    finally:
        session.close()
