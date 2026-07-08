import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO

st.set_page_config(page_title="Prohibited Medication IPD Dashboard", page_icon="⚠️", layout="wide")

REQUIRED_COLUMNS = [
    "Study ID", "Subject ID", "Country", "Site", "Treatment Arm", "Study Treatment",
    "Treatment Start", "Treatment End", "Medication Name", "Medication Start", "Medication End",
    "Prohibited Category", "Related AE", "Review Status", "IPD Assessment", "DV Reconciliation", "Reviewer Comment"
]
DATE_COLUMNS = ["Treatment Start", "Treatment End", "Medication Start", "Medication End"]

COLUMN_ALIASES = {
    "Study ID": ["STUDYID", "Study", "Protocol", "Protocol ID", "Protocol Number"],
    "Subject ID": ["USUBJID", "SUBJID", "Subject", "Subject Number", "Patient ID", "Participant ID"],
    "Country": ["COUNTRY", "Country Code"],
    "Site": ["SITEID", "Site ID", "Site Number", "Investigator Site"],
    "Treatment Arm": ["ARM", "ACTARM", "TRT01A", "Arm", "Randomized Arm"],
    "Study Treatment": ["EXTRT", "Treatment", "Study Drug", "Study Treatment Name"],
    "Treatment Start": ["TRTSDT", "TRTSDTM", "EXSTDTC", "Treatment Start Date", "First Dose Date", "RFSTDTC"],
    "Treatment End": ["TRTEDT", "TRTEDTM", "EXENDTC", "Treatment End Date", "Last Dose Date", "RFENDTC"],
    "Medication Name": ["CMTRT", "CMDECOD", "Medication", "Drug Name", "Conmed", "Concomitant Medication"],
    "Medication Start": ["CMSTDTC", "CMSTDT", "Medication Start Date", "CM Start Date", "Start Date"],
    "Medication End": ["CMENDTC", "CMENDT", "Medication End Date", "CM End Date", "End Date"],
    "Prohibited Category": ["ATC Class", "CMCLAS", "Category", "Drug Class", "Prohibited Medication Category", "Prohibited Class"],
    "Related AE": ["AESEQ", "AE Term", "AETERM", "AEDECOD", "Related Adverse Event", "AE"],
    "Review Status": ["Status", "Medical Review Status", "Reviewer Status"],
    "IPD Assessment": ["Important PD", "Important Protocol Deviation", "IPD", "PD Assessment", "DV Importance"],
    "DV Reconciliation": ["DV Match", "DV Status", "Deviation Reconciliation", "DV Reconciliation Status"],
    "Reviewer Comment": ["Comment", "Comments", "Medical Comment", "Programming Comment", "Reviewer Comments"],
}

@st.cache_data
def load_sample_data():
    data = [
        ["ONC-001", "1001-001", "US", "Site 1001", "Arm A", "Osimertinib", "2026-01-05", "2026-05-15", "Clarithromycin", "2026-02-02", "2026-02-08", "Strong CYP3A inhibitor", "AE-001", "Confirmed", "Important", "Matched", "Reviewed - important due to treatment overlap"],
        ["ONC-001", "1001-002", "US", "Site 1001", "Arm B", "Chemotherapy", "2026-01-11", "2026-04-21", "St. John's Wort", "2026-02-20", "2026-03-02", "Herbal prohibited product", "", "Pending", "Needs Review", "Missing in DV", "Need medical confirmation"],
        ["ONC-001", "1002-004", "CA", "Site 1002", "Arm A", "Osimertinib", "2026-01-18", "2026-06-11", "Rifampin", "2026-03-01", "2026-03-07", "Strong CYP3A inducer", "AE-021", "Confirmed", "Important", "Matched", "Potential exposure impact"],
        ["ONC-001", "1003-007", "UK", "Site 1003", "Arm B", "Chemotherapy", "2026-02-03", "2026-05-30", "Live vaccine", "2026-01-01", "2026-01-02", "Live vaccine", "", "Closed", "Not Important", "Not Applicable", "Before treatment window"],
        ["ONC-001", "1003-010", "UK", "Site 1003", "Arm A", "Osimertinib", "2026-02-09", "2026-06-18", "Ketoconazole", "2026-04-04", "2026-04-13", "Strong CYP3A inhibitor", "AE-032", "Pending", "Important", "Missing in DV", "Requires DV entry review"],
        ["ONC-002", "2001-003", "US", "Site 2001", "Arm A", "Immunotherapy", "2026-01-20", "2026-06-02", "Prednisone high dose", "2026-02-10", "2026-02-25", "Systemic corticosteroid", "AE-044", "Confirmed", "Important", "Matched", "Dose above protocol threshold"],
        ["ONC-002", "2002-006", "DE", "Site 2002", "Arm C", "Combination", "2026-02-14", "2026-06-12", "Investigational drug", "2026-05-01", "2026-05-03", "Other investigational therapy", "", "Pending", "Important", "Missing in DV", "Confirm source documentation"],
        ["ONC-002", "2002-008", "DE", "Site 2002", "Arm C", "Combination", "2026-02-22", "2026-06-25", "Ondansetron", "2026-03-03", "2026-03-04", "QT-prolonging drug", "AE-050", "Closed", "Needs Review", "Matched", "QT risk review completed"],
    ]
    df = pd.DataFrame(data, columns=REQUIRED_COLUMNS)
    for col in DATE_COLUMNS:
        df[col] = pd.to_datetime(df[col])
    return df

def normalize_col(x):
    return str(x).strip().lower().replace("_", " ").replace("-", " ")

def standardize_upload(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    existing = {normalize_col(c): c for c in df.columns}
    rename_map = {}
    for standard, aliases in COLUMN_ALIASES.items():
        possible = [standard] + aliases
        for p in possible:
            key = normalize_col(p)
            if key in existing:
                rename_map[existing[key]] = standard
                break
    df = df.rename(columns=rename_map)

    missing = []
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            missing.append(col)
            if col in DATE_COLUMNS:
                df[col] = pd.NaT
            elif col == "Review Status":
                df[col] = "Pending"
            elif col == "IPD Assessment":
                df[col] = "Needs Review"
            elif col == "DV Reconciliation":
                df[col] = "Needs Review"
            else:
                df[col] = ""
    return df, missing, rename_map

def prepare_data(df):
    df, missing, rename_map = standardize_upload(df)
    for col in DATE_COLUMNS:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    overlap = (
        df["Medication Start"].notna() & df["Medication End"].notna() &
        df["Treatment Start"].notna() & df["Treatment End"].notna() &
        (df["Medication Start"] <= df["Treatment End"]) &
        (df["Medication End"] >= df["Treatment Start"])
    )
    df["Treatment Overlap"] = overlap.map({True: "Yes", False: "No"})
    df["Prohibited Medication Flag"] = df["Prohibited Category"].fillna("").astype(str).str.strip().ne("").map({True: "Yes", False: "No"})
    df["Related AE Flag"] = df["Related AE"].fillna("").astype(str).str.strip().ne("").map({True: "Yes", False: "No"})

    for col in ["Review Status", "IPD Assessment", "DV Reconciliation"]:
        df[col] = df[col].fillna("Needs Review").astype(str).replace({"": "Needs Review"})

    def risk(row):
        score = 0
        if row.get("Treatment Overlap") == "Yes": score += 2
        if row.get("IPD Assessment") == "Important": score += 3
        if row.get("Related AE Flag") == "Yes": score += 1
        if row.get("DV Reconciliation") == "Missing in DV": score += 2
        if row.get("Review Status") == "Pending": score += 1
        if score >= 6: return "High"
        if score >= 3: return "Medium"
        return "Low"
    df["Risk Level"] = df.apply(risk, axis=1)
    df["Medication Month"] = df["Medication Start"].dt.to_period("M").astype(str).replace("NaT", "Missing Date")
    return df, missing, rename_map

def safe_options(df, col):
    vals = sorted([v for v in df[col].dropna().unique() if str(v).strip() != ""])
    return vals if vals else []

def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Prohibited Med Review")
    return output.getvalue()

st.title("⚠️ Oncology Prohibited Medication & Important Protocol Deviation Dashboard")
st.caption("Review potential prohibited medication use, treatment overlap, DV reconciliation, and important protocol deviation status.")

with st.sidebar:
    st.header("Data Input")
    uploaded = st.file_uploader("Upload review file (.csv or .xlsx)", type=["csv", "xlsx"])
    st.markdown("The app accepts template columns and common SDTM-like names such as STUDYID, USUBJID, CMTRT, CMSTDTC, CMENDTC, ARM, SITEID.")

try:
    if uploaded:
        if uploaded.name.lower().endswith(".csv"):
            df_raw = pd.read_csv(uploaded)
        else:
            df_raw = pd.read_excel(uploaded)
    else:
        df_raw = load_sample_data()
    df, missing_cols, rename_map = prepare_data(df_raw)
except Exception as e:
    st.error("File could not be read. Please upload a standard CSV/XLSX file or download the template below.")
    st.exception(e)
    df, missing_cols, rename_map = prepare_data(load_sample_data())

if uploaded and missing_cols:
    st.warning("Some expected columns were missing, so the app filled them with defaults/blanks: " + ", ".join(missing_cols))
if uploaded and rename_map:
    with st.expander("Column mapping used"):
        st.json(rename_map)

with st.sidebar:
    st.header("Filters")
    studies = st.multiselect("Study ID", safe_options(df, "Study ID"), default=safe_options(df, "Study ID"))
    countries = st.multiselect("Country", safe_options(df, "Country"), default=safe_options(df, "Country"))
    arms = st.multiselect("Treatment Arm", safe_options(df, "Treatment Arm"), default=safe_options(df, "Treatment Arm"))
    statuses = st.multiselect("Review Status", safe_options(df, "Review Status"), default=safe_options(df, "Review Status"))
    ipd = st.multiselect("IPD Assessment", safe_options(df, "IPD Assessment"), default=safe_options(df, "IPD Assessment"))
    risk_values = st.multiselect("Risk Level", safe_options(df, "Risk Level"), default=safe_options(df, "Risk Level"))

filtered = df.copy()
for col, selected in [("Study ID", studies), ("Country", countries), ("Treatment Arm", arms), ("Review Status", statuses), ("IPD Assessment", ipd), ("Risk Level", risk_values)]:
    if selected:
        filtered = filtered[filtered[col].isin(selected)]

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Subjects", filtered["Subject ID"].nunique())
c2.metric("Prohibited Med Records", len(filtered))
c3.metric("Important IPDs", int((filtered["IPD Assessment"] == "Important").sum()))
c4.metric("Pending Review", int((filtered["Review Status"] == "Pending").sum()))
c5.metric("Missing in DV", int((filtered["DV Reconciliation"] == "Missing in DV").sum()))
c6.metric("High Risk", int((filtered["Risk Level"] == "High").sum()))

st.divider()
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Executive Summary", "Subject Review", "Medication Categories", "DV Reconciliation", "Data Template"])
review_cols = ["Study ID", "Subject ID", "Country", "Site", "Treatment Arm", "Medication Name", "Prohibited Category", "Medication Start", "Medication End", "Treatment Start", "Treatment End", "Treatment Overlap", "Related AE Flag", "IPD Assessment", "DV Reconciliation", "Risk Level", "Review Status", "Reviewer Comment"]

with tab1:
    if filtered.empty:
        st.info("No records match the selected filters.")
    else:
        left, right = st.columns(2)
        with left:
            st.subheader("Important PDs by Site")
            by_site = filtered.groupby(["Site", "IPD Assessment"], dropna=False, as_index=False).size()
            st.plotly_chart(px.bar(by_site, x="Site", y="size", color="IPD Assessment", barmode="stack", labels={"size":"Record Count"}), use_container_width=True)
        with right:
            st.subheader("Review Status by Country")
            by_country = filtered.groupby(["Country", "Review Status"], dropna=False, as_index=False).size()
            st.plotly_chart(px.bar(by_country, x="Country", y="size", color="Review Status", barmode="stack", labels={"size":"Record Count"}), use_container_width=True)
        left2, right2 = st.columns(2)
        with left2:
            st.subheader("Monthly Trend")
            monthly = filtered.groupby("Medication Month", dropna=False, as_index=False).size()
            st.plotly_chart(px.line(monthly, x="Medication Month", y="size", markers=True, labels={"size":"Record Count"}), use_container_width=True)
        with right2:
            st.subheader("Risk Level Distribution")
            st.plotly_chart(px.pie(filtered, names="Risk Level", hole=0.45), use_container_width=True)

with tab2:
    st.subheader("Subject-Level Prohibited Medication Review")
    edited = st.data_editor(
        filtered[review_cols], use_container_width=True, hide_index=True, num_rows="dynamic",
        column_config={
            "Review Status": st.column_config.SelectboxColumn(options=["Pending", "Confirmed", "Closed", "Not Deviation", "Needs Review"]),
            "IPD Assessment": st.column_config.SelectboxColumn(options=["Important", "Not Important", "Needs Review"]),
            "DV Reconciliation": st.column_config.SelectboxColumn(options=["Matched", "Missing in DV", "Not Applicable", "Needs Review"]),
            "Risk Level": st.column_config.SelectboxColumn(options=["High", "Medium", "Low"]),
        }
    )
    st.download_button("Download Current Review Table", data=to_excel(edited), file_name="prohibited_med_review.xlsx")

with tab3:
    st.subheader("Medication Category Summary")
    cat = filtered.groupby(["Prohibited Category", "IPD Assessment"], dropna=False, as_index=False).size()
    if not cat.empty:
        st.plotly_chart(px.bar(cat, x="Prohibited Category", y="size", color="IPD Assessment", barmode="group", labels={"size":"Record Count"}), use_container_width=True)
    st.dataframe(cat, use_container_width=True, hide_index=True)

with tab4:
    st.subheader("DV Reconciliation Review")
    dv = filtered.groupby(["DV Reconciliation", "Review Status"], dropna=False, as_index=False).size()
    if not dv.empty:
        st.plotly_chart(px.bar(dv, x="DV Reconciliation", y="size", color="Review Status", barmode="stack", labels={"size":"Record Count"}), use_container_width=True)
    st.dataframe(filtered[filtered["DV Reconciliation"] == "Missing in DV"][review_cols], use_container_width=True, hide_index=True)

with tab5:
    st.subheader("Upload Template")
    st.write("Use this structure for production data. The app also accepts common SDTM-style column names and maps them automatically.")
    sample = load_sample_data()
    st.dataframe(sample, use_container_width=True, hide_index=True)
    st.download_button("Download Sample Template", data=to_excel(sample), file_name="prohibited_med_dashboard_template.xlsx")

st.divider()
st.info("Validation note: This dashboard is a review aid. Final IPD classification should follow the protocol, SAP/PD plan, medical review, and sponsor governance process.")
