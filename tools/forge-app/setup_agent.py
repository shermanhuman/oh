#!/usr/bin/env python3
"""Switch this machine's user (s) to the factory App identity, or back.

  setup_agent.py                  install the client and switch git and gh
  setup_agent.py --kube VIEW.yaml also move the admin kubeconfig to
                                  ~/.kube/admin.yaml and install VIEW.yaml as
                                  ~/.kube/config (plan row 7)
  setup_agent.py --undo           restore everything it changed, from the saved state

What it changes (plan rows 5 and 6), all in the user's own config:
- copies forge_client.py and bin/ to ~/.local/share/forge-app;
- prepends that bin/ to PATH through mise's global `[env] _.path`, so
  `mise exec -- gh` and a plain `gh` reach the wrapper;
- git: resets the credential helper list for github.com (an empty value first,
  which also skips a system osxkeychain helper) and sets git-credential-forge,
  turns on useHttpPath, rewrites SSH GitHub remotes to HTTPS, and makes
  mapleset-forge[bot] the committer (the owner stays the author);
- gh: git_protocol https.
Repo-local settings (a repo's own helper or author) are left alone.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
SRC = os.path.dirname(os.path.realpath(__file__))
DEST = os.path.join(HOME, ".local/share/forge-app")
BIN = os.path.join(DEST, "bin")
STATE = os.path.join(HOME, ".local/state/forge-app/undo.json")
MISE = os.path.join(HOME, ".config/mise/config.toml")
MISE_MARK = "# forge-app: the App-identity gh wrapper"
KUBE = os.path.join(HOME, ".kube/config")
ADMIN = os.path.join(HOME, ".kube/admin.yaml")
NY1_SERVER = "https://190.102.105.210:6443"

BOT_NAME = "mapleset-forge[bot]"
BOT_EMAIL = "358906886+mapleset-forge[bot]@users.noreply.github.com"
HELPER_KEYS = ["credential.https://github.com.helper", "credential.https://gist.github.com.helper"]
OTHER_KEYS = ["credential.https://github.com.usehttppath", "url.https://github.com/.insteadof",
              "committer.name", "committer.email"]


def git_get_all(key):
    out = subprocess.run(["git", "config", "--global", "--get-all", key], capture_output=True, text=True)
    return out.stdout.splitlines() if out.returncode == 0 else []


def git_set_all(key, values):
    subprocess.run(["git", "config", "--global", "--unset-all", key], capture_output=True)
    for v in values:
        subprocess.run(["git", "config", "--global", "--add", key, v], check=True)


def gh_protocol(value=None):
    """Read or set gh's git_protocol with the real gh (config needs no token)."""
    real = os.environ.get("FORGE_REAL_GH") or shutil.which("gh")
    if real is None:
        return None
    if value is None:
        out = subprocess.run([real, "config", "get", "git_protocol"], capture_output=True, text=True)
        return out.stdout.strip() or None
    subprocess.run([real, "config", "set", "git_protocol", value], check=True)
    return value


def mise_add():
    text = open(MISE).read() if os.path.exists(MISE) else ""
    if MISE_MARK in text:
        return False
    line = f'_.path = ["{BIN}"]  {MISE_MARK}'
    if re.search(r"(?m)^\[env\]\s*$", text):
        text = re.sub(r"(?m)^\[env\]\s*$", "[env]\n" + line, text, count=1)
    else:
        text = text.rstrip("\n") + "\n\n[env]\n" + line + "\n"
    os.makedirs(os.path.dirname(MISE), exist_ok=True)
    with open(MISE, "w") as f:
        f.write(text)
    return True


def mise_remove():
    if not os.path.exists(MISE):
        return
    lines = [l for l in open(MISE).read().split("\n") if MISE_MARK not in l]
    with open(MISE, "w") as f:
        f.write("\n".join(lines))


def kube_switch(view, state):
    if os.path.exists(ADMIN):
        sys.exit(f"setup_agent: {ADMIN} already exists; not overwriting it")
    shutil.move(KUBE, ADMIN)
    state["kube_moved"] = True
    # macmacmac names ny1's context "default"; give it the name the repo scripts use.
    out = subprocess.run(["kubectl", "--kubeconfig", ADMIN, "config", "view", "-o",
                          "jsonpath={range .contexts[*]}{.name}={.context.cluster}{'\\n'}{end}"],
                         capture_output=True, text=True)
    for line in out.stdout.splitlines():
        name, _, cluster = line.partition("=")
        server = subprocess.run(["kubectl", "--kubeconfig", ADMIN, "config", "view", "-o",
                                 f"jsonpath={{.clusters[?(@.name==\"{cluster}\")].cluster.server}}"],
                                capture_output=True, text=True).stdout.strip()
        if name == "default" and server == NY1_SERVER:
            subprocess.run(["kubectl", "--kubeconfig", ADMIN, "config", "rename-context", "default", "ny1"],
                           check=True, capture_output=True)
            state["renamed_context"] = True
    fd = os.open(KUBE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f, open(view) as src:
        f.write(src.read())


def install():
    os.makedirs(BIN, exist_ok=True)
    shutil.copy2(os.path.join(SRC, "forge_client.py"), DEST)
    for name in os.listdir(os.path.join(SRC, "bin")):
        shutil.copy2(os.path.join(SRC, "bin", name), BIN)


def switch(args):
    if os.path.exists(STATE):
        sys.exit(f"setup_agent: already switched ({STATE} exists); run --undo first")
    state = {"git": {k: git_get_all(k) for k in HELPER_KEYS + OTHER_KEYS},
             "gh_protocol": gh_protocol()}
    install()
    state["mise_added"] = mise_add()
    helper = os.path.join(BIN, "git-credential-forge")
    for key in HELPER_KEYS:
        git_set_all(key, ["", helper])
    git_set_all("credential.https://github.com.usehttppath", ["true"])
    git_set_all("url.https://github.com/.insteadof", ["git@github.com:", "ssh://git@github.com/"])
    # The owner stays the commits' author; the App is the committer (item 247).
    git_set_all("committer.name", [BOT_NAME])
    git_set_all("committer.email", [BOT_EMAIL])
    if gh_protocol() not in (None, "https"):
        gh_protocol("https")
    if args.kube:
        kube_switch(args.kube, state)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(state, f, indent=1)
    print("setup_agent: switched to the App identity; undo with --undo")


def undo():
    try:
        state = json.load(open(STATE))
    except FileNotFoundError:
        sys.exit("setup_agent: nothing to undo")
    for key, values in state["git"].items():
        git_set_all(key, values)
    if state.get("gh_protocol"):
        gh_protocol(state["gh_protocol"])
    if state.get("mise_added"):
        mise_remove()
    if state.get("kube_moved") and os.path.exists(ADMIN):
        if state.get("renamed_context"):
            subprocess.run(["kubectl", "--kubeconfig", ADMIN, "config", "rename-context", "ny1", "default"],
                           check=True, capture_output=True)
        os.replace(ADMIN, KUBE)
    os.remove(STATE)
    print("setup_agent: restored the previous settings")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--undo", action="store_true")
    p.add_argument("--kube", metavar="VIEW_KUBECONFIG")
    args = p.parse_args()
    undo() if args.undo else switch(args)


if __name__ == "__main__":
    main()
