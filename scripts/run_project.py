from __future__ import annotations

import argparse
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import matplotlib.pyplot as plt
import numpy as np
import scipy
from matplotlib.backends.backend_pdf import PdfPages

from smart_grid.cps_grid import SEED, full_project_results


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _table(headers: list[str], rows: list[list[Any]], digits: int = 4) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(cell, digits) for cell in row) + " |")
    return "\n".join(lines)


def _matrix_rows(matrix: list[list[float]], row_labels: list[str], col_labels: list[str]) -> str:
    rows = []
    for label, row in zip(row_labels, matrix):
        rows.append([label, *row])
    return _table(["", *col_labels], rows, digits=4)


def _html_table(headers: list[str], rows: list[list[Any]], digits: int = 4) -> str:
    head = "".join(f"<th>{header}</th>" for header in headers)
    body = []
    for row in rows:
        body.append(
            "<tr>" + "".join(f"<td>{_fmt(cell, digits)}</td>" for cell in row) + "</tr>"
        )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _html_matrix(matrix: list[list[float]], row_labels: list[str], col_labels: list[str]) -> str:
    rows = [[label, *row] for label, row in zip(row_labels, matrix)]
    return _html_table(["", *col_labels], rows, digits=4)


def build_markdown(results: dict[str, Any]) -> str:
    phase1 = results["phase1"]
    phase2 = results["phase2"]
    phase3 = results["phase3"]
    phase4 = results["phase4"]
    phase5 = results["phase5"]
    branches = results["scenario"]["branches"]

    flow_rows = [
        [branch["name"], phase1["line_flows_mw"][idx], phase1["ptdf_flow_crosscheck_mw"][idx]]
        for idx, branch in enumerate(branches)
    ]
    screening_rows = [
        [
            row["outage"],
            row["max_loading_pct"],
            row["worst_line"],
            row["overloaded"],
        ]
        for row in phase3["screening"]
    ]
    dispatch_rows = [
        [
            f"G{gid}",
            phase2["base_dcopf"]["dispatch_mw"][gid],
            phase4["scopf"]["dispatch_mw"][gid],
            phase4["scopf"]["dispatch_mw"][gid] - phase2["base_dcopf"]["dispatch_mw"][gid],
        ]
        for gid in phase2["base_dcopf"]["dispatch_mw"]
    ]
    state_rows = [
        [
            row["dispatch"],
            row["scenario"],
            row["max_loading_pct"],
            row["cost_usd_per_h"],
        ]
        for row in phase5["operating_state_table"]
    ]

    return f"""# CPS Smart Grid Simulation Report

Author: {os.getenv("SMART_GRID_AUTHOR", "Surname Name")}  
Generated: {datetime.now(timezone.utc).isoformat()}  
Seed: `{SEED}`  
Solver: `{results["metadata"]["solver"]}`

## Introduction

This report reproduces the course project pipeline for the custom 5-bus DC network:
DC power flow, PTDF, LODF, DCOPF, N-1 screening, single-contingency SCOPF, and the
operating-state comparison.

Use of generative AI tools is disclosed for implementation assistance. Numerical values
are produced by `scripts/run_project.py`.

## Phase 1: Ybus/DC PF/PTDF

Base dispatch for the foundation check: `{phase1["dispatch_mw"]}` MW.

Angles in radians:

{_table(["Bus", "theta"], [[idx + 1, val] for idx, val in enumerate(phase1["angles_rad"])])}

Line-flow cross-check:

{_table(["Line", "Direct DC PF MW", "PTDF MW"], flow_rows)}

Maximum cross-check error: `{phase1["max_flow_crosscheck_error_mw"]:.8f}` MW.  
Slack column of PTDF is zero: `{phase1["ptdf_slack_column_zero"]}`.

PTDF:

{_matrix_rows(phase1["ptdf"], [b["name"] for b in branches], ["Bus 1", "Bus 2", "Bus 3", "Bus 4", "Bus 5"])}

## Phase 2: DCOPF And LMPs

Base DCOPF cost: `{phase2["base_dcopf"]["total_cost_usd_per_h"]:.2f}` USD/h.  
Base dispatch: `{phase2["base_dcopf"]["dispatch_mw"]}` MW.  
Base LMPs: `{[_fmt(v, 2) for v in phase2["base_dcopf"]["lmps_usd_per_mwh"]]}` USD/MWh.  
Binding base lines: `{phase2["base_dcopf"]["binding_lines"]}`.

With engineered congestion `L2 = 30 MW`, cost is
`{phase2["congested_l2_30"]["total_cost_usd_per_h"]:.2f}` USD/h and dispatch is
`{phase2["congested_l2_30"]["dispatch_mw"]}` MW.

## Phase 3: LODF And N-1 Screening

LODF matrix:

{_matrix_rows(phase3["lodf"], [b["name"] for b in branches], [b["name"] for b in branches])}

Explicit LODF value `L_L3,L1 = {phase3["lodf_l3_l1"]:.4f}`.

Contingency table:

{_table(["Outage", "Max loading %", "Worst line", "Overloaded"], screening_rows, digits=2)}

Worst contingency: `{phase3["worst_contingency"]["outage"]}`.

Physical/adversarial event: {phase3["event_sentence"]}

## Phase 4: SCOPF

SCOPF enforced contingencies: `{phase4["contingencies"]}`.  
SCOPF cost: `{phase4["scopf"]["total_cost_usd_per_h"]:.2f}` USD/h.  
SCOPF dispatch: `{phase4["scopf"]["dispatch_mw"]}` MW.  
SCOPF LMPs: `{[_fmt(v, 2) for v in phase4["scopf"]["lmps_usd_per_mwh"]]}` USD/MWh.

Dispatch comparison:

{_table(["Generator", "Base DCOPF MW", "SCOPF MW", "Move MW"], dispatch_rows, digits=4)}

Cost of security: `{phase4["cost_of_security_usd_per_h"]:.2f}` USD/h
(`{phase4["cost_of_security_pct"]:.2f}%` of base DCOPF cost).

SCOPF post-contingency max loading under the selected outage:
`{phase4["scopf_post_contingency"]["max_loading_pct"]:.2f}%`.

## Phase 5: Operating-State Analysis

{_table(["Dispatch", "Scenario", "Max loading %", "Cost USD/h"], state_rows, digits=2)}

Interpretation: {phase5["interpretation"]}

Cyber-physical reflection: {phase5["cyber_physical_reflection"]}

## Conclusion

The implementation provides a reproducible numerical pipeline and an API surface for
rerunning the project calculations locally or in Docker.
"""


def write_chart(results: dict[str, Any], output_path: Path) -> None:
    rows = results["phase5"]["operating_state_table"]
    labels = [f"{row['dispatch']}\n{row['scenario']}" for row in rows]
    values = [row["max_loading_pct"] for row in rows]
    plt.figure(figsize=(10, 4.8))
    plt.bar(labels, values, color=["#2a9d8f", "#e76f51", "#457b9d", "#6d597a"])
    plt.axhline(100.0, color="#333333", linestyle="--", linewidth=1)
    plt.ylabel("Max line loading (%)")
    plt.xticks(rotation=12, ha="right")
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=160)
    plt.close()


def build_html(results: dict[str, Any], chart_path: Path) -> str:
    phase1 = results["phase1"]
    phase2 = results["phase2"]
    phase3 = results["phase3"]
    phase4 = results["phase4"]
    phase5 = results["phase5"]
    branches = results["scenario"]["branches"]
    chart_src = chart_path.name

    flow_rows = [
        [branch["name"], phase1["line_flows_mw"][idx], phase1["ptdf_flow_crosscheck_mw"][idx]]
        for idx, branch in enumerate(branches)
    ]
    screening_rows = [
        [row["outage"], row["max_loading_pct"], row["worst_line"], row["overloaded"]]
        for row in phase3["screening"]
    ]
    dispatch_rows = [
        [
            f"G{gid}",
            phase2["base_dcopf"]["dispatch_mw"][gid],
            phase4["scopf"]["dispatch_mw"][gid],
            phase4["scopf"]["dispatch_mw"][gid] - phase2["base_dcopf"]["dispatch_mw"][gid],
        ]
        for gid in phase2["base_dcopf"]["dispatch_mw"]
    ]
    state_rows = [
        [row["dispatch"], row["scenario"], row["max_loading_pct"], row["cost_usd_per_h"]]
        for row in phase5["operating_state_table"]
    ]

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>CPS Smart Grid Simulation Report</title>
  <style>
    @page {{
      size: A4;
      margin: 16mm 14mm;
      @bottom-right {{ content: "Page " counter(page) " / " counter(pages); color: #7b8190; font-size: 9px; }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      color: #17202a;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      font-size: 10.2px;
      line-height: 1.45;
      margin: 0;
    }}
    .cover {{
      border-bottom: 3px solid #1f6f78;
      margin-bottom: 16px;
      padding-bottom: 14px;
    }}
    .eyebrow {{
      color: #1f6f78;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    h1 {{
      color: #121826;
      font-size: 27px;
      line-height: 1.05;
      margin: 7px 0 8px;
    }}
    h2 {{
      border-bottom: 1px solid #d9dee8;
      color: #1f2d3d;
      font-size: 15px;
      margin: 18px 0 8px;
      padding-bottom: 4px;
    }}
    h3 {{
      color: #1f2d3d;
      font-size: 12px;
      margin: 12px 0 6px;
    }}
    p {{ margin: 5px 0 8px; }}
    .meta {{
      color: #4f5d75;
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      margin-top: 12px;
    }}
    .meta div, .metric {{
      background: #f5f7fa;
      border: 1px solid #e1e7ef;
      border-radius: 6px;
      padding: 8px;
    }}
    .label {{
      color: #687385;
      display: block;
      font-size: 8px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .value {{
      color: #17202a;
      display: block;
      font-size: 12px;
      font-weight: 700;
      margin-top: 2px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      margin: 10px 0 12px;
    }}
    table {{
      border-collapse: collapse;
      margin: 7px 0 12px;
      width: 100%;
    }}
    th {{
      background: #1f6f78;
      color: white;
      font-size: 8.8px;
      padding: 5px 6px;
      text-align: left;
    }}
    td {{
      border-bottom: 1px solid #e7ebf1;
      font-size: 8.7px;
      padding: 4px 6px;
      vertical-align: top;
    }}
    tr:nth-child(even) td {{ background: #f8fafc; }}
    .two-col {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }}
    .note {{
      background: #fff7ed;
      border-left: 4px solid #e76f51;
      padding: 8px 10px;
    }}
    .chart {{
      border: 1px solid #e1e7ef;
      border-radius: 6px;
      margin-top: 8px;
      padding: 8px;
      width: 100%;
    }}
    code {{
      background: #eef2f7;
      border-radius: 4px;
      padding: 1px 4px;
    }}
  </style>
</head>
<body>
  <section class="cover">
    <div class="eyebrow">Cyber-Physical Systems for Power & Smart Grids</div>
    <h1>5-Bus Smart Grid Simulation</h1>
    <p>End-to-end DC PF, PTDF/LODF, DCOPF, N-1 screening and preventive SCOPF pipeline.</p>
    <div class="meta">
      <div><span class="label">Author</span><span class="value">{os.getenv("SMART_GRID_AUTHOR", "Surname Name")}</span></div>
      <div><span class="label">Generated</span><span class="value">{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</span></div>
      <div><span class="label">Seed</span><span class="value">{SEED}</span></div>
      <div><span class="label">Solver</span><span class="value">HiGHS LP</span></div>
    </div>
  </section>

  <section class="metrics">
    <div class="metric"><span class="label">Base DCOPF Cost</span><span class="value">{phase2["base_dcopf"]["total_cost_usd_per_h"]:.2f} USD/h</span></div>
    <div class="metric"><span class="label">Worst Contingency</span><span class="value">{phase3["worst_contingency"]["outage"]}</span></div>
    <div class="metric"><span class="label">SCOPF Cost</span><span class="value">{phase4["scopf"]["total_cost_usd_per_h"]:.2f} USD/h</span></div>
    <div class="metric"><span class="label">Security Premium</span><span class="value">{phase4["cost_of_security_usd_per_h"]:.2f} USD/h</span></div>
  </section>

  <h2>1. Power-System Foundations</h2>
  <div class="two-col">
    <div>
      <h3>Bus Angles</h3>
      {_html_table(["Bus", "Theta rad"], [[idx + 1, val] for idx, val in enumerate(phase1["angles_rad"])])}
    </div>
    <div>
      <h3>Line-Flow Cross-Check</h3>
      {_html_table(["Line", "Direct MW", "PTDF MW"], flow_rows)}
    </div>
  </div>
  <p>Maximum DC PF vs PTDF flow error: <code>{phase1["max_flow_crosscheck_error_mw"]:.8f} MW</code>.
  Slack PTDF column equals zero: <code>{phase1["ptdf_slack_column_zero"]}</code>.</p>
  <h3>PTDF Matrix</h3>
  {_html_matrix(phase1["ptdf"], [b["name"] for b in branches], ["Bus 1", "Bus 2", "Bus 3", "Bus 4", "Bus 5"])}

  <h2>2. DCOPF And LMPs</h2>
  <p>Base dispatch: <code>{phase2["base_dcopf"]["dispatch_mw"]}</code> MW.
  Base LMPs: <code>{[_fmt(v, 2) for v in phase2["base_dcopf"]["lmps_usd_per_mwh"]]}</code> USD/MWh.
  Binding base lines: <code>{phase2["base_dcopf"]["binding_lines"]}</code>.</p>
  <p>With engineered congestion <code>L2 = 30 MW</code>, dispatch becomes
  <code>{phase2["congested_l2_30"]["dispatch_mw"]}</code> MW and cost is
  <code>{phase2["congested_l2_30"]["total_cost_usd_per_h"]:.2f} USD/h</code>.</p>

  <h2>3. LODF And N-1 Screening</h2>
  <p>Explicit LODF value <code>L_L3,L1 = {phase3["lodf_l3_l1"]:.4f}</code>.</p>
  {_html_table(["Outage", "Max loading %", "Worst line", "Overloaded"], screening_rows, digits=2)}
  <p class="note">{phase3["event_sentence"]}</p>

  <h2>4. Security-Constrained DCOPF</h2>
  <p>SCOPF enforced contingencies: <code>{phase4["contingencies"]}</code>.
  SCOPF LMPs: <code>{[_fmt(v, 2) for v in phase4["scopf"]["lmps_usd_per_mwh"]]}</code> USD/MWh.</p>
  {_html_table(["Generator", "Base DCOPF MW", "SCOPF MW", "Move MW"], dispatch_rows)}
  <p>Cost of security: <strong>{phase4["cost_of_security_usd_per_h"]:.2f} USD/h</strong>
  ({phase4["cost_of_security_pct"]:.2f}% of base DCOPF cost). Post-contingency SCOPF max loading:
  <strong>{phase4["scopf_post_contingency"]["max_loading_pct"]:.2f}%</strong>.</p>

  <h2>5. Operating-State Analysis</h2>
  {_html_table(["Dispatch", "Scenario", "Max loading %", "Cost USD/h"], state_rows, digits=2)}
  <img class="chart" src="{chart_src}" alt="Operating-state loading chart">
  <p>{phase5["interpretation"]}</p>
  <p>{phase5["cyber_physical_reflection"]}</p>

  <h2>6. Reproducibility</h2>
  <p>The numerical output is generated by <code>scripts/run_project.py</code>. Toolchain:
  Python {sys.version.split()[0]}, NumPy {np.__version__}, SciPy {scipy.__version__},
  solver <code>{results["metadata"]["solver"]}</code>.</p>
  <p>Use of generative AI tools is disclosed for implementation assistance. Numerical values are produced by the project code.</p>
</body>
</html>
"""


def write_pdf(markdown: str, chart_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    paragraphs = [line for line in markdown.splitlines() if line.strip()]
    with PdfPages(output_path) as pdf:
        page_lines: list[str] = []
        for line in paragraphs:
            page_lines.append(line[:115])
            if len(page_lines) >= 34:
                fig = plt.figure(figsize=(8.27, 11.69))
                fig.text(0.08, 0.95, "\n".join(page_lines), va="top", family="monospace", fontsize=8)
                pdf.savefig(fig)
                plt.close(fig)
                page_lines = []
        if page_lines:
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.text(0.08, 0.95, "\n".join(page_lines), va="top", family="monospace", fontsize=8)
            pdf.savefig(fig)
            plt.close(fig)


def write_styled_pdf(html: str, html_path: Path, pdf_path: Path) -> None:
    html_path.write_text(html, encoding="utf-8")
    try:
        from weasyprint import HTML
    except Exception:
        write_pdf(html, html_path.with_name("operating_state_loading.png"), pdf_path)
        return
    HTML(filename=str(html_path)).write_pdf(str(pdf_path))
        if chart_path.exists():
            image = plt.imread(chart_path)
            fig = plt.figure(figsize=(11.69, 8.27))
            plt.imshow(image)
            plt.axis("off")
            pdf.savefig(fig)
            plt.close(fig)


def print_summary(results: dict[str, Any]) -> None:
    print(f"SmartGridSimulation | {datetime.now(timezone.utc).isoformat()}")
    print(f"Python: {sys.version.split()[0]} on {platform.platform()}")
    print(f"NumPy: {np.__version__}")
    print(f"SciPy: {scipy.__version__}")
    print("Solver: scipy.optimize.linprog(method='highs')")
    print(f"Seed: {SEED}")
    print()
    print("Base DCOPF dispatch MW:", results["phase2"]["base_dcopf"]["dispatch_mw"])
    print("Base DCOPF cost USD/h:", f"{results['phase2']['base_dcopf']['total_cost_usd_per_h']:.2f}")
    print("Worst contingency:", results["phase3"]["worst_contingency"])
    print("SCOPF dispatch MW:", results["phase4"]["scopf"]["dispatch_mw"])
    print("SCOPF cost USD/h:", f"{results['phase4']['scopf']['total_cost_usd_per_h']:.2f}")
    print("Cost of security USD/h:", f"{results['phase4']['cost_of_security_usd_per_h']:.2f}")
    print()
    print("Operating-state table:")
    for row in results["phase5"]["operating_state_table"]:
        print(row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true", help="Write reports/report.md and reports/report.pdf.")
    args = parser.parse_args()

    results = full_project_results()
    print_summary(results)

    if args.write_report:
        report_dir = ROOT / "reports"
        chart_path = report_dir / "operating_state_loading.png"
        md_path = report_dir / "report.md"
        html_path = report_dir / "report.html"
        pdf_path = report_dir / "report.pdf"
        markdown = build_markdown(results)
        html = build_html(results, chart_path)
        report_dir.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown, encoding="utf-8")
        write_chart(results, chart_path)
        write_styled_pdf(html, html_path, pdf_path)
        print()
        print(f"Wrote {md_path}")
        print(f"Wrote {html_path}")
        print(f"Wrote {chart_path}")
        print(f"Wrote {pdf_path}")


if __name__ == "__main__":
    main()
