# forge-app: agents act as the `mapleset-forge` GitHub App

Agents (Claude Code and Codex, on soulglow and macmacmac) reach GitHub as the
`mapleset-forge` App instead of the owner's account, and ny1 through a
read-only `view` kubeconfig. Plan: http://soulglow:2026/plans/app-identity
(sugarhouse#104).

| Piece | Runs as | What it does |
|---|---|---|
| `forge_mint.py` + `systemd/` | `forge-app` (soulglow) | The only code that reads the App's key. Every 20 minutes mints a restricted token per installed account (Applesauce-Labs, shermanhuman) into `/var/spool/forge-app/<account>.json`, readable by `s` through an ACL. Tokens live 60 minutes. |
| `forge_client.py` | `s` | Picks the token for an owner: from the spool on soulglow, fetched over SSH from soulglow and cached elsewhere. |
| `bin/gh` | `s` | gh wrapper, on PATH through mise's global `[env] _.path`. Picks the owner from `-R`, a URL, an API path, a search qualifier, `FORGE_OWNER` or the cwd's `origin`; passes an existing `GH_TOKEN` through. |
| `bin/git-credential-forge` | `s` | git credential helper, by the URL's owner (`useHttpPath`). |
| `setup_agent.py` | `s` | Switches git, gh and mise to the above (and, with `--kube VIEW`, moves the admin kubeconfig to `~/.kube/admin.yaml`); `--undo` restores. |
| `check_agent_identity.py` | `s` | Checks an agent shell resolves to the App and `view`, without printing a credential. |

## Install

1. The owner, once: make the App installable on any account, install it on
   `shermanhuman` (All repositories), generate a private key, then on soulglow
   `sudo tools/forge-app/install-broker.sh ~/Downloads/<key>.pem` (it moves the key).
2. Each machine: `python3 tools/forge-app/setup_agent.py --kube <view-kubeconfig>`.
3. `FORGE_APP_KEY_SHA256=<fingerprint> python3 tools/forge-app/check_agent_identity.py`
   in a Claude tab and a Codex tab.

Rollback: `setup_agent.py --undo` on each machine.

The owner's own credentials stay on the machine (their pick, item 246); agents
don't use them (`oh:pull-requests`). Admin kubectl for the owner:
`KUBECONFIG=~/.kube/admin.yaml KUBE_CONTEXT=ny1 <command>`.
