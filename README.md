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
- seeds the updater's own checkout at `~/.local/share/open-server/repo`,
- creates a launcher command at `~/.local/bin/open-server`,
- creates a desktop entry at `~/.local/share/applications/open-server.desktop`.

If `~/.local/bin` is not on your `PATH`, add it and start a new shell session.

## Usage

Start the dashboard with `open-server`, or launch `open-server` from your
applications menu. It opens empty; press <kbd>F2</kbd> to pick a server and
connect. Every connection becomes its own panel, and the grid grows as you add
more — several servers (or several sessions to one server) stay live side by
side.

The interface is keyboard-only by design: there are no clickable buttons
anywhere, and every screen shows its own key legend on the bottom line.

| Key | Action |
| --- | --- |
| <kbd>F2</kbd> | Server inventory — connect, add (<kbd>a</kbd>), delete (<kbd>d</kbd>) |
| <kbd>F4</kbd> | Close the focused panel (ends that SSH session) |
| <kbd>F6</kbd> | Move focus to the next panel (scrolls it into view) |
| <kbd>F7</kbd> | Generate an application SSH key and show its public half |
| <kbd>F9</kbd> | Update open-server from GitHub |
| <kbd>F10</kbd> | Quit (closes every session) |

In the inventory, <kbd>Enter</kbd> connects, <kbd>a</kbd> opens the add form,
<kbd>d</kbd> deletes the selected entry and <kbd>Esc</kbd> goes back.

The add form is a full-screen form, not a dialog: <kbd>Tab</kbd> and
<kbd>Enter</kbd> move between fields, <kbd>Space</kbd> toggles a checkbox,
<kbd>Ctrl</kbd>+<kbd>S</kbd> saves and <kbd>Esc</kbd> cancels. It asks for the
user, the host/IP, an optional SSH password, and which key to use — the key is
picked from a list of the private keys found in `~/.ssh/` and
`~/.config/open-server/keys/`, with `ssh-agent` first. Name and port are
optional: the name defaults to `user@host` and the port to 22.

A password is kept only if you tick **Remember password in OS keyring**;
otherwise it lives in memory for that session alone. Either way it is typed into
ssh's own password prompt rather than passed as a command-line argument (so it
never shows up in `ps`), and it never reaches `servers.toml` — which still
refuses to load at all if it finds a password field.

Everything else goes straight to the shell in the focused panel, so
<kbd>Tab</kbd>, <kbd>Ctrl</kbd>+<kbd>C</kbd> and friends behave as usual.

Only the focused panel runs a full terminal emulator; background panels keep a
cheap output view, which is what keeps many open sessions affordable.

Panels never shrink below a size a shell can be used in — 40 columns wide and
10 rows tall. Once more sessions are open than the window can hold at that size,
the grid scrolls instead of squashing them, and <kbd>F6</kbd> scrolls the next
panel into view as it moves the focus there.

### SSH keys

open-server never creates a key on its own. If an entry points at a key file
that is not on disk, connecting fails with a message naming the missing path —
quietly generating a replacement would hand ssh a key the server has never
authorised, and you would be left debugging "Permission denied (publickey)".

Press <kbd>F7</kbd> to create an application key deliberately. It asks for a
name, writes the pair into `~/.config/open-server/keys/` (private half `0600`),
and shows the public key on screen so you can copy it into the server's
`~/.ssh/authorized_keys`.

### Updating from inside the app

Press <kbd>F9</kbd>. There are two channels, and the choice is remembered in
`~/.config/open-server/settings.toml` (separate from your server inventory):

| Channel | Branch | What you get |
| --- | --- | --- |
| stable | `main` | only what has been promoted to the main branch |
| rolling | `dev` | the newest work, which may break |

Keys on that screen: <kbd>s</kbd> stable, <kbd>r</kbd> rolling, <kbd>c</kbd>
check what the channel would bring, <kbd>u</kbd> update, <kbd>Esc</kbd> back.

The updater works on its own checkout at `~/.local/share/open-server/repo`
(cloned on first use if the installer did not seed it) and then reinstalls the
package into `~/.local/share/open-server/.venv`. Local edits to tracked files in
that checkout are stashed only after you confirm, and are restored afterwards —
including when a step fails and the update is rolled back.

Finishing an update needs a restart, which closes every open SSH panel; the app
says how many are open and waits for <kbd>Enter</kbd> before doing it.

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
│   ├── config.py          # servers.toml inventory + settings.toml preferences
│   ├── credentials.py     # ssh-agent / application keys / OS keyring
│   ├── ssh_session.py     # one ssh process in a PTY, lazy VT100 screen
│   ├── updater.py         # self-update: git checkout + venv reinstall (no UI)
│   ├── screens/           # inventory, key generation and update screens
│   └── widgets/           # dashboard grid and terminal panels
└── tests/                 # pytest suite (no live server needed)
```

## Roadmap

- [x] Repo scaffold + installer with welcome banner
- [x] Server inventory management (add / list / delete)
- [x] Multi-terminal TUI dashboard
- [x] Keys via `ssh-agent` or a generated application key
- [x] Picking an existing SSH key from disk when adding a connection
- [x] In-app flow for saving an SSH password to the OS keyring (opt-in)
- [x] Self-update from inside the app, with stable/rolling channels
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
