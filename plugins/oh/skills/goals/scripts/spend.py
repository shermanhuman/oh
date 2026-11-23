#!/usr/bin/env python3
"""Spend so far on a goal: python3 -I spend.py --goal <slug> [--json]

Sessions come from ~/.local/state/oh/goals/<slug>.jsonl, the log oh's
keep-going Stop hook appends to on every stop. Each push is priced too: the
messages of its session from the push to that session's next stop. Claude sessions (and their subagents) are priced at list
API rates from their transcripts, each message once; Codex sessions are
reported in tokens. Only this machine's transcripts are read.
"""
import argparse
import glob
import json
import os
import pathlib
import re

# Per million tokens: input, output, cache read. Cache writes: 1.25x input (5 min), 2x (1 h).
# Same table as forge's metrics/review_cost.py.
PRICES = {
    "claude-fable-5-2": (8.0, 40.0, 0.20),
    "claude-mythos-5-2": (8.0, 40.0, 0.20),
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.00),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def claude_files(session):
    home = os.path.expanduser("~/.claude/projects")
    return glob.glob(f"{home}/*/{glob.escape(session)}.jsonl") + glob.glob(f"{home}/*/{glob.escape(session)}/subagents/*.jsonl")


def price_claude(files, seen):
    cost, unpriced, models = 0.0, 0, {}
    for path in files:
        for d in lines(path):
            m = d.get("message")
            if not isinstance(m, dict) or not isinstance(m.get("usage"), dict) or not m.get("id") or m["id"] in seen:
                continue
            seen.add(m["id"])
            u, model = m["usage"], m.get("model")
            price = PRICES.get(model)
            if price is None:
                unpriced += 1
                continue
            split = u.get("cache_creation") or {}
            w1h = split.get("ephemeral_1h_input_tokens") or 0
            w5m = (split.get("ephemeral_5m_input_tokens") or 0) if split else (u.get("cache_creation_input_tokens") or 0)
            pin, pout, pread = price
            c = ((u.get("input_tokens") or 0) * pin + w5m * pin * 1.25 + w1h * pin * 2
                 + (u.get("cache_read_input_tokens") or 0) * pread + (u.get("output_tokens") or 0) * pout) / 1e6
            cost += c
            models[model] = models.get(model, 0) + c
    return cost, unpriced, models


def message_times(files):
    """(timestamp, message id, cost) for each priced message, oldest first."""
    rows, seen = [], set()
    for path in files:
        for d in lines(path):
            m = d.get("message")
            if not isinstance(m, dict) or not isinstance(m.get("usage"), dict) or not m.get("id") or m["id"] in seen:
                continue
            seen.add(m["id"])
            c, _, _ = price_claude_one(m)
            rows.append((d.get("timestamp") or "", c))
    return sorted(rows)


def price_claude_one(m):
    u, model = m["usage"], m.get("model")
    price = PRICES.get(model)
    if price is None:
        return 0.0, 1, model
    split = u.get("cache_creation") or {}
    w1h = split.get("ephemeral_1h_input_tokens") or 0
    w5m = (split.get("ephemeral_5m_input_tokens") or 0) if split else (u.get("cache_creation_input_tokens") or 0)
    pin, pout, pread = price
    return ((u.get("input_tokens") or 0) * pin + w5m * pin * 1.25 + w1h * pin * 2
            + (u.get("cache_read_input_tokens") or 0) * pread + (u.get("output_tokens") or 0) * pout) / 1e6, 0, model


def utc(stamp):
    """A hook-log time (local, with offset) as an ISO UTC string comparable with transcript times."""
    import datetime as dt
    try:
        return dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z").astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return stamp


def codex_tokens(session):
    total = None
    for path in glob.glob(os.path.expanduser(f"~/.codex/sessions/*/*/*/*{glob.escape(session)}*.jsonl")):
        for d in lines(path):
            p = d.get("payload") or {}
            if isinstance(p, dict) and p.get("type") == "token_count" and isinstance(p.get("info"), dict):
                total = p["info"].get("total_token_usage") or total
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--goal", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not SLUG.match(a.goal):
        raise SystemExit("goal: letters, digits, '.', '_' and '-' only")
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    path = pathlib.Path(base) / "oh" / "goals" / f"{a.goal}.jsonl"
    log = [r for r in lines(path) if isinstance(r, dict) and r.get("session")]
    if not log:
        raise SystemExit(f"no sessions recorded for goal {a.goal!r} yet ({path})")
    sessions = {}
    for r in log:
        sessions.setdefault(r["session"], {"host": r.get("host", "claude")})
    seen, cost, unpriced, models, codex, missing = set(), 0.0, 0, {}, {}, []
    for sid, info in sessions.items():
        if info.get("host") == "codex":
            t = codex_tokens(sid)
            if t:
                codex[sid] = t
            else:
                missing.append(sid)
            continue
        files = claude_files(sid)
        if not files:
            missing.append(sid)
            continue
        c, u, m = price_claude(files, seen)
        cost, unpriced = cost + c, unpriced + u
        for k, v in m.items():
            models[k] = models.get(k, 0) + v
    push_costs = []
    for i, r in enumerate(log):
        if not r.get("push") or sessions[r["session"]].get("host") == "codex":
            continue
        end = next((utc(x["at"]) for x in log[i + 1:] if x["session"] == r["session"]), "9999")
        start = utc(r["at"])
        times = message_times(claude_files(r["session"]))
        push_costs.append(sum(c for t, c in times if start <= t[:19] < end))
    out = {"goal": a.goal, "pushes": len([r for r in log if r.get("push")]), "push_dollars": round(sum(push_costs), 2), "claude_dollars": round(cost, 2), "by_model": {k: round(v, 2) for k, v in models.items()},
           "unpriced_messages": unpriced, "codex_tokens": codex, "sessions": len(sessions), "not_on_this_machine": missing}
    if a.json:
        print(json.dumps(out, indent=1))
        return
    print(f"Goal {a.goal}: ${cost:,.2f} of Claude usage at list API prices, over {len(sessions) - len(missing)} sessions on this machine.")
    for k, v in sorted(models.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: ${v:,.2f}")
    if out["pushes"]:
        print(f"  Keep-going pushes: {out['pushes']}, costing ${out['push_dollars']:,.2f} of the total (Claude only).")
    if codex:
        print(f"  Codex: {sum((t.get('total_tokens') or 0) for t in codex.values()):,} tokens (no dollar price)")
    if unpriced:
        print(f"  {unpriced} messages had no known price and are left out.")
    if missing:
        print(f"  {len(missing)} recorded sessions aren't on this machine.")


if __name__ == "__main__":
    main()
