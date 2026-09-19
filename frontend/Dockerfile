# Vite SPA built inside the pnpm workspace, served by nginx with /api proxied
# to the backend so the browser never makes a cross-origin request.
#
# The build stage is pinned to linux/amd64 because pnpm-workspace.yaml prunes
# every native binary except *-linux-x64-gnu (esbuild, rollup, lightningcss,
# @tailwindcss/oxide). Emulation costs only build time: the output is static
# assets, so the runtime stage below stays on the host architecture.
FROM --platform=linux/amd64 node:22-slim AS build

RUN corepack enable

WORKDIR /repo

# Workspace metadata first so the dependency layer caches independently of source.
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json ./
COPY frontend/package.json ./frontend/
COPY lib/api-client-react/package.json ./lib/api-client-react/
COPY lib/api-spec/package.json ./lib/api-spec/
COPY lib/api-zod/package.json ./lib/api-zod/
COPY lib/db/package.json ./lib/db/
COPY scripts/package.json ./scripts/

RUN pnpm install --frozen-lockfile --filter '@tracekite/web...'

COPY tsconfig.base.json ./
COPY lib ./lib
COPY frontend ./frontend

# Same-origin API: nginx proxies /api, so no base URL is baked into the bundle.
ENV NODE_ENV=production
RUN pnpm --filter '@tracekite/web' build


FROM nginx:1.29-alpine AS runtime

COPY --from=build /repo/frontend/dist/public /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# 127.0.0.1 explicitly: busybox wget resolves `localhost` to ::1 first and
# nginx only listens on 0.0.0.0:80, so the check refused forever.
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=10s \
    CMD wget -q -O /dev/null http://127.0.0.1/index.html || exit 1
