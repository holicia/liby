import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { assertAllowedWorkspace, filterEnv, mapWorkspacePath, type BridgeConfig } from "../src/config";

const ROOT = path.resolve("/srv/workspace");
const HOST_DIR = path.resolve("/host/projects");
const CONTAINER_DIR = path.resolve("/srv/workspace");

function makeConfig(overrides: Partial<BridgeConfig> = {}): BridgeConfig {
  return {
    host: "127.0.0.1",
    port: 8787,
    token: "secret",
    workspaceAllowlist: [ROOT],
    pathMappings: [{ from: HOST_DIR, to: CONTAINER_DIR }],
    envAllowlist: new Set(["ANTHROPIC_API_KEY"]),
    ...overrides
  };
}

describe("assertAllowedWorkspace", () => {
  const config = makeConfig();

  it("allows the allowlisted root itself", () => {
    expect(assertAllowedWorkspace(config, ROOT)).toBe(ROOT);
  });

  it("allows a subdirectory of an allowlisted root", () => {
    const sub = path.join(ROOT, "proj-a");
    expect(assertAllowedWorkspace(config, sub)).toBe(sub);
  });

  it("rejects parent-traversal escapes", () => {
    expect(() => assertAllowedWorkspace(config, path.join(ROOT, "..", "evil"))).toThrow(
      /outside WORKSPACE_ALLOWLIST/
    );
  });

  it("rejects a sibling whose path shares the root's prefix", () => {
    // e.g. root /srv/workspace must not accidentally allow /srv/workspace-evil
    expect(() => assertAllowedWorkspace(config, `${ROOT}-evil`)).toThrow(
      /outside WORKSPACE_ALLOWLIST/
    );
  });
});

describe("mapWorkspacePath", () => {
  const config = makeConfig();

  it("rewrites a host path under a mapping into the container path", () => {
    const requested = path.join(HOST_DIR, "proj-a");
    expect(mapWorkspacePath(config, requested)).toBe(path.join(CONTAINER_DIR, "proj-a"));
  });

  it("returns the resolved request unchanged when no mapping matches", () => {
    const requested = path.resolve("/elsewhere/thing");
    expect(mapWorkspacePath(config, requested)).toBe(requested);
  });
});

describe("filterEnv", () => {
  const config = makeConfig();
  let savedToken: string | undefined;

  beforeEach(() => {
    savedToken = process.env.BRIDGE_TOKEN;
    process.env.BRIDGE_TOKEN = "super-secret";
  });

  afterEach(() => {
    if (savedToken === undefined) {
      delete process.env.BRIDGE_TOKEN;
    } else {
      process.env.BRIDGE_TOKEN = savedToken;
    }
  });

  it("strips the bridge token from the child environment", () => {
    const env = filterEnv(config, undefined);
    expect(env.BRIDGE_TOKEN).toBeUndefined();
  });

  it("applies allowlisted request env vars and ignores the rest", () => {
    const env = filterEnv(config, {
      ANTHROPIC_API_KEY: "key-123",
      SHOULD_BE_IGNORED: "nope"
    });
    expect(env.ANTHROPIC_API_KEY).toBe("key-123");
    expect(env.SHOULD_BE_IGNORED).toBeUndefined();
  });
});
