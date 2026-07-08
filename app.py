
import io
import os
import zipfile
from datetime import datetime
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Oncology IPD Dashboard - Prohibited Medication",
    page_icon="⚕️",
    layout="wide",
)

APP_TITLE = "Oncology Important Protocol Deviation Dashboard"
APP_SUBTITLE = "Prohibited Medication Review | Dummy Oncology Study DUM-ONC-001"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SRC_DIR = os.path.join(DATA_DIR, "Source_CSV")
CT_DIR = os.path.join(DATA_DIR, "Controlled_Terminology")

REQUIRED_DOMAINS = ["dm", "ex", "cm", "ae", "dv", "ds", "lb", "vs"]

DATE_COLS = {
    "dm": ["RFSTDTC"],
    "ex": ["EXSTDTC", "EXENDTC"],
    "cm": ["CMSTDTC", "CMENDTC"],
    "ae": ["AESTDTC"],
    "dv": ["DVDTC"],
}

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df

def safe_date(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        df[col] = pd.NaT
    return pd.to_datetime(df[col], errors="coerce")

def read_csv_safe(path_or_buffer) -> pd.DataFrame:
    return normalize_columns(pd.read_csv(path_or_buffer))

@st.cache_data(show_spinner=False)
def load_default_data():
    data = {}
    for dom in REQUIRED_DOMAINS:
        path = os.path.join(SRC_DIR, f"{dom}.csv")
        if os.path.exists(path):
            data[dom] = read_csv_safe(path)
        else:
            data[dom] = pd.DataFrame()

    pm_path = os.path.join(CT_DIR, "prohibited_medication_list.csv")
    whodrug_path = os.path.join(CT_DIR, "whodrug_atc_dummy_dictionary.csv")
    data["prohibited"] = read_csv_safe(pm_path) if os.path.exists(pm_path) else pd.DataFrame()
    data["whodrug"] = read_csv_safe(whodrug_path) if os.path.exists(whodrug_path) else pd.DataFrame()
    return data

def load_uploaded_zip(uploaded_file):
    data = {dom: pd.DataFrame() for dom in REQUIRED_DOMAINS}
    data["prohibited"] = pd.DataFrame()
    data["whodrug"] = pd.DataFrame()

    with zipfile.ZipFile(uploaded_file) as z:
        names = [n for n in z.namelist() if not n.startswith("__MACOSX/") and not os.path.basename(n).startswith("._")]

        def find_csv(filename):
            filename = filename.lower()
            hits = [n for n in names if n.lower().endswith(filename)]
            return hits[0] if hits else None

        for dom in REQUIRED_DOMAINS:
            n = find_csv(f"{dom}.csv")
            if n:
                with z.open(n) as f:
                    data[dom] = read_csv_safe(f)

        n = find_csv("prohibited_medication_list.csv")
        if n:
            with z.open(n) as f:
                data["prohibited"] = read_csv_safe(f)

        n = find_csv("whodrug_atc_dummy_dictionary.csv")
        if n:
            with z.open(n) as f:
                data["whodrug"] = read_csv_safe(f)

    return data

def load_uploaded_csvs(files):
    data = {dom: pd.DataFrame() for dom in REQUIRED_DOMAINS}
    data["prohibited"] = pd.DataFrame()
    data["whodrug"] = pd.DataFrame()

    for f in files:
        name = f.name.lower()
        df = read_csv_safe(f)
        for dom in REQUIRED_DOMAINS:
            if name == f"{dom}.csv" or name.endswith(f"/{dom}.csv"):
                data[dom] = df
        if "prohibited_medication" in name:
            data["prohibited"] = df
        if "whodrug" in name or "dictionary" in name:
            data["whodrug"] = df
    return data

def max_date(series):
    s = pd.to_datetime(series, errors="coerce")
    return s.max() if not s.dropna().empty else pd.NaT

def min_date(series):
    s = pd.to_datetime(series, errors="coerce")
    return s.min() if not s.dropna().empty else pd.NaT

def prepare_review_dataset(data):
    dm = data.get("dm", pd.DataFrame()).copy()
    ex = data.get("ex", pd.DataFrame()).copy()
    cm = data.get("cm", pd.DataFrame()).copy()
    ae = data.get("ae", pd.DataFrame()).copy()
    dv = data.get("dv", pd.DataFrame()).copy()
    ds = data.get("ds", pd.DataFrame()).copy()
    prohibited = data.get("prohibited", pd.DataFrame()).copy()
    whodrug = data.get("whodrug", pd.DataFrame()).copy()

    for name, df in [("dm", dm), ("ex", ex), ("cm", cm), ("ae", ae), ("dv", dv), ("ds", ds), ("prohibited", prohibited), ("whodrug", whodrug)]:
        if not df.empty:
            df.columns = [str(c).strip().upper() for c in df.columns]

    if cm.empty:
        return pd.DataFrame(), {"error": "CM domain is missing or empty."}

    # Always create required columns before use.
    for col in ["STUDYID", "USUBJID", "CMSEQ", "CMTRT", "CMDECOD", "ATC1CD", "ATC1", "CMSTDTC", "CMENDTC", "PROHFL"]:
        if col not in cm.columns:
            cm[col] = pd.NA

    cm["CMSTDTC_DT"] = safe_date(cm, "CMSTDTC")
    cm["CMENDTC_DT"] = safe_date(cm, "CMENDTC")
    cm["CMENDTC_DT"] = cm["CMENDTC_DT"].fillna(cm["CMSTDTC_DT"])

    # Treatment window from EX.
    if not ex.empty and "USUBJID" in ex.columns:
        for col in ["EXSTDTC", "EXENDTC"]:
            if col not in ex.columns:
                ex[col] = pd.NaT
        ex["EXSTDTC_DT"] = safe_date(ex, "EXSTDTC")
        ex["EXENDTC_DT"] = safe_date(ex, "EXENDTC")
        ex_win = (
            ex.groupby("USUBJID", dropna=False)
              .agg(TRTSDT=("EXSTDTC_DT", "min"), TRTEDT=("EXENDTC_DT", "max"))
              .reset_index()
        )
    else:
        ex_win = pd.DataFrame(columns=["USUBJID", "TRTSDT", "TRTEDT"])

    review = cm.merge(ex_win, on="USUBJID", how="left")
    review["RESTRICT_START"] = review["TRTSDT"]
    review["RESTRICT_END"] = review["TRTEDT"] + pd.Timedelta(days=30)
    review["OVERLAPFL"] = (
        review["CMSTDTC_DT"].notna()
        & review["CMENDTC_DT"].notna()
        & review["RESTRICT_START"].notna()
        & review["RESTRICT_END"].notna()
        & (review["CMSTDTC_DT"] <= review["RESTRICT_END"])
        & (review["CMENDTC_DT"] >= review["RESTRICT_START"])
    ).map({True: "Y", False: "N"})

    # Prohibited medication matching from protocol list / WHODrug dictionary / CM PROHFL.
    prohibited_terms = set()
    if not prohibited.empty:
        for c in ["CMDECOD", "PROTOCOL TERM"]:
            if c in prohibited.columns:
                prohibited_terms.update(prohibited[c].dropna().astype(str).str.upper().str.strip().tolist())
    if not whodrug.empty:
        if "PROTOCOL_STATUS" in whodrug.columns and "WHODRUG_DECOD" in whodrug.columns:
            prohibited_terms.update(
                whodrug.loc[whodrug["PROTOCOL_STATUS"].astype(str).str.upper().eq("PROHIBITED"), "WHODRUG_DECOD"]
                .dropna().astype(str).str.upper().str.strip().tolist()
            )

    cmdecod = review["CMDECOD"].fillna("").astype(str).str.upper().str.strip()
    cmtrt = review["CMTRT"].fillna("").astype(str).str.upper().str.strip()
    protocol_match = cmdecod.isin(prohibited_terms) | cmtrt.isin(prohibited_terms)
    existing_proh = review["PROHFL"].fillna("").astype(str).str.upper().str.strip().isin(["Y", "YES", "TRUE", "1"])
    review["PROHMEDFL"] = (protocol_match | existing_proh).map({True: "Y", False: "N"})

    # Add protocol rationale/category from prohibited list.
    if not prohibited.empty and "CMDECOD" in prohibited.columns:
        merge_cols = [c for c in ["CMDECOD", "PROTOCOL TERM", "ATC CODE", "ATC CLASS", "PROTOCOL RATIONALE", "DEVIATION CLASSIFICATION"] if c in prohibited.columns]
        p2 = prohibited[merge_cols].drop_duplicates("CMDECOD")
        review = review.merge(p2, on="CMDECOD", how="left", suffixes=("", "_PROTOCOL"))

    # DM enrichment.
    if not dm.empty and "USUBJID" in dm.columns:
        dm_cols = [c for c in ["USUBJID", "SUBJID", "SITEID", "COUNTRY", "SEX", "AGE", "RACE", "ARM", "ACTARM", "RFSTDTC"] if c in dm.columns]
        review = review.merge(dm[dm_cols].drop_duplicates("USUBJID"), on="USUBJID", how="left")

    # AE linkage: any AE within +/- 14 days of prohibited medication start or any serious AE.
    if not ae.empty and "USUBJID" in ae.columns:
        for col in ["AESTDTC", "AESER", "AEDECOD", "AESEV"]:
            if col not in ae.columns:
                ae[col] = pd.NA
        ae["AESTDTC_DT"] = safe_date(ae, "AESTDTC")
        ae_summary = ae.groupby("USUBJID").agg(
            AE_COUNT=("USUBJID", "size"),
            SERIOUS_AE_COUNT=("AESER", lambda x: (x.astype(str).str.upper() == "Y").sum()),
            MAX_AE_SEV=("AESEV", lambda x: ", ".join(sorted(set(x.dropna().astype(str))))[:80]),
        ).reset_index()
        review = review.merge(ae_summary, on="USUBJID", how="left")
    else:
        review["AE_COUNT"] = 0
        review["SERIOUS_AE_COUNT"] = 0
        review["MAX_AE_SEV"] = ""

    review["AE_COUNT"] = review.get("AE_COUNT", 0).fillna(0).astype(int)
    review["SERIOUS_AE_COUNT"] = review.get("SERIOUS_AE_COUNT", 0).fillna(0).astype(int)
    review["AEREL_REVIEWFL"] = ((review["AE_COUNT"] > 0) & (review["PROHMEDFL"] == "Y")).map({True: "Y", False: "N"})

    # DV reconciliation.
    if not dv.empty and "USUBJID" in dv.columns:
        for col in ["DVCAT", "DVTERM", "IMPORTANT", "DVDTC"]:
            if col not in dv.columns:
                dv[col] = pd.NA
        dv["DVDTC_DT"] = safe_date(dv, "DVDTC")
        dv["IS_PROH_DV"] = (
            dv["DVCAT"].fillna("").astype(str).str.upper().str.contains("PROHIBITED", na=False)
            | dv["DVTERM"].fillna("").astype(str).str.upper().str.contains("PROHIBITED|MEDICATION", regex=True, na=False)
        )
        dv_proh = dv[dv["IS_PROH_DV"]].groupby("USUBJID").agg(
            DV_PROH_COUNT=("USUBJID", "size"),
            DV_IMPORTANT_COUNT=("IMPORTANT", lambda x: x.astype(str).str.upper().isin(["Y", "YES", "IMPORTANT"]).sum()),
            FIRST_DVDTC=("DVDTC_DT", "min"),
        ).reset_index()
        review = review.merge(dv_proh, on="USUBJID", how="left")
    else:
        review["DV_PROH_COUNT"] = 0
        review["DV_IMPORTANT_COUNT"] = 0
        review["FIRST_DVDTC"] = pd.NaT

    review["DV_PROH_COUNT"] = review.get("DV_PROH_COUNT", 0).fillna(0).astype(int)
    review["DV_IMPORTANT_COUNT"] = review.get("DV_IMPORTANT_COUNT", 0).fillna(0).astype(int)
    review["DV_MATCHFL"] = ((review["PROHMEDFL"] == "Y") & (review["DV_PROH_COUNT"] > 0)).map({True: "Y", False: "N"})
    review["DV_RECON_STATUS"] = "Not Applicable"
    review.loc[(review["PROHMEDFL"] == "Y") & (review["DV_PROH_COUNT"] > 0), "DV_RECON_STATUS"] = "Matched in DV"
    review.loc[(review["PROHMEDFL"] == "Y") & (review["DV_PROH_COUNT"] == 0), "DV_RECON_STATUS"] = "Potential Missing DV"

    review["IPD_FL"] = ((review["PROHMEDFL"] == "Y") & (review["OVERLAPFL"] == "Y")).map({True: "Y", False: "N"})
    review["REVIEW_STATUS"] = "No Action"
    review.loc[(review["PROHMEDFL"] == "Y") & (review["OVERLAPFL"] == "N"), "REVIEW_STATUS"] = "Timing Review"
    review.loc[(review["IPD_FL"] == "Y") & (review["DV_MATCHFL"] == "N"), "REVIEW_STATUS"] = "Needs DV Creation/Review"
    review.loc[(review["IPD_FL"] == "Y") & (review["DV_MATCHFL"] == "Y"), "REVIEW_STATUS"] = "Confirmed / Reconciled"

    review["RISK_LEVEL"] = "Low"
    review.loc[review["PROHMEDFL"] == "Y", "RISK_LEVEL"] = "Medium"
    review.loc[review["IPD_FL"] == "Y", "RISK_LEVEL"] = "High"
    review.loc[(review["IPD_FL"] == "Y") & (review["SERIOUS_AE_COUNT"] > 0), "RISK_LEVEL"] = "Critical"

    # Reviewer editable placeholders.
    review["MEDICAL_REVIEW_COMMENT"] = ""
    review["PROGRAMMING_NOTE"] = ""

    return review, {"error": None}

def render_metric(label, value):
    st.metric(label, value)

st.title(APP_TITLE)
st.caption(APP_SUBTITLE)

with st.sidebar:
    st.header("Data")
    mode = st.radio("Choose data source", ["Use bundled dummy data", "Upload full dummy package zip", "Upload individual CSV files"])
    uploaded_zip = None
    uploaded_csvs = None

    if mode == "Upload full dummy package zip":
        uploaded_zip = st.file_uploader("Upload Dummy_Oncology_Study_Package.zip", type=["zip"])
    elif mode == "Upload individual CSV files":
        uploaded_csvs = st.file_uploader(
            "Upload CSV files: dm, ex, cm, ae, dv, ds, lb, vs, prohibited list, dictionary",
            type=["csv"],
            accept_multiple_files=True,
        )

try:
    if mode == "Upload full dummy package zip" and uploaded_zip is not None:
        data = load_uploaded_zip(uploaded_zip)
    elif mode == "Upload individual CSV files" and uploaded_csvs:
        data = load_uploaded_csvs(uploaded_csvs)
    else:
        data = load_default_data()

    review, info = prepare_review_dataset(data)
except Exception as e:
    st.error("Data could not be processed. Please confirm the uploaded package includes Source_CSV/cm.csv and related SDTM files.")
    with st.expander("Technical detail"):
        st.exception(e)
    st.stop()

if info.get("error"):
    st.error(info["error"])
    st.stop()

with st.expander("Loaded domain summary", expanded=False):
    summary = []
    for k, df in data.items():
        summary.append({"Dataset": k.upper(), "Rows": len(df), "Columns": len(df.columns), "Column Names": ", ".join(list(df.columns)[:20])})
    st.dataframe(pd.DataFrame(summary), use_container_width=True)

# Sidebar filters
with st.sidebar:
    st.header("Filters")
    def options(col):
        if col in review.columns:
            vals = sorted([str(x) for x in review[col].dropna().unique()])
            return vals
        return []
    country_filter = st.multiselect("Country", options("COUNTRY"))
    site_filter = st.multiselect("Site", options("SITEID"))
    arm_filter = st.multiselect("Arm", options("ARM"))
    risk_filter = st.multiselect("Risk Level", options("RISK_LEVEL"), default=[])
    status_filter = st.multiselect("Review Status", options("REVIEW_STATUS"), default=[])
    ipd_only = st.checkbox("Show IPD only", value=False)
    proh_only = st.checkbox("Show prohibited medication only", value=True)

f = review.copy()
if country_filter and "COUNTRY" in f.columns:
    f = f[f["COUNTRY"].astype(str).isin(country_filter)]
if site_filter and "SITEID" in f.columns:
    f = f[f["SITEID"].astype(str).isin(site_filter)]
if arm_filter and "ARM" in f.columns:
    f = f[f["ARM"].astype(str).isin(arm_filter)]
if risk_filter:
    f = f[f["RISK_LEVEL"].astype(str).isin(risk_filter)]
if status_filter:
    f = f[f["REVIEW_STATUS"].astype(str).isin(status_filter)]
if ipd_only:
    f = f[f["IPD_FL"] == "Y"]
if proh_only:
    f = f[f["PROHMEDFL"] == "Y"]

# KPI row
c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: render_metric("Subjects", review["USUBJID"].nunique() if "USUBJID" in review.columns else 0)
with c2: render_metric("CM Records", len(review))
with c3: render_metric("Prohibited Med Records", int((review["PROHMEDFL"] == "Y").sum()))
with c4: render_metric("Important PD Candidates", int((review["IPD_FL"] == "Y").sum()))
with c5: render_metric("Potential Missing DV", int((review["DV_RECON_STATUS"] == "Potential Missing DV").sum()))
with c6: render_metric("Critical Risk", int((review["RISK_LEVEL"] == "Critical").sum()))

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Executive Summary",
    "Subject Review",
    "DV Reconciliation",
    "Protocol Medication List",
    "Data Quality Checks",
])

with tab1:
    st.subheader("Study-Level Oversight")
    left, right = st.columns(2)

    with left:
        st.markdown("**Important PD Candidates by Site**")
        if "SITEID" in f.columns and not f.empty:
            chart = f[f["IPD_FL"] == "Y"].groupby("SITEID").size().reset_index(name="Count")
            st.bar_chart(chart, x="SITEID", y="Count")
        else:
            st.info("No site data available.")

        st.markdown("**Review Status Distribution**")
        if not f.empty:
            st.dataframe(f["REVIEW_STATUS"].value_counts().reset_index().rename(columns={"REVIEW_STATUS":"Review Status", "count":"Count"}), use_container_width=True)

    with right:
        st.markdown("**Risk Level Distribution**")
        if not f.empty:
            st.bar_chart(f["RISK_LEVEL"].value_counts().reset_index().rename(columns={"RISK_LEVEL":"Risk Level", "count":"Count"}), x="Risk Level", y="Count")

        st.markdown("**Medication Category / ATC Class**")
        cat_col = "ATC CLASS" if "ATC CLASS" in f.columns else ("ATC1" if "ATC1" in f.columns else None)
        if cat_col and not f.empty:
            st.dataframe(f[f["PROHMEDFL"]=="Y"][cat_col].fillna("Missing").value_counts().reset_index().rename(columns={cat_col:"Category", "count":"Count"}), use_container_width=True)

with tab2:
    st.subheader("Subject-Level Prohibited Medication Review")
    display_cols = [
        "STUDYID", "USUBJID", "SUBJID", "SITEID", "COUNTRY", "ARM", "SEX", "AGE",
        "CMSEQ", "CMTRT", "CMDECOD", "ATC1CD", "ATC1", "CMSTDTC", "CMENDTC",
        "TRTSDT", "TRTEDT", "RESTRICT_START", "RESTRICT_END",
        "PROHMEDFL", "OVERLAPFL", "IPD_FL", "RISK_LEVEL",
        "AE_COUNT", "SERIOUS_AE_COUNT", "DV_RECON_STATUS", "REVIEW_STATUS",
        "PROTOCOL RATIONALE", "DEVIATION CLASSIFICATION",
        "MEDICAL_REVIEW_COMMENT", "PROGRAMMING_NOTE"
    ]
    available = [c for c in display_cols if c in f.columns]
    st.dataframe(f[available], use_container_width=True, hide_index=True)

    csv = f[available].to_csv(index=False).encode("utf-8")
    st.download_button("Download filtered review CSV", data=csv, file_name="ipd_prohibited_med_review.csv", mime="text/csv")

with tab3:
    st.subheader("CM vs DV Reconciliation")
    rec_cols = [c for c in [
        "USUBJID", "SITEID", "COUNTRY", "CMTRT", "CMDECOD", "CMSTDTC", "CMENDTC",
        "PROHMEDFL", "OVERLAPFL", "IPD_FL", "DV_PROH_COUNT", "DV_IMPORTANT_COUNT",
        "FIRST_DVDTC", "DV_RECON_STATUS", "REVIEW_STATUS"
    ] if c in f.columns]
    st.dataframe(f[rec_cols], use_container_width=True, hide_index=True)

with tab4:
    st.subheader("Protocol Prohibited Medication List")
    prohibited = data.get("prohibited", pd.DataFrame())
    whodrug = data.get("whodrug", pd.DataFrame())
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Protocol List**")
        st.dataframe(prohibited, use_container_width=True, hide_index=True)
    with c2:
        st.markdown("**WHODrug / ATC Dictionary**")
        st.dataframe(whodrug, use_container_width=True, hide_index=True)

with tab5:
    st.subheader("Data Quality Checks")
    checks = []
    domain_expected = {
        "dm": ["STUDYID", "USUBJID", "SITEID", "COUNTRY", "ARM", "RFSTDTC"],
        "ex": ["USUBJID", "EXTRT", "EXSTDTC", "EXENDTC"],
        "cm": ["USUBJID", "CMTRT", "CMDECOD", "CMSTDTC", "CMENDTC", "PROHFL"],
        "ae": ["USUBJID", "AEDECOD", "AESER", "AESTDTC"],
        "dv": ["USUBJID", "DVCAT", "DVTERM", "IMPORTANT", "DVDTC"],
    }
    for dom, cols in domain_expected.items():
        df = data.get(dom, pd.DataFrame())
        missing = [c for c in cols if c not in df.columns]
        checks.append({
            "Domain": dom.upper(),
            "Rows": len(df),
            "Status": "Pass" if not missing and len(df) > 0 else "Review",
            "Missing Columns": ", ".join(missing)
        })
    st.dataframe(pd.DataFrame(checks), use_container_width=True, hide_index=True)

    st.markdown("**Records requiring review**")
    st.dataframe(
        review[(review["PROHMEDFL"] == "Y") & ((review["OVERLAPFL"] == "N") | (review["DV_MATCHFL"] == "N"))]
        [[c for c in ["USUBJID", "CMTRT", "CMDECOD", "CMSTDTC", "CMENDTC", "OVERLAPFL", "IPD_FL", "DV_RECON_STATUS", "REVIEW_STATUS"] if c in review.columns]],
        use_container_width=True,
        hide_index=True,
    )

st.caption("Dashboard logic is for demonstration using dummy oncology SDTM-like data. Medical review and protocol interpretation should confirm final Important Protocol Deviation decisions.")
