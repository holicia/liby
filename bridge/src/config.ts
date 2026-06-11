import os from "node:os";
import path from "node:path";
import type { CodexPrices } from "./budget.js";
import type { AdapterName } from "./types.js";

export interface PathMapping {
  from: string;
  to: string;
}

export interface BridgeConfig {
  host: string;
  port: number;
  token: string;
  workspaceAllowlist: string[];
  pathMappings: PathMapping[];
  envAllowlist: Set<string>;
  /** Per-provider monthly USD budget. `null` means no limit. */
  monthlyLimits: Record<AdapterName, number | null>;
  /** Where the monthly spend ledger is persisted. */
  ledgerPath: string;
  /** Price table used to estimate Codex cost (it reports tokens, not USD). */
  codexPrices: CodexPrices;
  /** Adapter used when a request omits `adapter`. `null` makes it required. */
  defaultProvider: AdapterName | null;
  /**
   * `local` (default): prefer a local/subscription login, fall back to API keys
   * only when no local credentials are present. `api`: always use API keys.
   */
  authPreference: "local" | "api";
  /** Claude subscription credential file; its presence means "local login exists". */
  claudeCredentialsFile: string;
  /** Seconds to wait after SIGTERM before escalating to SIGKILL on stop/timeout. */
  graceSec: number;
}

function splitList(value: string | undefined): string[] {
  return (value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseMappings(value: string | undefined): PathMapping[] {
  return splitList(value).map((item) => {
    const separator = item.indexOf(":");
    if (separator <= 0) {
      throw new Error(`Invalid PATH_MAPPINGS entry: ${item}`);
    }

    return {
      from: path.resolve(item.slice(0, separator)),
      to: path.resolve(item.slice(separator + 1))
    };
  });
}

/** Parse a positive USD limit; blank/0/invalid -> null (no limit). */
function parseLimit(value: string | undefined): number | null {
  const n = Number(value);
  return value != null && value.trim() !== "" && Number.isFinite(n) && n > 0 ? n : null;
}

/** Parse a non-negative price; fall back to `fallback` when blank/invalid. */
function parsePrice(value: string | undefined, fallback: number): number {
  const n = Number(value);
  return value != null && value.trim() !== "" && Number.isFinite(n) && n >= 0 ? n : fallback;
}

function parseDefaultProvider(value: string | undefined): AdapterName | null {
  const v = (value ?? "").trim().toLowerCase();
  if (v === "") return null;
  // Accept common aliases for the OpenAI/Codex lane.
  if (v === "claude") return "claude";
  if (v === "codex" || v === "gpt" || v === "openai") return "codex";
  throw new Error(`Invalid DEFAULT_AI_PROVIDER: ${value} (expected "claude" or "codex")`);
}

export function loadConfig(): BridgeConfig {
  const token = process.env.BRIDGE_TOKEN;
  if (!token) {
    throw new Error("BRIDGE_TOKEN is required");
  }

  const workspaceAllowlist = splitList(process.env.WORKSPACE_ALLOWLIST).map((item) => path.resolve(item));
  if (workspaceAllowlist.length === 0) {
    throw new Error("WORKSPACE_ALLOWLIST must include at least one directory");
  }

  return {
    host: process.env.HOST ?? "127.0.0.1",
    port: Number(process.env.PORT ?? 8787),
    token,
    workspaceAllowlist,
    pathMappings: parseMappings(process.env.PATH_MAPPINGS),
    envAllowlist: new Set(splitList(process.env.ENV_ALLOWLIST)),
    monthlyLimits: {
      claude: parseLimit(process.env.CLAUDE_MONTHLY_LIMIT_USD),
      codex: parseLimit(process.env.GPT_MONTHLY_LIMIT_USD)
    },
    ledgerPath: process.env.USAGE_LEDGER_PATH ?? "usage-ledger.json",
    codexPrices: {
      // Estimates only (per 1M tokens). Override with your model's real rates.
      inputPerMTok: parsePrice(process.env.CODEX_PRICE_INPUT_PER_MTOK, 1.25),
      cachedInputPerMTok: parsePrice(process.env.CODEX_PRICE_CACHED_INPUT_PER_MTOK, 0.125),
      outputPerMTok: parsePrice(process.env.CODEX_PRICE_OUTPUT_PER_MTOK, 10.0)
    },
    defaultProvider: parseDefaultProvider(process.env.DEFAULT_AI_PROVIDER),
    authPreference: (process.env.AUTH_PREFERENCE ?? "local").trim().toLowerCase() === "api" ? "api" : "local",
    claudeCredentialsFile:
      process.env.CLAUDE_CREDENTIALS_FILE ??
      path.join(process.env.HOME ?? os.homedir(), ".claude", ".credentials.json"),
    graceSec: parsePrice(process.env.GRACE_SEC, 5)
  };
}

export function mapWorkspacePath(config: BridgeConfig, requestedPath: string): string {
  const resolvedRequest = path.resolve(requestedPath);
  for (const mapping of config.pathMappings) {
    const relative = path.relative(mapping.from, resolvedRequest);
    if (!relative.startsWith("..") && !path.isAbsolute(relative)) {
      return path.resolve(mapping.to, relative);
    }
  }

  return resolvedRequest;
}

export function assertAllowedWorkspace(config: BridgeConfig, candidate: string): string {
  const resolved = path.resolve(candidate);
  const allowed = config.workspaceAllowlist.some((root) => {
    const relative = path.relative(root, resolved);
    return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
  });

  if (!allowed) {
    throw new Error(`cwd is outside WORKSPACE_ALLOWLIST: ${candidate}`);
  }

  return resolved;
}

export function filterEnv(config: BridgeConfig, requestedEnv: Record<string, string> | undefined): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...process.env };
  // Never leak bridge-only secrets to the spawned agent (and its tools).
  delete env.BRIDGE_TOKEN;

  if (requestedEnv) {
    for (const [key, value] of Object.entries(requestedEnv)) {
      if (config.envAllowlist.has(key)) {
        env[key] = value;
      }
    }
  }

  return env;
}
