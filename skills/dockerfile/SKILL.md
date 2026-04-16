---
name: dockerfile
description: Docker best practices for multi-stage Alpine builds — security patches, image pinning, and layer optimization. Use when creating, reviewing, or updating Dockerfiles.
---

# Dockerfile — Alpine Multi-Stage Builds

## Base Image Pinning

There are two valid strategies. We use **Option A** because we don't run Renovate/Dependabot and the `apk upgrade` pattern covers the security gap.

### Option A: Pin minor, float patch _(our default)_

```dockerfile
ARG RUNNER_IMAGE="alpine:3.21"
```

Combined with `apk upgrade --no-cache` in the runtime stage, this automatically picks up security patches without manual digest tracking.

### Option B: Pin exact + automation _(industry standard for larger teams)_

```dockerfile
# Pin exact tag or SHA digest for full reproducibility
ARG RUNNER_IMAGE="alpine:3.21.6"
# Or even stricter:
ARG RUNNER_IMAGE="alpine@sha256:a8560b36..."
```

Requires Renovate or Dependabot to automatically open PRs when new versions are released. Best for teams that need deterministic builds and have the automation to stay patched.

### What to avoid

```dockerfile
# ❌ Floating major — surprise breaking changes
ARG RUNNER_IMAGE="alpine:latest"
```

### Builder images

For compound images (e.g. Elixir + Erlang + Alpine), pin the toolchain versions:

```dockerfile
ARG ELIXIR_VERSION=1.15.7
ARG OTP_VERSION=26.2.1
ARG BUILDER_IMAGE="hexpm/elixir:${ELIXIR_VERSION}-erlang-${OTP_VERSION}-alpine-3.21"
```

## Security Patches

Always add `apk upgrade --no-cache` early in the **runtime stage**. This pulls security patches even when Docker Hub hasn't rebuilt the base image tag yet.

```dockerfile
FROM ${RUNNER_IMAGE}
RUN apk upgrade --no-cache && apk add --no-cache libstdc++ openssl ncurses-libs
```

The `--no-cache` flag tells `apk` not to store the package index in the image layer. This is an `apk` flag, not a Docker flag — it keeps the image small.

### Why both floating tag + apk upgrade?

| Mechanism | What it catches | Limitation |
|-----------|----------------|------------|
| Floating tag (`alpine:3.21`) | New patch images when Docker Hub rebuilds | Docker Hub can lag hours/days behind Alpine releases |
| `apk upgrade --no-cache` | Package-level patches from Alpine repos | Requires network at build time |

Together they cover the gap.

### Reproducibility trade-off

`apk upgrade` means building the same Dockerfile two weeks apart may pull different package versions. We accept this because:

1. Trivy scans in CI catch regressions — a build with a vulnerable package won't pass the security check
2. Our images are rebuilt on every merge to main, not cached for weeks
3. The alternative (manual digest tracking) requires automation we don't run

If you need deterministic builds, pin exact versions with Option B and remove `apk upgrade`.

## .dockerignore

Every project with a Dockerfile should have a `.dockerignore`. This prevents context bloat, speeds up builds, and avoids leaking secrets.

```
.git
.gitignore
_build
deps
node_modules
.elixir_ls
.env*
*.md
.dockerignore
Dockerfile
.github
.promptherder
```

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

# Security patches + runtime dependencies (single layer)
RUN apk upgrade --no-cache && apk add --no-cache libstdc++ openssl ncurses-libs

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
- **Single RUN for related operations.** Merge `apk upgrade` + `apk add` into one layer.

## CI / GitHub Actions

Use `docker/build-push-action` with GHA cache. Do **not** use `--no-cache` on the Docker build — it kills layer caching and turns 2-minute builds into 8-minute builds.

```yaml
- uses: docker/build-push-action@v5
  with:
    context: .
    pull: true          # Check for fresh base image manifest (~5s)
    push: true
    tags: ${{ env.IMAGE }}:latest
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

| Flag | What it does | Use it? |
|------|-------------|---------|
| `pull: true` | Re-checks the base image tag for updates | ✅ Yes — ~5s cost, ensures fresh base |
| `no-cache: true` | Rebuilds every layer from scratch | ❌ No — kills GHA cache, slow |

The `apk upgrade` in the Dockerfile handles package-level patches. The `pull` flag handles base image freshness. The GHA cache keeps builds fast.
