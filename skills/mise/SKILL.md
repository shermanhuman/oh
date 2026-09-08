---
name: mise
description: Discover and run mise-managed tools or configure a requested project toolchain.
---

# Mise

Inspect the project's `mise.toml`, `.mise.toml`, lock/config files, and existing commands. If mise manages the tool and shell activation is absent, run `mise exec -- <command>`. `mise which <tool>` and `mise ls --current` help identify active tools. If mise itself is unavailable, use the project's documented equivalent or report the missing prerequisite; do not loop on a missing command.

Choose a version consistent with project pins and the requested task. `mise use <tool>@<version>` changes project configuration; use it when that change is intended. `mise install` installs configured tools. `mise use --global` alters user-wide configuration and is not a default recovery step for a missing local command. Project dependencies still use their normal package manager.

For an operation, use an available connected tool or CLI according to coverage, authorization, and user/host preferences. MCP is not universally cheaper and GitHub operations do not always require shelling out. When the chosen CLI is mise-managed, run it through mise. Consult [official mise documentation](https://mise.jdx.dev/) for version-sensitive syntax.
