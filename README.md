# liby

> Paste a YouTube URL, PDF, article text, or code — get a structured AI summary note in a local web library you own.

[![CI](https://github.com/holicia/liby/actions/workflows/ci.yml/badge.svg)](https://github.com/holicia/liby/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**English** | [한국어](README.ko.md)

![liby home (light)](docs/images/home-light.png)

<details>
<summary>Dark mode</summary>

![liby home (dark)](docs/images/home-dark.png)
</details>

## Features

- **Multiple input sources** — YouTube (subtitle extraction via yt-dlp), PDF (PyMuPDF), plain text, Markdown, code
- **Two summary depths** — quick summaries, or detailed notes with chapters, pull quotes, and footnote citations
- **YouTube timeline integration** — click a timestamp in a note and the embedded player jumps to that moment
- **Projects & topics** — group notes into projects, generate per-project digests
- **Pluggable AI providers** — Anthropic API, OpenAI API, or your own **Claude Pro / ChatGPT Plus subscription** via the bundled [agent-runner-bridge](bridge/README.md) (no API billing)
- **Cost guard** — monthly spend limit per provider plus a usage dashboard
- **Discord bot (optional)** — trigger analysis from your phone and read results over Tailscale ([guide](docs/operations-discord-tailscale.md), Korean)
- **Obsidian-friendly storage** — every note is a Markdown file in `vault/` plus a row in SQLite

## Quick start (Docker)

```bash
git clone <this-repo>
cd liby
cp .env.example .env
```

### Option A — API keys

Set in `.env`: `DEFAULT_AI_PROVIDER=claude` (or `gpt`) and the matching API key, then:

```bash
docker compose up --build
```

Open http://127.0.0.1:8000. (The bridge is opt-in, so this starts liby only.)

### Option B — your own subscription (Claude Pro / ChatGPT Plus)

Runs analyses through the Claude Code / Codex CLI authenticated with **your own account** — no API billing. Credentials are never baked into the repo or image; each user injects their own locally.

1. Install the CLI on your host and log in once: `claude` (or `codex`)
2. Copy your credentials into the (gitignored) mount directory:
   - Windows: `pwsh ./bridge/scripts/sync-creds.ps1`
   - macOS/Linux: `./bridge/scripts/sync-creds.sh`
3. Set `BRIDGE_TOKEN` in `.env` to any long random string, then start with the `bridge` profile:

```bash
docker compose --profile bridge up --build
```

The `bridge` profile starts both liby and the bridge; liby reaches the bridge over the internal network automatically. Without the profile only liby runs, so a missing `BRIDGE_TOKEN` never blocks the API-key path.

### Manual install (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn main:app --port 8000
```

Optional: install `ffmpeg` for YouTube chapter screenshots.

## Configuration

All settings live in `.env` — see [.env.example](.env.example) for the full annotated list.

| Variable | Purpose |
|----------|---------|
| `DEFAULT_AI_PROVIDER` | `claude` (Anthropic API), `gpt` (OpenAI API), `claude-cli` / `codex-cli` (subscription via bridge) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | API keys (only for the provider you use) |
| `CLAUDE_MONTHLY_LIMIT_USD` / `GPT_MONTHLY_LIMIT_USD` | Monthly spend caps; provider is blocked when exceeded |
| `BRIDGE_TOKEN` | Shared secret between liby and the bridge (subscription mode) |
| `DISCORD_LIBY_TOKEN` / `DISCORD_LIBY_CHANNEL_ID` | Optional Discord bot trigger |
| `DB_PATH` / `VAULT_PATH` | SQLite file and Markdown vault locations |

## Architecture

```
Browser (HTMX + Tailwind)
    ↕ server-rendered HTML fragments
FastAPI ── routers (youtube / pdf / text / code / items / projects / ...)
    ├── task queue (async analysis worker)
    ├── AI provider layer ── Anthropic API / OpenAI API
    │                        └── bridge (:8787) ── claude / codex CLI (your subscription)
    └── SQLite (liby.db) + Markdown files (vault/)
```

## Notes & limitations

- The web UI and generated summaries are currently **Korean-first**.
- Subscription mode: OAuth login cannot run inside the container — log in on the host, and re-run `sync-creds` whenever tokens refresh.
- Use only your **own** account credentials.

## Development

```bash
python -m pytest          # liby tests (all external calls mocked — no keys needed)
cd bridge && npm test     # bridge tests
git config core.hooksPath .githooks   # enable the secret-scan pre-commit hook (once per clone)
```

The `.githooks/pre-commit` hook blocks accidental commits of `.env`, the database, or API-key/credential patterns. Run the `git config` line once after cloning to enable it.

Design specs and implementation plans live in [docs/superpowers/](docs/superpowers/) (Korean).

## License

[MIT](LICENSE)
