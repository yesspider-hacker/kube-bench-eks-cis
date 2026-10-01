<#
  run.ps1 - Run kube-bench CIS EKS Job, collect JSON, and build the report.
  Windows PowerShell. Requires: kubectl (configured for your EKS cluster), python.

  Usage:
    .\run.ps1
    .\run.ps1 -Cluster "prod-banking-eks"
#>
param(
  [string]$Cluster = "(unspecified)",
  [string]$Namespace = "kube-bench",
  [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

Write-Host "==> Verifying cluster access..." -ForegroundColor Cyan
kubectl version --output=yaml *> $null
if (-not $?) { throw "kubectl cannot reach a cluster. Run 'aws eks update-kubeconfig --name <cluster> --region <region>' first." }

Write-Host "==> Cleaning any previous run..." -ForegroundColor Cyan
kubectl delete job kube-bench -n $Namespace --ignore-not-found=true *> $null

Write-Host "==> Applying job-eks.yaml..." -ForegroundColor Cyan
kubectl apply -f (Join-Path $ScriptDir "job-eks.yaml")

Write-Host "==> Waiting for job to complete (timeout ${TimeoutSeconds}s)..." -ForegroundColor Cyan
kubectl wait --for=condition=complete "job/kube-bench" -n $Namespace --timeout="${TimeoutSeconds}s"
if (-not $?) {
  Write-Host "Job did not report complete; collecting logs anyway for diagnosis." -ForegroundColor Yellow
}

Write-Host "==> Collecting results..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path (Join-Path $ScriptDir "reports") | Out-Null
$ResultFile = Join-Path $ScriptDir "reports\results.json"
kubectl logs "job/kube-bench" -n $Namespace | Out-File -FilePath $ResultFile -Encoding utf8

if (-not (Test-Path $ResultFile) -or (Get-Item $ResultFile).Length -eq 0) {
  throw "No output captured. Check: kubectl describe job kube-bench -n $Namespace"
}

Write-Host "==> Generating report..." -ForegroundColor Cyan
python (Join-Path $ScriptDir "generate_report.py") $ResultFile --out-dir (Join-Path $ScriptDir "reports") --cluster $Cluster

Write-Host "==> Cleaning up the job..." -ForegroundColor Cyan
kubectl delete job kube-bench -n $Namespace --ignore-not-found=true *> $null

Write-Host ""
Write-Host "Done. Open reports\kube-bench-report.html" -ForegroundColor Green
