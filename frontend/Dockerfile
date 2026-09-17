# syntax=docker/dockerfile:1.7
# Next.js standalone output (frontend/next.config.mjs sets output: "standalone").
# Build stage installs all deps + builds; runtime stage is Alpine with only the
# Node binary (no npm/yarn/corepack) plus the standalone server + static assets.

FROM node:26-alpine3.24 AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts

FROM node:26-alpine3.24 AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build

# alpine:3.24 matches node:26-alpine3.24 (musl). Runtime is the Node
# interpreter only — no npm/yarn/corepack from the Node image.
FROM alpine:3.24 AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080 \
    HOSTNAME=0.0.0.0
RUN apk add --no-cache libstdc++ \
    && addgroup -S -g 1001 nextjs \
    && adduser -S -u 1001 -G nextjs nextjs
COPY --from=build /usr/local/bin/node /usr/local/bin/node
COPY --from=build --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nextjs /app/.next/static ./.next/static
USER nextjs
EXPOSE 8080
CMD ["node", "server.js"]
