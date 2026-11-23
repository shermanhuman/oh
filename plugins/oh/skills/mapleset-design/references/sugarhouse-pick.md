# Picks on Sugarhouse

Loaded by `mapleset-design` when a UI pick goes to the user and `sugar` is on PATH. Otherwise the pick goes on a packet page, as the always-on *Questions* rule says.

Use this when `sugar` is on PATH. If any `sugar` command exits 3, the board is unreachable: use a packet page instead, and never read the failure as an answer.

1. Upload each option's two captures; each command prints a blob id:

   ```sh
   sugar image captures/A/<default theme>/w1280.png
   sugar image captures/A/<default theme>/w375.png
   ```

   `sugar help` lists the commands if this one has moved.

2. Write one decision item (`sugar schema` prints the full shape) and post it with `sugar post pick.json`, which prints the item's id and URL:

   ```json
   {
     "kind": "decision",
     "title": "Campaigns list: which layout?",
     "minutes": 2,
     "unblocks": "building the campaigns list",
     "recommendation": "B: density, a compact table that fits 25 rows at 1280",
     "summary": "Three mockups inside the brand. A is today's list improved; B and C each change one axis.",
     "options": [
       {
         "id": "A",
         "label": "Conventional: today's card list, with the filters moved above it",
         "blocks": [
           {"type": "image", "blob": "<id>", "alt": "desktop 1280", "caption": "Desktop, 1280"},
           {"type": "image", "blob": "<id>", "alt": "mobile 375", "caption": "Mobile, 375"},
           {"type": "table",
            "columns": [{"name": "Check", "measures": "which check ran"},
                        {"name": "Result", "measures": "pass, or the failures found"}],
            "rows": [["axe", "0 serious or critical"], ["contrast", "all pairs pass"],
                     ["overflow", "none at 320 to 1920"], ["brand lint", "0 findings"]]}
         ]
       }
     ]
   }
   ```

   B (`"label": "Density: a compact table, 25 rows at 1280", "recommended": true`) and C (`"label": "Navigation: the list on the left, the selected campaign on the right"`) follow with the same three blocks. Exactly one option is `recommended`; the board opens it first and adds More discussion and a note field itself. A `mockup` block (HTML in a sandboxed frame) may stand in for an image when the interaction is the point; captures stay the default.

3. Wait with `sugar wait <id>` (default timeout 30 minutes; on timeout, carry on with other work and check later with `sugar get <id>`; the build waits for the answer, because a pick is a taste call). The answer is `answers[0].choice`: an option id, or `"more"` with the user's note in `answers[0].note`.
