#!/usr/bin/env python3
"""
Generate a banking-grade CIS EKS report from kube-bench JSON output.

Usage:
    python generate_report.py results.json [--out-dir ./reports] [--cluster NAME]

Produces:
    reports/kube-bench-report.md    (Markdown summary, FAIL/WARN first)
    reports/kube-bench-report.html  (styled, printable HTML)
    reports/kube-bench-findings.csv (one row per failed/warned check, for tracking)
"""
import argparse
import csv
import datetime as dt
import html
import json
import os
import sys

SEV_ORDER = {"FAIL": 0, "WARN": 1, "INFO": 2, "PASS": 3}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    # kube-bench may print a non-JSON preamble; slice from the first brace.
    start = raw.find("{")
    if start == -1:
        sys.exit(f"ERROR: no JSON object found in {path}")
    try:
        return json.loads(raw[start:])
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: failed to parse JSON in {path}: {e}")


def collect(data):
    """Flatten kube-bench JSON into a list of check dicts + totals."""
    checks = []
    totals = {"PASS": 0, "FAIL": 0, "WARN": 0, "INFO": 0}
    for control in data.get("Controls", []):
        bench = control.get("version", control.get("id", ""))
        for test in control.get("tests", []):
            section = test.get("section", "")
            section_desc = test.get("desc", "")
            for r in test.get("results", []):
                status = r.get("status", "INFO").upper()
                totals[status] = totals.get(status, 0) + 1
                checks.append({
                    "benchmark": bench,
                    "section": section,
                    "section_desc": section_desc,
                    "id": r.get("test_number", ""),
                    "desc": r.get("test_desc", ""),
                    "status": status,
                    "scored": r.get("scored", False),
                    "remediation": (r.get("remediation", "") or "").strip(),
                })
    checks.sort(key=lambda c: (SEV_ORDER.get(c["status"], 9), c["id"]))
    return checks, totals


def risk_grade(totals):
    fail = totals.get("FAIL", 0)
    warn = totals.get("WARN", 0)
    total = sum(totals.values()) or 1
    scored = totals.get("PASS", 0) + fail
    pass_rate = (totals.get("PASS", 0) / scored * 100) if scored else 0
    if fail == 0 and warn == 0:
        grade = "A  (Compliant)"
    elif fail == 0:
        grade = "B  (Pass, manual review items remain)"
    elif fail <= 3:
        grade = "C  (Minor gaps)"
    elif fail <= 8:
        grade = "D  (Significant gaps)"
    else:
        grade = "F  (Not compliant)"
    return grade, pass_rate


def write_csv(checks, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Status", "Scored", "Section", "Description", "Remediation"])
        for c in checks:
            if c["status"] in ("FAIL", "WARN"):
                w.writerow([c["id"], c["status"], c["scored"], c["section"],
                            c["desc"], c["remediation"]])


def write_md(checks, totals, meta, path):
    grade, pass_rate = risk_grade(totals)
    lines = []
    lines.append("# CIS Amazon EKS Benchmark — kube-bench Report")
    lines.append("")
    lines.append(f"- **Cluster:** {meta['cluster']}")
    lines.append(f"- **Generated:** {meta['generated']}")
    lines.append(f"- **Benchmark:** {meta['benchmark']}")
    lines.append(f"- **Profile:** banking / strong-compliance")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"| Result | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| ✅ PASS | {totals.get('PASS', 0)} |")
    lines.append(f"| ❌ FAIL | {totals.get('FAIL', 0)} |")
    lines.append(f"| ⚠️ WARN (manual) | {totals.get('WARN', 0)} |")
    lines.append(f"| ℹ️ INFO | {totals.get('INFO', 0)} |")
    lines.append("")
    lines.append(f"- **Compliance grade:** `{grade}`")
    lines.append(f"- **Scored pass rate:** {pass_rate:.1f}%")
    lines.append("")
    lines.append("> Banking note: every ❌ FAIL must be remediated or risk-accepted with "
                 "sign-off, and every ⚠️ WARN must be manually verified — several EKS "
                 "controls (audit logging, secrets encryption, private endpoint) are "
                 "confirmed at the AWS layer, not by kube-bench. Cross-check with "
                 "`aws eks describe-cluster` and Prowler.")
    lines.append("")

    for sev, title in (("FAIL", "❌ Failed Checks (remediate)"),
                       ("WARN", "⚠️ Manual Review Required"),
                       ("INFO", "ℹ️ Informational")):
        items = [c for c in checks if c["status"] == sev]
        if not items:
            continue
        lines.append(f"## {title} — {len(items)}")
        lines.append("")
        for c in items:
            lines.append(f"### `{c['id']}` {c['desc']}")
            lines.append(f"- **Section:** {c['section']} {c['section_desc']}")
            lines.append(f"- **Scored:** {c['scored']}")
            if c["remediation"]:
                lines.append(f"- **Remediation:**")
                for rl in c["remediation"].splitlines():
                    lines.append(f"  > {rl}")
            lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_html(checks, totals, meta, path):
    grade, pass_rate = risk_grade(totals)
    color = {"FAIL": "#c0392b", "WARN": "#b9770e", "PASS": "#1e8449", "INFO": "#2471a3"}

    def rows(sev):
        out = []
        for c in checks:
            if c["status"] != sev:
                continue
            rem = html.escape(c["remediation"]).replace("\n", "<br>")
            out.append(
                f"<tr><td class='id'>{html.escape(c['id'])}</td>"
                f"<td><span class='badge' style='background:{color[sev]}'>{sev}</span></td>"
                f"<td>{html.escape(c['desc'])}</td>"
                f"<td class='rem'>{rem}</td></tr>")
        return "\n".join(out)

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CIS EKS kube-bench Report</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px;
          background: #f7f7f8; color: #1a1a1a; }}
  @media (prefers-color-scheme: dark) {{ body {{ background:#15171a; color:#e8e8e8; }}
    .card,.table-wrap {{ background:#1e2126 !important; }} th {{ background:#262a30 !important; }} }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .meta {{ color:#666; font-size: 13px; margin-bottom: 20px; }}
  .cards {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; }}
  .card {{ background:#fff; border-radius:10px; padding:14px 18px; min-width:120px;
           box-shadow:0 1px 3px rgba(0,0,0,.1); }}
  .card .n {{ font-size:28px; font-weight:700; }}
  .card .l {{ font-size:12px; text-transform:uppercase; letter-spacing:.5px; color:#888; }}
  .grade {{ font-size:18px; font-weight:700; padding:14px 18px; border-radius:10px;
            background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.1); }}
  .note {{ background:#fff8e1; border-left:4px solid #f1c40f; padding:12px 16px;
           border-radius:6px; font-size:13px; margin:16px 0; color:#5b4b00; }}
  .table-wrap {{ background:#fff; border-radius:10px; overflow:hidden; margin:18px 0;
                 box-shadow:0 1px 3px rgba(0,0,0,.1); }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:left; padding:10px 12px; border-bottom:1px solid rgba(128,128,128,.2);
           vertical-align:top; }}
  th {{ background:#f0f0f2; font-size:11px; text-transform:uppercase; letter-spacing:.5px; }}
  .id {{ font-family: ui-monospace, monospace; white-space:nowrap; }}
  .rem {{ font-size:12px; color:#555; }}
  .badge {{ color:#fff; padding:2px 8px; border-radius:10px; font-size:11px; font-weight:700; }}
  h2 {{ margin-top:28px; font-size:16px; }}
  @media print {{ body {{ background:#fff; }} .card,.table-wrap {{ box-shadow:none; border:1px solid #ddd; }} }}
</style></head><body>
<h1>CIS Amazon EKS Benchmark — kube-bench Report</h1>
<div class="meta">Cluster: <b>{html.escape(meta['cluster'])}</b> &nbsp;|&nbsp;
  Benchmark: {html.escape(meta['benchmark'])} &nbsp;|&nbsp;
  Generated: {html.escape(meta['generated'])} &nbsp;|&nbsp; Profile: banking</div>
<div class="cards">
  <div class="card"><div class="n" style="color:{color['PASS']}">{totals.get('PASS',0)}</div><div class="l">Pass</div></div>
  <div class="card"><div class="n" style="color:{color['FAIL']}">{totals.get('FAIL',0)}</div><div class="l">Fail</div></div>
  <div class="card"><div class="n" style="color:{color['WARN']}">{totals.get('WARN',0)}</div><div class="l">Warn</div></div>
  <div class="card"><div class="n" style="color:{color['INFO']}">{totals.get('INFO',0)}</div><div class="l">Info</div></div>
  <div class="grade">Grade: {html.escape(grade)}<br><span style="font-weight:400;font-size:13px">Scored pass rate: {pass_rate:.1f}%</span></div>
</div>
<div class="note"><b>Banking note:</b> remediate or formally risk-accept every FAIL; manually
verify every WARN. AWS-layer controls (audit logging, secrets KMS encryption, private API
endpoint) are confirmed via <code>aws eks describe-cluster</code> and Prowler, not kube-bench.</div>

<h2>❌ Failed Checks</h2>
<div class="table-wrap"><table><tr><th>ID</th><th>Status</th><th>Check</th><th>Remediation</th></tr>
{rows('FAIL') or '<tr><td colspan=4>None 🎉</td></tr>'}</table></div>

<h2>⚠️ Manual Review Required</h2>
<div class="table-wrap"><table><tr><th>ID</th><th>Status</th><th>Check</th><th>Remediation</th></tr>
{rows('WARN') or '<tr><td colspan=4>None</td></tr>'}</table></div>

</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file")
    ap.add_argument("--out-dir", default="reports")
    ap.add_argument("--cluster", default="(unspecified)")
    args = ap.parse_args()

    data = load_json(args.json_file)
    checks, totals = collect(data)
    os.makedirs(args.out_dir, exist_ok=True)

    bench = ""
    if data.get("Controls"):
        bench = data["Controls"][0].get("version", "eks")
    meta = {
        "cluster": args.cluster,
        "benchmark": bench or "eks",
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    md = os.path.join(args.out_dir, "kube-bench-report.md")
    htmlf = os.path.join(args.out_dir, "kube-bench-report.html")
    csvf = os.path.join(args.out_dir, "kube-bench-findings.csv")
    write_md(checks, totals, meta, md)
    write_html(checks, totals, meta, htmlf)
    write_csv(checks, csvf)

    print(f"PASS={totals.get('PASS',0)} FAIL={totals.get('FAIL',0)} "
          f"WARN={totals.get('WARN',0)} INFO={totals.get('INFO',0)}")
    print("Reports written:")
    for p in (md, htmlf, csvf):
        print("  -", p)


if __name__ == "__main__":
    main()
