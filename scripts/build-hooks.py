"""Build each plugin's hooks/session-start.json from its hooks/always-on.md.

Run after editing an always-on.md; `--check` fails when any JSON is stale.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def render(source: pathlib.Path) -> str:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": source.read_text(encoding="utf-8").strip(),
        }
    }
    return json.dumps(payload, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    check = "--check" in sys.argv
    stale = []
    for source in sorted(ROOT.glob("plugins/*/hooks/always-on.md")):
        target = source.with_name("session-start.json")
        expected = render(source)
        if check:
            actual = target.read_text(encoding="utf-8") if target.exists() else ""
            if actual != expected:
                stale.append(str(target.relative_to(ROOT)))
        else:
            target.write_text(expected, encoding="utf-8")
            print(f"wrote {target.relative_to(ROOT)}")
    if stale:
        sys.exit("stale, run python3 scripts/build-hooks.py: " + ", ".join(stale))
    if check:
        print("hook outputs are up to date")
