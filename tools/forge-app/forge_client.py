#!/usr/bin/env python3
"""Agent side of the factory App identity: which token, for which owner.

Used by the `gh` wrapper and `git-credential-forge`, and as a CLI:
  forge_client.py token [OWNER]     print a valid token for OWNER's installation
  forge_client.py owner [ARGS...]   print the owner `gh ARGS` would act on

Tokens come from soulglow's spool (`/var/spool/forge-app/<account>.json`,
written by forge_mint.py). Elsewhere (macmacmac) they are fetched over the
existing SSH login to soulglow and cached until under 10 minutes remain.

Environment:
  FORGE_ACCOUNTS   installed accounts, first is the default
                   (default "Applesauce-Labs shermanhuman")
  FORGE_SPOOL      spool directory (default /var/spool/forge-app)
  FORGE_REMOTE     ssh host holding the spool when it isn't local (default soulglow)
  FORGE_CACHE      cache dir for fetched tokens (default ~/.local/state/forge-app)
  FORGE_OWNER      force the owner (callers that know it but can't pass it in args)
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

DEFAULT_ACCOUNTS = "Applesauce-Labs shermanhuman"
REFETCH_LEFT = 600   # fetch a fresh copy when under 10 minutes remain (review M12)
STALE_LEFT = 300     # on the spool's own machine, under 5 minutes means the timer stalled


class ForgeError(Exception):
    pass


def accounts():
    return os.environ.get("FORGE_ACCOUNTS", DEFAULT_ACCOUNTS).split()


def canonical(owner):
    """The installed account an owner maps to; unknown owners get the default.

    The default token can still read any public repository, and a private repo
    of an uninstalled owner fails loudly (404), never as someone else.
    """
    if owner:
        for acct in accounts():
            if acct.lower() == owner.lower():
                return acct
    return accounts()[0]


def seconds_left(payload, now=None):
    exp = dt.datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
    now = now or dt.datetime.now(dt.timezone.utc)
    return (exp - now).total_seconds()


def _read(path):
    with open(path) as f:
        return json.load(f)


def token(owner=None, now=None):
    acct = canonical(owner)
    spool = os.environ.get("FORGE_SPOOL", "/var/spool/forge-app")
    local = os.path.join(spool, f"{acct}.json")
    if os.path.isdir(spool):
        try:
            payload = _read(local)
        except PermissionError:
            raise ForgeError(f"forge: can't read {local}; is the read ACL for this user in place?")
        except FileNotFoundError:
            raise ForgeError(f"forge: no token for {acct} in {spool}; is forge-app.timer running?")
        if seconds_left(payload, now) < STALE_LEFT:
            raise ForgeError(f"forge: the {acct} token in {spool} is about to expire; "
                             "forge-app.timer has stopped minting (systemctl status forge-app.timer)")
        return payload["token"]

    cache = os.path.expanduser(os.environ.get("FORGE_CACHE", "~/.local/state/forge-app"))
    cached = os.path.join(cache, f"{acct}.json")
    try:
        payload = _read(cached)
        if seconds_left(payload, now) >= REFETCH_LEFT:
            return payload["token"]
    except (FileNotFoundError, ValueError, KeyError):
        pass
    remote = os.environ.get("FORGE_REMOTE", "soulglow")
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", remote, "cat", local],
                         capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise ForgeError(f"forge: fetching the {acct} token from {remote} failed: {out.stderr.strip()}")
    payload = json.loads(out.stdout)
    if seconds_left(payload, now) < STALE_LEFT:
        raise ForgeError(f"forge: the {acct} token on {remote} is about to expire; "
                         f"forge-app.timer on {remote} has stopped minting")
    os.makedirs(cache, mode=0o700, exist_ok=True)
    tmp = cached + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, cached)
    return payload["token"]


# --- which owner a gh command acts on ---------------------------------------

REPO_FLAGS = {"-R", "--repo"}
OWNER_FLAGS = {"--owner"}
PATH_OWNER = re.compile(r"(?:^|/)(?:repos|orgs|users)/([A-Za-z0-9][A-Za-z0-9-]*)(?:/|$|\?)")
URL_OWNER = re.compile(r"github\.com[/:]([A-Za-z0-9][A-Za-z0-9-]*)/")
QUALIFIER = re.compile(r"(?:^|[\s=+&?]|%20)(?:user|org|owner|repo)(?::|%3A)([A-Za-z0-9][A-Za-z0-9-]*)")


def _repo_value_owner(value):
    m = URL_OWNER.search(value)
    if m:
        return m.group(1)
    parts = value.split("/")
    if len(parts) == 3:          # HOST/OWNER/REPO
        return parts[1]
    if len(parts) == 2:          # OWNER/REPO
        return parts[0]
    return None


def owner_from_args(args):
    """The owner named in gh's arguments, or None."""
    for i, a in enumerate(args):
        for flag in REPO_FLAGS | OWNER_FLAGS:
            value = None
            if a == flag and i + 1 < len(args):
                value = args[i + 1]
            elif a.startswith(flag + "=") and flag.startswith("--"):
                value = a.split("=", 1)[1]
            elif flag == "-R" and a.startswith("-R") and len(a) > 2:
                value = a[2:]
            if value:
                return value if flag in OWNER_FLAGS else _repo_value_owner(value)
    for a in args:
        for pattern in (URL_OWNER, PATH_OWNER, QUALIFIER):
            m = pattern.search(a)
            if m:
                return m.group(1)
    return None


def owner_from_cwd(cwd=None):
    out = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd,
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return _repo_value_owner(out.stdout.strip())


def owner_for(args, cwd=None):
    return os.environ.get("FORGE_OWNER") or owner_from_args(args) or owner_from_cwd(cwd)


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        if argv[0] == "token":
            print(token(argv[1] if len(argv) > 1 else owner_for([])))
            return 0
        if argv[0] == "owner":
            print(canonical(owner_for(argv[1:])))
            return 0
    except ForgeError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"forge_client: unknown command {argv[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
