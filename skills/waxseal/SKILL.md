---
name: waxseal
description: WaxSeal SealedSecrets management — creating, resealing, and rotating Kubernetes secrets with GSM as source of truth. Use when working with SealedSecrets, secret metadata, or GSM in any GitOps repo.
---

# WaxSeal Skill

> Go CLI making SealedSecrets GitOps-friendly with Google Secret Manager (GSM) as source of truth.

## Core Mental Model

WaxSeal manages **three linked artifacts** for every secret:

1. **GSM secret** — plaintext value stored in Google Secret Manager (source of truth)
2. **Metadata file** — `.waxseal/metadata/<shortName>.yaml` mapping keys to GSM resources
3. **SealedSecret manifest** — encrypted YAML in `apps/` that ArgoCD deploys

**These three must be created together.** Never hand-write metadata pointing to GSM secrets that don't exist. Use WaxSeal commands to create them atomically.

---

## Command Reference

WaxSeal has two tiers of commands:

- **Primary** — shown in `waxseal --help`: `edit`, `rotate`, `reseal`, `check`, `meta`, `setup`
- **Advanced** — shown via `waxseal advanced`: `addkey`, `updatekey`, `retirekey`, `discover`, `gsm bootstrap`

The `edit` command is a **TUI wizard** (interactive only). The advanced commands (`addkey`, `updatekey`, `retirekey`) are **fully scriptable** with CLI flags.

### Global Flags

| Flag        | Default                | Purpose                                        |
| ----------- | ---------------------- | ---------------------------------------------- |
| `--repo`    | `.`                    | Path to the GitOps repository                  |
| `--config`  | `.waxseal/config.yaml` | Path to waxseal config file                    |
| `--dry-run` | `false`                | Show what would be done without making changes |
| `--yes`     | `false`                | Skip confirmation prompts                      |

---

## Creating New Secrets

### `addkey` — create secret atomically (all three artifacts)

```bash
# Interactive mode (TUI wizard, no flags needed)
waxseal addkey my-app-secrets

# Non-interactive with --key flags (prompts only for static key values)
waxseal addkey my-app-secrets \
  --namespace=default \
  --key=username \
  --key=password:random \
  --manifest-path=apps/my-app/sealed-secret.yaml

# All-random keys = fully non-interactive (no prompts at all)
waxseal addkey my-app-secrets \
  --namespace=default \
  --key=api_key:random \
  --key=db_password:random \
  --random-length=64 \
  --manifest-path=apps/my-app/sealed-secret.yaml

# Custom secret type (e.g., CNPG basic-auth)
waxseal addkey my-pg-creds \
  --namespace=default \
  --key=username \
  --key=password:random \
  --type=kubernetes.io/basic-auth \
  --manifest-path=apps/my-app/pg-sealed.yaml
```

**Flags:**

| Flag                                   | Default                               | Purpose                                                                 |
| -------------------------------------- | ------------------------------------- | ----------------------------------------------------------------------- |
| `--key=name`                           | —                                     | Static key (prompts for value securely, never in shell history)         |
| `--key=name:random`                    | —                                     | Generated random value (mode: `generated`)                              |
| `--key=name:template=PREFIX{{secret}}` | —                                     | Templated key with prefix (GSM-backed, rotatable)                       |
| `--namespace`                          | —                                     | Required when using `--key` flags                                       |
| `--manifest-path`                      | `apps/<shortName>/sealed-secret.yaml` | Where to write the SealedSecret                                         |
| `--scope`                              | `strict`                              | Sealing scope: `strict`, `namespace-wide`, `cluster-wide`               |
| `--type`                               | `Opaque`                              | K8s Secret type (e.g., `kubernetes.io/basic-auth`, `kubernetes.io/tls`) |
| `--generator`                          | `randomBase64`                        | Generator kind: `randomBase64`, `randomHex`                             |
| `--random-length`                      | `32`                                  | Bytes for generated random values                                       |

**Templated key example (Garage S3):**

```bash
waxseal addkey garage-openobserve-creds \
  --namespace=default \
  --key=access-key:template=GK{{secret}} \
  --key=secret-key:random \
  --generator=randomHex \
  --random-length=12 \
  --manifest-path=apps/infrastructure/garage/garage-openobserve-credentials-sealed.yaml
```

**What `addkey` does atomically:**

1. Creates GSM secrets (via `store.CreateSecretVersion`)
2. Writes metadata to `.waxseal/metadata/`
3. Seals and writes the SealedSecret manifest

### `edit` — interactive TUI wizard

```bash
waxseal edit           # Pick a secret or create new
waxseal edit addkey    # Jump directly to add-key flow
waxseal edit updatekey # Jump directly to update-key flow
waxseal edit retirekey # Jump directly to retire-key flow
```

---

## Updating Existing Keys

### `updatekey` — update a key's value in-place

```bash
waxseal updatekey my-app-secrets api_key
waxseal updatekey my-app-secrets api_key --generate-random
waxseal updatekey my-app-secrets api_key --generate-random --random-length=64
echo "new-value" | waxseal updatekey my-app-secrets api_key --stdin
waxseal updatekey my-app-secrets new_key --create --generate-random
```

**What `updatekey` does:**

1. Creates a new version in GSM with the new value
2. Updates the metadata with the new version number
3. Reseals the SealedSecret manifest

---

## Retiring, Resealing, Rotating, Health Checks

```bash
waxseal retirekey my-old-secret --reason "Replaced" --delete-manifest
waxseal reseal              # All active secrets (re-encrypt, same values)
waxseal rotate my-secret password       # Rotate one key
waxseal rotate my-secret --generated    # Batch rotate ALL generated keys
waxseal check             # Full health check
waxseal meta list secrets  # List all registered secrets
waxseal discover           # Scan repo for existing SealedSecrets
```

---

## Never Do

- **Never hand-write metadata files** — use `waxseal addkey`
- **Never use `gcloud secrets versions add`** for managed secrets — use `waxseal addkey`
- **Never use GSM aliases** (`latest`) — always pin numeric versions
- **Never put plaintext secrets** in metadata, YAML, comments, or logs
- **Never hand-edit `spec.encryptedData`** — use `waxseal reseal`

---

## Metadata Schema

```yaml
shortName: default-my-app-secrets
manifestPath: apps/my-app/sealed-secret.yaml
sealedSecret:
  name: my-app-secrets
  namespace: default
  scope: strict
  type: Opaque
status: active
keys:
  - keyName: password
    source:
      kind: gsm
    gsm:
      secretResource: projects/PROJECT/secrets/SECRET_ID
      version: "1"
    rotation:
      mode: generated
      generator:
        kind: randomBase64
        bytes: 32
```

### Rotation modes

| Mode        | Behavior                 | Use case                        |
| ----------- | ------------------------ | ------------------------------- |
| `static`    | Never auto-rotated       | Usernames, config values        |
| `generated` | Auto-generates new value | Passwords, API keys             |
| `external`  | Prompts operator         | OAuth tokens, third-party creds |

## Config Location

- Config: `.waxseal/config.yaml`
- Metadata: `.waxseal/metadata/*.yaml`
- Certificate: `keys/pub-cert.pem`
