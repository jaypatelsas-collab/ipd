# Clinexa AI – TrialGuard v1.2 Demo Edition

## Purpose
TrialGuard is the first application in the Clinexa AI Clinical Intelligence Platform. This release keeps clinical-rule execution deterministic while preparing the workflow and rule workbook for a future human-governed AI Rule Builder.

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```

## v1.2 experience updates
- Guided **Study Setup** sidebar: Protocol, SAP, Rule Source, and Datasets.
- **Rule Source** clearly separates the current workbook upload from the disabled **AI Rule Builder – Coming Soon** capability.
- New study-setup summary shows document source, enabled rules, loaded domains, and execution readiness.
- Product-level cards explain Data Quality Firewall, Rule Readiness, and the future AI capability.
- Versioned footer and product positioning as **Clinexa AI Platform → TrialGuard**.
- AI-ready governance fields retained in rule-workbook review and exports:
  - `EVIDENCE_REFERENCE`
  - `AI_CONFIDENCE`
  - `REVIEW_STATUS`
  - `APPROVED_BY`
  - `VERSION`

## Execution model
- Current rule execution remains deterministic and does not call an AI model.
- Future AI functionality will draft rules from controlled study documents.
- AI-generated rules must be reviewed and approved before TrailGuard execution.

## Existing clinical and data-quality safeguards
- Ongoing CM records are carried to study cutoff and are never truncated to one day.
- Missing unresolved CM end dates are marked Not Evaluable (`OVERLAPFL=U`).
- Partial ISO dates are explicitly detected and excluded from automated date rules.
- AE linkage is medication-specific and uses a configurable ±14-day window plus serious-AE logic.
- DV reconciliation uses configurable controlled phrases and a temporal linkage window.
- Missing treatment-window configuration is visible and does not silently default to 30 days.
- Duplicate prohibited-list rationale conflicts are surfaced.

## Demo files
- `data/Study_Rules_DUM_ONC_001.xlsx`: AI-ready governed rule workbook.
- `data/study_rules.csv`: normal configured demo.
- `data/study_rules_demo_missing_window.csv`: configuration-health warning demo.
- `DEMO_ISSUE_MANIFEST.csv`: seeded scenarios and expected outcomes.
- `tests/`: regression tests for critical logic.

## Deployment notes
Do not commit `.venv`, `__pycache__`, or `.pytest_cache` to GitHub. The packaged release excludes these local artifacts.
