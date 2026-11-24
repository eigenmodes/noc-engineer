#!/bin/sh
# Install Langfuse for the NOC agent. Run from deploy/langfuse/ with kubectl + helm (>= 3.17) pointed at the cluster.
# Versions match the langfuse-k8s minimal-installation example (chart 2.x). Air-gapped: see LANGFUSE.md first.
set -eu
NS=${NS:-langfuse}
CHART=${CHART:-oci://ghcr.io/langfuse/langfuse-k8s/charts/langfuse}
CHART_VERSION=${CHART_VERSION:-2.2.6}

# 1. Cluster prerequisites for the bundled ClickHouse (once per cluster; skip if present)
if ! kubectl get crd clickhouseclusters.clickhouse.com >/dev/null 2>&1; then
  kubectl get crd certificates.cert-manager.io >/dev/null 2>&1 || \
    helm install cert-manager oci://quay.io/jetstack/charts/cert-manager --version v1.20.2 \
      --namespace cert-manager --create-namespace --set crds.enabled=true
  kubectl wait --for=condition=Established crd/certificates.cert-manager.io crd/issuers.cert-manager.io --timeout=120s
  helm install clickhouse-operator oci://ghcr.io/clickhouse/clickhouse-operator-helm --version 0.0.8 \
    --namespace clickhouse-operator --create-namespace
  kubectl wait --for=condition=Established crd/clickhouseclusters.clickhouse.com crd/keeperclusters.clickhouse.com --timeout=120s
fi

# 2. Namespace + secrets (secret.yaml = your filled copy of secret.example.yaml, never committed)
kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create namespace "$NS"
kubectl apply -n "$NS" -f secret.yaml

# 3. Langfuse
helm upgrade --install langfuse "$CHART" --version "$CHART_VERSION" -n "$NS" -f values.yaml
kubectl -n "$NS" rollout status deploy/langfuse-web --timeout=600s
echo "Langfuse is up. Next: python3 bootstrap.py (models + score configs), then connect Hermes (LANGFUSE.md step 4)."
