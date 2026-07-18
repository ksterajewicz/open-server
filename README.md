# open-server

A self-hosted tool for managing SSH connections to multiple servers and working
across them from one place — so you configure your servers once instead of
juggling SSH commands by hand.

> **Status:** early development. The installer and project scaffold are in place;
> the application is being designed. Expect things to change.

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

- A POSIX shell environment (Linux or macOS)
- `ssh` (OpenSSH client)

## Install

```bash
git clone https://github.com/ksterajewicz/open-server.git
cd open-server
chmod +x install/install.sh
./install/install.sh
```

The installer checks prerequisites and creates a private config directory at
`~/.config/open-server/` with a starter `servers.toml` inventory.

## Project structure

```
open-server/
├── README.md          # you are here
├── CHANGES.md         # changelog
├── LICENCE.md         # license
├── install/
│   └── install.sh     # installer
└── scripts/           # (planned) server management commands
```

## Roadmap

- [x] Repo scaffold + installer with welcome banner
- [ ] Server inventory management (add / list / edit / remove)
- [ ] Secure credential storage (keyring / ssh-agent)
- [ ] Multi-terminal TUI dashboard
- [ ] AI-agent integration (MCP)
- [ ] Web interface behind an auth layer

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for coding rules and commit message
guidelines.

## License

Released under the MIT License — see [LICENCE.md](LICENCE.md). You're free to use,
modify, and redistribute it, including commercially; just keep the copyright and
license notice. If you use open-server in your own project, a credit linking back
to this repository is appreciated.
