#!/usr/bin/env bash
#
# rebuild.sh - start-of-day LOCAL cluster for Vaultly.
#
# LOCAL DEV ONLY. This runs Vault in DEV MODE on purpose:
#   * a single vault-0 pod, auto-unsealed, Ready in seconds
#   * KV v2 auto-mounted at secret/
#   * a fixed root token, no Shamir keys, no manual unseal, no Raft quorum
#
# That removes the whole init / unseal / raft-join sequence that left
# vault-1 and vault-2 stuck at 0/1 (a Vault pod only reports 1/1 once it
# is unsealed; sealed standbys that were never joined stay 0/1 forever).
#
# This is NOT highly available and is NOT how the cloud cluster should
# run. Real 3-node HA with auto-unseal (KMS / Key Vault) belongs in the
# EKS/AKS script, where each peer is joined and unsealed properly.
#
# Rebuild is destructive of the local kind cluster only.

set -euo pipefail
cd "$(dirname "$0")"

# ---- config -------------------------------------------------------------
CLUSTER_NAME="vaultly"
VAULT_NS="vault"
APP_NS="vaultly"
VAULT_ROOT_TOKEN="vaultly-dev-root-token"
APP_IMAGE="vaultly:local"
PF_PID=""

# ---- helpers ------------------------------------------------------------
log() { printf '\n=== %s ===\n' "$*"; }

cleanup() {
  # always stop the port-forward we started, on success or failure
  if [[ -n "$PF_PID" ]] && kill -0 "$PF_PID" 2>/dev/null; then
    kill "$PF_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command '$1' not found in PATH." >&2
    exit 1
  }
}

# ---- 0: preflight -------------------------------------------------------
log "0/9: Preflight (checking required tools)"
for bin in kind kubectl helm docker vault; do require "$bin"; done

# ---- 1: kind cluster ----------------------------------------------------
log "1/9: Creating kind cluster '$CLUSTER_NAME'"
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  echo "Cluster '$CLUSTER_NAME' already exists. Run ./takedown.sh first for a clean rebuild." >&2
  exit 1
fi
kind create cluster --name "$CLUSTER_NAME" --config infra/kind/kind-config.yaml

# ---- 2: allow scheduling on the control-plane if needed -----------------
log "2/9: Removing control-plane taint (non-fatal if already absent)"
kubectl taint nodes "${CLUSTER_NAME}-control-plane" \
  node-role.kubernetes.io/control-plane:NoSchedule- 2>/dev/null || true

# ---- 3: namespaces (idempotent) -----------------------------------------
log "3/9: Creating namespaces"
kubectl create namespace "$VAULT_NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace "$APP_NS"  --dry-run=client -o yaml | kubectl apply -f -

# ---- 4: install Vault (DEV MODE) ----------------------------------------
log "4/9: Installing Vault in dev mode (single node, auto-unsealed)"
helm repo add hashicorp https://helm.releases.hashicorp.com >/dev/null 2>&1 || true
helm repo update >/dev/null 2>&1 || true
helm install vault hashicorp/vault \
  --namespace "$VAULT_NS" \
  --set "server.dev.enabled=true" \
  --set "server.dev.devRootToken=${VAULT_ROOT_TOKEN}" \
  --set "injector.enabled=false"

# ---- 5: wait for Vault to be Ready --------------------------------------
# rollout status waits for the StatefulSet's pod to become Ready and
# handles the brief window before the pod object exists (no hard-coded
# "vault-0 not found" race, and no blind sleeps).
log "5/9: Waiting for Vault to be Ready"
kubectl wait --for=condition=Ready pod \
  -l app.kubernetes.io/name=vault \
  -n vault \
  --timeout=120s   

# ---- 6: port-forward so the host vault CLI can configure Vault ----------
log "6/9: Port-forwarding vault 8200 -> localhost"
kubectl port-forward -n "$VAULT_NS" svc/vault 8200:8200 >/dev/null 2>&1 &
PF_PID=$!
export VAULT_ADDR="http://127.0.0.1:8200"
export VAULT_TOKEN="$VAULT_ROOT_TOKEN"
# wait until the API actually answers instead of guessing with sleep
for _ in $(seq 1 30); do
  if vault status >/dev/null 2>&1; then break; fi
  sleep 1
done
vault status >/dev/null || { echo "ERROR: Vault API not reachable on :8200" >&2; exit 1; }

# ---- 7: configure Vault (KV v2 + Kubernetes auth) -----------------------
log "7/9: Configuring Vault (KV v2 + Kubernetes auth)"
# dev mode already mounts KV v2 at secret/, so tolerate "already in use"
vault secrets enable -path=secret kv-v2 2>/dev/null || true

vault auth enable kubernetes 2>/dev/null || true
vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc"

vault policy write vaultly-policy - <<'EOF'
path "secret/data/vaultly/*" {
  capabilities = ["read", "create", "update"]
}
path "secret/metadata/vaultly/*" {
  capabilities = ["read", "list"]
}
EOF

vault write auth/kubernetes/role/vaultly \
  bound_service_account_names="vaultly-sa" \
  bound_service_account_namespaces="$APP_NS" \
  policies="vaultly-policy" \
  ttl=1h \
  max_ttl=4h

# ---- 8: Kubernetes RBAC for token review --------------------------------
log "8/9: Kubernetes RBAC (ServiceAccount + TokenReview binding)"
kubectl create serviceaccount vaultly-sa -n "$APP_NS" \
  --dry-run=client -o yaml | kubectl apply -f -
# lets Vault call the TokenReview API to validate the app pod's SA JWT
kubectl create clusterrolebinding vault-tokenreview-binding \
  --clusterrole=system:auth-delegator \
  --serviceaccount="${VAULT_NS}:vault" \
  --dry-run=client -o yaml | kubectl apply -f -

# ---- 9: build image, load into kind, deploy the app ---------------------
log "9/9: Building image, loading into kind, deploying Vaultly"
docker build -t "$APP_IMAGE" -f docker/Dockerfile .
kind load docker-image "$APP_IMAGE" --name "$CLUSTER_NAME"

# Dev-mode Vault exposes the 'vault' service. The 'vault-active' service
# only exists in HA mode, so the manifest's VAULTLY_VAULT_ADDR would not
# resolve here and the app would CrashLoop. The committed manifest keeps
# vault-active for the future cloud/HA deploy; override it for local dev
# at apply time instead of editing the file.
sed 's|vault-active\.vault\.svc|vault.vault.svc|' k8s/vaultly.yml \
  | kubectl apply -f -

kubectl rollout status deployment/vaultly -n "$APP_NS" --timeout=120s

# ---- done ---------------------------------------------------------------
log "DONE"
cat <<EOF
Cluster : $CLUSTER_NAME
Vault   : kubectl port-forward -n $VAULT_NS svc/vault 8200:8200   (root token: $VAULT_ROOT_TOKEN)
App     : kubectl port-forward -n $APP_NS  svc/vaultly 8080:8080

Smoke test (start the app port-forward above first, then in another shell):
  curl -s -X PUT http://127.0.0.1:8080/api/v1/secrets/vaultly/test \\
    -H "Content-Type: application/json" \\
    -H "Authorization: Bearer dev-token-change-me" \\
    -d '{"hello": "world"}'

  curl -s http://127.0.0.1:8080/api/v1/secrets/vaultly/test \\
    -H "Authorization: Bearer dev-token-change-me"
EOF
