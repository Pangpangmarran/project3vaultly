#!/bin/bash
# Start-of-day rebuild. Creates everything from scratch.
# Local dev: 1 replica (no Raft quorum issues).
# Cloud (EKS/AKS): use replicas=3 in a separate script.
set -e

cd "$(dirname "$0")"

CLUSTER_NAME="vaultly"
VAULT_NS="vault"
APP_NS="vaultly"
CRED_FILE=".vault-local-credentials"

echo "=== 1/10: Creating kind cluster ==="
kind create cluster --name "$CLUSTER_NAME" --config infra/kind/kind-config.yaml

echo "=== 2/10: Removing control-plane taint ==="
kubectl taint nodes "${CLUSTER_NAME}-control-plane" \
  node-role.kubernetes.io/control-plane:NoSchedule-

echo "=== 3/10: Creating namespaces ==="
kubectl create ns "$VAULT_NS"
kubectl create ns "$APP_NS"

echo "=== 4/10: Installing Vault (single node, local dev) ==="
helm repo add hashicorp https://helm.releases.hashicorp.com 2>/dev/null || true
helm install vault hashicorp/vault --namespace "$VAULT_NS" \
  --set "server.ha.enabled=true" \
  --set "server.ha.raft.enabled=true" \
  --set "server.ha.replicas=1"   
  
echo "=== 5/10: Waiting for vault-0 ==="
echo "Waiting for pod to appear..."
for i in $(seq 1 30); do
  if kubectl get pod vault-0 -n "$VAULT_NS" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
kubectl wait --for=condition=ready pod/vault-0 -n "$VAULT_NS" --timeout=300s   

echo "=== 6/10: Initializing Vault (Shamir 5/3) ==="
kubectl port-forward -n "$VAULT_NS" svc/vault-active 8200:8200 &
PF_PID=$!
sleep 3

export VAULT_ADDR=http://127.0.0.1:8200

INIT_JSON=$(vault operator init -format=json)
ROOT_TOKEN=$(echo "$INIT_JSON" | jq -r '.root_token')

cat > "$CRED_FILE" << CREDS
root_token=$ROOT_TOKEN
unseal_keys:
$(echo "$INIT_JSON" | jq -r '.unseal_keys_b64[] | "  " + .')
CREDS
chmod 600 "$CRED_FILE"

for key in $(echo "$INIT_JSON" | jq -r '.unseal_keys_b64[0:3][]'); do
  vault operator unseal <<< "$key"
done

echo "Vault initialized and unsealed. Credentials in ./$CRED_FILE"

echo "=== 7/10: Configuring Vault (KV v2 + K8s auth) ==="
export VAULT_TOKEN="$ROOT_TOKEN"

vault secrets enable -path=secret kv-v2 2>/dev/null || true

vault auth enable kubernetes 2>/dev/null || true
vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc"

cat > /tmp/vaultly-policy.hcl << 'EOF'
path "secret/data/vaultly/*" {
  capabilities = ["read", "create", "update"]
}
path "secret/metadata/vaultly/*" {
  capabilities = ["read", "list"]
}
EOF
vault policy write vaultly-policy /tmp/vaultly-policy.hcl

vault write auth/kubernetes/role/vaultly \
  bound_service_account_names=vaultly-sa \
  bound_service_account_namespaces="$APP_NS" \
  policies=vaultly-policy \
  ttl=1h \
  max_ttl=4h

echo "=== 8/10: K8s RBAC (ServiceAccount + TokenReview binding) ==="
kubectl create serviceaccount vaultly-sa -n "$APP_NS"
kubectl create clusterrolebinding vault-tokenreview-binding \
  --clusterrole=system:auth-delegator \
  --serviceaccount="${VAULT_NS}:vault"

echo "=== 9/10: Building and loading Docker image ==="
docker build -t vaultly:local -f docker/Dockerfile .
kind load docker-image vaultly:local --name "$CLUSTER_NAME"

echo "=== 10/10: Deploying Vaultly ==="
kubectl apply -f k8s/vaultly.yml
kubectl wait --for=condition=ready pod -l app=vaultly -n "$APP_NS" --timeout=120s

kill $PF_PID 2>/dev/null || true

echo ""
echo "=== DONE ==="
echo "Cluster: $CLUSTER_NAME"
echo "Vault:   kubectl port-forward -n $VAULT_NS svc/vault-active 8200:8200"
echo "App:     kubectl port-forward -n $APP_NS svc/vaultly 8080:8080"
echo "Test:    curl -X PUT http://127.0.0.1:8080/api/v1/secrets/vaultly/test \\"
echo "         -H 'Content-Type: application/json' \\"
echo "         -H 'Authorization: Bearer dev-token-change-me' \\"
echo "         -d '{\"data\": \"hello\"}'"   