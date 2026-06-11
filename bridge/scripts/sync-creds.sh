#!/usr/bin/env sh
# POSIX equivalent of sync-creds.ps1: copies your local Claude/Codex subscription
# credentials into ./creds so the container can mount credential-ONLY directories.
# Run once after logging in on the host (and again whenever tokens refresh):
#   ./scripts/sync-creds.sh
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$root/creds/claude" "$root/creds/codex"

if [ -f "$HOME/.claude/.credentials.json" ]; then
  cp "$HOME/.claude/.credentials.json" "$root/creds/claude/.credentials.json"
  echo "synced claude credentials"
else
  echo "warning: no Claude credentials at ~/.claude/.credentials.json (run 'claude' and log in first)" >&2
fi

if [ -f "$HOME/.codex/auth.json" ]; then
  cp "$HOME/.codex/auth.json" "$root/creds/codex/auth.json"
  echo "synced codex credentials"
else
  echo "warning: no Codex credentials at ~/.codex/auth.json (run 'codex' and log in first)" >&2
fi
