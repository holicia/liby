export type AdapterName = "claude" | "codex";
export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "timed_out";
export type StreamName = "stdout" | "stderr" | "event";

const TERMINAL_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "succeeded",
  "failed",
  "cancelled",
  "timed_out"
]);

export function isTerminalStatus(status: RunStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

export interface RunEvent {
  id: number;
  at: string;
  stream: StreamName;
  data: string;
}

export interface RunRequest {
  adapter: AdapterName;
  prompt: string;
  cwd: string;
  execution?: "host";
  model?: string;
  timeoutSec?: number;
  graceSec?: number;
  env?: Record<string, string>;
  sessionId?: string;
}

export interface RunRecord {
  id: string;
  adapter: AdapterName;
  cwd: string;
  requestedCwd: string;
  status: RunStatus;
  prompt: string;
  model?: string;
  sessionId?: string;
  startedAt?: string;
  finishedAt?: string;
  exitCode?: number | null;
  signal?: NodeJS.Signals | null;
  error?: string;
  summary?: string;
  usage?: unknown;
  costUsd?: number;
  events: RunEvent[];
}

export interface AdapterCommand {
  command: string;
  args: string[];
  stdin: string;
}

export interface AgentAdapter {
  name: AdapterName;
  buildCommand(request: RunRequest): AdapterCommand;
  parseEvent?(record: RunRecord, event: RunEvent): void;
}
