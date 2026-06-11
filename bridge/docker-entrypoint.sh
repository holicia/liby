#!/bin/sh
set -e

# Claude Code reads ANTHROPIC_API_KEY from the environment directly, but the
# Codex CLI authenticates from ~/.codex/auth.json. When an API key is provided
# (auth mode A), log in so `codex exec` has credentials. With local-first auth
# (the default), an existing local/subscription login wins and the API key is
# only a fallback.
AUTH_PREFERENCE="${AUTH_PREFERENCE:-local}"
if [ -n "${OPENAI_API_KEY:-}" ]; then
  if [ "$AUTH_PREFERENCE" = "local" ] && [ -f "$HOME/.codex/auth.json" ]; then
    echo "[entrypoint] codex: keeping existing local login (AUTH_PREFERENCE=local)"
  elif printf '%s' "$OPENAI_API_KEY" | codex login --with-api-key >/dev/null 2>&1; then
    echo "[entrypoint] codex: authenticated via OPENAI_API_KEY"
  else
    echo "[entrypoint] codex: login with OPENAI_API_KEY failed (continuing)" >&2
  fi
fi

exec "$@"
