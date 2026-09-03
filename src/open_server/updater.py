"""Updating open-server from inside open-server.

The application is installed into a virtualenv, not run from a checkout, so the
updater keeps its **own** checkout of the repository next to that virtualenv
(``~/.local/share/open-server/repo``), pulls into it, and then reinstalls the
package from it with the virtualenv's own pip.

The git sequence mirrors the shell updater used in the author's other project:
fetch, stash local changes to tracked files, checkout, ``pull --ff-only``, pop
the stash, reinstall.  The caution matters more than the ``git pull``: every
step that fails aborts with a readable message and puts a stash back, so a
failed update never eats the user's local edits.

Deliberately UI-agnostic — the TUI only calls these functions, and the planned
web front end will call the same ones.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import load_settings, save_setting

REPO_URL = "https://github.com/ksterajewicz/open-server.git"

# No tags, no releases: the branches *are* the channels.
CHANNEL_BRANCHES = {"stable": "main", "rolling": "dev"}
CHANNEL_LABELS = {
    "stable": "stable (main) — only what has been promoted",
    "rolling": "rolling (dev) — newest work, may break",
}
DEFAULT_CHANNEL = "stable"
CHANNEL_SETTING = "update_channel"

# Anything network-bound gets a deadline: no network must not mean a UI that
# never comes back.
GIT_TIMEOUT = 120
PIP_TIMEOUT = 600
LOCAL_GIT_TIMEOUT = 30

# How much of a failing command's stderr to hand the user. Enough to see the
# cause, not so much that the screen turns into a stack trace.
STDERR_LIMIT = 600

Progress = Callable[[str], None]


class UpdateError(Exception):
    """An update could not be completed; the message is meant for the user."""


@dataclass
class RepoState:
    """Where the updater's checkout currently sits."""

    branch: str | None = None
    commit: str | None = None
    subject: str | None = None

    def describe(self) -> str:
        if self.commit is None:
            return "no checkout yet"
        branch = self.branch or "(detached HEAD)"
        subject = f" — {self.subject}" if self.subject else ""
        return f"{branch} @ {self.commit}{subject}"


@dataclass
class UpdateStatus:
    """What an update on this channel would do, as far as we can tell."""

    channel: str
    branch: str
    local: RepoState
    remote: RepoState | None = None
    behind: int | None = None
    error: str | None = None

    def up_to_date(self) -> bool:
        return self.behind == 0


def data_dir() -> Path:
    """The install root, mirroring ``install/install.sh``."""
    override = os.environ.get("OPEN_SERVER_DATA_DIR")
    if override:
        return Path(override)
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(data_home) / "open-server"


def repo_dir() -> Path:
    """The updater's own checkout of the repository."""
    return data_dir() / "repo"


def venv_pip() -> Path:
    """The pip belonging to the virtualenv the application was installed into."""
    return data_dir() / ".venv" / "bin" / "pip"


def branch_for_channel(channel: str) -> str:
    """Map a channel to its branch, refusing anything not on the hard list.

    The branch name ends up in a git argument list, so it is never allowed to
    be free text — only these two names can ever reach git.
    """
    try:
        return CHANNEL_BRANCHES[channel]
    except KeyError:
        allowed = ", ".join(sorted(CHANNEL_BRANCHES))
        raise UpdateError(
            f"unknown update channel '{channel}' (expected one of: {allowed})"
        ) from None


def current_channel() -> str:
    """The channel the user picked, from ``settings.toml``."""
    value = load_settings().get(CHANNEL_SETTING)
    return str(value) if str(value) in CHANNEL_BRANCHES else DEFAULT_CHANNEL


def set_channel(channel: str) -> str:
    """Persist the chosen channel; returns the branch it maps to."""
    branch = branch_for_channel(channel)
    save_setting(CHANNEL_SETTING, channel)
    return branch


# --- running commands -------------------------------------------------------


def _run(
    args: list[str], *, cwd: Path | None = None, timeout: int = LOCAL_GIT_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    """Run one command as an argument list. Never a shell, never a format string."""
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, shell=False, validated branch
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        raise UpdateError(f"{args[0]} not found on PATH — cannot update.") from error
    except subprocess.TimeoutExpired as error:
        raise UpdateError(
            f"'{' '.join(args[:3])}…' timed out after {timeout}s — is the network reachable?"
        ) from error


def _summarise(result: subprocess.CompletedProcess[str]) -> str:
    """Turn a failed command into one readable line or two, never a traceback."""
    text = (result.stderr or result.stdout or "").strip()
    if len(text) > STDERR_LIMIT:
        text = text[:STDERR_LIMIT].rstrip() + " …"
    return text or f"exit code {result.returncode}"


def _git(
    args: list[str], *, cwd: Path | None = None, timeout: int = LOCAL_GIT_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd, timeout=timeout)


def _git_or_fail(
    args: list[str], what: str, *, cwd: Path | None = None, timeout: int = LOCAL_GIT_TIMEOUT
) -> str:
    result = _git(args, cwd=cwd, timeout=timeout)
    if result.returncode != 0:
        raise UpdateError(f"{what} failed: {_summarise(result)}")
    return result.stdout.strip()


# --- inspecting the checkout ------------------------------------------------


def has_checkout() -> bool:
    return (repo_dir() / ".git").exists()


def local_state() -> RepoState:
    """The checkout's current branch and commit, or an empty state if absent."""
    if not has_checkout():
        return RepoState()
    repo = repo_dir()
    branch = _git(["branch", "--show-current"], cwd=repo).stdout.strip() or None
    described = _git(["log", "-1", "--format=%h\t%s"], cwd=repo)
    if described.returncode != 0:
        return RepoState(branch=branch)
    commit, _, subject = described.stdout.strip().partition("\t")
    return RepoState(branch=branch, commit=commit or None, subject=subject or None)


def _remote_state(branch: str) -> RepoState:
    repo = repo_dir()
    ref = f"origin/{branch}"
    described = _git(["log", "-1", "--format=%h\t%s", ref], cwd=repo)
    if described.returncode != 0:
        raise UpdateError(f"no {ref} in the checkout — the fetch did not bring it in.")
    commit, _, subject = described.stdout.strip().partition("\t")
    return RepoState(branch=ref, commit=commit or None, subject=subject or None)


def _commits_behind(branch: str) -> int:
    repo = repo_dir()
    count = _git(["rev-list", "--count", f"HEAD..origin/{branch}"], cwd=repo).stdout.strip()
    return int(count) if count.isdigit() else 0


def dirty_tracked_files() -> list[str]:
    """Locally modified files that git tracks — the ones a pull would fight over.

    Untracked files are left out on purpose: a pull does not touch them, so
    there is no reason to stash them away from the user.
    """
    if not has_checkout():
        return []
    output = _git(
        ["status", "--porcelain", "--untracked-files=no"], cwd=repo_dir()
    ).stdout.splitlines()
    return [line[3:] for line in output if line.strip()]


# --- the update itself ------------------------------------------------------


def ensure_checkout(progress: Progress | None = None) -> Path:
    """Return the checkout, cloning it on first use.

    Installations made by an older installer have a virtualenv but no checkout,
    so the first update clones one — and says so, because it goes to the
    network and takes a moment.
    """
    repo = repo_dir()
    if (repo / ".git").exists():
        return repo

    _say(progress, f"No local checkout yet — cloning {REPO_URL} into {repo} (first update only).")
    if repo.exists() and any(repo.iterdir()):
        raise UpdateError(f"{repo} exists but is not a git checkout — move it aside and retry.")

    repo.parent.mkdir(parents=True, exist_ok=True)
    _git_or_fail(["clone", REPO_URL, str(repo)], "clone", timeout=GIT_TIMEOUT)
    _say(progress, "Clone finished.")
    return repo


def check(channel: str, progress: Progress | None = None) -> UpdateStatus:
    """Fetch and report what an update on ``channel`` would bring. Touches the network."""
    branch = branch_for_channel(channel)
    status = UpdateStatus(channel=channel, branch=branch, local=local_state())
    if not has_checkout():
        status.error = "no local checkout yet — updating will clone one first."
        return status

    _say(progress, f"Fetching origin/{branch}…")
    result = _git(["fetch", "origin", branch], cwd=repo_dir(), timeout=GIT_TIMEOUT)
    if result.returncode != 0:
        status.error = f"fetch failed: {_summarise(result)}"
        return status

    status.remote = _remote_state(branch)
    status.behind = _commits_behind(branch)
    return status


def update(channel: str, *, progress: Progress | None = None, allow_stash: bool = False) -> str:
    """Update the installation to the head of ``channel``; returns a summary line.

    ``allow_stash`` is the user's answer to "you have local changes in tracked
    files, may I stash them?".  Without it, local changes abort the update
    instead of being silently shelved.
    """
    branch = branch_for_channel(channel)
    repo = ensure_checkout(progress)

    _say(progress, f"Fetching origin/{branch}…")
    fetched = _git(["fetch", "origin", branch], cwd=repo, timeout=GIT_TIMEOUT)
    if fetched.returncode != 0:
        raise UpdateError(f"fetch failed: {_summarise(fetched)}. Check the network.")

    stashed = False
    dirty = dirty_tracked_files()
    if dirty:
        if not allow_stash:
            listed = ", ".join(dirty[:5]) + (" …" if len(dirty) > 5 else "")
            raise UpdateError(
                f"{len(dirty)} locally modified tracked file(s) in {repo}: {listed}. "
                "Confirm stashing them, or commit/discard them first."
            )
        label = f"open-server update {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}"
        pushed = _git(["stash", "push", "-u", "-m", label], cwd=repo)
        if pushed.returncode != 0:
            raise UpdateError(f"could not stash local changes: {_summarise(pushed)}. Aborted.")
        stashed = True
        _say(progress, f"Stashed {len(dirty)} local change(s).")

    try:
        _say(progress, f"Switching to {branch}…")
        checked_out = _git(["checkout", branch], cwd=repo)
        if checked_out.returncode != 0:
            raise UpdateError(f"checkout {branch} failed: {_summarise(checked_out)}")

        _say(progress, f"Pulling origin/{branch} (fast-forward only)…")
        pulled = _git(["pull", "--ff-only", "origin", branch], cwd=repo, timeout=GIT_TIMEOUT)
        if pulled.returncode != 0:
            raise UpdateError(
                f"pull failed: {_summarise(pulled)}. "
                "The checkout may have diverged — resolve it with git by hand."
            )
    except UpdateError:
        # Whatever went wrong, the user's changes go back where they were.
        if stashed:
            _restore_stash(repo, progress)
        raise

    if stashed:
        _restore_stash(repo, progress)

    _say(progress, "Reinstalling the package into the virtualenv…")
    _reinstall(repo, progress)

    state = local_state()
    _say(progress, f"Updated to {state.describe()}.")
    return state.describe()


def _restore_stash(repo: Path, progress: Progress | None) -> None:
    """Put stashed local changes back, saying so loudly if it cannot be done."""
    popped = _git(["stash", "pop"], cwd=repo)
    if popped.returncode == 0:
        _say(progress, "Local changes restored.")
    else:
        _say(
            progress,
            "Could not restore your local changes automatically — they are still "
            f"safe in 'git stash list' inside {repo}. ({_summarise(popped)})",
        )


def _reinstall(repo: Path, progress: Progress | None) -> None:
    pip = venv_pip()
    if not pip.exists():
        raise UpdateError(
            f"the code was updated in {repo}, but the virtualenv pip is missing at {pip} — "
            "rerun install/install.sh from that checkout to finish."
        )
    result = _run([str(pip), "install", "--upgrade", str(repo)], timeout=PIP_TIMEOUT)
    if result.returncode != 0:
        raise UpdateError(
            f"the code was updated in {repo}, but pip install failed: {_summarise(result)}"
        )
    _say(progress, "Reinstall finished.")


def _say(progress: Progress | None, message: str) -> None:
    if progress is not None:
        progress(message)


# --- restarting -------------------------------------------------------------


def restart_command() -> list[str]:
    """The argv to re-exec so the freshly installed code is the one running."""
    launcher = shutil.which("open-server")
    if launcher:
        return [launcher]
    return [sys.executable, "-m", "open_server"]


def restart() -> None:
    """Replace this process with the updated application. Does not return.

    Callers must have closed their SSH sessions first: ``execv`` never comes
    back, so nothing after it can clean up.
    """
    argv = restart_command()
    os.execv(argv[0], argv)  # noqa: S606 - fixed argv from which()/sys.executable
