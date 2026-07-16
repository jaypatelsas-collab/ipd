# Clinexa AI — TrialGuard

**Clinical Intelligence Platform**

Initial single-page module: **Prohibited Medication & Important Protocol Deviation Review**.

# Oncology Important Protocol Deviation Dashboard

Metadata-driven Streamlit demonstration app for prohibited-medication review.

## Supported inputs
- Protocol: DOCX, PDF, TXT
- SAP: DOCX, PDF, TXT
- Rule file: XLSX/XLSM (preferred `Rule Engine` sheet) or CSV
- Datasets: CSV, SAS7BDAT, XPT/XPORT, or a ZIP containing those formats

Domain filenames should be `dm`, `ex`, `cm`, `ae`, `dv`, `ds`, `lb`, or `vs` plus the extension.

## Deploy
```bash
pip install -r requirements.txt
streamlit run prohibited-medication.py
```

This is a dummy educational prototype. Final IPD decisions require approved protocol/SAP interpretation, validated rules, medical review, and controlled change management.


## ATC hierarchy support
- Bundled dummy CM data uses ATC Level 4 only (`ATC4CD`, `ATC4`).
- Uploaded datasets may include ATC Levels 4 through 7 using `ATC4CD/ATC4` ... `ATC7CD/ATC7`.
- Medication matching searches all available ATC levels.
- Dashboard tables display all detected ATC levels and summaries use the most detailed available class.
- Legacy `ATC1CD/ATC1` inputs remain supported.
