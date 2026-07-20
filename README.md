# Clinexa AI · TrialGuard

## Prohibited Medication & Important Protocol Deviation Review

This release adds a **Data Quality Firewall** for record-level date issues.

### Date-quality behavior
- Invalid nonblank dates are identified as actionable data queries.
- Start dates after end dates are identified as critical record issues.
- Affected records are marked **Needs Data Correction**.
- Date-dependent rules are skipped only for affected records.
- Valid records continue through prohibited-medication and IPD review.
- The Data Validation Center provides a downloadable date-query CSV.

### Deployment
Use `prohibited-medication.py` as the Streamlit Cloud main file.

### Supported datasets
CSV, SAS7BDAT, XPT/XPORT, and ZIP packages containing supported domains.
