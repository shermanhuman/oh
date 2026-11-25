#!/usr/bin/env python3
"""Mint short-lived installation tokens for the `mapleset-forge` GitHub App.

Runs as the `forge-app` system user (systemd timer, every 20 minutes). It is the
only code that reads the App's private key. For each named account it writes
`<spool>/<account>.json` = {"token": ..., "expires_at": ..., "account": ...},
mode 0640 with a read ACL for the agents' user, atomically.

Configuration comes from the environment (the unit's EnvironmentFile):
  FORGE_APP_ID        the App's numeric ID
  FORGE_APP_KEY       path of the PEM private key (0400, owned by forge-app)
  FORGE_ACCOUNTS      space-separated account logins to mint for; any other
                      installation is ignored, because a public App can be
                      installed by anyone
  FORGE_SPOOL         directory the tokens go to (default /var/spool/forge-app)
  FORGE_READER        Unix user granted read by ACL (default s; empty: none)
  FORGE_API           API base (default https://api.github.com; tests override)
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

# What agents may do (plan row 3). Checks and statuses stay read-only, so no
# agent can fake a required check.
PERMISSIONS = {
    "contents": "write",
    "pull_requests": "write",
    "issues": "write",
    "workflows": "write",
    "actions": "write",
    "checks": "read",
    "statuses": "read",
    "metadata": "read",
}


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def app_jwt(app_id, key_path, now=None):
    """An RS256 JWT for the App, signed with openssl (no third-party library)."""
    now = int(now if now is not None else time.time())
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    # iat 60 s in the past absorbs clock drift; GitHub allows at most 10 minutes.
    claims = b64url(json.dumps({"iat": now - 60, "exp": now + 540, "iss": str(app_id)},
                               separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode()
    sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_path],
                         input=signing_input, capture_output=True, check=True).stdout
    return f"{header}.{claims}.{b64url(sig)}"


def api(base, method, path, jwt, body=None):
    req = urllib.request.Request(
        base.rstrip("/") + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "forge-app-minter",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def installations(base, jwt):
    found, page = {}, 1
    while True:
        batch = api(base, "GET", f"/app/installations?per_page=100&page={page}", jwt)
        for inst in batch:
            found[inst["account"]["login"].lower()] = inst["id"]
        if len(batch) < 100:
            return found
        page += 1


def write_atomic(spool, account, payload, reader):
    """Write <spool>/<account>.json so a reader never sees a partial or unreadable file.

    The mode and ACL are set on the temporary file before the rename: a file made
    by mkstemp is 0600, and a default ACL on the directory would then be masked
    to nothing (plan review m9).
    """
    fd, tmp = tempfile.mkstemp(dir=spool, prefix=f".{account}.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        os.chmod(tmp, 0o640)
        if reader:
            subprocess.run(["setfacl", "-m", f"u:{reader}:r", tmp], check=True)
        os.replace(tmp, os.path.join(spool, f"{account}.json"))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main():
    app_id = os.environ["FORGE_APP_ID"]
    key = os.environ["FORGE_APP_KEY"]
    accounts = os.environ["FORGE_ACCOUNTS"].split()
    spool = os.environ.get("FORGE_SPOOL", "/var/spool/forge-app")
    reader = os.environ.get("FORGE_READER", "s")
    base = os.environ.get("FORGE_API", "https://api.github.com")

    jwt = app_jwt(app_id, key)
    by_login = installations(base, jwt)
    failed = []
    for account in accounts:
        inst = by_login.get(account.lower())
        if inst is None:
            print(f"forge-mint: the App isn't installed on {account}", file=sys.stderr)
            failed.append(account)
            continue
        try:
            tok = api(base, "POST", f"/app/installations/{inst}/access_tokens", jwt,
                      {"permissions": PERMISSIONS})
        except urllib.error.HTTPError as e:
            print(f"forge-mint: minting for {account} failed: HTTP {e.code}", file=sys.stderr)
            failed.append(account)
            continue
        write_atomic(spool, account, {"account": account, "token": tok["token"],
                                      "expires_at": tok["expires_at"]}, reader)
    # A failure exits non-zero so systemd records it; the other accounts' tokens
    # were still written.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
