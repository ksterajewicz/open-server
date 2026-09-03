"""Credential handling: which key (if any) to hand to ssh for an entry.

Keys first, passwords never stored in plaintext.  Two modes are supported:
``agent`` (rely on the user's running ssh-agent) and an application key kept
in ``<config>/keys/``.  Anything that genuinely has to be a secret goes to the
OS keyring, and only when the user explicitly asks to save it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from .config import CONFIG_DIR_MODE, ServerEntry, config_dir

KEY_FILE_MODE = 0o600
KEYRING_SERVICE = "open-server"

AGENT_MODE = "agent"

PRIVATE_KEY_HEADER = "-----BEGIN "
PRIVATE_KEY_TRAILER = "PRIVATE KEY-----"

# Files that live next to keys in ~/.ssh but are never private keys.
NON_KEY_NAMES = frozenset(
    {
        "config",
        "known_hosts",
        "known_hosts.old",
        "authorized_keys",
        "authorized_keys2",
        "environment",
        "rc",
    }
)
NON_KEY_SUFFIXES = (".pub", ".ppk", ".crt", ".cer", ".req", ".old", ".bak")

# Passwords typed for one session but deliberately not saved: they live here
# until the process exits, keyed by entry name like the keyring entries.
_MEMORY_SECRETS: dict[str, str] = {}


@dataclass
class SshIdentity:
    """How to authenticate one connection."""

    key_path: Path | None = None

    def ssh_args(self) -> list[str]:
        """Extra ssh arguments for this identity (empty means: use the agent)."""
        if self.key_path is None:
            return []
        return ["-i", str(self.key_path)]


class MissingKeyError(Exception):
    """Raised when an entry points at a private key that is not on disk.

    Deliberately loud: silently generating a replacement key would hand ssh a
    keypair the server has never seen, and the user would be left staring at
    "Permission denied (publickey)" instead of "that key file is gone".
    """

    def __init__(self, key_path: Path, entry_name: str | None = None) -> None:
        self.key_path = key_path
        self.entry_name = entry_name
        where = f" for '{entry_name}'" if entry_name else ""
        super().__init__(
            f"SSH key{where} not found: {key_path}. "
            "Nothing was generated — point the entry at a key that exists, or "
            "generate a new application key and add its public half to the "
            "server's authorized_keys."
        )


def keys_dir() -> Path:
    return config_dir() / "keys"


def ensure_keys_dir() -> Path:
    directory = keys_dir()
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(CONFIG_DIR_MODE)
    return directory


def key_path_for(key_ref: str) -> Path:
    """Resolve a ``key_ref`` to a path, without caring whether it exists.

    A bare name lands in ``keys_dir()``; anything absolute (or ``~``-relative)
    is taken as the user's own key somewhere else on disk.
    """
    key_path = Path(key_ref).expanduser()
    if not key_path.is_absolute():
        key_path = keys_dir() / key_ref
    return key_path


def resolve_identity(entry: ServerEntry) -> SshIdentity:
    """Return the identity to use for ``entry``.

    Never creates anything: a missing key file raises ``MissingKeyError``.  Key
    generation is an explicit user action (``generate_app_key``), never a side
    effect of connecting.
    """
    if entry.key_ref == AGENT_MODE:
        return SshIdentity(key_path=None)

    key_path = key_path_for(entry.key_ref)
    if not key_path.exists():
        raise MissingKeyError(key_path, entry.name)
    return SshIdentity(key_path=key_path)


def generate_app_key(key_path: Path) -> Path:
    """Create an ed25519 keypair at ``key_path`` (private) + ``.pub``.

    Called only from an explicit user action — see ``resolve_identity``.
    """
    ensure_keys_dir()
    if key_path.exists():
        raise FileExistsError(
            f"{key_path} already exists — refusing to overwrite an existing key. "
            "Pick another name, or delete the old key first."
        )
    private_key = ed25519.Ed25519PrivateKey.generate()

    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    key_path.chmod(KEY_FILE_MODE)

    public_path = key_path.with_name(key_path.name + ".pub")
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        + b"\n"
    )
    return key_path


def public_key_text(key_path: Path) -> str:
    """Return the public key line to paste into the remote ``authorized_keys``."""
    public_path = key_path.with_name(key_path.name + ".pub")
    if not public_path.exists():
        raise FileNotFoundError(f"no public key next to {key_path}")
    return public_path.read_text(encoding="utf-8").strip()


def ssh_dir() -> Path:
    """The user's own OpenSSH directory (keys the user already manages)."""
    return Path.home() / ".ssh"


def looks_like_private_key(path: Path) -> bool:
    """Decide whether ``path`` is a usable private key file.

    A file counts as a private key when a matching ``<name>.pub`` sits next to
    it, or when its first line carries a PEM/OpenSSH private-key header.
    Bookkeeping files (``config``, ``known_hosts``, ``*.pub``, …) never do.
    """
    if not path.is_file():
        return False
    if path.name in NON_KEY_NAMES or path.name.startswith("."):
        return False
    if path.suffix in NON_KEY_SUFFIXES:
        return False

    if path.with_name(path.name + ".pub").is_file():
        return True

    try:
        with path.open("r", encoding="utf-8", errors="strict") as handle:
            first_line = handle.readline(200).strip()
    except (OSError, UnicodeDecodeError):
        return False
    return first_line.startswith(PRIVATE_KEY_HEADER) and first_line.endswith(PRIVATE_KEY_TRAILER)


def list_private_keys() -> list[Path]:
    """Every private key found on disk, in ``~/.ssh`` and in ``keys_dir()``.

    UI-agnostic on purpose: the TUI turns this into a picker, and a later web
    front end can render the same list.
    """
    found: list[Path] = []
    seen: set[Path] = set()
    for directory in (ssh_dir(), keys_dir()):
        try:
            candidates = sorted(directory.iterdir())
        except OSError:
            continue
        for candidate in candidates:
            resolved = candidate.absolute()
            if resolved in seen or not looks_like_private_key(candidate):
                continue
            seen.add(resolved)
            found.append(candidate)
    return found


def key_choices() -> list[tuple[str, str]]:
    """``(label, key_ref)`` pairs for a key picker, ssh-agent first."""
    choices = [("ssh-agent (no key file)", AGENT_MODE)]
    for path in list_private_keys():
        choices.append((f"{path.name}  ({path.parent})", str(path)))
    return choices


def get_saved_secret(entry: ServerEntry) -> str | None:
    """Read a secret the user chose to save for this entry, if any."""
    import keyring

    return keyring.get_password(KEYRING_SERVICE, entry.name)


def save_secret(entry: ServerEntry, secret: str) -> None:
    """Store a secret in the OS keyring. Called only from an explicit user action."""
    import keyring

    keyring.set_password(KEYRING_SERVICE, entry.name, secret)


def cache_secret(entry: ServerEntry, secret: str) -> None:
    """Hold a secret in memory for this process only (user declined saving)."""
    _MEMORY_SECRETS[entry.name] = secret


def forget_secret(entry: ServerEntry) -> None:
    """Drop the in-memory copy of a secret."""
    _MEMORY_SECRETS.pop(entry.name, None)


def get_secret(entry: ServerEntry) -> str | None:
    """The password to use for one connection: memory first, then the keyring.

    A missing or broken keyring backend is not an error here — it just means
    there is no saved password, and ssh falls back to asking interactively.
    """
    cached = _MEMORY_SECRETS.get(entry.name)
    if cached is not None:
        return cached
    try:
        return get_saved_secret(entry)
    except Exception:  # noqa: BLE001 - any keyring backend failure means "no secret"
        return None
