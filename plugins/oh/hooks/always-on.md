Oh (Sherman's working agreements) is installed. In every session:

**Mise first.** Install and run CLI tools through mise (`mise which`, `mise use`, `mise exec --`), never `apt`, `brew`, `npm install -g`, `go install` or `pip install` for tools mise provides. GitHub always goes through `mise exec -- gh`. Details: `oh:mise`.

**Pull requests.** A PR is a release: one per repository (push to your open one), built in a separate worktree, tested the way CI does, reviewed with `compound-v:review-loop` and every round posted on it. It stays a draft until the user could merge it right now, and keeping it mergeable and green is yours. Bump the version last (`oh:release`). After a merge, clean up its branches and worktrees, close what it finished, and update plugin installs everywhere. The procedure is in `oh:pull-requests`.

**Production guard.** Merging a PR, pushing to a default branch, force-pushing, pushing every branch and deleting a repository are the user's: hand them the exact command. These production actions wait for their yes: deletes, drains, cordons, scaling to zero, `helm uninstall`, and destructive SQL on a database that isn't local. Never rebase a PR branch, never route around a refusal, and never loosen a grant, role or allowlist to get past a block. A guard hook enforces this for shell commands; the rule also covers interpreter code, MCP tools and port-forwarded databases. The release routine (rollout restarts, Argo refreshes, migration Jobs, deploy scripts) isn't guarded.

**Secrets.** In a repository with `.waxseal/`, every secret change is one visible waxseal command (`oh:waxseal`): no `kubeseal`, hand-written `encryptedData` or Secret Manager access another way; if waxseal can't do it, ask the user. Never print a file that holds secrets, even filtered, by any tool (shell, the Read tool, code); pass secrets by path or environment variable.

**Processes.** Other sessions share the machine: kill one process you started per command (`kill <pid>`), never by name or pattern. A guard hook refuses pattern kills and printing secret files in shell commands.

**No silent failures.** Never ship a change that makes something fail silently for some users; when a fix removes a fallback, find out who relied on it.

**Questions.** Bookend the user's attention: one packet after planning, one after reviews. A question that comes up in between waits on the work's issue for the next packet, unless it blocks the work. A packet is one web page (`compound-v:interrogate`) on the packet server in `~/github/factory-packets` (the `factory-packets` user service; `serve.py`): give its link by machine name (`http://<machine>:7879/<packet>/`) so it opens from any tailnet device, and don't launch a browser. Where that folder is missing, a local HTML file, answers in chat; never a claude.ai artifact. In packets, show numbers as charts and an HTML table whose columns say what they measure. Every decision ends with More discussion; walkthroughs (release reviews, PR summaries) work the same way. A request to act on a website carries the direct link, IDs filled in.

**Rough edges.** When the user corrects you, picks More discussion, overrides a recommendation for a reason research could have found, or does by hand what a rule should have covered; when a follow-up packet asks what the first could have; when a skill misfires, a problem escapes review or work gets stuck: log it as `oh:rough-edges` describes.

**Reviewers.** In Claude Code, reviewer and plan-review subagents run on `fable` at high effort. The second voice, and any "Astra" review, is Astra high through Codex (command in `oh:pull-requests`); in a Codex session it's Claude Fable.
