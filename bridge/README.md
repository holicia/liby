# Agent Runner Bridge

A small REST bridge that runs **local Claude Code or Codex CLI** and exposes them
over HTTP so other apps can drive a coding agent.

This intentionally extracts only the *local runner* idea from Paperclip-style
adapters. It deliberately omits task queues, org/project management, billing,
budgets, governance, and Paperclip's UI.

## How it works

```
[your app] --HTTP--> [bridge :8787] --spawn--> [claude / codex CLI]
                          |                          |
                     /workspace (mounted)  <--read/write--+
```

A caller submits `{ adapter, prompt, cwd, ... }`; the bridge spawns the CLI in
headless mode, parses its `stream-json` / JSONL output, and exposes the run
(status, summary, usage, session id, logs) via REST and SSE.

Sessions are not stored server-side: the response returns a `sessionId`; send it
back on the next request to continue the conversation (the CLI persists its own
state under its home directory).

## Recommended: run the bridge in Docker

The image installs `claude` and `codex` and runs the server as a non-root user.
(Claude Code refuses `--dangerously-skip-permissions` under root, and non-root is
safer for an agent that executes arbitrary tool calls.)

### 1. Configure

```powershell
cd agent-runner-bridge
Copy-Item .env.example .env
```

Edit `.env`:

```text
PORT=8787
BRIDGE_TOKEN=use-a-long-random-token        # callers send this as a Bearer token
HOST_WORKSPACE=C:\Projects                   # host dir mounted into the container at /workspace
PATH_MAPPINGS=                               # optional, see "Workspaces" below
```

### 2. Provide authentication

`AUTH_PREFERENCE` controls precedence (default `local`):

- **`local` (default): prefer the local/subscription login, use API keys only as
  a fallback.** If a mounted login exists (Claude `~/.claude/.credentials.json`,
  Codex `~/.codex/auth.json`), it is used and any API key is ignored for that
  provider. If no local login exists, the API key (if set) is used instead.
- **`api`: always use API keys.**

**Mode B — subscription login (preferred under local-first).** Log in once on the
host (`claude` / `codex`), copy the credentials into `./creds`, and activate the
`docker-compose.local-auth.yml` override.

```powershell
pwsh ./scripts/sync-creds.ps1     # copies ~/.claude/.credentials.json + ~/.codex/auth.json into ./creds
```

Then set in `.env` (so plain `docker compose up` picks up the override):

```text
COMPOSE_PATH_SEPARATOR=;
COMPOSE_FILE=docker-compose.yml;docker-compose.local-auth.yml
CLAUDE_CREDS=./creds/claude
CODEX_CREDS=./creds/codex
```

The container runs as the `node` user, so credentials mount under `/home/node`,
not `/root`. Interactive OAuth cannot run inside the container — log in on the
host first, then re-run `sync-creds.ps1` whenever the tokens refresh.

> **Why credential-only dirs, not the live `~/.claude` / `~/.codex`?** On Windows,
> mounting the full live `~/.codex` breaks Codex — its sqlite/app-server cannot
> initialize on a Windows bind mount (`Operation not permitted`). Live mounts also
> let the container write history/logs/tokens into your real directories. Mounting
> the curated `./creds` dirs (just `auth.json` / `.credentials.json`) avoids both.

**Mode A — API keys (fallback, or set `AUTH_PREFERENCE=api`).** Put the keys in
`.env`:

```text
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

Billing is API metered (separate from any Claude/ChatGPT subscription). Claude
Code reads `ANTHROPIC_API_KEY` directly; for Codex the container entrypoint runs
`codex login --with-api-key` from `OPENAI_API_KEY` at startup (Codex authenticates
from `~/.codex/auth.json`, not the env var). Under local-first this API login is
skipped when a mounted `~/.codex/auth.json` is already present.

### Monthly budget guard

Set `CLAUDE_MONTHLY_LIMIT_USD` and/or `GPT_MONTHLY_LIMIT_USD` (blank/0 = no limit).
When a provider's month-to-date spend reaches its limit, `POST /v1/runs` returns
`402` with `code: "budget_exceeded"` before the agent is spawned. Spend is
persisted to `USAGE_LEDGER_PATH` (a Docker volume by default) and resets each UTC
month. Claude uses its reported `total_cost_usd`; Codex reports only tokens, so
its USD cost is estimated from the `CODEX_PRICE_*_PER_MTOK` rates (override the
placeholder defaults with your model's real pricing). Inspect current spend via
`GET /v1/budget`.

### 3. Build and start

```powershell
docker compose up -d --build
curl http://127.0.0.1:8787/health          # -> {"ok":true}
```

Verify each CLI is installed and reachable:

```bash
curl -X POST http://127.0.0.1:8787/v1/adapters/claude/test \
  -H "Authorization: Bearer $BRIDGE_TOKEN"
# -> {"ok":true,"command":"claude"}
```

The container has a healthcheck; `docker compose ps` shows `healthy` once up.

## Alternative: run on the host (no Docker)

Use this only if `claude` / `codex` are already installed and logged in on the
host and you do not need isolation.

```powershell
cd agent-runner-bridge
npm install
Copy-Item .env.example .env   # set BRIDGE_TOKEN + WORKSPACE_ALLOWLIST
npm run dev
```

When running on the host, set `WORKSPACE_ALLOWLIST` to the real host directories
callers may target (e.g. `C:\Projects`) instead of `/workspace`.

## Workspaces

- **Docker:** the host directory `HOST_WORKSPACE` is mounted at `/workspace`.
  Callers reference work by its in-container path, e.g. `cwd: "/workspace/my-repo"`.
  `WORKSPACE_ALLOWLIST=/workspace` (set in `docker-compose.yml`) confines runs to
  that tree; `..` traversal and prefix-sibling escapes are rejected.
- **PATH_MAPPINGS (optional):** rewrite a caller-supplied host path to its
  in-container path before spawning, e.g. `PATH_MAPPINGS=C:\Projects:/workspace`.
  Leave blank if callers already send `/workspace/...` paths.

## API

All endpoints except `/health` require:

```text
Authorization: Bearer <BRIDGE_TOKEN>
```

### Create a run

```bash
curl -X POST http://127.0.0.1:8787/v1/runs \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "adapter": "claude",
    "prompt": "Summarize this repo",
    "cwd": "/workspace/my-repo",
    "model": "claude-opus-4-8",
    "sessionId": "optional-id-to-resume",
    "timeoutSec": 900
  }'
```

Returns `202` with the run record (`status: "queued"`), or `402` if the
provider's monthly budget is exhausted. Fields: `adapter`, `model`, `effort`,
`timeoutSec`, `graceSec`, and request-supplied `env` keys (filtered by
`ENV_ALLOWLIST`) are optional. When `adapter` is omitted, `DEFAULT_AI_PROVIDER`
is used (a request with neither is rejected with `400`).

On `timeoutSec` expiry or `POST /v1/runs/:id/cancel`, the agent is sent `SIGTERM`,
then `SIGKILL` after `graceSec` (request field, default `GRACE_SEC`=5s) if it has
not exited. Termination targets the agent's process group, its session, and its
captured descendant tree, so the agent and the synchronous tools it spawned are
reliably cleaned up. Caveat: tasks an agent intentionally daemonizes (e.g. Claude
Code's `run_in_background`) detach from the agent's tree and are not force-killed;
isolating those would require a per-run PID namespace.

### Budget

```bash
curl http://127.0.0.1:8787/v1/budget \
  -H "Authorization: Bearer $BRIDGE_TOKEN"
# -> { "month": "2026-06", "providers": {
#      "claude": { "spendUsd": 0.12, "limitUsd": 5, "remainingUsd": 4.88 },
#      "codex":  { "spendUsd": 0,    "limitUsd": null, "remainingUsd": null } } }
```

### Check result

```bash
curl http://127.0.0.1:8787/v1/runs/<run-id> \
  -H "Authorization: Bearer $BRIDGE_TOKEN"
```

Terminal `status` is one of `succeeded` / `failed` / `cancelled` / `timed_out`.
The record carries `summary`, `sessionId`, `usage`, `exitCode`, and `events`.

### Stream logs (SSE)

```bash
curl -N http://127.0.0.1:8787/v1/runs/<run-id>/events \
  -H "Authorization: Bearer $BRIDGE_TOKEN"
```

Replays existing events, then streams new ones. The connection closes when the
run reaches a terminal state (a final `[status] <state>` event is emitted).

### Cancel

```bash
curl -X POST http://127.0.0.1:8787/v1/runs/<run-id>/cancel \
  -H "Authorization: Bearer $BRIDGE_TOKEN"
```

### Check CLI availability

```bash
curl -X POST http://127.0.0.1:8787/v1/adapters/codex/test \
  -H "Authorization: Bearer $BRIDGE_TOKEN"
```

## Calling the bridge from another Docker app

Publish only on loopback (the default). A sibling container reaches the bridge
through the host gateway — see `docker-client-compose.example.yml`:

```yaml
services:
  app:
    environment:
      AGENT_RUNNER_BRIDGE_URL: http://host.docker.internal:8787
      AGENT_RUNNER_BRIDGE_TOKEN: <same BRIDGE_TOKEN>
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

## Safety defaults

- The published port is bound to `127.0.0.1` only. For remote access, put a
  reverse proxy with its own TLS/auth in front.
- Bearer auth is required on every endpoint except `/health`; the token is
  compared in constant time.
- `cwd` must resolve inside `WORKSPACE_ALLOWLIST`; traversal and prefix-sibling
  escapes are rejected.
- Request-provided environment variables are ignored unless listed in
  `ENV_ALLOWLIST`. `BRIDGE_TOKEN` is never passed to the spawned agent.
- The agents run with permissions/approvals bypassed (`claude
  --dangerously-skip-permissions`, `codex --dangerously-bypass-approvals-and-sandbox`)
  so they can act autonomously. Run the bridge only for trusted callers, and rely
  on the container + workspace mount as the isolation boundary.

## Logs

Requests are logged one concise line each (`method`, `url`, `statusCode`,
`responseTimeMs`); `/health` probes are not logged (the Docker healthcheck still
tracks liveness). Docker rotates logs with `json-file` (`max-size: 10m`,
`max-file: 5` = 50 MB total), which holds well over a month at normal request
volume. View them with `docker compose logs --since 720h` (≈30 days). Retention
is size-based, not time-based; raise `max-size`/`max-file` in `docker-compose.yml`
for higher volumes, or add a log shipper for permanent history.

## Development

```powershell
npm run typecheck   # tsc --noEmit
npm test            # vitest: parser + workspace-path unit tests
npm run build       # emit dist/
```
