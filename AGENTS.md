# oh

Six Claude Code and Codex plugins under `plugins/`: `oh` (working agreements, always-on hook) and the stack and API plugins `oh-phoenix`, `oh-tekmetric`, `oh-telnyx`, `oh-postmark`, `oh-groq`. They are listed in the Compound V marketplace (`shermanhuman/compound-v`); this repository has no marketplace of its own, so nobody installs the same plugin twice.

- **Merging is the user's step.** Don't merge or squash-merge a PR and don't push to the default branch, because each merge starts a release. Creating branches, pushing feature branches and creating PRs are fine. Merge the default branch into your feature branch when it moves; don't rebase or force-push, so commit SHAs already posted on the PR stay valid.
- **Pull requests start as drafts.** Open the draft (`mise exec -- gh pr create --draft`) before the review loop, as the `pull-requests` skill says; post each round on it as it lands; mark it ready (`mise exec -- gh pr ready`) only after the loop's final round passes with no must-fix findings. A plugin's version bump still lands last, so Version Bump Check stays red on the draft until then.
- Every PR bumps `version` in each changed plugin's `.claude-plugin/plugin.json` (CI checks each one). Without a bump, installed copies never update.
- After editing `plugins/oh/hooks/always-on.md`, run `python3 scripts/build-hooks.py` and commit the regenerated `session-start.json` (CI checks they match).
- Before a PR: `claude plugin validate plugins/<name>` for each changed plugin and `python3 scripts/build-hooks.py --check`. To try a plugin locally without installing it: `claude --plugin-dir plugins/<name>`.
