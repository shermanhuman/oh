---
name: mise
description: >
  Mise dev tool manager — installing tools, running mise-managed commands,
  and configuring .mise.toml. Use when installing tools, running CLI commands
  that aren't found, or setting up project environments.
---

# Mise

[mise](https://mise.jdx.dev) manages all dev tools and runtimes. It replaces nvm, pyenv, goenv, and manual binary installs.

## Key problem: shell activation

In non-interactive shells (CI, agent contexts, subprocesses), mise shims may not be on `$PATH`. If a command fails with "not found" and the tool is mise-managed, use:

```bash
mise exec -- <command> [args...]
```

This is the single most common agent mistake. Always try `mise exec --` before concluding a tool is missing.

## Common commands

### Discovery

```bash
mise which gh              # Check if gh is managed by mise
mise ls                    # List all installed tools + versions
mise ls --current          # Show tools active in current directory
```

### Installing tools

```bash
mise use go@1.24           # Add to local .mise.toml (project-scoped)
mise use --global gh@latest # Add globally (~/.config/mise/config.toml)
mise install               # Install all tools from .mise.toml
```

### Running tools

```bash
mise exec -- gh pr create          # Run gh via mise
mise exec -- kubectl get pods      # Run kubectl via mise
mise exec node@22 -- node -v       # Run with a specific version override
```

### Tasks (project scripts)

```bash
mise run test              # Run a task defined in .mise.toml
mise run build             # Tasks replace Makefiles / npm scripts
```

## Configuration: .mise.toml

```toml
[tools]
node = "22"
go = "1.24"
python = "3.12"

[env]
DATABASE_URL = "postgres://localhost/myapp_dev"

[tasks.test]
run = "go test ./..."

[tasks.dev]
run = "npm run dev"
```

- **Project-scoped:** `.mise.toml` in repo root — committed to git
- **Local overrides:** `.mise.local.toml` — gitignored, for machine-specific settings
- **Global:** `~/.config/mise/config.toml` — user-wide defaults

## Decision tree: "I need to interact with X"

1. **Is there an MCP server for it?** Check connected MCP servers (e.g., `kubernetes-mcp-server` for k8s, `argocd-mcp` for Argo CD, `postgres-mcp` for databases)
2. **Yes →** Use MCP tools. They're cheaper (no shell overhead) and purpose-built.
3. **No →** Run `mise which <tool>` — is the CLI mise-managed?
4. **Yes →** Run with `mise exec -- <tool> [args]`
5. **Not installed →** `mise use --global <tool>@latest`, then retry
6. **Not in mise registry →** Only then consider `apt`, `brew`, or direct download

## MCP servers managed by mise

These MCP servers are typically installed via mise and should be preferred over their CLI equivalents:

| MCP Server | Replaces CLI | Purpose |
|------------|-------------|---------|
| `kubernetes-mcp-server` | `kubectl` | Kubernetes resource management |
| `argocd-mcp` | `argocd` | Argo CD application management |
| `postgres-mcp` | `psql` | PostgreSQL queries and management |
| `@playwright/mcp` | `playwright` | Browser automation and testing |

## Common tools managed by mise

These tools are typically mise-managed in this environment. Always check before installing separately:

| Tool | Mise key | Purpose |
|------|----------|---------|
| `gh` | `gh` | GitHub CLI |
| `kubectl` | `kubectl` | Kubernetes CLI |
| `kubeseal` | `kubeseal` | SealedSecrets CLI |
| `gcloud` | `gcloud` | Google Cloud SDK |
| `node` | `node` | Node.js runtime |
| `go` | `go` | Go runtime |
| `python` | `python` | Python runtime |
| `argocd` | `argocd` | Argo CD CLI |
| `semgrep` | `semgrep` | Static analysis |
