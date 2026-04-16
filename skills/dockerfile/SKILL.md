---
name: dockerfile
description: Docker best practices for multi-stage Alpine builds — security patches, image pinning, and layer optimization. Use when creating, reviewing, or updating Dockerfiles.
---

# Dockerfile — Alpine Multi-Stage Builds

## Base Image Pinning

Pin to **minor**, float **patch**. This gets automatic security patches without surprise breaking changes.

```dockerfile
# ✅ Pin minor, float patch
ARG RUNNER_IMAGE="alpine:3.21"

# ❌ Pin to exact patch — misses security updates
ARG RUNNER_IMAGE="alpine:3.21.6"

# ❌ Floating major — surprise breaking changes
ARG RUNNER_IMAGE="alpine:latest"
```

For builder images with compound versions (e.g. Elixir + Erlang + Alpine), pin the toolchain versions but float the Alpine patch:

```dockerfile
ARG ELIXIR_VERSION=1.15.7
ARG OTP_VERSION=26.2.1
ARG BUILDER_IMAGE="hexpm/elixir:${ELIXIR_VERSION}-erlang-${OTP_VERSION}-alpine-3.21"
```

## Security Patches

Always add `apk upgrade --no-cache` early in the **runtime stage**. This pulls security patches even when Docker Hub hasn't rebuilt the base image tag yet.

```dockerfile
FROM ${RUNNER_IMAGE}
RUN apk upgrade --no-cache
```

The `--no-cache` flag tells `apk` not to store the package index in the image layer. This is an `apk` flag, not a Docker flag — it keeps the image small.

### Why both?

| Mechanism | What it catches | Limitation |
|-----------|----------------|------------|
| Floating tag (`alpine:3.21`) | New patch images when Docker Hub rebuilds | Docker Hub can lag hours/days behind Alpine releases |
| `apk upgrade --no-cache` | Package-level patches from Alpine repos | Requires network at build time |

Together they cover the gap.

## Multi-Stage Structure

```dockerfile
# =============================================================================
# Build Stage
# =============================================================================
FROM ${BUILDER_IMAGE} AS builder

# Install build-only dependencies
RUN apk add --no-cache build-base git

WORKDIR /app
# Copy dependency files first for layer caching
COPY mix.exs mix.lock ./
RUN mix deps.get --only prod && mix deps.compile

# Copy app source and build release
COPY . .
RUN mix release

# =============================================================================
# Runtime Stage
# =============================================================================
FROM ${RUNNER_IMAGE}

# Security patches
RUN apk upgrade --no-cache

# Runtime dependencies only (no build tools)
RUN apk add --no-cache libstdc++ openssl ncurses-libs

# Non-root user
RUN addgroup -S appuser && adduser -S appuser -G appuser
USER appuser
WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app/_build/prod/rel/myapp ./

CMD ["bin/myapp", "start"]
```

## Key Rules

- **Never install build tools in the runtime stage.** `build-base`, `gcc`, `make` stay in the builder.
- **Use `--no-cache` on every `apk add` and `apk upgrade`.** No stale package indexes in the image.
- **Run as non-root.** Always `adduser` + `USER` in the runtime stage.
- **Order layers by change frequency.** Dependencies first (cached), source code last (changes often).

## CI / GitHub Actions

Use `docker/build-push-action` with GHA cache. Do **not** use `--no-cache` on the Docker build itself — it kills layer caching and makes builds slow.

```yaml
- uses: docker/build-push-action@v5
  with:
    context: .
    push: true
    tags: ${{ env.IMAGE }}:latest
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

The `apk upgrade` in the Dockerfile handles security patches. The GHA cache handles build speed. No conflict.
