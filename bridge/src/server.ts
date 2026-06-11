import "dotenv/config";
import { spawn } from "node:child_process";
import { timingSafeEqual } from "node:crypto";
import cors from "@fastify/cors";
import Fastify from "fastify";
import { z } from "zod";
import { adapters } from "./adapters.js";
import { UsageLedger } from "./budget.js";
import { assertAllowedWorkspace, loadConfig, mapWorkspacePath } from "./config.js";
import { Runner } from "./runner.js";
import { RunStore } from "./run-store.js";
import { isTerminalStatus } from "./types.js";
import type { AdapterName, RunEvent, RunRecord, RunRequest } from "./types.js";

const PROVIDERS: AdapterName[] = ["claude", "codex"];

const runRequestSchema = z.object({
  adapter: z.enum(["claude", "codex"]).optional(),
  prompt: z.string().min(1),
  cwd: z.string().min(1),
  execution: z.literal("host").optional(),
  model: z.string().min(1).optional(),
  timeoutSec: z.number().int().min(1).max(24 * 60 * 60).optional(),
  graceSec: z.number().int().min(0).max(300).optional(),
  env: z.record(z.string()).optional(),
  sessionId: z.string().min(1).optional()
});

function round6(value: number): number {
  return Math.round(value * 1e6) / 1e6;
}

const config = loadConfig();

function isAuthorized(header: string | undefined): boolean {
  const expected = Buffer.from(`Bearer ${config.token}`);
  const provided = Buffer.from(header ?? "");
  // timingSafeEqual throws on length mismatch, so guard length first.
  return provided.length === expected.length && timingSafeEqual(provided, expected);
}

const store = new RunStore();
const ledger = new UsageLedger(config.ledgerPath);
const runner = new Runner(config, store, ledger);
// Disable Fastify's per-request auto logs (they spam two lines per /health probe
// every 30s) and log non-health requests concisely ourselves instead.
const app = Fastify({ logger: true, disableRequestLogging: true });

await app.register(cors, { origin: false });

app.addHook("onResponse", async (request, reply) => {
  if (request.url === "/health") {
    return;
  }
  request.log.info(
    {
      method: request.method,
      url: request.url,
      statusCode: reply.statusCode,
      responseTimeMs: Math.round(reply.elapsedTime)
    },
    "request"
  );
});

app.addHook("preHandler", async (request, reply) => {
  if (request.url === "/health") {
    return;
  }

  if (!isAuthorized(request.headers.authorization)) {
    return reply.code(401).send({ error: "Unauthorized" });
  }
});

function publicRun(record: RunRecord): Omit<RunRecord, "prompt"> {
  const { prompt: _prompt, ...rest } = record;
  return rest;
}

function writeSse(reply: { raw: NodeJS.WritableStream }, event: RunEvent): void {
  reply.raw.write(`id: ${event.id}\n`);
  reply.raw.write(`event: ${event.stream}\n`);
  reply.raw.write(`data: ${JSON.stringify(event)}\n\n`);
}

app.get("/health", async () => ({ ok: true }));

app.post("/v1/runs", async (request, reply) => {
  const parsed = runRequestSchema.parse(request.body);

  const adapter = parsed.adapter ?? config.defaultProvider;
  if (!adapter) {
    return reply
      .code(400)
      .send({ error: "adapter is required (no DEFAULT_AI_PROVIDER configured)" });
  }

  const limit = config.monthlyLimits[adapter];
  if (limit != null) {
    const spendUsd = ledger.getSpend(adapter);
    if (spendUsd >= limit) {
      return reply.code(402).send({
        error: `Monthly budget exceeded for ${adapter}`,
        code: "budget_exceeded",
        provider: adapter,
        spendUsd: round6(spendUsd),
        limitUsd: limit
      });
    }
  }

  let cwd: string;
  try {
    cwd = assertAllowedWorkspace(config, mapWorkspacePath(config, parsed.cwd));
  } catch (err) {
    // A disallowed/invalid cwd is a client error, not a server fault.
    return reply.code(400).send({ error: err instanceof Error ? err.message : "Invalid cwd" });
  }

  const record = store.create({
    adapter,
    prompt: parsed.prompt,
    cwd,
    requestedCwd: parsed.cwd,
    model: parsed.model,
    sessionId: parsed.sessionId
  });

  const runRequest: RunRequest = { ...parsed, adapter };
  setImmediate(() => runner.start(record, runRequest));
  return reply.code(202).send(publicRun(record));
});

app.get("/v1/budget", async () => {
  const month = ledger.month();
  const providers = Object.fromEntries(
    PROVIDERS.map((provider) => {
      const limitUsd = config.monthlyLimits[provider];
      const spendUsd = round6(ledger.getSpend(provider));
      return [
        provider,
        {
          spendUsd,
          limitUsd,
          remainingUsd: limitUsd != null ? round6(Math.max(0, limitUsd - spendUsd)) : null
        }
      ];
    })
  );
  return { month, providers };
});

app.get("/v1/runs/:id", async (request, reply) => {
  const { id } = z.object({ id: z.string() }).parse(request.params);
  const record = store.get(id);
  if (!record) {
    return reply.code(404).send({ error: "Run not found" });
  }

  return publicRun(record);
});

app.get("/v1/runs/:id/events", async (request, reply) => {
  const { id } = z.object({ id: z.string() }).parse(request.params);
  const record = store.get(id);
  if (!record) {
    return reply.code(404).send({ error: "Run not found" });
  }

  reply.hijack();
  reply.raw.writeHead(200, {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    connection: "keep-alive"
  });

  for (const event of record.events) {
    writeSse(reply, event);
  }

  if (isTerminalStatus(record.status)) {
    reply.raw.end();
    return;
  }

  const unsubscribe = store.subscribe(id, (event) => {
    writeSse(reply, event);
    const current = store.get(id);
    if (current && isTerminalStatus(current.status)) {
      unsubscribe();
      reply.raw.end();
    }
  });
  request.raw.on("close", unsubscribe);
});

app.post("/v1/runs/:id/cancel", async (request, reply) => {
  const { id } = z.object({ id: z.string() }).parse(request.params);
  if (!store.get(id)) {
    return reply.code(404).send({ error: "Run not found" });
  }

  return { cancelled: runner.cancel(id) };
});

app.post("/v1/adapters/:adapter/test", async (request, reply) => {
  const { adapter } = z.object({ adapter: z.enum(["claude", "codex"]) }).parse(request.params);
  const command = adapters[adapter].buildCommand({
    adapter,
    prompt: "",
    cwd: process.cwd(),
    execution: "host"
  });

  const result = await new Promise<{ ok: boolean; command: string; error?: string }>((resolve) => {
    const child = spawn(command.command, ["--version"], { shell: false });
    let error = "";
    child.stderr.on("data", (chunk) => {
      error += chunk.toString("utf8");
    });
    child.on("error", (err) => resolve({ ok: false, command: command.command, error: err.message }));
    child.on("close", (code) => resolve({ ok: code === 0, command: command.command, error: error.trim() || undefined }));
  });

  return reply.code(result.ok ? 200 : 503).send(result);
});

app.setErrorHandler((error, _request, reply) => {
  const status = error instanceof z.ZodError ? 400 : 500;
  const message = error instanceof Error ? error.message : "Unknown error";
  reply.code(status).send({ error: message });
});

await app.listen({ host: config.host, port: config.port });
