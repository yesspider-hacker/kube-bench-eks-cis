#!/usr/bin/env bash
# run.sh - Run kube-bench CIS EKS Job, collect JSON, and build the report.
# Requires: kubectl (configured for your EKS cluster), python3.
#
# Usage:
#   ./run.sh
#   CLUSTER="prod-banking-eks" ./run.sh

set -euo pipefail

CLUSTER="${CLUSTER:-(unspecified)}"
NAMESPACE="${NAMESPACE:-kube-bench}"
TIMEOUT="${TIMEOUT:-300s}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "==> Verifying cluster access..."
kubectl version >/dev/null 2>&1 || {
  echo "ERROR: kubectl cannot reach a cluster."
  echo "Run: aws eks update-kubeconfig --name <cluster> --region <region>"
  exit 1
}

echo "==> Cleaning any previous run..."
kubectl delete job kube-bench -n "$NAMESPACE" --ignore-not-found=true >/dev/null 2>&1 || true

echo "==> Applying job-eks.yaml..."
kubectl apply -f "$DIR/job-eks.yaml"

echo "==> Waiting for job to complete (timeout $TIMEOUT)..."
kubectl wait --for=condition=complete job/kube-bench -n "$NAMESPACE" --timeout="$TIMEOUT" || \
  echo "WARN: job did not report complete; collecting logs anyway."

echo "==> Collecting results..."
mkdir -p "$DIR/reports"
kubectl logs job/kube-bench -n "$NAMESPACE" > "$DIR/reports/results.json"

[ -s "$DIR/reports/results.json" ] || {
  echo "ERROR: no output captured. Check: kubectl describe job kube-bench -n $NAMESPACE"
  exit 1
}

echo "==> Generating report..."
python3 "$DIR/generate_report.py" "$DIR/reports/results.json" \
  --out-dir "$DIR/reports" --cluster "$CLUSTER"

echo "==> Cleaning up the job..."
kubectl delete job kube-bench -n "$NAMESPACE" --ignore-not-found=true >/dev/null 2>&1 || true

echo ""
echo "Done. Open reports/kube-bench-report.html"
