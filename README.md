# Vaultly

A minimal secrets API wrapper around [HashiCorp Vault](https://www.vaultproject.io/). Vaultly
exposes a small REST API for reading, writing, and deleting secrets in Vault's KV v2 engine, and
demonstrates a live database-credential rotation cycle: change a secret in Vault and a running
Vaultly instance picks up the new value on its next poll, with **no restart**.

This repo is the *application*. It intentionally does **not** include Kubernetes manifests, Vault
HA/auto-unseal configuration, Terraform, CI/CD security scanning, or cloud IAM — those are the
subject of the accompanying DevSecOps lab (`project.md`) that deploys and secures this app.

## Why it exists

Vaultly is a real, working stand-in for "an app that needs secrets," so a DevSecOps exercise can
focus entirely on how those secrets are managed, rotated, and access-controlled, instead of also
having to design an application from scratch.

## Quickstart (local dev)

Requires Docker.

```bash
docker compose up --build
```

This starts a Vault **dev-mode** server (in-memory, auto-unsealed, root token
`vaultly-dev-root-token` — dev mode only, never do this in production) and Vaultly itself,
authenticating with a static token (`VAULTLY_VAULT_AUTH_METHOD=token`), which is likewise only
acceptable for local development. See [Security model](#security-model) below.

Seed a secret and read it back:

```bash
export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=vaultly-dev-root-token

curl -s -X PUT http://127.0.0.1:8080/api/v1/secrets/app-config/widget \
  -H "Authorization: Bearer local-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "abc123"}'

curl -s http://127.0.0.1:8080/api/v1/secrets/app-config/widget \
  -H "Authorization: Bearer local-dev-token"
```

## Running without Docker Compose

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

docker run --rm -d --name vaultly-dev-vault -p 8200:8200 \
  -e VAULT_DEV_ROOT_TOKEN_ID=vaultly-dev-root-token \
  hashicorp/vault server -dev

cp .env.example .env
uvicorn app.main:create_app --factory --reload --port 8080
```

## Running the tests

Tests run against a real Vault dev server (no mocked Vault client) — start one the same way as
above, then:

```bash
export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=vaultly-dev-root-token
pytest -v
```

Tests that need Vault auto-skip with a clear message if no dev server is reachable.

## API

All `/api/v1/*` routes require `Authorization: Bearer <VAULTLY_API_BEARER_TOKEN>`.

| Method | Path                          | Description                                     |
|--------|-------------------------------|-------------------------------------------------|
| GET    | `/healthz`                    | Liveness probe                                  |
| GET    | `/readyz`                     | Readiness probe (checks Vault session is valid) |
| GET    | `/api/v1/secrets/{path}`      | Read a secret                                   |
| PUT    | `/api/v1/secrets/{path}`      | Create/update a secret (JSON object of strings) |
| DELETE | `/api/v1/secrets/{path}`      | Delete all versions of a secret                 |
| GET    | `/api/v1/db/status`           | Current DB credential version/username (rotation demo; never returns the password) |

## Rotation demo

Vaultly polls `VAULTLY_DB_SECRET_PATH` (default `vaultly/database`) every
`VAULTLY_ROTATION_POLL_INTERVAL_SECONDS` and swaps its in-memory DB credential state whenever the
value in Vault changes — see `app/db.py::CredentialRotator`. To see it live:

```bash
# initial credential
curl -s -X PUT http://127.0.0.1:8200/v1/secret/data/vaultly/database \
  -H "X-Vault-Token: vaultly-dev-root-token" \
  -d '{"data": {"username": "app_user", "password": "v1"}}'

curl -s http://127.0.0.1:8080/api/v1/db/status -H "Authorization: Bearer local-dev-token"
# {"username": "app_user", "version": 1, ...}

# rotate it
curl -s -X PUT http://127.0.0.1:8200/v1/secret/data/vaultly/database \
  -H "X-Vault-Token: vaultly-dev-root-token" \
  -d '{"data": {"username": "app_user", "password": "v2"}}'

# wait for the next poll interval, no restart of vaultly happened
curl -s http://127.0.0.1:8080/api/v1/db/status -H "Authorization: Bearer local-dev-token"
# {"username": "app_user", "version": 2, ...}
```

A full secrets-rotation runbook (how to rotate the real Vault database secrets engine credentials
that back a deployed instance) belongs in the deploying lab's documentation, since it depends on
that deployment's actual database and Vault topology.

## Configuration

All configuration is via environment variables, prefixed `VAULTLY_` (see `app/config.py` and
`.env.example`). Nothing is hardcoded — there is no default `api_bearer_token` or Vault token
baked into the app; `VAULTLY_API_BEARER_TOKEN` must be supplied explicitly or the app fails to
start.

Two Vault auth methods are supported:

- **`kubernetes`** (default, intended for real deployments) — Vaultly reads the pod's projected
  service account JWT and exchanges it for a Vault token via Vault's Kubernetes auth method.
  Requires `VAULTLY_VAULT_K8S_ROLE` to be set to a role configured on the Vault side, bound to the
  app's Kubernetes service account. No static credential is ever stored by the app.
- **`token`** — a static `VAULTLY_VAULT_TOKEN`, for local development against `vault server -dev`
  only. Vaultly logs a warning on startup if this method is used.

## Security model, and what this app deliberately does not do

Vaultly is scoped as *the application under management*, not the security control plane around it.
By design:

- **API auth is a single shared bearer token**, compared with `hmac.compare_digest`. This is
  enough to keep the service from being an open Vault proxy on the network, but it is not
  per-client identity, authorization scoping, or audit-attributable access. A real deployment is
  expected to front Vaultly with proper per-client identity (mTLS, OIDC/JWT per caller, or
  Kubernetes-network-level isolation via NetworkPolicy) — that's lab work, not app work.
- **No TLS termination in-app.** Vaultly is meant to sit behind an ingress/load balancer that
  terminates TLS; it speaks plain HTTP on its own.
- **The container runs as a non-root user** (`docker/Dockerfile`), but the Kubernetes
  `PodSecurityContext`/RBAC/NetworkPolicy hardening around it is the lab's responsibility.
- **Secret values are never logged.** `app/vault_client.py` and `app/db.py` log paths, key names,
  and rotation events, never values.
- **`/api/v1/db/status` never returns the password**, only username/version/rotation timestamp —
  see `DBCredentialState.public_status()`.

## Project layout

```
app/
  main.py          FastAPI app + routes
  config.py        Settings (env-driven, pydantic-settings)
  vault_client.py  hvac wrapper: auth (kubernetes/token) + KV v2 read/write/delete
  security.py      Bearer-token dependency for /api/v1 routes
  db.py            DBCredentialState + CredentialRotator (the rotation demo)
  models.py        Request/response schemas
tests/             pytest suite, runs against a real Vault dev server
docker/Dockerfile  non-root, healthchecked image
docker-compose.yml Vault dev server + Vaultly for local use
```
------------------------------------------------------------------

For the local cluster:

# Start of day
./rebuild.sh

# End of day
./takedown.sh   

Notes:

rebuild.sh takes about 3–4 minutes (mostly the Docker build + kind image load).
The .vault-local-credentials file stores the root token and all 5 unseal keys. It's gitignored. Delete it if you ever takedown and don't plan to rebuild (fresh cluster = fresh keys anyway).
The helm repo add line is idempotent — it won't fail if the repo is already added.
When the cloud cluster is ready, a separate rebuild-eks.sh / takedown-eks.sh will replace these. The local ones stay for quick iteration.