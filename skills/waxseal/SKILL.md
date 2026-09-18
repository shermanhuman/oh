---
name: waxseal
description: WaxSeal 0.5+ SealedSecrets management — adding keys, setting values, rotating, resealing and health checks, with Google Secret Manager as the source of truth. Use in GitOps repositories that have a .waxseal/ directory.
---

# waxseal

Read [the focused guide](references/guide.md) when this integration is part of the current task. Use only the sections relevant to the operation being performed.

Confirm the installed version first: `waxseal --version`. This guide describes **0.5.x**, a ground-up rewrite with a new command tree and no aliases for the old names (`addkey`, `updatekey`, `retirekey`, `edit`, `meta`, `advanced` are gone). On-disk formats are unchanged, so an existing repository works with either version, but the commands do not.

Every command can be driven entirely by flags. On a terminal, waxseal prompts for whatever is left out; with `--no-input` (or in CI) it fails instead, naming the missing flag. Secret values are never taken from the command line: use `--from-file PATH`, `--from-file -` for stdin, or `--generate`.

Preserve the user's requested scope: resealing or checking does not authorize rotating or retiring; adding one key does not authorize touching others. `-y` accepts confirmations, it does not grant authorization. Never print, log or echo a secret value, including in error reports.
