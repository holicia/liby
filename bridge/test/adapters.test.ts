import { describe, expect, it } from "vitest";
import { adapters } from "../src/adapters";
import type { RunEvent, RunRecord, RunRequest } from "../src/types";

function makeRecord(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "run_1",
    adapter: "claude",
    cwd: "/workspace/proj",
    requestedCwd: "/workspace/proj",
    status: "running",
    prompt: "hi",
    events: [],
    ...overrides
  };
}

function makeEvent(data: string): RunEvent {
  return { id: 1, at: "2026-06-01T00:00:00.000Z", stream: "stdout", data };
}

function baseRequest(overrides: Partial<RunRequest> = {}): RunRequest {
  return { adapter: "claude", prompt: "do the thing", cwd: "/workspace/proj", ...overrides };
}

describe("claude.buildCommand", () => {
  it("runs headless stream-json with skipped permissions and pipes the prompt via stdin", () => {
    const command = adapters.claude.buildCommand(baseRequest());
    expect(command.command).toBe("claude");
    expect(command.args).toEqual([
      "--print",
      "--output-format",
      "stream-json",
      "--verbose",
      "--dangerously-skip-permissions"
    ]);
    expect(command.stdin).toBe("do the thing");
  });

  it("appends model and resume flags when provided", () => {
    const command = adapters.claude.buildCommand(
      baseRequest({ model: "claude-opus-4-8", sessionId: "sess-123" })
    );
    expect(command.args).toContain("--model");
    expect(command.args[command.args.indexOf("--model") + 1]).toBe("claude-opus-4-8");
    expect(command.args).toContain("--resume");
    expect(command.args[command.args.indexOf("--resume") + 1]).toBe("sess-123");
  });
});

describe("codex.buildCommand", () => {
  it("runs exec --json in non-git workspaces with stdin prompt", () => {
    const command = adapters.codex.buildCommand(baseRequest({ adapter: "codex" }));
    expect(command.command).toBe("codex");
    expect(command.args).toEqual([
      "exec",
      "--json",
      "--skip-git-repo-check",
      "--dangerously-bypass-approvals-and-sandbox",
      "-"
    ]);
    expect(command.stdin).toBe("do the thing");
  });

  it("uses the `resume <id>` subcommand (not a --resume flag) before the trailing dash", () => {
    const command = adapters.codex.buildCommand(
      baseRequest({ adapter: "codex", sessionId: "thread-9" })
    );
    expect(command.args).not.toContain("--resume");
    const resumeIdx = command.args.indexOf("resume");
    expect(resumeIdx).toBeGreaterThan(-1);
    expect(command.args[resumeIdx + 1]).toBe("thread-9");
    // the stdin marker must remain the final argument
    expect(command.args[command.args.length - 1]).toBe("-");
  });
});

describe("claude.parseEvent", () => {
  it("extracts session id, result summary and usage from stream-json lines", () => {
    const record = makeRecord();
    adapters.claude.parseEvent!(
      record,
      makeEvent(JSON.stringify({ type: "system", subtype: "init", session_id: "sess-abc" }))
    );
    adapters.claude.parseEvent!(
      record,
      makeEvent(
        JSON.stringify({
          type: "result",
          result: "all done",
          usage: { input_tokens: 10, output_tokens: 5 }
        })
      )
    );

    expect(record.sessionId).toBe("sess-abc");
    expect(record.summary).toBe("all done");
    expect(record.usage).toEqual({ input_tokens: 10, output_tokens: 5 });
  });

  it("tolerates SSE-style `data:` prefixes and ignores non-JSON lines", () => {
    const record = makeRecord();
    adapters.claude.parseEvent!(record, makeEvent("data: " + JSON.stringify({ session_id: "sess-x" })));
    adapters.claude.parseEvent!(record, makeEvent("not json at all"));
    expect(record.sessionId).toBe("sess-x");
  });
});

describe("codex.parseEvent", () => {
  it("maps nested codex events to session id, summary and usage", () => {
    const record = makeRecord({ adapter: "codex" });
    adapters.codex.parseEvent!(
      record,
      makeEvent(JSON.stringify({ type: "thread.started", thread_id: "thread-42" }))
    );
    adapters.codex.parseEvent!(
      record,
      makeEvent(JSON.stringify({ type: "item.completed", item: { text: "final answer" } }))
    );
    adapters.codex.parseEvent!(
      record,
      makeEvent(
        JSON.stringify({
          type: "turn.completed",
          usage: { input_tokens: 3, cached_input_tokens: 1, output_tokens: 2 }
        })
      )
    );

    expect(record.sessionId).toBe("thread-42");
    expect(record.summary).toBe("final answer");
    expect(record.usage).toEqual({ input_tokens: 3, cached_input_tokens: 1, output_tokens: 2 });
  });

  it("does not capture a top-level session_id the way the generic parser would", () => {
    const record = makeRecord({ adapter: "codex" });
    adapters.codex.parseEvent!(record, makeEvent(JSON.stringify({ session_id: "wrong-shape" })));
    expect(record.sessionId).toBeUndefined();
  });
});
