import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { UsageLedger, estimateCodexCostUsd, estimateRunCostUsd, type CodexPrices } from "../src/budget";
import type { RunRecord } from "../src/types";

const prices: CodexPrices = { inputPerMTok: 2, cachedInputPerMTok: 0.5, outputPerMTok: 10 };

function makeRecord(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "r1",
    adapter: "codex",
    cwd: "/workspace",
    requestedCwd: "/workspace",
    status: "succeeded",
    prompt: "x",
    events: [],
    ...overrides
  };
}

describe("estimateCodexCostUsd", () => {
  it("prices non-cached input, cached input and output separately", () => {
    // 1,000,000 input of which 200,000 cached, 500,000 output
    const usage = { input_tokens: 1_000_000, cached_input_tokens: 200_000, output_tokens: 500_000 };
    // nonCached 800k*2 + cached 200k*0.5 + output 500k*10, all /1e6
    // = 1.6 + 0.1 + 5.0 = 6.7
    expect(estimateCodexCostUsd(usage, prices)).toBeCloseTo(6.7, 9);
  });

  it("counts reasoning tokens as output and tolerates missing fields", () => {
    const usage = { output_tokens: 100_000, reasoning_output_tokens: 100_000 };
    expect(estimateCodexCostUsd(usage, prices)).toBeCloseTo(2.0, 9); // 200k*10/1e6
    expect(estimateCodexCostUsd(undefined, prices)).toBe(0);
  });
});

describe("estimateRunCostUsd", () => {
  it("uses Claude's reported costUsd directly", () => {
    const record = makeRecord({ adapter: "claude", costUsd: 0.42, usage: { input_tokens: 999 } });
    expect(estimateRunCostUsd("claude", record, prices)).toBe(0.42);
  });

  it("estimates Codex cost from tokens", () => {
    const record = makeRecord({ adapter: "codex", usage: { input_tokens: 1_000_000, output_tokens: 0 } });
    expect(estimateRunCostUsd("codex", record, prices)).toBeCloseTo(2.0, 9);
  });
});

describe("UsageLedger", () => {
  let dir: string;
  let file: string;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "ledger-"));
    file = path.join(dir, "nested", "usage-ledger.json");
  });

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("starts empty and accumulates spend persistently", () => {
    const ledger = new UsageLedger(file);
    expect(ledger.getSpend("claude")).toBe(0);
    ledger.addSpend("claude", 1.5);
    ledger.addSpend("claude", 0.5);
    expect(ledger.getSpend("claude")).toBe(2.0);

    // A fresh instance reads the same persisted file (creating parent dirs).
    const reopened = new UsageLedger(file);
    expect(reopened.getSpend("claude")).toBe(2.0);
    expect(reopened.getSpend("codex")).toBe(0);
  });

  it("ignores non-positive spend and does not double count providers", () => {
    const ledger = new UsageLedger(file);
    ledger.addSpend("codex", 0);
    ledger.addSpend("codex", -5);
    expect(ledger.getSpend("codex")).toBe(0);
    ledger.addSpend("codex", 3);
    expect(ledger.getSpend("codex")).toBe(3);
    expect(ledger.getSpend("claude")).toBe(0);
  });

  it("resets spend when the persisted month is stale", () => {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ month: "2000-01", spend: { claude: 99 } }));
    const ledger = new UsageLedger(file);
    const thisMonth = new Date().toISOString().slice(0, 7);
    expect(ledger.month()).toBe(thisMonth);
    expect(ledger.getSpend("claude")).toBe(0);
  });
});
