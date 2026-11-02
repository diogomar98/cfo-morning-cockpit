# BCBS Cockpit — Cover Memo / GRC prototype

## Branch and scope

Branch: feature/bcbs-cover-memo

This branch extends the existing A.R.C. Streamlit CFO Morning Cockpit without removing its original features.

- **BCBS Cockpit (default):** three-layer navigation, with a built Layer 3 GRC executive dashboard.
- **Layer 1 — Operations:** navigation placeholder for granular control evidence and lineage.
- **Layer 2 — Cover Memo:** navigation placeholder for the existing report-owner Power BI content.
- **Layer 3 — GRC:** interactive report reliability and limitations prototype, styled in navy / electric blue / cyan using the J.A.R.V.I.S. visual reference.
- **CFO Cockpit (legacy):** retains the existing home, Morning Brief, Horizon, What-If, Treasury, Peers, Strategy, News and Copilot views.

### Entry point and navigation

The deployment entry point remains cockpit/app/app.py.

With the existing Databricks App deployment, no entrypoint change is necessary.

Run locally (if requirements and credentials are available):

    streamlit run cockpit/app/app.py

Navigation:
- /?layer=3 — default GRC reliability dashboard
- /?layer=2 — Cover Memo placeholder
- /?layer=1 — Operations placeholder
- /?module=home — legacy CFO Cockpit
- /?module=brief — Morning Brief
- /?module=horizon — Horizon
- /?module=scenario — What-If

The existing CFO module links keep working because a module query parameter routes to the original app. The CFO area includes a link back to BCBS Layer 3. The router exits before running CFO SQL queries when a BCBS layer is selected.

## Layer 3 content

The executive layout contains:

1. **Report reliability conclusion**, evidence confidence and sign-off condition.
2. **Material limitations summary**, with severity, affected metric, reporting impact, assessment-evidence grade and acceptance status.
3. **Selected limitation drill-down**, describing the mechanism, affected metric/portfolio, mitigation, owner, action and management decision.
4. **Period-on-period status**, focusing on changes in material limitations.
5. **Management decisions / escalations** and the A–D evidence maturity ladder.

The metric and severity filters are functional; the selected issue panel updates accordingly. An illustrative limitations register can be downloaded as CSV.

## CRITICAL: synthetic example data

The code uses only in-memory fictional examples stored in cockpit/app/bcbs_cover_memo.py. These are **not real ABN AMRO deficiencies, MIs, risk exposures, report findings, governance approvals or reliability conclusions**. Report selection switches the display label only. The data do not come from the CFO Databricks tables, the real Power BI Cover Memo or any bank source.

Do not use the prototype to assess the reliability of actual reports until the data is connected, ownership and sign-off are agreed and the impact-assessment methodology is approved.

## Proposed future data contract

A governed Layer 3 integration can begin with one row per material report limitation.

| Field | Purpose |
|---|---|
| report_id, reporting_period | Identify the report and point in time |
| issue_id, mi_id, source_system | Trace back to existing operational registers |
| affected_metric, affected_portfolio, report_cell | Report-level lineage |
| severity, materiality_rationale | Priority and decision sensitivity |
| affected_population_amount, affected_population_unit | Scope at risk; **not the monetary error** |
| actual_error_amount, estimated_error_lower, estimated_error_upper | Measured or supported estimated reporting error where available |
| evidence_level | A = validated error, B = estimated/bounded, C = affected scope, D = unknown |
| residual_risk_status, accepted_by, acceptance_expires_on | Risk acceptance, not issue closure |
| compensating_controls, owner, target_date | Remediation and accountability |
| decision_required, report_owner_conclusion | GRC decision/action |
| assessment_date, assessed_by, reviewed_by | Auditability |

**Important rules:** a control failure rate is not a report error rate; affected RWA or EAD is not a measured monetary misstatement. An accepted MI does not establish that the report metric is correct. Unknown material impact should never be automatically treated as low risk or green.

The overall report conclusion must be signed off by accountable owners. This prototype **does not algorithmically derive a reliability percentage**.

## Change isolation

- cockpit/app/app.py: a small early workspace switch and link back from CFO.
- cockpit/app/bcbs_cover_memo.py: new independent, in-memory prototype.
- cockpit/app/BCBS_README.md: this note.

No Databricks views, CFO calculations, dependencies or original CFO module logic have been changed. No production deployment is performed by creating this branch.
