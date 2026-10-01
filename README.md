# CIS Amazon EKS Benchmark — kube-bench (Banking / Strong-Compliance Profile)

Runs the **CIS Amazon EKS Benchmark** against your cluster using
[kube-bench](https://github.com/aquasecurity/kube-bench), then produces a
clean **HTML + Markdown + CSV** report suitable for an audit or VAPT deliverable.

This profile is tuned for banking / financial-grade review:
- Runs all three targets: `node`, `policies`, `managedservices`
- Dedicated `kube-bench` namespace + **least-privilege RBAC** (no default ServiceAccount)
- Hardened pod securityContext (drops all caps, read-only root FS)
- Skips Fargate nodes automatically (kube-bench needs host filesystem access)
- JSON output → graded report (PASS / FAIL / WARN / INFO) with remediation per finding

> ⚠️ **AWS manages the EKS control plane.** kube-bench cannot verify master/etcd
> settings. Controls like audit logging, secrets KMS encryption, and private API
> endpoint show as **WARN** and must be confirmed at the AWS layer (see
> [Step 6](#6-cross-check-the-aws-layer-important-for-banking)).

---

## Files

| File | Purpose |
|------|---------|
| `job-eks.yaml` | The kube-bench Kubernetes Job + namespace + RBAC |
| `generate_report.py` | Parses kube-bench JSON → HTML / Markdown / CSV report |
| `run.ps1` | One-command runner for **Windows PowerShell** |
| `run.sh` | One-command runner for **Linux / macOS / WSL** |
| `reports/` | Created on run — contains `results.json` + the reports |

---

## Prerequisites

1. **kubectl** installed and pointed at the target cluster:
   ```bash
   aws eks update-kubeconfig --name <cluster-name> --region <region>
   kubectl get nodes          # confirm you can see worker nodes
   ```
2. **AWS CLI** configured with credentials that can reach the cluster.
3. **Python 3** (for the report generator). Check with `python --version`.
4. Worker nodes able to pull `docker.io/aquasec/kube-bench` (see
   [Air-gapped / ECR](#air-gapped--private-clusters-ecr) if not).
5. Your kubeconfig identity must be mapped in the cluster's `aws-auth`
   ConfigMap (or an EKS access entry) with rights to create namespaces, jobs,
   and clusterrolebindings.

---

## Quick Start

### Windows (PowerShell)
```powershell
cd <this-folder>
.\run.ps1 -Cluster "prod-banking-eks"
```

### Linux / macOS / WSL
```bash
cd <this-folder>
chmod +x run.sh
CLUSTER="prod-banking-eks" ./run.sh
```

The script will: clean old runs → apply the job → wait for completion →
pull JSON → build the report → delete the job. Then open:

```
reports/kube-bench-report.html
```

---

## Manual Steps (if you prefer not to use the runner)

### 1. Match the benchmark to your Kubernetes version
Check your version:
```bash
kubectl version
```
Edit `job-eks.yaml` → `--benchmark eks-1.5.0` if a different version fits, and
confirm the image tag against the
[releases page](https://github.com/aquasecurity/kube-bench/releases).

### 2. Apply the job
```bash
kubectl apply -f job-eks.yaml
```

### 3. Wait for it to finish
```bash
kubectl wait --for=condition=complete job/kube-bench -n kube-bench --timeout=300s
```

### 4. Collect the JSON results
```bash
kubectl logs job/kube-bench -n kube-bench > reports/results.json
```

### 5. Generate the report
```bash
python generate_report.py reports/results.json --out-dir reports --cluster "prod-banking-eks"
```

Outputs:
- `reports/kube-bench-report.html` — styled, printable (save as PDF for the client)
- `reports/kube-bench-report.md` — Markdown summary
- `reports/kube-bench-findings.csv` — one row per FAIL/WARN, for a tracker

### 6. Cross-check the AWS layer (important for banking)
kube-bench's WARN items need AWS-side confirmation:
```bash
aws eks describe-cluster --name <cluster> --region <region> \
  --query 'cluster.{Endpoint:resourcesVpcConfig.endpointPublicAccess, \
           PublicCIDRs:resourcesVpcConfig.publicAccessCidrs, \
           Logging:logging.clusterLogging, \
           SecretsEncryption:encryptionConfig}'
```
Confirm:
- `endpointPublicAccess: false` (or tightly restricted `publicAccessCidrs`)
- All 5 control-plane log types enabled (`api, audit, authenticator, controllerManager, scheduler`)
- `encryptionConfig` present (KMS envelope encryption for secrets)

For a fuller cloud-posture pass, also run
[Prowler](https://github.com/prowler-cloud/prowler): `prowler aws --services eks`.

### 7. Clean up
```bash
kubectl delete -f job-eks.yaml
```

---

## Reading the Results

| Status | Meaning | Action for banking |
|--------|---------|--------------------|
| ✅ PASS | Control met | None |
| ❌ FAIL | Control not met | **Remediate**, or risk-accept with documented sign-off |
| ⚠️ WARN | Needs manual verification | **Must** be manually checked and evidenced |
| ℹ️ INFO | Informational | Review |

The report's **grade** (A–F) and **scored pass rate** give a quick posture
snapshot; the FAIL and WARN tables list each check with its remediation text.

---

## Air-gapped / Private Clusters (ECR)

If nodes can't reach Docker Hub, mirror the image to ECR and update the job:
```bash
aws ecr create-repository --repository-name kube-bench
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=<region>
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com
docker pull aquasec/kube-bench:v0.10.7
docker tag  aquasec/kube-bench:v0.10.7 $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/kube-bench:v0.10.7
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/kube-bench:v0.10.7
```
Then set `image:` in `job-eks.yaml` to the ECR URI.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `kubectl cannot reach a cluster` | Run `aws eks update-kubeconfig ...` |
| Job `Pending`, never schedules | Only Fargate nodes present — kube-bench needs an EC2 node group |
| `ImagePullBackOff` | Private cluster — use the ECR steps above |
| Empty `results.json` | `kubectl describe job kube-bench -n kube-bench` and check events |
| Pod blocked by Pod Security Admission | The job uses host mounts + hostPID; run it in a namespace labeled `pod-security.kubernetes.io/enforce: privileged` (the `kube-bench` namespace here is unlabeled/privileged by default) |
| `python` not found (Windows) | Install Python 3 or use `py generate_report.py ...` |

---

## Notes on Scope

This tool covers the **Kubernetes/CIS layer** of an EKS VAPT. A complete
engagement also includes IAM/IRSA review, IMDS/SSRF testing, image scanning
(Trivy), RBAC analysis (kubiscan), and network-policy testing. kube-bench is
the CIS-benchmark component of that larger assessment.
