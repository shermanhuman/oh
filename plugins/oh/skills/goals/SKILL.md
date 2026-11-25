---
name: goals
description: How an agent carries a goal in the user's setup — the Herdr tab labels that mark its goal and phase (the keep-going Stop hook reads them), how to ask the user for a step only they can do (push back first, then a task with exact links and commands), and the spend command. Use when starting, planning, building or finishing a goal, when you need the user to do something, or when asked what a goal has cost.
---

# Goals

A goal is one piece of work carried by one agent from intent to done (forge's DESIGN.md). `compound-v:plan` says how the intent conversation, the plan and the build run. This skill covers the user's machinery around them.

## Labels and phases

In a Herdr tab, `HC_TERMINAL_ID` names your terminal. Mark the goal on it (`hc` lives in `~/.local/bin`, which some shells, Codex's among them, leave off `PATH`):

| When | Run |
|---|---|
| The goal starts (before the intent conversation), or you resume it in a new session | `~/.local/bin/hc label $HC_TERMINAL_ID goal=<slug> goal.phase=intent goal.type=<Patch\|Change\|Feature\|Product> goal.owner=${CLAUDE_CODE_SESSION_ID:-$CODEX_THREAD_ID}` (`build` instead of `intent` for a bug or upkeep; on resume, keep the phase it was in). Sugarhouse's ETA comes from past goals of the same type |
| You open a PR for the goal | `~/.local/bin/hc label $HC_TERMINAL_ID goal.prs="<existing urls> <new url>"` (space-separated). Sugarhouse records it and tells this tab once when it merges |
| The user says to start planning | `~/.local/bin/hc label $HC_TERMINAL_ID goal.phase=plan` |
| Building starts: the plan is approved, or it needs no approval (a bug, upkeep, a patch) | `~/.local/bin/hc label $HC_TERMINAL_ID goal.phase=build` |
| No step of the goal can move until the user acts: every remaining step waits on a task for them (see *Tasks for the user*), a packet waiting for their answers, or a question that has to wait for them. While another step can move, keep working on it instead | `~/.local/bin/hc label $HC_TERMINAL_ID blocked=<link to the Sugarhouse item>`; while Sugarhouse is down, `blocked=local:<path of the local page>`, replaced by the item's link once it's back |
| The user has done it or answered | `~/.local/bin/hc label $HC_TERMINAL_ID blocked=` |
| The user asks you to pause | `~/.local/bin/hc label $HC_TERMINAL_ID goal.phase=paused` |
| The goal is done: merged, installed, cleaned up | `~/.local/bin/hc label $HC_TERMINAL_ID goal.phase=done` |

`<slug>` is short and stable (`rules-release`, `sugarhouse`): letters, digits, `.`, `_` and `-`, starting with a letter or digit, 64 characters at most. The hook ignores a tab whose slug doesn't fit. Outside Herdr (no `HC_TERMINAL_ID`), skip the labels.

**In the build phase, don't end a turn announcing a next step you could take now: take it.** oh's keep-going Stop hook backs this up. If the session that owns the goal ends a turn in build, with nothing blocked and no background work or scheduled wake-up pending, it sends it back once for that turn. It never pushes reviewers or other sessions. In the intent, plan and build phases it also nudges once when the turn ends on a question to the user in the chat: post it on the board, unless compound-v's *Answer where the user engages* keeps it in the tab. Answering the user's question in build is fine: answer, then carry on. The user can turn the hook off with `touch ~/.local/state/oh/keep-going.off`.

## Tasks for the user

Push back on yourself first and write the task as `compound-v:interrogate`'s *Tasks for the human* says. Post it to Sugarhouse as an item of kind `task` (`sugar post`; `sugar schema` shows `task.reason_human`, `tried`, `steps` and `check`), not on the issue. **A step waiting on the user doesn't stop the goal:**
- **Keep working on what can move:** the goal's other steps, and the waiting step as far as it goes locally (local commits, a drafted PR description, everything staged), so the user's part takes seconds. Set no label while another step can move.
- **Set `blocked` only when no step can move,** and only after that preparation.

When the user presses Done, your tab is told; run your check before carrying on, and if it failed, reopen the item with what failed (`~/.local/share/mise/shims/sugar reopen <id> --note "<what failed>"`). Unless it's a step the rules reserve for the user, each task is also a rough edge of kind `manual-step` (`oh:rough-edges`), so recurring ones get automated; Sugarhouse's weekly view lists the most frequent ones.

## Spend

`python3 -I <this skill's folder>/scripts/spend.py --goal <slug>` prints the goal's Claude spend at list API prices, from the sessions the keep-going hook logged on this machine (reviewers and child sessions included), plus Codex tokens and what the hook's pushes cost. It's for reporting; there are no budgets until there's history to set them from. Sugarhouse shows it per goal, summed over both machines; put the figure in the goal's review packet too.
