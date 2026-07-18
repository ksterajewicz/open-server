# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## What this is

**open-server** is a self-hosted tool for managing SSH connections to multiple
servers and working across them from a single interface. The goal is to stop
"messing around with SSH" by hand: configure servers once, then reach them
through a persistent, well-organized UI.

- **Author:** Karol Terajewicz — https://github.com/ksterajewicz/open-server
- **Status:** early scaffold. Installer + docs exist; the app itself is being designed.

## Product vision

Two phases, built in order:

1. **Terminal (TUI) — CURRENT PRIORITY.** A **btop-style** interface: a
   connection manager plus a dashboard grid of live terminals, each labeled with
   the server it's attached to, with a per-pane option to open a new connection /
   start a new task. This is the foundation and the sole focus for now.
2. **Web later** — the same capabilities reachable from a browser after logging
   in, so it works from anywhere. Deliberately deferred: the web app is built
   **on top of** the TUI core, so the TUI must come first and its architecture
   should keep the core logic (inventory, connections, sessions) reusable by a
   future web layer.

An AI-agent integration is a later goal: an agent should be able to connect to
open-server and drive tasks on configured servers (MCP is the intended protocol).

## Architecture decisions (living log)

- **Build the btop-style TUI first; the web app comes later on top of it.**
  The terminal interface is the current priority and sole focus. The web phase
  is explicitly deferred and will reuse the TUI's core. Practical consequence:
  keep the domain/core logic (server inventory, connection handling, session
  management) in a UI-agnostic layer so a future web front-end can call the same
  code instead of forcing a rewrite. The TUI is one front-end over that core, not
  the whole app.
- **Stack: Python + Textual.** The TUI is built with
  [Textual](https://github.com/Textualize/textual). This directly serves the
  two-phase plan, because a Textual app can be served to a browser as-is:
  - **Web phase** uses `textual-serve` (self-hosted; runs the app in a subprocess
    and talks to the browser over a websocket) and/or `textual-web` (public URLs).
    Security note: textual-serve exposes only the app, **not a raw shell**, to the
    browser — unlike `textual-web -t` which serves an actual terminal and must not
    be shared. So the web phase is "serve our Textual app", never "serve a shell".
  - **Embedded terminals** (the btop-style grid) are built on `pyte` (VT100
    emulation) + the stdlib `pty` / `ptyprocess` for the PTY. `textual-terminal`
    (mitosch) is a ready pyte-based widget that can host several live terminals in
    one app — good for prototyping — but it's lightly maintained and slow because
    emulation is pure-Python. See the terminal-rendering open question below.
  - **Core/domain logic stays UI-agnostic** (plain Python modules) so the same
    code backs the TUI now and a possible `FastAPI` layer later. Tooling:
    `black` + `ruff`, `pyproject.toml`, target modern CPython (3.11+).
- **Separate three concerns that "SSH by hand" conflates:** persistence (keeping
  things running), transport (how you reach them), and auth (proving who you are).
  "Autostart" belongs to persistence; it must not become "no auth" on any
  network-reachable surface.
- **Credential handling: key-based first, never store passwords.** This mirrors
  how Odysseus handles SSH for its Cookbook servers (a generated app-owned key
  whose *public* half is added to the remote's `authorized_keys`), *not* how it
  stores provider API keys (DB/`.env` behind auth). SSH access has a far larger
  blast radius than a revocable API token, so it gets a higher bar. Rules:
  - **Prefer key auth, store nothing when possible.** Two modes: (a) reference
    the user's existing keys via `ssh-agent`; (b) app-owned key — generate a
    dedicated ed25519 in `~/.config/open-server/keys/` (dir `700`, key `600`)
    with a helper that prints the public key for `authorized_keys`.
  - **`servers.toml` holds metadata only** (host / port / user + a key reference
    or keyring entry id), never secrets.
  - **If a secret must be held** (a key passphrase, or a password for a
    password-only host): OS keyring via the Python `keyring` library
    (Secret Service / libsecret on Linux, Keychain on macOS). Fallback for
    headless boxes without a Secret Service: an `age` / libsodium-encrypted file
    unlocked by a master passphrase entered at startup. Never plaintext.
  - **Hygiene:** `.gitignore` `data/`, keys, and `.env`; never log secrets;
    redact tokens in error output (as Hermes does).
- **Config location:** `${XDG_CONFIG_HOME:-~/.config}/open-server/`, dir mode
  `700`, `servers.toml` mode `600`.
- **Web phase must sit behind a real access layer** (reverse proxy + forward-auth
  such as Authelia/Authentik, and/or Tailscale/Cloudflare Access), with the app
  bound to localhost — never `0.0.0.0` exposed directly.

## Open questions / decisions pending

- **Terminal rendering approach** (the btop grid) — three routes: (a) reuse
  `textual-terminal` as-is to move fast, accepting the perf/maintenance risk;
  (b) build a leaner pyte-based Terminal widget tuned for many panes; or
  (c) hybrid — render panes as live output tiles (Textual `RichLog`) and only
  spin up a fully-interactive emulator for the focused pane. Decide once we see
  how many concurrent panes need true interactivity.

(Credential handling is now decided — see the decisions log above.)

## Repository layout

```
open-server/
├── CLAUDE.md          # this file
├── README.md          # user-facing overview + install
├── CHANGES.md         # changelog (Keep a Changelog format)
├── CONTRIBUTING.md    # coding rules + Conventional Commits guidelines
├── LICENCE.md         # license (MIT, with repo URL in the copyright notice)
├── install/
│   └── install.sh     # installer: welcome banner + base setup
└── scripts/           # (planned) VPS management: add / list / edit / remove
```

## Conventions

- **Bash:** `#!/usr/bin/env bash`, `set -euo pipefail`, pass `shellcheck`.
  Gate colors on `[[ -t 1 ]]` and honor `NO_COLOR`. Keep scripts idempotent.
- **Commits:** follow Conventional Commits per `CONTRIBUTING.md` (types,
  open-server scopes, imperative lowercase subject, 100-char lines).
- **Changelog:** update `CHANGES.md` under `[Unreleased]` for every change.
- **Docs upkeep:** when a decision is made, record it here and reflect
  user-facing effects in `README.md`.

## Notes for maintaining these docs

This file, `README.md`, and `CHANGES.md` are kept up to date as the design
evolves. When adding a feature: append to `CHANGES.md`, update `README.md`
usage/roadmap, and log any architectural decision above.
