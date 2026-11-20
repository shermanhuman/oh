---
name: rough-edges
description: Logs a rough edge on the user's improvement log. Use when the user corrects the agent or picks More discussion on a packet, when a follow-up packet asks what the first could have, when the user overrides a recommendation for a reason research could have found or does by hand what a skill or rule should have covered, when a skill runs when it shouldn't or doesn't when it should, when a problem reaches staging, a release or production that a review should have caught, or when work stops after failed rounds.
---

# Rough edges

Each rough edge is one comment on the private log [Applesauce-Labs/forge#8](https://github.com/Applesauce-Labs/forge/issues/8), which holds the full definitions. Log it when it happens, not at the end of the session.

First line, exactly: `rough-edge: <skill or rule> · <kind> · <link>`, where the link points to the plan, PR, issue or session concerned. Then a line or two on what was missing or went wrong.

Kinds:
- `more-discussion`: a decision packet didn't give the user enough to decide.
- `foreseeable-follow-up`: a follow-up packet asked something the first one could have.
- `override-knowable`: the user overrode a recommendation for a reason research could have found.
- `correction`: the user corrected you.
- `manual-step`: the user did by hand what a skill or rule should have covered.
- `missed-trigger`: a skill didn't run when it should have, or ran when it shouldn't.
- `escape`: a problem reached staging, a release or production that a review or check should have caught.
- `stuck`: work stopped after failed rounds.
- `other`.

Steps the rules reserve for the user (merging, signing in, guarded production actions) aren't rough edges. If you can't post, as in a read-only sandbox, put the line in your final message for the caller to post.
