---
activation: always
---
# Tooling

Respect the target project's toolchain pins. When mise is configured or the tool is mise-managed, use its environment (`mise exec -- <command>` if shell activation is unavailable). Check existing tools and project configuration before installing anything. Prefer project-scoped pinned tools; a project task does not imply permission to alter global tools or upgrade runtime versions.

Use a connected API/MCP tool when it supports the operation and matches the task's account and permissions. Otherwise use the appropriate CLI; for GitHub prefer `gh` over browser automation when it covers the operation. This preference does not override explicit user or host tool instructions. Neither MCP nor mise grants authorization for the operation itself.
