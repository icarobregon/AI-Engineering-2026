# =============================================================================
# Stage 1 — dependencies
# =============================================================================
# Manifests are copied before the source so this layer is only rebuilt when the
# dependency set actually changes, not on every edit to a component.
#
# `node-linker=hoisted` turns pnpm's symlink farm into a real directory tree,
# which is what makes the runtime stage able to COPY the Prisma CLI out of it.
FROM node:22-slim AS deps
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile --config.node-linker=hoisted


# =============================================================================
# Stage 2 — build
# =============================================================================
FROM node:22-slim AS builder
RUN corepack enable
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# `pnpm build` is `prisma generate && next build`: the client is generated from
# the schema at build time, so the runtime image never needs the generator.
RUN pnpm build


# =============================================================================
# Stage 3 — runtime
# =============================================================================
# Next's standalone output carries only the traced dependencies, so this image
# does not ship node_modules — except the Prisma CLI, which the container needs
# to apply migrations before serving.
FROM node:22-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Never run a container as root.
RUN groupadd --system app && useradd --system --gid app --create-home app

COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static
COPY --from=builder --chown=app:app /app/public ./public

USER app

EXPOSE 3000

# Hits the app's own liveness route, which does NOT call the AI service: a
# healthcheck that depended on a downstream hiccup would get this container
# restarted every time something else sneezed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]

# Serving only. Migrations run in their own one-shot container off the `builder`
# stage (see docker-compose.yml): shipping the Prisma CLI here would add 250 MB
# and 136 packages — Studio and its d3/radix tree included — to an image whose
# whole point is to carry just what it needs to serve.
CMD ["node", "server.js"]
