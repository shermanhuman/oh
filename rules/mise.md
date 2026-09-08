---
activation: always
---

# Mise-First Policy

Mise is this repository's preferred CLI tool/runtime manager. Check `mise which <tool>` or `mise ls` before installing tools. Never use `apt`, `brew`, `npm install -g`, `go install`, or `pip install` for tools mise provides. Per-project dependencies (`npm install`, pip into a venv) are exempt.

- **Install through mise:** `mise install` for configured tools; `mise use <tool>@<version>` to add project tools. Use `--global` only for intended user-wide installs. Preserve project pins.
- **Run through mise:** When shell activation is unavailable, use `mise exec -- <command>`.
- **GitHub always uses `mise exec -- gh <command>`**, including PR creation and viewing. This takes precedence over MCP preference. Never use a browser for operations `gh` supports.
- **Other operations: MCP first, CLI second.** Use a connected MCP when it covers the operation (e.g., Kubernetes, Argo CD, PostgreSQL); otherwise use the CLI through mise.
- **Fallback only if mise cannot provide the tool:** use an existing installation or documented alternative and explain why. Do not introduce a competing manager or upgrade pins merely to run a command.
