"""Self-update logic, exercised against a real local git repository.

No network is touched: a throwaway "upstream" repo with ``main`` and ``dev``
branches stands in for GitHub, and the checkout is cloned from it over the
filesystem.  What is asserted is the observable state afterwards — which commit
the checkout sits on, whether a stash survived a failure — not exit codes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from open_server import updater
from open_server.config import settings_file
from open_server.updater import UpdateError

pytestmark = pytest.mark.usefixtures("isolated_dirs")


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Point both the config and the install root at a throwaway directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("OPEN_SERVER_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def upstream(tmp_path) -> Path:
    """A stand-in for GitHub: a real repo with a main and a dev branch."""
    repo = tmp_path / "upstream"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")

    (repo / "VERSION").write_text("main-1\n", encoding="utf-8")
    # A file both branches share and no later commit touches: what a user's own
    # local tweak looks like, and what the stash has to carry across a switch.
    (repo / "notes.txt").write_text("upstream notes\n", encoding="utf-8")
    git(repo, "add", "VERSION", "notes.txt")
    git(repo, "commit", "-qm", "main one")

    git(repo, "checkout", "-q", "-b", "dev")
    (repo / "VERSION").write_text("dev-1\n", encoding="utf-8")
    git(repo, "commit", "-qam", "dev one")

    git(repo, "checkout", "-q", "main")
    return repo


@pytest.fixture
def checkout(upstream, tmp_path) -> Path:
    """The updater's own checkout, cloned from the fake upstream."""
    repo = updater.repo_dir()
    repo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "-q", str(upstream), str(repo)], check=True, capture_output=True
    )
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    return repo


@pytest.fixture
def fake_pip(monkeypatch, tmp_path) -> Path:
    """A pip that records the arguments it was given instead of installing."""
    pip = updater.data_dir() / ".venv" / "bin" / "pip"
    pip.parent.mkdir(parents=True, exist_ok=True)
    record = tmp_path / "pip-calls.txt"
    pip.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> " + f'"{record}"\n', encoding="utf-8"
    )
    pip.chmod(0o755)
    return record


# --- channels ---------------------------------------------------------------


def test_channels_map_to_the_two_branches():
    assert updater.branch_for_channel("stable") == "main"
    assert updater.branch_for_channel("rolling") == "dev"


def test_an_unknown_channel_never_reaches_git():
    """The branch name lands in an argv, so free text must not get that far."""
    for bogus in ("main; rm -rf /", "master", "", "--upload-pack=evil"):
        with pytest.raises(UpdateError):
            updater.branch_for_channel(bogus)


def test_the_channel_is_remembered_on_disk_apart_from_the_inventory():
    assert updater.current_channel() == "stable"
    updater.set_channel("rolling")

    assert updater.current_channel() == "rolling"
    text = settings_file().read_text(encoding="utf-8")
    assert "rolling" in text
    assert settings_file().name == "settings.toml"
    assert settings_file().stat().st_mode & 0o777 == 0o600


def test_a_corrupt_settings_file_falls_back_to_the_default():
    settings_file().parent.mkdir(parents=True, exist_ok=True)
    settings_file().write_text("this is not = = toml\n", encoding="utf-8")
    assert updater.current_channel() == "stable"


# --- inspecting ------------------------------------------------------------


def test_without_a_checkout_the_state_is_empty_and_check_says_so():
    assert updater.has_checkout() is False
    assert updater.local_state().commit is None

    status = updater.check("stable")
    assert status.error is not None
    assert "clone" in status.error


def test_the_first_update_clones_the_missing_checkout(upstream, fake_pip, monkeypatch):
    """Installs made by the old installer have a venv but no checkout."""
    monkeypatch.setattr(updater, "REPO_URL", str(upstream))
    lines: list[str] = []

    updater.update("stable", progress=lines.append)

    assert updater.has_checkout() is True
    assert (updater.repo_dir() / "VERSION").read_text().strip() == "main-1"
    assert any("cloning" in line.lower() for line in lines)


def test_a_non_git_directory_in_the_way_is_reported(upstream, monkeypatch):
    monkeypatch.setattr(updater, "REPO_URL", str(upstream))
    updater.repo_dir().mkdir(parents=True)
    (updater.repo_dir() / "stray.txt").write_text("hi\n", encoding="utf-8")

    with pytest.raises(UpdateError) as raised:
        updater.update("stable")
    assert "not a git checkout" in str(raised.value)


def test_check_reports_what_the_channel_would_bring(checkout, upstream):
    status = updater.check("rolling")

    assert status.error is None
    assert status.branch == "dev"
    assert status.behind == 1  # dev is one commit ahead of the cloned main
    assert status.remote.subject == "dev one"
    assert status.local.branch == "main"


# --- updating --------------------------------------------------------------


def test_update_switches_channel_and_reinstalls(checkout, upstream, fake_pip):
    updater.update("rolling")

    assert (checkout / "VERSION").read_text().strip() == "dev-1"
    assert git(checkout, "branch", "--show-current") == "dev"
    # The freshly pulled checkout is what got installed into the venv.
    assert f"install --upgrade {checkout}" in fake_pip.read_text()


def test_update_fast_forwards_new_upstream_commits(checkout, upstream, fake_pip):
    (upstream / "VERSION").write_text("main-2\n", encoding="utf-8")
    git(upstream, "commit", "-qam", "main two")

    updater.update("stable")

    assert (checkout / "VERSION").read_text().strip() == "main-2"
    assert updater.local_state().subject == "main two"


def test_local_changes_stop_the_update_until_the_user_agrees(checkout, upstream, fake_pip):
    (checkout / "VERSION").write_text("hand-edited\n", encoding="utf-8")

    with pytest.raises(UpdateError) as raised:
        updater.update("rolling")

    assert "Confirm stashing" in str(raised.value)
    # Nothing moved, and the edit is still there.
    assert (checkout / "VERSION").read_text().strip() == "hand-edited"
    assert git(checkout, "branch", "--show-current") == "main"
    assert not fake_pip.exists()


def test_agreed_stash_is_restored_after_a_successful_update(checkout, upstream, fake_pip):
    (checkout / "notes.txt").write_text("my own note\n", encoding="utf-8")

    updater.update("rolling", allow_stash=True)

    # Updated *and* the hand edit survived the branch switch and the pull.
    assert git(checkout, "branch", "--show-current") == "dev"
    assert (checkout / "VERSION").read_text().strip() == "dev-1"
    assert (checkout / "notes.txt").read_text().strip() == "my own note"
    assert git(checkout, "stash", "list") == ""


def test_a_failed_pull_puts_the_stash_back(checkout, upstream, fake_pip):
    """A diverged branch must not cost the user their local edits."""
    # Diverge the local dev from the upstream dev, so --ff-only cannot work.
    git(checkout, "checkout", "-q", "dev")
    (checkout / "VERSION").write_text("local-only\n", encoding="utf-8")
    git(checkout, "commit", "-qam", "diverging local commit")
    git(upstream, "checkout", "-q", "dev")
    (upstream / "VERSION").write_text("dev-2\n", encoding="utf-8")
    git(upstream, "commit", "-qam", "dev two")
    git(upstream, "checkout", "-q", "main")

    (checkout / "notes.txt").write_text("my own note\n", encoding="utf-8")

    with pytest.raises(UpdateError) as raised:
        updater.update("rolling", allow_stash=True)

    assert "pull failed" in str(raised.value)
    # The stash came back rather than being left sitting in the stash list.
    assert (checkout / "notes.txt").read_text().strip() == "my own note"
    assert git(checkout, "stash", "list") == ""
    assert not fake_pip.exists()


def test_a_missing_venv_pip_is_reported_not_crashed(checkout, upstream):
    with pytest.raises(UpdateError) as raised:
        updater.update("rolling")

    assert "pip is missing" in str(raised.value)
    # The code itself did land, so the message has to say what is left to do.
    assert "install/install.sh" in str(raised.value)


def test_an_unreachable_origin_fails_with_a_readable_message(checkout, upstream, fake_pip):
    git(checkout, "remote", "set-url", "origin", str(upstream) + "-gone")

    with pytest.raises(UpdateError) as raised:
        updater.update("stable")

    assert "fetch failed" in str(raised.value)
    assert "Traceback" not in str(raised.value)


def test_progress_messages_describe_every_step(checkout, upstream, fake_pip):
    lines: list[str] = []
    updater.update("rolling", progress=lines.append)

    joined = "\n".join(lines).lower()
    for step in ("fetching", "switching", "pulling", "reinstalling", "updated to"):
        assert step in joined, step


def test_restart_command_is_an_argument_list_not_a_shell_string():
    command = updater.restart_command()
    assert isinstance(command, list)
    assert all(isinstance(part, str) for part in command)
    assert command[0]
