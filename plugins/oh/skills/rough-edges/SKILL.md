---
name: rough-edges
description: Logs a rough edge on the user's improvement log. Use when the user corrects the agent or picks More discussion on a packet, when a follow-up packet asks what the first could have, when the user overrides a recommendation for a reason research could have found or does by hand what a skill or rule should have covered, when a skill runs when it shouldn't or doesn't when it should, when a problem reaches staging, a release or production that a review should have caught, or when work stops after failed rounds.
---

# Rough edges

First line, exactly: `rough-edge: <skill or rule> · <kind> · <link>`, where the link points to the plan, PR, issue or session concerned; then a line or two on what was missing or went wrong. The kinds are compound-v's (`compound-v:interrogate`, references/rough-edges.md). On this machine, each rough edge is one comment on the private log [Applesauce-Labs/forge#8](https://github.com/Applesauce-Labs/forge/issues/8), which holds the full definitions: `mise exec -- gh issue comment 8 -R Applesauce-Labs/forge --body-file <file>`. Log it when it happens, not at the end of the session.

If you can't post a rough edge, as in a read-only sandbox, put the line in your final message for the caller to post.

Don't log a Sugarhouse item the user marks "not useful to ask": the board records those marks, and the user reviews them in its weekly view.
