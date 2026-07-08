import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from io import BytesIO

st.set_page_config(
    page_title="Prohibited Medication IPD Dashboard",
    page_icon="⚠️",
    layout="wide"
)

# -----------------------------
# Helper functions
# -----------------------------
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
    columns = [
        "Study ID", "Subject ID", "Country", "Site", "Treatment Arm", "Study Treatment",
        "Treatment Start", "Treatment End", "Medication Name", "Medication Start", "Medication End",
        "Prohibited Category", "Related AE", "Review Status", "IPD Assessment", "DV Reconciliation", "Reviewer Comment"
    ]
    df = pd.DataFrame(data, columns=columns)
    date_cols = ["Treatment Start", "Treatment End", "Medication Start", "Medication End"]
    for col in date_cols:
        df[col] = pd.to_datetime(df[col])
    return df

def prepare_data(df):
    date_cols = ["Treatment Start", "Treatment End", "Medication Start", "Medication End"]
    for col in date_cols:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    df["Treatment Overlap"] = (
        (df["Medication Start"] <= df["Treatment End"]) &
        (df["Medication End"] >= df["Treatment Start"])
    ).map({True: "Yes", False: "No"})

    df["Prohibited Medication Flag"] = df["Prohibited Category"].notna().map({True: "Yes", False: "No"})
    df["Related AE Flag"] = df["Related AE"].fillna("").astype(str).str.strip().ne("").map({True: "Yes", False: "No"})

    def risk(row):
        score = 0
        if row["Treatment Overlap"] == "Yes": score += 2
        if row["IPD Assessment"] == "Important": score += 3
        if row["Related AE Flag"] == "Yes": score += 1
        if row["DV Reconciliation"] == "Missing in DV": score += 2
        if row["Review Status"] == "Pending": score += 1
        if score >= 6: return "High"
        if score >= 3: return "Medium"
        return "Low"

    df["Risk Level"] = df.apply(risk, axis=1)
    df["Medication Month"] = df["Medication Start"].dt.to_period("M").astype(str)
    return df

def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Prohibited Med Review")
    return output.getvalue()

# -----------------------------
# App layout
# -----------------------------
st.title("⚠️ Oncology Prohibited Medication & Important Protocol Deviation Dashboard")
st.caption("Review potential prohibited medication use, treatment overlap, DV reconciliation, and important protocol deviation status.")

with st.sidebar:
    st.header("Data Input")
    uploaded = st.file_uploader("Upload review file (.csv or .xlsx)", type=["csv", "xlsx"])
    st.markdown("Required columns should match the sample template. If no file is uploaded, sample data will be used.")

if uploaded:
    if uploaded.name.endswith(".csv"):
        df_raw = pd.read_csv(uploaded)
    else:
        df_raw = pd.read_excel(uploaded)
else:
    df_raw = load_sample_data()

df = prepare_data(df_raw.copy())

# Sidebar filters
with st.sidebar:
    st.header("Filters")
    studies = st.multiselect("Study ID", sorted(df["Study ID"].dropna().unique()), default=sorted(df["Study ID"].dropna().unique()))
    countries = st.multiselect("Country", sorted(df["Country"].dropna().unique()), default=sorted(df["Country"].dropna().unique()))
    arms = st.multiselect("Treatment Arm", sorted(df["Treatment Arm"].dropna().unique()), default=sorted(df["Treatment Arm"].dropna().unique()))
    statuses = st.multiselect("Review Status", sorted(df["Review Status"].dropna().unique()), default=sorted(df["Review Status"].dropna().unique()))
    ipd = st.multiselect("IPD Assessment", sorted(df["IPD Assessment"].dropna().unique()), default=sorted(df["IPD Assessment"].dropna().unique()))
    risk = st.multiselect("Risk Level", sorted(df["Risk Level"].dropna().unique()), default=sorted(df["Risk Level"].dropna().unique()))

filtered = df[
    df["Study ID"].isin(studies) &
    df["Country"].isin(countries) &
    df["Treatment Arm"].isin(arms) &
    df["Review Status"].isin(statuses) &
    df["IPD Assessment"].isin(ipd) &
    df["Risk Level"].isin(risk)
]

# KPI section
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Subjects", filtered["Subject ID"].nunique())
c2.metric("Prohibited Med Records", len(filtered))
c3.metric("Important IPDs", int((filtered["IPD Assessment"] == "Important").sum()))
c4.metric("Pending Review", int((filtered["Review Status"] == "Pending").sum()))
c5.metric("Missing in DV", int((filtered["DV Reconciliation"] == "Missing in DV").sum()))
c6.metric("High Risk", int((filtered["Risk Level"] == "High").sum()))

st.divider()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Executive Summary", "Subject Review", "Medication Categories", "DV Reconciliation", "Data Template"
])

with tab1:
    left, right = st.columns(2)
    with left:
        st.subheader("Important PDs by Site")
        by_site = filtered.groupby(["Site", "IPD Assessment"], as_index=False).size()
        fig = px.bar(by_site, x="Site", y="size", color="IPD Assessment", barmode="stack", labels={"size":"Record Count"})
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("Review Status by Country")
        by_country = filtered.groupby(["Country", "Review Status"], as_index=False).size()
        fig = px.bar(by_country, x="Country", y="size", color="Review Status", barmode="stack", labels={"size":"Record Count"})
        st.plotly_chart(fig, use_container_width=True)

    left2, right2 = st.columns(2)
    with left2:
        st.subheader("Monthly Trend")
        monthly = filtered.groupby("Medication Month", as_index=False).size()
        fig = px.line(monthly, x="Medication Month", y="size", markers=True, labels={"size":"Record Count"})
        st.plotly_chart(fig, use_container_width=True)
    with right2:
        st.subheader("Risk Level Distribution")
        fig = px.pie(filtered, names="Risk Level", hole=0.45)
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Subject-Level Prohibited Medication Review")
    review_cols = [
        "Study ID", "Subject ID", "Country", "Site", "Treatment Arm", "Medication Name",
        "Prohibited Category", "Medication Start", "Medication End", "Treatment Start", "Treatment End",
        "Treatment Overlap", "Related AE Flag", "IPD Assessment", "DV Reconciliation", "Risk Level",
        "Review Status", "Reviewer Comment"
    ]
    edited = st.data_editor(
        filtered[review_cols],
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "Review Status": st.column_config.SelectboxColumn(options=["Pending", "Confirmed", "Closed", "Not Deviation"]),
            "IPD Assessment": st.column_config.SelectboxColumn(options=["Important", "Not Important", "Needs Review"]),
            "DV Reconciliation": st.column_config.SelectboxColumn(options=["Matched", "Missing in DV", "Not Applicable"]),
            "Risk Level": st.column_config.SelectboxColumn(options=["High", "Medium", "Low"]),
        }
    )
    st.download_button("Download Current Review Table", data=to_excel(edited), file_name="prohibited_med_review.xlsx")

with tab3:
    st.subheader("Medication Category Summary")
    cat = filtered.groupby(["Prohibited Category", "IPD Assessment"], as_index=False).size()
    fig = px.bar(cat, x="Prohibited Category", y="size", color="IPD Assessment", barmode="group", labels={"size":"Record Count"})
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(cat, use_container_width=True, hide_index=True)

with tab4:
    st.subheader("DV Reconciliation Review")
    dv = filtered.groupby(["DV Reconciliation", "Review Status"], as_index=False).size()
    fig = px.bar(dv, x="DV Reconciliation", y="size", color="Review Status", barmode="stack", labels={"size":"Record Count"})
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(filtered[filtered["DV Reconciliation"] == "Missing in DV"][review_cols], use_container_width=True, hide_index=True)

with tab5:
    st.subheader("Upload Template")
    st.write("Use this structure for production data. You can export the sample file and replace with your study data.")
    st.dataframe(load_sample_data(), use_container_width=True, hide_index=True)
    st.download_button("Download Sample Template", data=to_excel(load_sample_data()), file_name="prohibited_med_dashboard_template.xlsx")

st.divider()
st.info("Validation note: This dashboard is a review aid. Final IPD classification should follow the protocol, SAP/PD plan, medical review, and sponsor governance process.")
