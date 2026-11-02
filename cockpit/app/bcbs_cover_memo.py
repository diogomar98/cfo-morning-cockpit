"""BCBS Cockpit / GRC report reliability workspace.

This is a presentation-only prototype with deliberately fictional data.
No report reliability result is calculated from live bank data.
"""
from __future__ import annotations

import csv
import html
import io
from textwrap import dedent

import streamlit as st


# Never imply that sample limitations, reported exposures or conclusions are real.
DEMO_REPORTS = ["CRMI", "CFO Cover Memo", "FR GRID"]
DEMO_ISSUES = [
    {
        "id": "DEMO-001",
        "title": "Incomplete risk classification on source exposures",
        "type": "Data gap",
        "severity": "High",
        "metric": "RWA",
        "portfolio": "Corporate lending",
        "impact_label": "€2.1bn RWA within potentially affected scope",
        "impact_kind": "Affected scope — NOT a measured reporting error",
        "assessment_level": "C",
        "acceptance": "Not accepted",
        "mi": "MI-014 (illustrative)",
        "description": "A missing source attribute is carried into downstream reporting for selected exposure records.",
        "limitation": "Unable to confirm whether all affected risk-weighted asset calculations are correctly classified.",
        "mitigation": "Sample-based manual review of critical exposures; full recalculation pending.",
        "action": "Reconcile records to affected RWA cells and quantify any actual misstatement.",
        "owner": "Risk Data Owner",
        "due": "Next GRC cycle",
        "decision": "Agree restrictions on use of the affected RWA breakdown until validation is complete.",
        "previous": "Open / unquantified",
        "trend": "Unchanged",
    },
    {
        "id": "DEMO-002",
        "title": "Unreconciled nominal amount differences",
        "type": "Reconciliation",
        "severity": "High",
        "metric": "Gross carrying amount",
        "portfolio": "Retail mortgages",
        "impact_label": "€85m difference awaiting reconciliation",
        "impact_kind": "Observed difference — reporting error not yet confirmed",
        "assessment_level": "B",
        "acceptance": "Pending review",
        "mi": "MI-021 (illustrative)",
        "description": "Selected values differ between the finance and risk reporting layers.",
        "limitation": "The report owner cannot yet confirm the origin and treatment of the difference.",
        "mitigation": "Daily exception review and manual cross-check of the largest mismatches.",
        "action": "Trace the unexplained balance and document the accepted treatment.",
        "owner": "Finance Reconciliation Lead",
        "due": "Next reporting close",
        "decision": "Confirm interim treatment and sign-off requirements for affected GCA figures.",
        "previous": "€110m unreconciled",
        "trend": "Improving",
    },
    {
        "id": "DEMO-003",
        "title": "Manual adjustment without complete lineage",
        "type": "Management issue",
        "severity": "Medium",
        "metric": "EAD",
        "portfolio": "Wholesale",
        "impact_label": "Impact not yet quantifiable",
        "impact_kind": "Unknown impact — assessment gap",
        "assessment_level": "D",
        "acceptance": "Accepted with conditions",
        "mi": "MI-031 (illustrative)",
        "description": "A controlled manual intervention is used to prepare selected report output.",
        "limitation": "Impact on the final metric has not been fully isolated and evidenced.",
        "mitigation": "Four-eyes review and post-report sample verification.",
        "action": "Complete downstream lineage and validate the size of adjustment.",
        "owner": "Report Owner",
        "due": "Next reporting cycle",
        "decision": "Review the conditions and expiry of the temporary risk acceptance.",
        "previous": "Accepted with conditions",
        "trend": "Unchanged",
    },
    {
        "id": "DEMO-004",
        "title": "DQ control exception on non-critical attributes",
        "type": "DQ check",
        "severity": "Low",
        "metric": "RWA",
        "portfolio": "SME",
        "impact_label": "No demonstrated impact on reported totals",
        "impact_kind": "Impact assessment based on targeted validation",
        "assessment_level": "A",
        "acceptance": "Closed after validation",
        "mi": "—",
        "description": "A non-critical metadata validation failed in a limited subset of records.",
        "limitation": "No remaining limitation identified for the reported metric.",
        "mitigation": "Corrected upstream and regression tested.",
        "action": "Monitor after deployment.",
        "owner": "DQ Controls Team",
        "due": "Complete",
        "decision": "No decision required.",
        "previous": "Open",
        "trend": "Resolved",
    },
]
DEMO_CHANGES = [
    ("01", "Material remediation", "One illustrative issue resolved", "Improving"),
    ("02", "Affected financial scope", "Reconciliation gap reduced from €110m to €85m", "Improving"),
    ("03", "Uncertainty", "One material limitation remains unquantified", "Open"),
]
LEVEL_DESCRIPTIONS = {
    "A": "Actual impact quantified and validated",
    "B": "Estimated / bounded impact with evidence",
    "C": "Affected population identified, actual error unknown",
    "D": "Impact unknown / assessment incomplete",
}
SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_html(markup: str) -> None:
    st.html(dedent(markup).strip())


def _query_value(key: str, default: str) -> str:
    value = st.query_params.get(key, default)
    return str(value[-1] if isinstance(value, list) else value)


def _status_class(value: str) -> str:
    if value == "High" or value in ("Not accepted", "Unknown"):
        return "risk-high"
    if value == "Medium" or value in ("Pending review", "Accepted with conditions"):
        return "risk-medium"
    return "risk-low"


def _style() -> None:
    render_html("""
    <style>
    :root {
        --bc-bg:#020b14; --bc-panel:#071b2a; --bc-panel2:#092334;
        --bc-cyan:#55e5fa; --bc-blue:#548dff; --bc-ink:#e7f8ff;
        --bc-muted:#8babbc; --bc-line:rgba(98,217,251,.22);
    }
    html, body, [data-testid="stApp"], .stApp {
        background:radial-gradient(circle at 78% 3%,rgba(35,91,145,.18),transparent 36%),
                   radial-gradient(circle at 12% 32%,rgba(30,187,220,.075),transparent 35%),
                   #020b14 !important;
        color:var(--bc-ink);
    }
    [data-testid="stHeader"] {background:transparent !important;}
    [data-testid="stDecoration"] {display:none;}
    .block-container {max-width:1380px !important; padding-top:1.3rem !important; padding-bottom:2rem !important;}
    [data-testid="stToolbar"] {visibility:hidden;}
    .bc-shell {font-family:Inter,Arial,sans-serif;color:var(--bc-ink);letter-spacing:.005em;}
    .bc-mono,.bc-kicker,.bc-nav,.bc-eyebrow,.bc-pill,.bc-foot,.bc-kpi-label,.bc-severity {
        font-family:"Cascadia Mono",Consolas,monospace;
    }
    .bc-topbar {display:flex;align-items:center;justify-content:space-between;gap:1.1rem;margin-bottom:1.5rem;flex-wrap:wrap}
    .bc-brand {display:flex;align-items:center;gap:.78rem}
    .bc-emblem {width:46px;height:46px;position:relative;border-radius:50%;
        background:radial-gradient(circle,#64efff 0 7%,transparent 10% 24%,rgba(69,190,250,.13) 25% 47%,transparent 48%),
        conic-gradient(from 35deg,transparent 0 12%,#55e5fa 13% 32%,transparent 33% 39%,#538cf4 40% 61%,transparent 62% 70%,#55e5fa 71% 91%,transparent 92%);
        box-shadow:0 0 16px rgba(78,198,245,.22);border:1px solid rgba(85,229,250,.50)}
    .bc-emblem:after {content:"";position:absolute;inset:8px;border-radius:50%;border:2px solid rgba(85,229,250,.6);box-shadow:inset 0 0 9px rgba(85,229,250,.25)}
    .bc-kicker {font-size:.62rem;color:var(--bc-cyan);letter-spacing:.21em;font-weight:740}
    .bc-brand-title {font-size:1.07rem;letter-spacing:.075em;font-weight:800;margin-top:.20rem;}
    .bc-brand-sub {font-size:.66rem;color:var(--bc-muted);margin-top:.20rem}
    .bc-nav {display:flex;align-items:center;flex-wrap:wrap;gap:.4rem}
    .bc-nav a {display:inline-flex;align-items:center;gap:.4rem;min-height:37px;padding:.5rem .77rem;
        color:#98b6ca;text-decoration:none;border:1px solid var(--bc-line);
        background:rgba(5,26,42,.8);font-size:.63rem;font-weight:730;letter-spacing:.04em}
    .bc-nav a:hover,.bc-nav a.active {color:#eaffff;background:rgba(64,159,209,.16);border-color:rgba(85,229,250,.70);
        box-shadow:inset 0 -2px rgba(85,229,250,.6)}
    .bc-nav a.bc-nav-cfo {border-color:rgba(108,142,230,.29);color:#b5caff}
    .bc-panel {border:1px solid var(--bc-line);background:linear-gradient(135deg,rgba(11,37,57,.93),rgba(5,21,36,.94));
        box-shadow:0 18px 35px rgba(0,0,0,.18);border-radius:9px}
    .bc-hero {display:grid;grid-template-columns:minmax(180px,.72fr) minmax(0,1.6fr);gap:1.15rem;
        align-items:center;padding:1.05rem 1.7rem;margin-bottom:1rem;min-height:280px;
        border:1px solid rgba(85,229,250,.28);background:linear-gradient(115deg,rgba(6,26,43,.93),rgba(5,17,30,.92));
        position:relative;overflow:hidden}
    .bc-hero:after {content:"";position:absolute;inset:0;pointer-events:none;
        background:repeating-linear-gradient(0deg,transparent 0 34px,rgba(82,179,235,.025) 35px 36px),
                   repeating-linear-gradient(90deg,transparent 0 34px,rgba(82,179,235,.025) 35px 36px)}
    .bc-arc-wrap {display:flex;justify-content:center;align-items:center;min-height:245px}
    .bc-arc {height:210px;width:210px;position:relative;display:grid;place-items:center;border-radius:50%;
        background:radial-gradient(circle,rgba(25,87,122,.15) 0 32%,transparent 33%),
        repeating-conic-gradient(from -20deg,rgba(105,214,252,.55) 0 1deg,transparent 1deg 13deg);
        -webkit-mask:radial-gradient(circle,transparent 0 48%,black 49% 51%,transparent 52% 76%,black 77% 80%,transparent 81%);
        mask:radial-gradient(circle,transparent 0 48%,black 49% 51%,transparent 52% 76%,black 77% 80%,transparent 81%);
        filter:drop-shadow(0 0 7px rgba(85,229,250,.5))}
    .bc-arc::before {content:"";position:absolute;inset:15px;border-radius:50%;
        background:conic-gradient(from 0deg,#51e7ff 0 28%,transparent 29% 41%,#527cfa 42% 72%,transparent 73% 80%,#51e7ff 81% 97%,transparent 98%);
        -webkit-mask:radial-gradient(circle,transparent 0 86%,black 87% 96%,transparent 97%);
        mask:radial-gradient(circle,transparent 0 86%,black 87% 96%,transparent 97%);
        animation:bc-spin 30s linear infinite}
    @keyframes bc-spin {to{transform:rotate(360deg)}}
    .bc-arc-core {position:absolute;z-index:2;display:grid;place-items:center;text-align:center;
        width:128px;height:128px;border-radius:50%;border:1px solid rgba(79,220,248,.47);
        background:radial-gradient(circle,rgba(37,108,158,.19),rgba(3,20,33,.97) 71%);
        box-shadow:0 0 25px rgba(71,181,255,.19),inset 0 0 28px rgba(67,181,245,.12)}
    .bc-arc-core strong {font-size:1.2rem;letter-spacing:.14em}
    .bc-arc-core span {font:.54rem Consolas,monospace;letter-spacing:.13em;color:var(--bc-cyan)}
    .bc-eyebrow {font-size:.62rem;letter-spacing:.16em;font-weight:750;color:var(--bc-cyan);text-transform:uppercase}
    .bc-title {font-size:clamp(1.5rem,2.4vw,2.35rem);letter-spacing:-.02em;line-height:1.17;margin:.52rem 0 .8rem;font-weight:790}
    .bc-copy {color:#b1cfdb;font-size:.85rem;line-height:1.72;max-width:850px}
    .bc-pills {display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1.2rem}
    .bc-pill {padding:.33rem .55rem;font-size:.60rem;letter-spacing:.07em;border:1px solid rgba(80,170,226,.32);
        color:#9cc9e0;background:rgba(51,126,175,.10)}
    .bc-pill.important {color:#b8ecff;border-color:rgba(85,229,250,.47)}
    .bc-section-head {display:flex;align-items:center;justify-content:space-between;margin:1.35rem 0 .7rem;gap:1rem;flex-wrap:wrap}
    .bc-section-head h3 {margin:0;font-size:1.02rem;letter-spacing:.018em}
    .bc-section-head small {color:var(--bc-muted);font:.65rem Consolas,monospace}
    .bc-section-n {color:#55e5fa;font:.66rem Consolas,monospace;margin-right:.65rem}
    .bc-assessment {display:grid;grid-template-columns:5px minmax(0,1fr);overflow:hidden}
    .bc-assessment-accent {background:linear-gradient(#5c97fb,#53e4fb)}
    .bc-assessment-main {padding:1.08rem 1.18rem}
    .bc-assessment-label {font:.60rem Consolas,monospace;letter-spacing:.14em;color:#8fb4c7}
    .bc-assessment-name {font-size:1.35rem;font-weight:770;color:#f0fbff;margin:.48rem 0}
    .bc-assessment-desc {color:#adcad8;font-size:.81rem;line-height:1.6}
    .bc-assessment-floor {margin-top:.95rem;padding-top:.75rem;border-top:1px solid var(--bc-line);
        display:flex;gap:1rem;justify-content:space-between;flex-wrap:wrap;color:#a3c7d6;font-size:.68rem}
    .bc-kpis {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.7rem;margin-top:.85rem}
    .bc-kpi {padding:.93rem 1rem;min-height:104px}
    .bc-kpi-label {color:#86b6ce;font-size:.6rem;letter-spacing:.075em}
    .bc-kpi-value {font-size:1.85rem;font-weight:780;line-height:1.5;color:#f1fbff}
    .bc-kpi-note {font-size:.66rem;color:var(--bc-muted)}
    .bc-kpi-value em {font-size:.68rem;font-style:normal;color:#82cadb}
    .bc-table-wrap {overflow-x:auto;border:1px solid var(--bc-line);border-radius:8px;background:rgba(4,20,34,.78)}
    table.bc-table {border-collapse:collapse;width:100%;font-size:.78rem;text-align:left}
    .bc-table th {background:rgba(18,60,86,.65);font:.62rem Consolas,monospace;color:#96c9e3;
        letter-spacing:.07em;text-transform:uppercase;padding:.76rem .72rem;white-space:nowrap}
    .bc-table td {padding:.87rem .72rem;border-top:1px solid rgba(103,193,227,.12);color:#c9e2ed;vertical-align:top}
    .bc-table .bc-muted {font-size:.67rem;color:var(--bc-muted);margin-top:.2rem}
    .bc-table .bc-id {font:.60rem Consolas,monospace;color:#56d6ee}
    .bc-severity {padding:.24rem .43rem;font-size:.60rem;border:1px solid;border-radius:3px;white-space:nowrap}
    .bc-severity.risk-high {background:rgba(234,110,129,.10);border-color:rgba(234,110,129,.40);color:#ffc0ca}
    .bc-severity.risk-medium {background:rgba(230,166,78,.11);border-color:rgba(230,166,78,.38);color:#ffd7a0}
    .bc-severity.risk-low {background:rgba(89,214,229,.10);border-color:rgba(89,214,229,.30);color:#96e2ef}
    .bc-evidence {display:inline-grid;place-items:center;border:1px solid #2d7796;border-radius:4px;
        min-width:29px;padding:4px 8px;font:.78rem Consolas,monospace;color:#b8efff;background:rgba(51,156,208,.12)}
    .bc-two-col {display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
    .bc-detail {padding:1rem 1.05rem}
    .bc-detail dt {font:.62rem Consolas,monospace;letter-spacing:.08em;color:#81b9cf;text-transform:uppercase;margin-bottom:.24rem}
    .bc-detail dd {font-size:.79rem;color:#d5eaf4;margin:0 0 .9rem;line-height:1.58}
    .bc-detail h4 {font-size:1rem;margin:.3rem 0 .72rem}
    .bc-detail .impact {font-size:.93rem;color:#ccf4ff;font-weight:700}
    .bc-detail .impact-hint {font-size:.65rem;color:#97bbd0;line-height:1.5}
    .bc-progression {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.7rem}
    .bc-progress {padding:.95rem}
    .bc-progress .n {color:#5ee2f4;font:.63rem Consolas,monospace}
    .bc-progress strong {display:block;font-size:.8rem;margin:.47rem 0}
    .bc-progress span {display:block;color:var(--bc-muted);font-size:.73rem;line-height:1.52}
    .bc-decisions {display:grid;grid-template-columns:1fr;gap:.65rem}
    .bc-decision {display:grid;grid-template-columns:42px minmax(0,1fr) auto;gap:.85rem;
        padding:.82rem .95rem;align-items:start}
    .bc-decision .num {font:700 1.01rem Consolas,monospace;color:#57e0f5}
    .bc-decision strong {font-size:.8rem}
    .bc-decision p {font-size:.74rem;color:#bdd8e5;margin:.35rem 0;line-height:1.55}
    .bc-decision small {font-size:.66rem;color:#88b2c7}
    .bc-levels {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.65rem;margin-top:1rem}
    .bc-level {background:rgba(8,32,49,.8);padding:.75rem;border:1px solid var(--bc-line)}
    .bc-level strong {display:block;color:#77ddf2;font:.9rem Consolas,monospace}
    .bc-level span {font-size:.7rem;line-height:1.5;color:#aac6d5}
    .bc-foot {margin:1.3rem 0 .5rem;padding-top:.8rem;border-top:1px solid var(--bc-line);
        display:flex;gap:.7rem;justify-content:space-between;flex-wrap:wrap;font-size:.61rem;color:#688da0}
    .bc-notice {border-left:2px solid #5bd7f1;padding:.72rem 1rem;background:rgba(56,140,181,.10);
        font-size:.79rem;color:#b4d7e6;line-height:1.65}
    .bc-placeholder {padding:1.5rem;margin-top:1rem}
    .bc-placeholder h3 {font-size:1.1rem;margin:0 0 .7rem}
    .bc-placeholder p {color:#a3c5d6;font-size:.82rem;line-height:1.7}
    [data-testid="stSelectbox"] label,[data-testid="stMultiSelect"] label {color:#a4c8da !important;font-size:.73rem !important}
    [data-testid="stSelectbox"] [data-baseweb="select"] > div {background:#0b263b !important;color:#e8f9ff !important;border-color:#246587 !important}
    [data-testid="stDownloadButton"] button {background:#0a3049 !important;color:#b3eeff !important;border:1px solid rgba(85,229,250,.55) !important}
    @media(max-width:1000px){.bc-hero{grid-template-columns:1fr;padding:1rem}.bc-arc-wrap{min-height:195px}.bc-arc{transform:scale(.8)}.bc-kpis{grid-template-columns:repeat(2,1fr)}.bc-levels{grid-template-columns:repeat(2,1fr)}}
    @media(max-width:620px){.bc-kpis,.bc-two-col,.bc-progression,.bc-levels{grid-template-columns:1fr}.bc-hero{gap:0}.bc-decision{grid-template-columns:32px minmax(0,1fr)}.bc-decision .bc-severity{grid-column:2}.bc-title{font-size:1.5rem}.bc-topbar{margin-bottom:1rem}}
    @media(prefers-reduced-motion:reduce){.bc-arc::before{animation:none}}
    </style>
    """)


def _nav(layer: int, report: str) -> None:
    items = [
        (1, "01 / Operations"),
        (2, "02 / Cover Memo"),
        (3, "03 / GRC"),
    ]
    nav = "".join(
        f'<a class="{"active" if layer == number else ""}" href="?layer={number}" '
        f'target="_self">{label}</a>'
        for number, label in items
    )
    render_html(f"""
    <div class="bc-shell bc-topbar">
      <div class="bc-brand">
        <div class="bc-emblem"></div>
        <div>
          <div class="bc-kicker">A.R.C. / RISK DATA INTELLIGENCE</div>
          <div class="bc-brand-title">BCBS COCKPIT</div>
          <div class="bc-brand-sub">Risk data aggregation · report reliability · management oversight</div>
        </div>
      </div>
      <nav class="bc-nav" aria-label="Cockpit workspaces">
        {nav}
        <a class="bc-nav-cfo" href="?module=home" target="_self">↗ CFO Cockpit</a>
      </nav>
    </div>
    """)


def _hero(layer: int, report: str) -> None:
    headings = {
        1: ("Operational evidence", "Control results, checks, affected records and detailed lineage."),
        2: ("Cover Memo / Report Owner", "Status, trends, reconciliations and remediation progress."),
        3: ("Report reliability & limitations", "Can management rely on the report, where are the material uncertainties, and which decisions require attention?"),
    }
    heading, explanation = headings[layer]
    render_html(f"""
    <div class="bc-shell bc-hero">
      <div class="bc-arc-wrap">
        <div style="position:relative;display:grid;place-items:center;">
          <div class="bc-arc"></div>
          <div class="bc-arc-core"><div><span>BCBS / COMMAND</span><br>
          <strong>LAYER {layer:02d}</strong><br><span>{"GRC" if layer == 3 else "IN DEVELOPMENT"}</span></div></div>
        </div>
      </div>
      <div style="position:relative;z-index:1">
        <div class="bc-eyebrow">{"Executive intelligence / GRC" if layer == 3 else "Architecture preview"}</div>
        <div class="bc-title">{esc(heading)}</div>
        <div class="bc-copy">{esc(explanation)}</div>
        <div class="bc-pills">
          <span class="bc-pill important">{esc(report)} / illustrative prototype</span>
          <span class="bc-pill">BCBS 239</span>
          <span class="bc-pill">Not connected to live DQ evidence</span>
        </div>
      </div>
    </div>
    """)


def _section(number: int, title: str, subtitle: str = "") -> None:
    render_html(f"""
    <div class="bc-shell bc-section-head">
      <h3><span class="bc-section-n">{number:02d} /</span>{esc(title)}</h3>
      <small>{esc(subtitle)}</small>
    </div>
    """)


def _placeholder(layer: int) -> None:
    specs = {
        1: ("Operational control evidence",
            "Future workspace: granular DQ test results, failed records, source-to-report lineage, control evidence and owners.",
            ["Record-level control results", "Failure population and metric mapping", "Source / GREAT / report lineage"]),
        2: ("Cover Memo / Report Owner",
            "Future workspace: the current Power BI Cover Memo concepts, including trends, reconciliation, DQ checks, MIs, controls and remediation.",
            ["Analysis and trends", "Reconciliations, gaps and MIs", "Control framework and feedback loop"]),
    }
    title, details, cards = specs[layer]
    render_html(f"""
    <div class="bc-shell bc-panel bc-placeholder">
      <div class="bc-eyebrow">Planned / not developed in this branch</div>
      <h3>{esc(title)}</h3><p>{esc(details)}</p>
      <div class="bc-notice">Layer {layer} is intentionally a navigation placeholder. No operational or report-owner data is currently loaded.</div>
    </div>
    <div class="bc-shell bc-section-head"><h3>Planned building blocks</h3></div>
    <div class="bc-shell bc-progression">
      {"".join(f'<div class="bc-panel bc-progress"><div class="n">0{i+1}</div><strong>{esc(x)}</strong><span>Future integration with governed data sources.</span></div>' for i,x in enumerate(cards))}
    </div>
    """)
    st.info("Open Layer 03 / GRC to explore the interactive report reliability prototype.")


def _metrics(issues: list[dict]) -> None:
    material = [issue for issue in issues if issue["severity"] in ("High", "Medium")]
    high = sum(issue["severity"] == "High" for issue in material)
    pending = sum(issue["acceptance"] in ("Not accepted", "Pending review") for issue in issues)
    unknown = sum(issue["assessment_level"] == "D" for issue in material)
    render_html(f"""
    <div class="bc-shell bc-panel bc-assessment">
      <div class="bc-assessment-accent"></div>
      <div class="bc-assessment-main">
        <div class="bc-assessment-label">OVERALL RELIABILITY CONCLUSION / ILLUSTRATIVE</div>
        <div class="bc-assessment-name">Reliability with material limitations — assessment incomplete</div>
        <div class="bc-assessment-desc">The example report may be used only with clearly disclosed qualifications.
           Material deficiencies could affect selected RWA and GCA figures. Actual errors have not
           been established for every limitation. This sample conclusion is not a governance sign-off.</div>
        <div class="bc-assessment-floor">
          <span>Assessment confidence: <strong>PARTIAL / further validation required</strong></span>
          <span>Final acceptance: <strong>REPORT OWNER / GOVERNANCE SIGN-OFF PENDING</strong></span>
        </div>
      </div>
    </div>
    <div class="bc-shell bc-kpis">
      <div class="bc-panel bc-kpi"><div class="bc-kpi-label">MATERIAL LIMITATIONS</div>
        <div class="bc-kpi-value">{len(material)}</div><div class="bc-kpi-note">{high} high · {len(material)-high} medium</div></div>
      <div class="bc-panel bc-kpi"><div class="bc-kpi-label">UNACCEPTED / PENDING</div>
        <div class="bc-kpi-value">{pending}</div><div class="bc-kpi-note">Residual risk decisions outstanding</div></div>
      <div class="bc-panel bc-kpi"><div class="bc-kpi-label">IMPACT UNKNOWN</div>
        <div class="bc-kpi-value">{unknown}</div><div class="bc-kpi-note">Material limitations at evidence level D</div></div>
      <div class="bc-panel bc-kpi"><div class="bc-kpi-label">EVIDENCE STATUS</div>
        <div class="bc-kpi-value">C–D <em>/ selected issues</em></div>
        <div class="bc-kpi-note">Affected population ≠ monetary error</div></div>
    </div>
    """)


def _issues_table(issues: list[dict]) -> None:
    rows = []
    for issue in sorted(issues, key=lambda item: SEVERITY_ORDER[item["severity"]]):
        rows.append(f"""
        <tr>
          <td><div class="bc-id">{esc(issue["id"])}</div>
              <strong>{esc(issue["title"])}</strong>
              <div class="bc-muted">{esc(issue["type"])} · {esc(issue["portfolio"])}</div></td>
          <td>{esc(issue["metric"])}</td>
          <td><strong>{esc(issue["impact_label"])}</strong>
              <div class="bc-muted">{esc(issue["impact_kind"])}</div></td>
          <td><span class="bc-severity {_status_class(issue["severity"])}">{esc(issue["severity"])}</span></td>
          <td><span class="bc-evidence">{esc(issue["assessment_level"])}</span></td>
          <td><span class="bc-severity {_status_class(issue["acceptance"])}">{esc(issue["acceptance"])}</span></td>
        </tr>""")
    render_html(f"""
    <div class="bc-shell bc-table-wrap">
      <table class="bc-table" aria-label="Illustrative report limitations">
        <thead><tr><th>Limitation</th><th>Metric</th><th>Potential report impact</th>
          <th>Severity</th><th>Evidence</th><th>Acceptance</th></tr></thead>
        <tbody>{''.join(rows) if rows else '<tr><td colspan="6">No matches</td></tr>'}</tbody>
      </table>
    </div>
    """)


def _detail(issue: dict) -> None:
    render_html(f"""
    <div class="bc-shell bc-two-col">
      <div class="bc-panel bc-detail">
        <div class="bc-eyebrow">Selected limitation / {esc(issue["id"])}</div>
        <h4>{esc(issue["title"])}</h4>
        <dl><dt>Why the report is limited</dt><dd>{esc(issue["limitation"])}</dd>
            <dt>Impacted reporting metric / portfolio</dt><dd>{esc(issue["metric"])} · {esc(issue["portfolio"])}</dd>
            <dt>Magnitude / available evidence</dt>
            <dd class="impact">{esc(issue["impact_label"])}</dd>
            <dd class="impact-hint">{esc(issue["impact_kind"])}</dd>
            <dt>Evidence maturity</dt><dd>Level {esc(issue["assessment_level"])} — {esc(LEVEL_DESCRIPTIONS[issue["assessment_level"]])}</dd>
        </dl>
      </div>
      <div class="bc-panel bc-detail">
        <div class="bc-eyebrow">Risk governance and remediation</div>
        <h4>Acceptance, controls & next action</h4>
        <dl><dt>Management issue</dt><dd>{esc(issue["mi"])}</dd>
            <dt>Residual risk acceptance</dt><dd>{esc(issue["acceptance"])}</dd>
            <dt>Compensating controls</dt><dd>{esc(issue["mitigation"])}</dd>
            <dt>Next action</dt><dd>{esc(issue["action"])}</dd>
            <dt>Accountability</dt><dd>{esc(issue["owner"])} · {esc(issue["due"])}</dd>
        </dl>
      </div>
    </div>
    """)


def _progression() -> None:
    render_html('<div class="bc-shell bc-progression">' + "".join(
        f'<div class="bc-panel bc-progress"><div class="n">{number}</div>'
        f'<strong>{esc(title)}</strong><span>{esc(description)}</span></div>'
        for number, title, description, _ in DEMO_CHANGES
    ) + '</div>')


def _decisions(issues: list[dict]) -> None:
    rows = []
    for index, issue in enumerate(issues[:3], 1):
        rows.append(f"""
        <div class="bc-panel bc-decision">
          <span class="num">{index:02d}</span>
          <div><strong>{esc(issue["metric"])} / {esc(issue["title"])}</strong>
            <p>{esc(issue["decision"])}</p>
            <small>Accountable: {esc(issue["owner"])} · Target: {esc(issue["due"])}</small></div>
          <span class="bc-severity {_status_class(issue["severity"])}">{esc(issue["severity"])}</span>
        </div>""")
    render_html('<div class="bc-shell bc-decisions">' + "".join(rows) + '</div>')


def _evidence() -> None:
    render_html('<div class="bc-shell bc-levels">' + "".join(
        f'<div class="bc-level"><strong>LEVEL {code}</strong><span>{esc(label)}</span></div>'
        for code, label in LEVEL_DESCRIPTIONS.items()
    ) + '</div>')


def _csv_bytes(issues: list[dict]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(DEMO_ISSUES[0].keys()))
    writer.writeheader()
    writer.writerows(issues)
    return output.getvalue().encode("utf-8-sig")


def render_bcbs_cockpit() -> None:
    """Render BCBS layers. Does not connect to CFO or ABN data sources."""
    _style()
    requested = _query_value("layer", "3")
    layer = int(requested) if requested in ("1", "2", "3") else 3
    report = st.session_state.get("bcbs_demo_report", DEMO_REPORTS[0])
    _nav(layer, report)
    _hero(layer, report)

    if layer != 3:
        _placeholder(layer)
    else:
        _section(1, "Executive reliability conclusion", "Can I rely on the report?")
        report_col, caption_col = st.columns([1, 3])
        with report_col:
            report = st.selectbox(
                "Illustrative report",
                DEMO_REPORTS,
                key="bcbs_demo_report",
                help="Selection is a UI prototype; all reports use the same explicitly fictional data.",
            )
        with caption_col:
            st.caption("PROTOTYPE / SYNTHETIC DATA. Changing the report label does not change the sample evidence. Live integration and sign-off are not implemented.")
        _metrics(DEMO_ISSUES)

        _section(2, "Material deficiencies & report impact", "Consequences, not issue counts")
        filter_col, sev_col = st.columns(2)
        metrics = ["All metrics"] + sorted(set(item["metric"] for item in DEMO_ISSUES))
        with filter_col:
            selected_metric = st.selectbox("Filter by affected report metric", metrics, key="bcbs_metric")
        with sev_col:
            selected_severity = st.selectbox("Filter by materiality", ["All severities", "High", "Medium", "Low"], key="bcbs_severity")
        visible = [item for item in DEMO_ISSUES
                   if (selected_metric == "All metrics" or item["metric"] == selected_metric)
                   and (selected_severity == "All severities" or item["severity"] == selected_severity)]
        _issues_table(visible)
        st.caption("The affected monetary scope is not equivalent to a monetary misstatement. Evidence levels are shown separately from severity and acceptance.")

        if visible:
            selected_id = st.selectbox(
                "Inspect a specific limitation",
                options=[issue["id"] for issue in visible],
                format_func=lambda issue_id: next(
                    f"{issue_id} · {issue['title']}" for issue in visible if issue["id"] == issue_id
                ),
                key="bcbs_selected_issue",
            )
            _detail(next(issue for issue in visible if issue["id"] == selected_id))
        else:
            st.info("No illustrative issues match these filters.")

        _section(3, "Change since previous reporting period", "Are limitations improving?")
        _progression()

        _section(4, "Management decisions & attention", "What requires GRC action?")
        _decisions([issue for issue in DEMO_ISSUES if issue["severity"] in ("High", "Medium")])
        _section(5, "Impact-assessment methodology", "Do not confuse scope and error")
        render_html("""
        <div class="bc-shell bc-notice">An observed control failure or affected exposure amount does not establish
        the actual reporting error. Quantified conclusions require downstream metric mapping,
        recalculation or a documented expert-supported estimate. An accepted MI is not the same
        as a reliable metric.</div>""")
        _evidence()
        st.download_button(
            "Download illustrative limitations register (CSV)",
            data=_csv_bytes(DEMO_ISSUES),
            file_name="bcbs_demo_limitations.csv",
            mime="text/csv",
            key="bcbs_export",
        )

    render_html("""
    <div class="bc-shell bc-foot">
      <span>A.R.C. / BCBS 239 REPORT RELIABILITY PROTOTYPE</span>
      <span>ALL DEFICIENCIES, EXPOSURES, MI REFERENCES AND DECISIONS ARE FICTIONAL</span>
      <span>NO LIVE REPORT DATA / NO GOVERNANCE SIGN-OFF</span>
    </div>
    """)
