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
