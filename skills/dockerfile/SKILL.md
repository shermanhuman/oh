---
name: dockerfile
description: Review or build project Dockerfiles with correct toolchain compatibility, cache freshness, and runtime boundaries.
---

# Docker builds

Inspect the existing build and deployment conventions before choosing base images. Preserve project runtime pins and verify that a requested compound image tag exists and that builder/runtime libc and library versions are compatible. Do not copy historical sample versions as current recommendations.

A digest pins image content; a tag alone can move. Package installation during the build can still vary even with a pinned base. Choose the project's intended reproducibility/patching tradeoff and verify its actual update automation rather than assuming scanners or scheduled rebuilds exist.

`apk upgrade --no-cache` updates packages **when the RUN layer executes**. Docker can reuse that layer even after repositories publish fixes. `--pull` refreshes the base image, but an unchanged base does not force a cached package layer to rerun. For a patch refresh, invalidate the relevant stage or use a deliberate uncached rebuild. Keep ordinary builds cached when freshness is not the task. [Docker cache behavior](https://docs.docker.com/build/cache/invalidation/).

For multi-stage releases, keep build tools out of the runtime image where practical and run the application as a non-root user when supported. Set the production build environment explicitly (for example `MIX_ENV=prod`) before fetching/compiling release dependencies. Match runtime libraries to the built release. Check the resulting image and application startup, not just Dockerfile syntax.

Keep `.dockerignore` specific to the project. Exclude secrets and unnecessary build context, but do not blanket-ignore `*.md` or other files that package tooling, `COPY`, or compile-time documentation reads require. Publishing images or deploying them remains a separately scoped action.
