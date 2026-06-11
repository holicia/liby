import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { UsageLedger } from "../src/budget";
import type { BridgeConfig } from "../src/config";
import { Runner } from "../src/runner";
import { RunStore } from "../src/run-store";
import type { AgentAdapter } from "../src/types";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const isAlive = (pid: number): boolean => {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
};

function makeConfig(graceSec: number): BridgeConfig {
  return {
    host: "127.0.0.1",
    port: 0,
    token: "t",
    workspaceAllowlist: [os.tmpdir()],
    pathMappings: [],
    envAllowlist: new Set<string>(),
    monthlyLimits: { claude: null, codex: null },
    ledgerPath: path.join(os.tmpdir(), `led-${Date.now()}-${Math.random()}.json`),
    codexPrices: { inputPerMTok: 0, cachedInputPerMTok: 0, outputPerMTok: 0 },
    defaultProvider: null,
    authPreference: "api",
    claudeCredentialsFile: "/nonexistent/.credentials.json",
    graceSec
  };
}

// A process that ignores SIGTERM, so only SIGKILL escalation can stop it.
const trapAdapter: AgentAdapter = {
  name: "claude",
  buildCommand: () => ({
    command: "sh",
    args: ["-c", "trap '' TERM; while true; do sleep 1; done"],
    stdin: ""
  })
};

// POSIX-only: relies on signals and process groups (the bridge runs on Linux).
describe.skipIf(process.platform === "win32")("SIGKILL escalation", () => {
  it("kills a SIGTERM-ignoring process group after the grace period", async () => {
    const config = makeConfig(1);
    const store = new RunStore();
    const runner = new Runner(config, store, new UsageLedger(config.ledgerPath), { claude: trapAdapter });

    const record = store.create({ adapter: "claude", prompt: "", cwd: os.tmpdir(), requestedCwd: os.tmpdir() });
    runner.start(record, { adapter: "claude", prompt: "", cwd: os.tmpdir() });

    await sleep(800);
    const child = (runner as unknown as { processes: Map<string, { pid?: number }> }).processes.get(record.id);
    const pid = child?.pid;
    expect(pid).toBeTruthy();
    expect(isAlive(pid!)).toBe(true);

    runner.cancel(record.id); // SIGTERM (ignored) + schedule SIGKILL after graceSec

    await sleep(400); // still within the 1s grace window
    expect(isAlive(pid!)).toBe(true); // SIGTERM alone did NOT stop it -> escalation is required

    await sleep(1400); // past the grace window -> SIGKILL must have fired
    expect(isAlive(pid!)).toBe(false);
    expect(store.get(record.id)!.status).toBe("cancelled");
  }, 15000);
});
