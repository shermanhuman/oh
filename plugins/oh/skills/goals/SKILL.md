---
name: goals
description: How an agent carries a goal in the user's setup — the Herdr tab labels that mark its goal and phase (the keep-going Stop hook reads them), how to ask the user for a step only they can do (push back first, then a task with exact links and commands), and the spend command. Use when starting, planning, building or finishing a goal, when you need the user to do something, or when asked what a goal has cost.
---

# Goals

A goal is one piece of work carried by one agent from intent to done (forge's DESIGN.md). `compound-v:plan` says how the intent conversation, the plan and the build run. This skill covers the user's machinery around them.

## Labels and phases

In a Herdr tab, `HC_TERMINAL_ID` names your terminal. Mark the goal on it:

| When | Run |
|---|---|
| The goal starts (before the intent conversation), or you resume it in a new session | `hc label $HC_TERMINAL_ID goal=<slug> goal.phase=intent goal.owner=${CLAUDE_CODE_SESSION_ID:-$CODEX_THREAD_ID}` (on resume, keep the phase it was in) |
| The user says to start planning | `hc label $HC_TERMINAL_ID goal.phase=plan` |
| Building starts: the plan is approved, or it needs no approval (a bug, upkeep, a patch) | `hc label $HC_TERMINAL_ID goal.phase=build` |
| Only the user can unblock you (see *Tasks for the user*) | `hc label $HC_TERMINAL_ID blocked=<link to the task>` |
| The user has done it | `hc label $HC_TERMINAL_ID blocked=` |
| The user asks you to pause | `hc label $HC_TERMINAL_ID goal.phase=paused` |
| The goal is done: merged, installed, cleaned up | `hc label $HC_TERMINAL_ID goal.phase=done` |

`<slug>` is short and stable (`rules-release`, `sugarhouse`), letters, digits, `.`, `_` and `-`. Outside Herdr (no `HC_TERMINAL_ID`), skip the labels.

**In the build phase, don't end a turn announcing a next step you could take now: take it.** oh's keep-going Stop hook backs this up. If the session that owns the goal ends a turn in build, with nothing blocked and no background work running, it sends it back once, until the user's next message. It never pushes reviewers or other sessions, and never in another phase. Answering the user's question in build is fine: answer, then carry on. The user can turn the hook off with `touch ~/.local/state/oh/keep-going.off`.

## Tasks for the user

Every task you hand the user spends their attention, the factory's scarcest resource. **Push back on yourself first:**
1. **Is there a way in?** A CLI through mise, an API, an MCP server, or a setting that makes the step unnecessary. Look before you ask.
2. **Is it really theirs?** Only for one of these reasons, which you name on the task:
   - it's one of the steps the always-on rules reserve for the user (merging, guarded production actions, signing in);
   - it needs their own sign-in, identity or second factor;
   - it spends money;
   - it's physical;
   - the service offers no way for an agent to do it.
3. **Make their part as small as it can be.** Prepare the exact command, the values to enter, and the link with every ID filled in.

Then post the task under a **Needs the user** heading on the goal's issue (until Sugarhouse takes these), set `blocked`, and stop. Use this shape:

```
### Sign in to Google Cloud for waxseal   ~1 min · unblocks <what>
**Why it's yours:** needs your sign-in (the credentials expired).
**Tried:** `waxseal key add …` → "application default credentials expired".

1. In a terminal on soulglow, run:
   `gcloud auth application-default login`
2. Approve in the browser window that opens, with your Google account.
   You should see: "You are now authenticated with the gcloud CLI!"

**I'll check it myself:** `waxseal key list` succeeds. Tell me "done".
```

Rules for the steps:
- Every link goes to the exact page, never "go to settings".
- Every command is ready to paste.
- Every step says what the user should see.

When they say done, run your check before carrying on, and say if it failed. Each task is also a rough edge of kind `manual-step` (`oh:rough-edges`), so recurring ones get automated.

## Spend

`python3 -I <this skill's folder>/scripts/spend.py --goal <slug>` prints the goal's Claude spend at list API prices, from the sessions the keep-going hook logged on this machine (reviewers and child sessions included), plus Codex tokens and what the hook's pushes cost. It's for reporting; there are no budgets until there's history to set them from. Put the figure in the goal's review packet.
