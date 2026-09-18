# WaxSeal 0.5 Skill

> Go CLI that keeps the plaintext of every Kubernetes secret in Google Secret Manager (GSM) and only ciphertext in Git. Verified against waxseal 0.5.0 (2026-09-18); check `waxseal --version` before relying on any command here.

## Core mental model

Every managed secret is **three linked artifacts** that waxseal keeps in agreement:

1. **GSM secret** — the plaintext, one GSM secret per key, pinned to a numeric version (`latest` is rejected).
2. **Metadata** — `.waxseal/metadata/<shortName>.yaml`: keys, GSM references, rotation mode, expiry, computed templates.
3. **SealedSecret manifest** — the encrypted YAML under `apps/` that Argo CD applies (`manifestPath` in metadata).

waxseal owns the metadata and manifest files: it rewrites them whole and validates before writing. Do not hand-write metadata or edit `spec.encryptedData`. If a GSM value must be changed outside waxseal, register it with `waxseal key set`, never by editing metadata to point at a version waxseal did not create.

## Non-interactive rule

| Situation | What happens |
| --- | --- |
| Terminal, flag omitted | waxseal prompts (masked for values) |
| `--no-input`, or no TTY (CI, an agent's shell) | fails with an error naming the missing flag |

An agent shell has no TTY. **Always pass every flag** and `--no-input`; add `-y` to accept confirmations. If a command still asks for something, the error names the flag — supply it rather than retrying.

Global flags: `--repo PATH` (default `.`), `--dry-run`, `-y/--yes`, `--no-input`, `-o text|json`, `--no-color`, `--verbose`. Any mutating command accepts `--dry-run`; any command accepts `-o json`.

## Command tree

| Command | What it does |
| --- | --- |
| `secret list` / `secret show <s>` | what is managed; keys, where values live, expiry |
| `secret retire <s> [--reason ..] [--replaced-by <s2>] [--delete-manifest]` | mark retired (skipped by reseal/rotate/check); GSM untouched |
| `key add <s> <k>` | add a key; **creates the secret on its first key** (needs `--namespace`) |
| `key set <s> <k>` | store a new value (new GSM version) and reseal |
| `key edit <s> <k>` | change rotation / generator / expiry / template / params (metadata, or a new computed payload) |
| `rotate <s> [k]...` | new values for **generated** keys only, then reseal |
| `reseal [s]...` | re-encrypt from GSM; detects a rotated controller certificate and asks before adopting it (`--skip-cert-check` for CI) |
| `check [cert\|expiry\|metadata\|gsm\|cluster]...` | health; exit 0 healthy, 1 errors, 2 warnings with `--fail-on-warning` |
| `init`, `gcp provision`, `cert fetch`, `discover`, `import`, `setup` | first-time setup (`setup` sequences the others on a terminal) |
| `reminders configure` / `sync` / `clear` | expiry reminders in Google Tasks or Calendar |

## Adding a key (and creating a secret)

```sh
# A value you already have, from a file (one trailing newline is stripped)
waxseal key add my-app api_token --namespace prod --rotation external \
  --from-file ./token.txt --manifest apps/my-app/sealed-secret.yaml --no-input -y

# From stdin
echo -n 'value' | waxseal key add my-app api_token --namespace prod --rotation external --from-file - --no-input -y

# Generated (rotatable): base64 or hex, N bytes
waxseal key add my-app db_password --namespace prod --generate --generator randomHex --bytes 32 --no-input -y

# Static, non-secret value that still has to live in the Secret (e.g. a CNPG role's username)
echo -n 'app' | waxseal key add my-app username --namespace prod --rotation static --from-file - --no-input -y
```

`key add` flags: `--namespace` (required on the first key), `--manifest` (default `apps/<secret>/sealed-secret.yaml`), `--name` (SealedSecret name, default the short name), `--scope strict|namespace-wide|cluster-wide`, `--type Opaque|kubernetes.io/basic-auth|kubernetes.io/tls|...`, `--rotation generated|external|static|unknown`, `--generate`, `--generator randomBase64|randomHex`, `--bytes N`, `--expires YYYY-MM-DD|none`, `--template`, `--param name=value`.

The short name is the metadata file name; by default it is also the Kubernetes Secret's name. Pass `--name` when the Secret should be called something else.

**Delete the source file once the key is stored.** `key add` reads it; it does not remove it.

## Changing a value

```sh
waxseal key set my-app api_token --from-file - --no-input -y < new-token.txt   # rotated at the vendor
waxseal key set my-app db_password --generate --no-input -y                     # key with a generator
waxseal key set my-app api_token --expires 2027-01-01 --from-file -            # and record expiry
```

`key set` creates a new GSM version, updates the pinned version in metadata and reseals. For a computed key the value is the `{{secret}}` part only.

## Rotation modes

| Mode | Meaning | Rotate with |
| --- | --- | --- |
| `generated` | waxseal makes the value (`randomBase64` / `randomHex`, `--bytes N`) | `waxseal rotate <s> [k]` |
| `external` | rotated at a vendor (API keys, OAuth secrets) | `waxseal key set <s> <k> --from-file -` |
| `static` | not expected to change (usernames, config-ish values) | — |
| `unknown` | not decided yet | `key edit --rotation` |

`rotate` only ever touches generated keys; others are listed as skipped. It cannot be made to rotate an external key with `-y`.

**Choose the alphabet for where the value ends up.** A password that Kubernetes will splice into a URL with `$(VAR)` must be `randomHex` — Kubernetes does no percent-encoding and base64's `+` and `/` corrupt the DSN.

## Computed keys (connection strings)

A computed key renders a template whose `{{secret}}` is the rotatable part:

```sh
waxseal key add my-app DATABASE_URL --namespace prod --generate --generator randomHex \
  --template 'postgresql://app:{{secret}}@{{host}}:{{port}}/{{database}}' \
  --param host=db.internal --param port=5432 --param database=app --no-input -y
waxseal key edit my-app DATABASE_URL --param host=db2.internal --no-input -y   # re-render, secret untouched
waxseal rotate my-app DATABASE_URL --no-input -y                               # new password, re-rendered
```

`import` recognises connection strings in cluster secrets and turns them into computed keys. Prefer not to seal a DSN at all when the consumer can build it from a password env var — the coordinates are not secret.

## Registering existing manifests

```sh
waxseal discover                 # read-only: lists manifests and whether metadata covers them
waxseal import my-app other-app  # reads plaintext from the cluster, stores in GSM, writes metadata
```

`import` registers every key as `external`; fix that with `key edit --rotation`. `discover` writes nothing.

## Health and CI

```sh
waxseal check                          # everything; GSM/cluster checks skip when credentials are absent
waxseal check gsm cluster              # named checks are mandatory
waxseal check --fail-on-warning --warn-days 30
waxseal reseal --skip-cert-check --no-input   # CI, no cluster access
```

`check cluster` compares metadata against the live Secret's keys and manifest scope; a key present in metadata but missing from the cluster, or a manifest that has not been applied yet, is reported — expected for a secret on an unmerged branch.

## Prerequisites

`gcloud` authenticated with **Application Default Credentials** (`gcloud auth application-default login` — a plain `gcloud auth login` is not enough), `kubeseal`, and `kubectl` pointed at the cluster that runs the sealed-secrets controller (`$KUBECONFIG` is honoured; there is no `--kubeconfig` flag). IAM: `secretmanager.secretAccessor` to reseal; `secretVersionAdder` plus create/delete to add keys, set values and rotate.

## Files

```
.waxseal/config.yaml           project, controller location, reminders
.waxseal/metadata/<name>.yaml  one file per secret
keys/pub-cert.pem              the controller's sealing certificate
apps/<...>/*sealed*.yaml       SealedSecret manifests (path per secret in metadata)
```

`state.yaml` is no longer written by 0.5; an existing one is left alone.

## Never do

- Never hand-write or hand-edit metadata, or `spec.encryptedData` — use `key add` / `key set` / `reseal`.
- Never pass a secret value on the command line (there is no flag for it); never `echo` one into logs.
- Never point metadata at a GSM version waxseal did not create; never use `latest`.
- Never store non-secret configuration as a sealed key just to get it into a container when an env `value:` or the application's own config store will do — sealing is for secrets.
- Do not rotate or retire because a reseal or check was requested. Scope stays with the named secrets and keys.

## Migrating from 0.4 (memory aid)

| 0.4 | 0.5 |
| --- | --- |
| `addkey <s> --key=k --key=k2:random` | one `key add <s> <k>` per key (first one creates the secret) |
| `updatekey <s> <k> --stdin` | `key set <s> <k> --from-file -` |
| `updatekey --create` | `key add` |
| `retirekey <s>` | `secret retire <s>` |
| `meta list secrets` / `meta showkey` | `secret list` / `secret show` |
| `rotate <s> --generated` | `rotate <s>` |
| `edit` (TUI), `advanced` | removed — use flags |
| `--config`, `--kubeconfig` | removed |
