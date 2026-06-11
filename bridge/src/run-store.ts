import { nanoid } from "nanoid";
import { isTerminalStatus } from "./types.js";
import type { AdapterName, RunEvent, RunRecord, RunStatus } from "./types.js";

export class RunStore {
  private readonly runs = new Map<string, RunRecord>();
  private readonly subscribers = new Map<string, Set<(event: RunEvent) => void>>();

  create(input: { adapter: AdapterName; prompt: string; cwd: string; requestedCwd: string; model?: string; sessionId?: string }): RunRecord {
    const record: RunRecord = {
      id: nanoid(),
      adapter: input.adapter,
      prompt: input.prompt,
      cwd: input.cwd,
      requestedCwd: input.requestedCwd,
      model: input.model,
      sessionId: input.sessionId,
      status: "queued",
      events: []
    };

    this.runs.set(record.id, record);
    return record;
  }

  get(id: string): RunRecord | undefined {
    return this.runs.get(id);
  }

  updateStatus(id: string, status: RunStatus, extra: Partial<RunRecord> = {}): RunRecord {
    const record = this.require(id);
    Object.assign(record, extra, { status });
    // Emit a final event on terminal states so SSE subscribers can detect
    // completion and close the connection.
    if (isTerminalStatus(status)) {
      this.appendEvent(id, "event", `[status] ${status}`);
    }
    return record;
  }

  appendEvent(id: string, stream: RunEvent["stream"], data: string): RunEvent {
    const record = this.require(id);
    const event: RunEvent = {
      id: record.events.length + 1,
      at: new Date().toISOString(),
      stream,
      data
    };
    record.events.push(event);

    for (const subscriber of this.subscribers.get(id) ?? []) {
      subscriber(event);
    }

    return event;
  }

  subscribe(id: string, callback: (event: RunEvent) => void): () => void {
    if (!this.subscribers.has(id)) {
      this.subscribers.set(id, new Set());
    }

    this.subscribers.get(id)?.add(callback);
    return () => {
      this.subscribers.get(id)?.delete(callback);
    };
  }

  private require(id: string): RunRecord {
    const record = this.runs.get(id);
    if (!record) {
      throw new Error(`Run not found: ${id}`);
    }
    return record;
  }
}
