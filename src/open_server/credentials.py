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


@dataclass
class SshIdentity:
    """How to authenticate one connection."""

    key_path: Path | None = None

    def ssh_args(self) -> list[str]:
        """Extra ssh arguments for this identity (empty means: use the agent)."""
        if self.key_path is None:
            return []
        return ["-i", str(self.key_path)]


def keys_dir() -> Path:
    return config_dir() / "keys"


def ensure_keys_dir() -> Path:
    directory = keys_dir()
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(CONFIG_DIR_MODE)
    return directory


def resolve_identity(entry: ServerEntry) -> SshIdentity:
    """Return the identity to use for ``entry``, generating an app key if needed."""
    if entry.key_ref == AGENT_MODE:
        return SshIdentity(key_path=None)

    key_path = Path(entry.key_ref).expanduser()
    if not key_path.is_absolute():
        key_path = keys_dir() / entry.key_ref

    if not key_path.exists():
        generate_app_key(key_path)
    return SshIdentity(key_path=key_path)


def generate_app_key(key_path: Path) -> Path:
    """Create an ed25519 keypair at ``key_path`` (private) + ``.pub``."""
    ensure_keys_dir()
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


def get_saved_secret(entry: ServerEntry) -> str | None:
    """Read a secret the user chose to save for this entry, if any."""
    import keyring

    return keyring.get_password(KEYRING_SERVICE, entry.name)


def save_secret(entry: ServerEntry, secret: str) -> None:
    """Store a secret in the OS keyring. Called only from an explicit user action."""
    import keyring

    keyring.set_password(KEYRING_SERVICE, entry.name, secret)
