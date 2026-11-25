#!/usr/bin/env python3
"""Check that an agent shell's defaults resolve to the factory App and the view kubeconfig.

Run it in an agent shell (Claude Code and Codex, on each machine). Prints one
line per probe and exits non-zero if any fails. Never prints a credential.

Probes:
  gh <owner>     `gh api /installation/repositories` works for each installed
                 account, which only an installation token can do
  git <repo>     `git ls-remote` over HTTPS works for a repo of each account
  committer      git's global committer is the App's bot
  kubectl        `kubectl auth whoami` is the factory-agent ServiceAccount
  kubeconfig     ~/.kube/config holds no system:masters certificate for ny1
                 (a local cluster's, such as rancher-desktop, is allowed)
  app key        no file under $HOME holds the App's private key (by the
                 public-key fingerprint from the App's settings page,
                 FORGE_APP_KEY_SHA256), and the broker's home isn't listable
Options: --repos OWNER/REPO ... to pick the git probes' repositories.
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys

BOT = "mapleset-forge[bot]"
NY1_SERVER = "https://190.102.105.210:6443"
DEFAULT_REPOS = ["Applesauce-Labs/sugarhouse", "shermanhuman/oh"]
SKIP_DIRS = {".cache", "node_modules", ".local/share/mise", ".rustup", ".cargo", "github", ".npm",
             ".local/share/Steam", "ComfyUI", ".mozilla", ".config/BraveSoftware", ".config/google-chrome"}


def run(cmd, env=None):
    return subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=60)


def probe_gh(owner):
    r = run(["gh", "api", "/installation/repositories", "--jq", ".total_count"], {"FORGE_OWNER": owner})
    return r.returncode == 0, f"installation token, {r.stdout.strip()} repos" if r.returncode == 0 else r.stderr.strip()[:200]


def probe_git(repo):
    """ls-remote works, and the credential git uses for it is an installation token."""
    r = run(["git", "ls-remote", f"https://github.com/{repo}", "HEAD"], {"GIT_TERMINAL_PROMPT": "0"})
    if r.returncode != 0:
        return False, r.stderr.strip()[:200]
    fill = subprocess.run(["git", "credential", "fill"], input=f"protocol=https\nhost=github.com\npath={repo}.git\n\n",
                          capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, timeout=60)
    password = next((l.split("=", 1)[1] for l in fill.stdout.splitlines() if l.startswith("password=")), "")
    kind = "installation token" if password.startswith("ghs_") else "not an installation token"
    return password.startswith("ghs_"), f"ls-remote ok, {kind}"


def probe_committer():
    name = run(["git", "config", "--global", "committer.name"]).stdout.strip()
    return name == BOT, name or "(unset)"


def probe_kubectl():
    r = run(["kubectl", "--context", "ny1", "auth", "whoami", "-o", "json"])
    if r.returncode != 0:
        return False, r.stderr.strip()[:200]
    user = json.loads(r.stdout).get("status", {}).get("userInfo", {}).get("username", "")
    return user.endswith(":factory-agent"), user


def masters_for_ny1(kubeconfig_path):
    """Names of users in the file that hold a system:masters certificate for ny1's server."""
    r = run(["kubectl", "--kubeconfig", kubeconfig_path, "config", "view", "--raw", "-o", "json"])
    if r.returncode != 0:
        return []
    cfg = json.loads(r.stdout)
    clusters = {c["name"]: c["cluster"].get("server") for c in cfg.get("clusters") or []}
    users = {u["name"]: u.get("user", {}) for u in cfg.get("users") or []}
    hits = []
    for ctx in cfg.get("contexts") or []:
        c = ctx["context"]
        if clusters.get(c.get("cluster")) != NY1_SERVER:
            continue
        cert = users.get(c.get("user"), {}).get("client-certificate-data")
        if not cert:
            continue
        subj = subprocess.run(["openssl", "x509", "-noout", "-subject"], input=base64.b64decode(cert),
                              capture_output=True).stdout.decode()
        if "system:masters" in subj:
            hits.append(c.get("user"))
    return hits


def probe_kubeconfig():
    path = os.path.expanduser("~/.kube/config")
    if not os.path.exists(path):
        return False, "no ~/.kube/config"
    hits = masters_for_ny1(path)
    return not hits, "no admin user for ny1" if not hits else f"admin user(s) for ny1: {', '.join(hits)}"


def key_fingerprint(path):
    r = subprocess.run(["openssl", "pkey", "-in", path, "-pubout", "-outform", "DER"], capture_output=True)
    if r.returncode != 0:
        return None
    return "SHA256:" + base64.b64encode(hashlib.sha256(r.stdout).digest()).decode().rstrip("=")


def probe_app_key():
    if os.access("/var/lib/forge-app", os.R_OK):
        return False, "/var/lib/forge-app is readable"
    want = os.environ.get("FORGE_APP_KEY_SHA256", "").rstrip("=")
    if not want:
        return False, "set FORGE_APP_KEY_SHA256 (the key's fingerprint on the App's settings page)"
    home = os.path.expanduser("~")
    found = []
    for root, dirs, files in os.walk(home):
        rel = os.path.relpath(root, home)
        dirs[:] = [d for d in dirs if os.path.normpath(os.path.join(rel, d)) not in SKIP_DIRS]
        for f in files:
            p = os.path.join(root, f)
            try:
                if os.path.getsize(p) > 16384 or os.path.islink(p):
                    continue
                with open(p, "rb") as fh:
                    if b"PRIVATE KEY-----" not in fh.read():
                        continue
            except OSError:
                continue
            if key_fingerprint(p) == want:
                found.append(p)
    return not found, "not found" if not found else f"found at {', '.join(found)}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repos", nargs="+", default=DEFAULT_REPOS)
    args = p.parse_args()
    probes = [(f"gh {r.split('/')[0]}", lambda o=r.split('/')[0]: probe_gh(o)) for r in args.repos]
    probes += [(f"git {r}", lambda r=r: probe_git(r)) for r in args.repos]
    probes += [("committer", probe_committer), ("kubectl", probe_kubectl), ("kubeconfig", probe_kubeconfig),
               ("app key", probe_app_key)]
    failed = 0
    for name, fn in probes:
        try:
            ok, detail = fn()
        except Exception as e:  # a probe that can't run is a failure, not a pass
            ok, detail = False, f"{type(e).__name__}: {e}"
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
