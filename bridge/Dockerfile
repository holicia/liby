# syntax=docker/dockerfile:1

# --- build stage: compile TypeScript -> dist ---
FROM node:20-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# --- runtime stage: agent CLIs + bridge server ---
FROM node:20-bookworm-slim AS runtime
ENV NODE_ENV=production
# Bind to all interfaces so the published port is reachable from the host.
ENV HOST=0.0.0.0
WORKDIR /app

# Tools the coding agents commonly rely on at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Locally runnable Claude Code + Codex CLIs.
RUN npm install -g @anthropic-ai/claude-code @openai/codex \
    && npm cache clean --force

# Production dependencies only.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=build /app/dist ./dist

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Persistent dir for the monthly usage ledger; owned by node so the unprivileged
# process can write it. A named volume mounted here inherits this ownership.
RUN mkdir -p /data && chown node:node /data

# Run as the unprivileged `node` user shipped in the base image: Claude Code
# refuses --dangerously-skip-permissions under root, and non-root is safer for
# an agent that executes arbitrary tool calls. HOME is where the CLIs read/write
# their credentials and state.
ENV HOME=/home/node
USER node

EXPOSE 8787
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["node", "dist/server.js"]
