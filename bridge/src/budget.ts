import fs from "node:fs";
import path from "node:path";
import type { AdapterName, RunRecord } from "./types.js";

export interface CodexPrices {
  inputPerMTok: number;
  cachedInputPerMTok: number;
  outputPerMTok: number;
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** Estimate Codex cost in USD from its token usage and a configured price table. */
export function estimateCodexCostUsd(usage: unknown, prices: CodexPrices): number {
  if (!usage || typeof usage !== "object") {
    return 0;
  }
  const u = usage as Record<string, unknown>;
  const input = num(u.input_tokens);
  const cached = num(u.cached_input_tokens);
  const output = num(u.output_tokens) + num(u.reasoning_output_tokens);
  const nonCached = Math.max(0, input - cached);
  return (
    (nonCached * prices.inputPerMTok +
      cached * prices.cachedInputPerMTok +
      output * prices.outputPerMTok) /
    1_000_000
  );
}

/**
 * Final USD cost of a run. Claude reports `total_cost_usd` directly (captured on
 * the record as `costUsd`); Codex reports only tokens, so we estimate.
 */
export function estimateRunCostUsd(adapter: AdapterName, record: RunRecord, prices: CodexPrices): number {
  if (adapter === "claude") {
    return typeof record.costUsd === "number" ? record.costUsd : 0;
  }
  return estimateCodexCostUsd(record.usage, prices);
}

interface LedgerData {
  month: string;
  spend: Record<string, number>;
}

/**
 * Per-provider monthly spend, persisted to a JSON file (mount it on a volume to
 * survive container restarts). Resets automatically when the UTC month changes.
 */
export class UsageLedger {
  private data: LedgerData;

  constructor(private readonly filePath: string) {
    this.data = this.load();
  }

  private currentMonth(): string {
    return new Date().toISOString().slice(0, 7); // YYYY-MM (UTC)
  }

  private load(): LedgerData {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.filePath, "utf8")) as Partial<LedgerData>;
      if (parsed && typeof parsed.month === "string" && parsed.spend && typeof parsed.spend === "object") {
        return { month: parsed.month, spend: { ...(parsed.spend as Record<string, number>) } };
      }
    } catch {
      // Missing or invalid file -> start fresh.
    }
    return { month: this.currentMonth(), spend: {} };
  }

  private rollover(): void {
    const now = this.currentMonth();
    if (this.data.month !== now) {
      this.data = { month: now, spend: {} };
    }
  }

  private persist(): void {
    try {
      fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
      const tmp = `${this.filePath}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(this.data, null, 2));
      fs.renameSync(tmp, this.filePath);
    } catch {
      // Best effort: never fail a run because the ledger could not be written.
    }
  }

  month(): string {
    this.rollover();
    return this.data.month;
  }

  getSpend(provider: AdapterName): number {
    this.rollover();
    return this.data.spend[provider] ?? 0;
  }

  addSpend(provider: AdapterName, usd: number): number {
    this.rollover();
    if (usd > 0) {
      this.data.spend[provider] = (this.data.spend[provider] ?? 0) + usd;
      this.persist();
    }
    return this.data.spend[provider] ?? 0;
  }
}
