# Clinexa AI – TrialGuard v1.1 Demo Edition

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```

The bundled data intentionally contains quality and clinical-review scenarios. See `DEMO_ISSUE_MANIFEST.csv`.

## Key corrections
- Ongoing CM records are carried to study cutoff and are never truncated to one day.
- Missing unresolved CM end dates are marked Not Evaluable (`OVERLAPFL=U`).
- Partial ISO dates are explicitly detected and excluded from automated date rules.
- AE linkage is medication-specific and uses a configurable ±14-day window plus serious-AE logic.
- DV reconciliation uses configurable controlled phrases and a temporal linkage window; bare `MEDICATION` no longer matches.
- Missing treatment-window configuration is visible and does not silently default to 30 days.
- Duplicate prohibited-list rationale conflicts are surfaced.

## Demo files
- `data/study_rules.csv`: normal configured demo
- `data/study_rules_demo_missing_window.csv`: alternate configuration-health warning demo
- `DEMO_ISSUE_MANIFEST.csv`: seeded scenarios and expected outcomes
- `tests/`: regression tests for critical logic
