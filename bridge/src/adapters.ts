import type { AdapterCommand, AgentAdapter, RunEvent, RunRecord, RunRequest } from "./types.js";

function stripJsonPrefix(line: string): string {
  const trimmed = line.trim();
  return trimmed.startsWith("data:") ? trimmed.slice(5).trim() : trimmed;
}

function parseJsonLine(line: string): unknown | undefined {
  const candidate = stripJsonPrefix(line);
  if (!candidate.startsWith("{") && !candidate.startsWith("[")) {
    return undefined;
  }

  try {
    return JSON.parse(candidate);
  } catch {
    return undefined;
  }
}

function rememberStructuredOutput(record: RunRecord, value: unknown): void {
  if (!value || typeof value !== "object") {
    return;
  }

  const payload = value as Record<string, unknown>;
  if (typeof payload.session_id === "string") {
    record.sessionId = payload.session_id;
  }
  if (typeof payload.sessionId === "string") {
    record.sessionId = payload.sessionId;
  }
  if (typeof payload.summary === "string") {
    record.summary = payload.summary;
  }
  if (typeof payload.result === "string") {
    record.summary = payload.result;
  }
  if (payload.usage) {
    record.usage = payload.usage;
  }
  if (typeof payload.total_cost_usd === "number") {
    record.costUsd = payload.total_cost_usd;
  }
}

function parseJsonOutput(record: RunRecord, event: RunEvent): void {
  const value = parseJsonLine(event.data);
  rememberStructuredOutput(record, value);
}

// Codex emits its session id and usage on nested events rather than at the top
// level, so the generic extractor cannot see them.
function parseCodexOutput(record: RunRecord, event: RunEvent): void {
  const value = parseJsonLine(event.data);
  if (!value || typeof value !== "object") {
    return;
  }

  const payload = value as Record<string, unknown>;
  const type = typeof payload.type === "string" ? payload.type : "";

  if (type === "thread.started" && typeof payload.thread_id === "string") {
    record.sessionId = payload.thread_id;
  }
  if (type === "turn.completed" && payload.usage) {
    record.usage = payload.usage;
  }
  if (type === "item.completed") {
    const item = payload.item;
    if (item && typeof item === "object" && typeof (item as Record<string, unknown>).text === "string") {
      record.summary = (item as Record<string, unknown>).text as string;
    }
  }
}

const claude: AgentAdapter = {
  name: "claude",
  buildCommand(request: RunRequest): AdapterCommand {
    // headless --print mode cannot answer interactive permission prompts, so we
    // skip them (matches paperclip's claude_local default). Prompt is piped via stdin.
    const args = [
      "--print",
      "--output-format",
      "stream-json",
      "--verbose",
      "--dangerously-skip-permissions"
    ];
    if (request.model) {
      args.push("--model", request.model);
    }
    if (request.sessionId) {
      args.push("--resume", request.sessionId);
    }

    return {
      command: "claude",
      args,
      stdin: request.prompt
    };
  },
  parseEvent: parseJsonOutput
};

const codex: AgentAdapter = {
  name: "codex",
  buildCommand(request: RunRequest): AdapterCommand {
    // --skip-git-repo-check lets codex run in non-git workspaces; the bypass flag
    // makes exec non-interactive (no approval/sandbox prompts). Resume is a
    // positional subcommand (`exec ... resume <id>`), not a flag.
    const args = [
      "exec",
      "--json",
      "--skip-git-repo-check",
      "--dangerously-bypass-approvals-and-sandbox"
    ];
    if (request.model) {
      args.push("--model", request.model);
    }
    if (request.sessionId) {
      args.push("resume", request.sessionId);
    }
    args.push("-");

    return {
      command: "codex",
      args,
      stdin: request.prompt
    };
  },
  parseEvent: parseCodexOutput
};

export const adapters: Record<string, AgentAdapter> = {
  claude,
  codex
};
