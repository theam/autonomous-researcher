# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS dependencies

RUN corepack enable && corepack prepare pnpm@11.16.0 --activate
WORKDIR /repo/apps/web

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
RUN --mount=type=secret,id=node_auth_token,required=true \
    token="$(cat /run/secrets/node_auth_token)" \
    && printf '%s\n' \
      '@theam:registry=https://npm.pkg.github.com' \
      "//npm.pkg.github.com/:_authToken=${token}" \
      'always-auth=true' > /tmp/limina-npmrc \
    && NPM_CONFIG_USERCONFIG=/tmp/limina-npmrc pnpm install --frozen-lockfile \
    && rm -f /tmp/limina-npmrc

FROM dependencies AS builder

COPY . .
ENV CI=1 \
    NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:22-alpine AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=127.0.0.1 \
    PORT=3000
WORKDIR /app/apps/web

RUN addgroup --system --gid 10001 limina \
    && adduser --system --uid 10001 --ingroup limina limina

COPY --from=builder --chown=limina:limina /repo/apps/web/.next/standalone /app
COPY --from=builder --chown=limina:limina /repo/apps/web/.next/static /app/apps/web/.next/static
COPY --from=builder --chown=limina:limina /repo/apps/web/public /app/apps/web/public

USER limina
EXPOSE 3000
CMD ["node", "server.js"]
