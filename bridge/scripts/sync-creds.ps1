# Copies your local Claude/Codex subscription credentials into ./creds so the
# container can mount credential-ONLY directories. On Windows, mounting the full
# live ~/.codex directory breaks Codex (its sqlite/app-server cannot initialize
# on a Windows bind mount), so we mount a clean dir containing just auth.json.
#
# Run this once after logging in on the host (and again whenever tokens refresh):
#   pwsh ./scripts/sync-creds.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$claudeSrc = Join-Path $env:USERPROFILE ".claude\.credentials.json"
$codexSrc  = Join-Path $env:USERPROFILE ".codex\auth.json"

New-Item -ItemType Directory -Force -Path (Join-Path $root "creds\claude") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $root "creds\codex")  | Out-Null

if (Test-Path $claudeSrc) {
  Copy-Item $claudeSrc (Join-Path $root "creds\claude\.credentials.json") -Force
  Write-Host "synced claude credentials"
} else {
  Write-Warning "no Claude credentials at $claudeSrc (run 'claude' and log in first)"
}

if (Test-Path $codexSrc) {
  Copy-Item $codexSrc (Join-Path $root "creds\codex\auth.json") -Force
  Write-Host "synced codex credentials"
} else {
  Write-Warning "no Codex credentials at $codexSrc (run 'codex' and log in first)"
}
