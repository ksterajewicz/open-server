# open-server

A self-hosted tool for managing SSH connections to multiple servers and working
across them from one place — so you configure your servers once instead of
juggling SSH commands by hand.

> **Status:** early development, but usable — you can save servers and run
> several live SSH sessions side by side in one window. Expect things to change.

Made by **Karol Terajewicz** — https://github.com/ksterajewicz/open-server

**Built with:** Python + [Textual](https://github.com/Textualize/textual) — the
terminal UI can also be served to a browser, which is the basis for the planned
web interface.

## Planned features

- **Server inventory** — store connection details for your VPS/servers and add,
  list, and edit them from simple commands.
- **Multi-terminal dashboard** — a "btop-style" view with several live terminals
  at once, each labeled with its server, and a per-pane option to open a new
  connection or start a new task.
- **Secure by default** — connection metadata is kept separate from secrets;
  passwords and passphrases go in the OS keyring or via `ssh-agent`, never
  plaintext.
- **Web access (later)** — reach the same interface from a browser after logging
  in, safely placed behind an access/auth layer.

## Requirements

- Linux (only supported platform for now)
- `ssh` (OpenSSH client)

## Install

```bash
git clone https://github.com/ksterajewicz/open-server.git
cd open-server
chmod +x install/install.sh
./install/install.sh
```

The installer now does the whole user-local setup:

- creates a private config directory at `~/.config/open-server/` with a starter
  `servers.toml` inventory,
- installs the app into `~/.local/share/open-server/.venv`,
- creates a launcher command at `~/.local/bin/open-server`,
- creates a desktop entry at `~/.local/share/applications/open-server.desktop`.

If `~/.local/bin` is not on your `PATH`, add it and start a new shell session.

## Usage

Start the dashboard with `open-server`, or launch `open-server` from your
applications menu. It opens empty; press <kbd>F2</kbd> to pick a server and
connect. Every connection becomes its own panel, and the grid grows as you add
more — several servers (or several sessions to one server) stay live side by
side.

| Key | Action |
| --- | --- |
| <kbd>F2</kbd> | Server inventory — connect, add (<kbd>a</kbd>), delete (<kbd>d</kbd>) |
| <kbd>F4</kbd> | Close the focused panel (ends that SSH session) |
| <kbd>F6</kbd> | Move focus to the next panel |
| <kbd>F10</kbd> | Quit (closes every session) |

Everything else goes straight to the shell in the focused panel, so
<kbd>Tab</kbd>, <kbd>Ctrl</kbd>+<kbd>C</kbd> and friends behave as usual.

Only the focused panel runs a full terminal emulator; background panels keep a
cheap output view, which is what keeps many open sessions affordable.

## Project structure

```
open-server/
├── README.md              # you are here
├── LICENCE.md             # license
├── pyproject.toml         # package metadata and dependencies
├── install/
│   └── install.sh         # user-local install: venv, launcher, desktop entry
├── src/open_server/
│   ├── app.py             # the application, screens and key bindings
│   ├── config.py          # servers.toml inventory (metadata only)
│   ├── credentials.py     # ssh-agent / application keys / OS keyring
│   ├── ssh_session.py     # one ssh process in a PTY, lazy VT100 screen
│   ├── screens/           # server inventory screens
│   └── widgets/           # dashboard grid and terminal panels
└── tests/                 # pytest suite (no live server needed)
```

## Roadmap

- [x] Repo scaffold + installer with welcome banner
- [x] Server inventory management (add / list / delete)
- [x] Multi-terminal TUI dashboard
- [x] Keys via `ssh-agent` or a generated application key
- [ ] In-app flow for saving a passphrase to the OS keyring
- [ ] Editing existing inventory entries
- [ ] AI-agent integration (MCP)
- [ ] Web interface behind an auth layer

## Contributing

Shell scripts use `set -euo pipefail` and must pass `shellcheck`; Python is
formatted with `black` and linted with `ruff` (both configured in
`pyproject.toml`). Commits follow [Conventional Commits](https://www.conventionalcommits.org/).
Run the test suite with `.venv/bin/pytest` — it needs no live SSH server.

## License

Released under the MIT License — see [LICENCE.md](LICENCE.md). You're free to use,
modify, and redistribute it, including commercially; just keep the copyright and
license notice. If you use open-server in your own project, a credit linking back
to this repository is appreciated.
