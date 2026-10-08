# French Learning Hub: one personal-use image containing the Go service and the
# built workbench. Base images are pinned by version and digest (see
# docs/RELEASE.md). No configuration, .env file, credential or database is
# copied in; runtime settings are passed explicitly by compose.yaml.

# --- Workbench: locked install and production build ---------------------------
FROM node:24.11.1-alpine3.22@sha256:2867d550cf9d8bb50059a0fff528741f11a84d985c732e60e19e8e75c7239c43 AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- Server: verified modules, static binary ----------------------------------
FROM golang:1.26.5-alpine@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2 AS server
WORKDIR /src
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOFLAGS=-mod=readonly
COPY go.mod go.sum ./
RUN go mod download && go mod verify
COPY cmd ./cmd
COPY internal ./internal
COPY migrations ./migrations
RUN go build -trimpath -ldflags="-s -w" -o /out/server ./cmd/server

# --- Runtime -------------------------------------------------------------------
FROM alpine:3.22.2@sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412
RUN addgroup -S -g 1000 flh \
 && adduser -S -D -H -u 1000 -G flh flh \
 && mkdir -p /data \
 && chown 1000:1000 /data
COPY --from=server /out/server /app/server
COPY --from=web /src/web/dist /app/web
# The working directory holds no .env, so configuration comes only from the
# container environment.
WORKDIR /app
ENV PORT=8080 DB_PATH=/data/app.db
USER 1000:1000
EXPOSE 8080
# Readiness, not liveness: /readyz pings SQLite with a 2 s bound.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --start-interval=1s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/readyz || exit 1
ENTRYPOINT ["/app/server", "-web-dir", "/app/web"]
