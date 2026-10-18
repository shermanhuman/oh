---
name: waxseal
description: WaxSeal 0.6+ SealedSecrets management — adding keys, copying a value waxseal already stores into another secret or namespace, setting values, rotating, resealing and health checks, with Google Secret Manager as the source of truth. Use in GitOps repositories that have a .waxseal/ directory.
---

# waxseal

Read [the focused guide](references/guide.md) when this integration is part of the current task. Use only the sections relevant to the operation being performed.

Confirm the installed version first: `waxseal --version`, and use the version the repository pins (breakdown-infra pins it in `.mise.toml`; run `mise exec -- waxseal` when the shell isn't mise-activated). This guide describes **0.6.x**. 0.5 was a ground-up rewrite with a new command tree and no aliases for the old names (`addkey`, `updatekey`, `retirekey`, `edit`, `meta`, `advanced` are gone). 0.6 adds `--from-key` and records copies in metadata as `copiedFrom`, which 0.5 refuses to read, so a repository that has used `--from-key` needs 0.6 everywhere.

Every command can be driven entirely by flags. On a terminal, waxseal prompts for whatever is left out; with `--no-input` (or in CI) it fails instead, naming the missing flag. Secret values are never taken from the command line: use `--from-file PATH`, `--from-file -` for stdin, `--generate`, or `--from-key <secret>/<key>` to copy a value waxseal already stores.

Every change goes through waxseal, one visible command per call: no wrapper scripts, no `kubeseal`, no hand-edited `encryptedData`, and no reading or writing Secret Manager outside waxseal. oh's guard hook refuses `kubeseal`, `gcloud secrets` commands other than list/describe/get-iam-policy/versions list|describe/locations, and Secret Manager URLs given to curl or wget; it doesn't read scripts' code, so the rest is on you. To reuse a value waxseal already stores, for another namespace or under a new key name, copy it with `--from-key`; never read it out of Secret Manager to seal it again. When waxseal has no command for the job, stop and ask the user; that's a waxseal gap to file on shermanhuman/waxseal, not something to script around.

Preserve the user's requested scope: resealing or checking does not authorize rotating or retiring; adding one key does not authorize touching others. `-y` accepts confirmations, it does not grant authorization. Never print, log or echo a secret value, including in error reports.
