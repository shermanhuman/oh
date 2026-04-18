---
trigger: always_on
---

# Mise-First Policy

This environment uses [mise](https://mise.jdx.dev) to manage CLI tools and runtimes. Never install **tools** via `apt`, `brew`, `npm install -g`, `go install`, or `pip install` without checking mise first. This does not apply to per-project dependencies (e.g., `pip install` into a venv or `npm install` for project packages).

## Rules

- **MCP first, CLI second:** If an MCP server exists for a tool (e.g., `kubernetes-mcp-server` for kubectl, `argocd-mcp` for argocd, `postgres-mcp` for psql), use the MCP tools instead of shelling out. Fall back to `mise exec -- <command>` only when MCP doesn't cover the operation.
- **Check before installing:** Run `mise which <tool>` or `mise ls` to see if a tool is already available.
- **Install via mise:** Use `mise use <tool>@<version>` to add tools. Use `mise use --global` for user-wide tools.
- **Run mise-managed tools:** If mise is not activated in the shell (common in non-interactive/agent contexts), use `mise exec -- <command>` to run tools. Example: `mise exec -- gh pr create`.
- **Never bypass mise:** Do not `apt install`, `brew install`, `npm install -g`, `go install`, or `pip install` tools that mise manages. This avoids version conflicts and ensures reproducibility.
