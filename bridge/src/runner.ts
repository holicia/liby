import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import fs from "node:fs";
import { adapters as defaultAdapters } from "./adapters.js";
import { estimateRunCostUsd, type UsageLedger } from "./budget.js";
import type { BridgeConfig } from "./config.js";
import { filterEnv } from "./config.js";
import type { AgentAdapter, RunRecord, RunRequest } from "./types.js";
import type { RunStore } from "./run-store.js";

const ON_WINDOWS = process.platform === "win32";

/**
 * All PIDs in the given session (Linux /proc). The agent is started as a session
 * leader (detached -> setsid), so its session id equals its pid and includes the
 * tools it spawned even when they live in separate process groups or get
 * reparented after the agent dies. Returns [] where /proc is unavailable.
 */
function pidsInSession(sid: number): number[] {
  let entries: string[];
  try {
    entries = fs.readdirSync("/proc");
  } catch {
    return [];
  }
  const out: number[] = [];
  for (const entry of entries) {
    const pid = Number(entry);
    if (!Number.isInteger(pid)) continue;
    try {
      const stat = fs.readFileSync(`/proc/${pid}/stat`, "utf8");
      // Fields after the comm ")" are: state ppid pgrp session ...
      const after = stat.slice(stat.lastIndexOf(")") + 2).split(" ");
      if (Number(after[3]) === sid) out.push(pid);
    } catch {
      // Process exited between readdir and read — ignore.
    }
  }
  return out;
}

/**
 * All descendant PIDs of `root` (Linux /proc), walking the parent (ppid) tree.
 * Must be called while the agent is still alive; agents may run tools in their
 * own session/group, so this ppid walk is what reliably finds them.
 */
function collectDescendants(root: number): number[] {
  let entries: string[];
  try {
    entries = fs.readdirSync("/proc");
  } catch {
    return [];
  }
  const childrenOf = new Map<number, number[]>();
  for (const entry of entries) {
    const pid = Number(entry);
    if (!Number.isInteger(pid)) continue;
    try {
      const stat = fs.readFileSync(`/proc/${pid}/stat`, "utf8");
      const ppid = Number(stat.slice(stat.lastIndexOf(")") + 2).split(" ")[1]);
      if (Number.isInteger(ppid)) {
        (childrenOf.get(ppid) ?? childrenOf.set(ppid, []).get(ppid)!).push(pid);
      }
    } catch {
      // ignore
    }
  }
  const out: number[] = [];
  const stack = [root];
  while (stack.length) {
    for (const child of childrenOf.get(stack.pop()!) ?? []) {
      out.push(child);
      stack.push(child);
    }
  }
  return out;
}

export class Runner {
  private readonly processes = new Map<string, ChildProcessWithoutNullStreams>();
  private readonly killTimers = new Map<string, NodeJS.Timeout>();

  constructor(
    private readonly config: BridgeConfig,
    private readonly store: RunStore,
    private readonly ledger: UsageLedger,
    private readonly adapterRegistry: Record<string, AgentAdapter> = defaultAdapters
  ) {}

  start(record: RunRecord, request: RunRequest): void {
    const adapter = this.adapterRegistry[record.adapter];
    const command = adapter.buildCommand(request);
    const timeoutMs = Math.max(1, request.timeoutSec ?? 900) * 1000;
    const graceMs = Math.max(0, request.graceSec ?? this.config.graceSec) * 1000;

    if (!fs.existsSync(record.cwd) || !fs.statSync(record.cwd).isDirectory()) {
      this.store.updateStatus(record.id, "failed", {
        finishedAt: new Date().toISOString(),
        error: `cwd does not exist or is not a directory: ${record.cwd}`
      });
      return;
    }

    this.store.updateStatus(record.id, "running", { startedAt: new Date().toISOString() });
    this.store.appendEvent(record.id, "event", `Starting ${command.command} ${command.args.join(" ")}`);

    const child = spawn(command.command, command.args, {
      cwd: record.cwd,
      env: this.buildChildEnv(record.adapter, request),
      shell: false,
      // On POSIX, run in its own process group so we can signal the whole tree
      // (the agent plus any tools it spawns), not just the direct child.
      detached: !ON_WINDOWS,
      stdio: ["pipe", "pipe", "pipe"]
    });

    this.processes.set(record.id, child);

    const timeout = setTimeout(() => {
      this.store.appendEvent(record.id, "event", `Timed out after ${timeoutMs}ms`);
      this.terminate(record.id, child, graceMs);
      this.store.updateStatus(record.id, "timed_out", {
        finishedAt: new Date().toISOString(),
        error: "Run timed out"
      });
    }, timeoutMs);

    // Stream chunks do not respect line boundaries, so buffer partial lines and
    // only emit/parse complete lines. Remaining buffers are flushed on close.
    let stdoutBuffer = "";
    let stderrBuffer = "";

    const emit = (stream: "stdout" | "stderr", line: string): void => {
      if (!line) {
        return;
      }
      const event = this.store.appendEvent(record.id, stream, line);
      if (stream === "stdout") {
        adapter.parseEvent?.(record, event);
      }
    };

    const drain = (stream: "stdout" | "stderr", buffer: string): string => {
      let rest = buffer;
      let index = rest.indexOf("\n");
      while (index !== -1) {
        emit(stream, rest.slice(0, index).replace(/\r$/, ""));
        rest = rest.slice(index + 1);
        index = rest.indexOf("\n");
      }
      return rest;
    };

    child.stdout.on("data", (chunk: Buffer) => {
      stdoutBuffer = drain("stdout", stdoutBuffer + chunk.toString("utf8"));
    });

    child.stderr.on("data", (chunk: Buffer) => {
      stderrBuffer = drain("stderr", stderrBuffer + chunk.toString("utf8"));
    });

    child.on("error", (error) => {
      clearTimeout(timeout);
      this.clearKillTimer(record.id);
      this.processes.delete(record.id);
      this.store.updateStatus(record.id, "failed", {
        finishedAt: new Date().toISOString(),
        error: error.message
      });
    });

    child.on("close", (exitCode, signal) => {
      clearTimeout(timeout);
      this.clearKillTimer(record.id);
      this.processes.delete(record.id);

      // Flush any trailing partial line (e.g. final stream-json output with no newline).
      emit("stdout", stdoutBuffer.replace(/\r$/, ""));
      emit("stderr", stderrBuffer.replace(/\r$/, ""));
      stdoutBuffer = "";
      stderrBuffer = "";

      const current = this.store.get(record.id);
      if (!current || current.status === "cancelled" || current.status === "timed_out") {
        return;
      }

      const costUsd = estimateRunCostUsd(record.adapter, record, this.config.codexPrices);
      this.store.updateStatus(record.id, exitCode === 0 ? "succeeded" : "failed", {
        finishedAt: new Date().toISOString(),
        exitCode,
        signal,
        costUsd,
        error: exitCode === 0 ? undefined : `Process exited with code ${exitCode}`
      });
      this.ledger.addSpend(record.adapter, costUsd);
    });

    // Guard against EPIPE when the child exits before reading stdin (e.g. missing
    // binary); an unhandled stream error would otherwise crash the server.
    child.stdin.on("error", () => {});
    child.stdin.end(command.stdin);
  }

  /**
   * Build the agent's environment. With local-first auth, when a Claude
   * subscription credential exists we drop ANTHROPIC_API_KEY so Claude Code uses
   * the local login instead of the API key. (Codex auth precedence is handled at
   * container startup since it reads ~/.codex/auth.json, not the env var.)
   */
  private buildChildEnv(adapter: RunRecord["adapter"], request: RunRequest): NodeJS.ProcessEnv {
    const env = filterEnv(this.config, request.env);
    if (
      this.config.authPreference === "local" &&
      adapter === "claude" &&
      fs.existsSync(this.config.claudeCredentialsFile)
    ) {
      delete env.ANTHROPIC_API_KEY;
    }
    return env;
  }

  cancel(id: string): boolean {
    const child = this.processes.get(id);
    if (!child) {
      return false;
    }

    this.terminate(id, child, Math.max(0, this.config.graceSec) * 1000);
    this.processes.delete(id);
    this.store.updateStatus(id, "cancelled", { finishedAt: new Date().toISOString() });
    this.store.appendEvent(id, "event", "Run cancelled");
    return true;
  }

  /**
   * Ask the process (group) to stop with SIGTERM, then escalate to SIGKILL after
   * a grace period if it has not exited. On POSIX we signal the whole process
   * group (negative pid) so tools the agent spawned are killed too.
   */
  private terminate(id: string, child: ChildProcessWithoutNullStreams, graceMs: number): void {
    const pid = child.pid;

    if (ON_WINDOWS || !pid) {
      try {
        child.kill("SIGTERM");
      } catch {
        /* already gone */
      }
      this.clearKillTimer(id);
      const timer = setTimeout(() => {
        this.killTimers.delete(id);
        try {
          child.kill("SIGKILL");
        } catch {
          /* gone */
        }
      }, graceMs);
      timer.unref?.();
      this.killTimers.set(id, timer);
      return;
    }

    // Capture the full descendant tree NOW, while the agent is still alive —
    // agents may run tools in their own session/group, and once the agent dies
    // those tools reparent (their ppid link is lost) but their PIDs stay valid.
    const doomed = new Set<number>([pid, ...collectDescendants(pid), ...pidsInSession(pid)]);
    const signal = (sig: NodeJS.Signals): void => {
      for (const p of [...collectDescendants(pid), ...pidsInSession(pid)]) doomed.add(p);
      try {
        process.kill(-pid, sig); // the agent's own process group
      } catch {
        /* gone */
      }
      for (const target of doomed) {
        try {
          process.kill(target, sig);
        } catch {
          /* ESRCH */
        }
      }
    };

    signal("SIGTERM");
    this.clearKillTimer(id);
    const timer = setTimeout(() => {
      this.killTimers.delete(id);
      signal("SIGKILL");
    }, graceMs);
    timer.unref?.();
    this.killTimers.set(id, timer);
  }

  private clearKillTimer(id: string): void {
    const timer = this.killTimers.get(id);
    if (timer) {
      clearTimeout(timer);
      this.killTimers.delete(id);
    }
  }
}
