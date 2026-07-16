
import io
import os
import zipfile
import hashlib
import re
import traceback
from datetime import datetime
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Clinexa AI | TrialGuard",
    page_icon="🛡️",
    layout="wide",
)

APP_TITLE = "TrialGuard"
APP_SUBTITLE = "Prohibited Medication & Important Protocol Deviation Review"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SRC_DIR = os.path.join(DATA_DIR, "Source_CSV")
CT_DIR = os.path.join(DATA_DIR, "Controlled_Terminology")
RULES_PATH = os.path.join(DATA_DIR, "study_rules.csv")
RULES_XLSX_PATH = os.path.join(DATA_DIR, "Study_Rules_DUM_ONC_001.xlsx")
XPT_DIR = os.path.join(DATA_DIR, "SDTM_XPT")

REQUIRED_DOMAINS = ["dm", "ex", "cm", "ae", "dv", "ds", "lb", "vs"]

# Study datasets may contain ATC hierarchy levels 4 through 7.
ATC_LEVELS = [4, 5, 6, 7]
ATC_CODE_COLUMNS = [f"ATC{level}CD" for level in ATC_LEVELS]
ATC_CLASS_COLUMNS = [f"ATC{level}" for level in ATC_LEVELS]
ATC_ALL_COLUMNS = [item for level in ATC_LEVELS for item in (f"ATC{level}CD", f"ATC{level}")]
ATC_LEGACY_ALIASES = ["ATC1CD", "ATC1", "ATC_CODE", "ATC_CLASS", "ATC CODE", "ATC CLASS"]

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


def read_sas_safe(path_or_buffer, extension: str) -> pd.DataFrame:
    extension = extension.lower()
    fmt = "xport" if extension in [".xpt", ".xport"] else "sas7bdat"
    return normalize_columns(pd.read_sas(path_or_buffer, format=fmt, encoding="utf-8"))


def read_dataset_safe(file_or_path, filename: str | None = None) -> pd.DataFrame:
    name = (filename or getattr(file_or_path, "name", "") or str(file_or_path)).lower()
    ext = os.path.splitext(name)[1]
    if ext == ".csv":
        return read_csv_safe(file_or_path)
    if ext in [".xpt", ".xport", ".sas7bdat"]:
        # UploadedFile/ZipExtFile objects are buffered to avoid seek limitations.
        if hasattr(file_or_path, "read") and not isinstance(file_or_path, (str, os.PathLike)):
            raw = file_or_path.read()
            try:
                file_or_path.seek(0)
            except Exception:
                pass
            return read_sas_safe(io.BytesIO(raw), ext)
        return read_sas_safe(file_or_path, ext)
    raise ValueError(f"Unsupported dataset type: {ext or name}")


def domain_from_filename(filename: str):
    """Infer an SDTM domain from flexible filenames and nested ZIP paths."""
    stem = os.path.splitext(os.path.basename(filename).lower())[0]
    normalized = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    aliases = {"suppcm": "cm", "suppdv": "dv"}
    if normalized in REQUIRED_DOMAINS:
        return normalized
    if normalized in aliases:
        return aliases[normalized]
    # Accept names such as cm_2026, sdtm_cm, study-cm-final, dm_data.
    tokens = [t for t in normalized.split("_") if t]
    for dom in REQUIRED_DOMAINS:
        if dom in tokens:
            return dom
    # Conservative prefix/suffix fallback.
    for dom in REQUIRED_DOMAINS:
        if normalized.startswith(dom) or normalized.endswith(dom):
            return dom
    return None


@st.cache_data(show_spinner=False)
def load_default_data():
    data = {}
    for dom in REQUIRED_DOMAINS:
        csv_path = os.path.join(SRC_DIR, f"{dom}.csv")
        xpt_path = os.path.join(XPT_DIR, f"{dom}.xpt")
        if os.path.exists(csv_path):
            data[dom] = read_dataset_safe(csv_path, f"{dom}.csv")
        elif os.path.exists(xpt_path):
            data[dom] = read_dataset_safe(xpt_path, f"{dom}.xpt")
        else:
            data[dom] = pd.DataFrame()

    pm_path = os.path.join(CT_DIR, "prohibited_medication_list.csv")
    whodrug_path = os.path.join(CT_DIR, "whodrug_atc_dummy_dictionary.csv")
    data["prohibited"] = read_csv_safe(pm_path) if os.path.exists(pm_path) else pd.DataFrame()
    data["whodrug"] = read_csv_safe(whodrug_path) if os.path.exists(whodrug_path) else pd.DataFrame()
    data["source_formats"] = "Bundled CSV/XPT"
    return data


def empty_data():
    data = {dom: pd.DataFrame() for dom in REQUIRED_DOMAINS}
    data["prohibited"] = pd.DataFrame()
    data["whodrug"] = pd.DataFrame()
    return data


def load_uploaded_zip(uploaded_file):
    data = empty_data()
    loaded_formats = []
    with zipfile.ZipFile(uploaded_file) as z:
        names = [n for n in z.namelist() if not n.startswith("__MACOSX/") and not os.path.basename(n).startswith("._")]
        # Prefer CSV when duplicate domains exist because it preserves the complete configurable ATC hierarchy; SAS/XPT remain supported when supplied alone.
        priority = {".csv": 3, ".sas7bdat": 2, ".xpt": 1, ".xport": 1}
        candidates = {}
        for n in names:
            ext = os.path.splitext(n.lower())[1]
            dom = domain_from_filename(n)
            if dom and ext in priority:
                if dom not in candidates or priority[ext] > priority[os.path.splitext(candidates[dom].lower())[1]]:
                    candidates[dom] = n
        for dom, n in candidates.items():
            with z.open(n) as f:
                data[dom] = read_dataset_safe(f, n)
                loaded_formats.append(f"{dom.upper()}:{os.path.splitext(n)[1].upper()}")
        for n in names:
            low = n.lower()
            if low.endswith("prohibited_medication_list.csv"):
                with z.open(n) as f: data["prohibited"] = read_csv_safe(f)
            elif low.endswith("whodrug_atc_dummy_dictionary.csv"):
                with z.open(n) as f: data["whodrug"] = read_csv_safe(f)
    data["source_formats"] = ", ".join(loaded_formats) or "No supported domains found"
    return data


def load_uploaded_datasets(files):
    data = empty_data()
    loaded_formats = []
    for f in files:
        name = f.name.lower()
        if "prohibited_medication" in name and name.endswith(".csv"):
            data["prohibited"] = read_csv_safe(f)
            continue
        if ("whodrug" in name or "dictionary" in name) and name.endswith(".csv"):
            data["whodrug"] = read_csv_safe(f)
            continue
        dom = domain_from_filename(name)
        if dom:
            data[dom] = read_dataset_safe(f, name)
            loaded_formats.append(f"{dom.upper()}:{os.path.splitext(name)[1].upper()}")
    data["source_formats"] = ", ".join(loaded_formats) or "No supported domains found"
    return data

def max_date(series):
    s = pd.to_datetime(series, errors="coerce")
    return s.max() if not s.dropna().empty else pd.NaT

def min_date(series):
    s = pd.to_datetime(series, errors="coerce")
    return s.min() if not s.dropna().empty else pd.NaT


RULE_COLUMNS = ["RULE_ID", "SOURCE", "SECTION", "RULE_NAME", "DESCRIPTION", "SEVERITY", "ENABLED", "RULE_TYPE", "DOMAIN", "MATCH_FIELDS", "OPERATOR", "PARAMETER", "EXPECTED_VALUE", "IMPORTANT_PD", "ACTION"]


def standardize_rules(rules: pd.DataFrame) -> pd.DataFrame:
    rules = normalize_columns(rules)
    # Backward-compatible mapping for the prior CSV template.
    if "MATCH_FIELDS" not in rules.columns and "RULE_TYPE" in rules.columns:
        rules["MATCH_FIELDS"] = ""
    if "OPERATOR" not in rules.columns:
        rules["OPERATOR"] = ""
    if "DOMAIN" not in rules.columns:
        rules["DOMAIN"] = ""
    if "IMPORTANT_PD" not in rules.columns:
        rules["IMPORTANT_PD"] = ""
    if "ACTION" not in rules.columns:
        rules["ACTION"] = ""
    for col in RULE_COLUMNS:
        if col not in rules.columns:
            rules[col] = ""
    return rules[RULE_COLUMNS].fillna("")


def read_rules_file(file_or_path, filename=None) -> pd.DataFrame:
    name = (filename or getattr(file_or_path, "name", "") or str(file_or_path)).lower()
    if name.endswith(".csv"):
        return standardize_rules(pd.read_csv(file_or_path))
    if name.endswith((".xlsx", ".xlsm")):
        xl = pd.ExcelFile(file_or_path)
        preferred = next((x for x in xl.sheet_names if x.strip().lower() == "rule engine"), xl.sheet_names[0])
        # Dummy workbook has title in row 1 and headers in row 2.
        probe = pd.read_excel(xl, sheet_name=preferred, header=None, nrows=4)
        header_row = 0
        for i in range(len(probe)):
            vals = probe.iloc[i].astype(str).str.upper().tolist()
            if "RULE_ID" in vals and "RULE_TYPE" in vals:
                header_row = i
                break
        return standardize_rules(pd.read_excel(xl, sheet_name=preferred, header=header_row))
    raise ValueError("Rule file must be CSV or XLSX.")


def load_default_rules() -> pd.DataFrame:
    if os.path.exists(RULES_XLSX_PATH):
        return read_rules_file(RULES_XLSX_PATH, RULES_XLSX_PATH)
    if os.path.exists(RULES_PATH):
        return read_rules_file(RULES_PATH, RULES_PATH)
    return standardize_rules(pd.DataFrame())


VALIDATION_REQUIRED = {
    "dm": ["STUDYID", "USUBJID", "SITEID", "COUNTRY", "ARM"],
    "ex": ["STUDYID", "USUBJID", "EXTRT", "EXSTDTC"],
    "cm": ["STUDYID", "USUBJID", "CMTRT", "CMSTDTC"],
    "dv": ["STUDYID", "USUBJID", "DVTERM"],
}

VALIDATION_RECOMMENDED = {
    "dm": ["RFSTDTC", "SEX", "AGE"],
    "ex": ["EXENDTC"],
    "cm": ["CMDECOD", "CMENDTC", "CMSEQ"],
    "dv": ["DVCAT", "IMPORTANT", "DVDTC"],
    "ae": ["USUBJID", "AEDECOD", "AESER", "AESTDTC"],
}


def _result(check_id, domain, check, severity, status, detail, affected=0, action=""):
    return {
        "CHECK_ID": check_id,
        "DOMAIN": domain.upper() if domain else "STUDY",
        "CHECK": check,
        "SEVERITY": severity,
        "STATUS": status,
        "AFFECTED_RECORDS": int(affected or 0),
        "DETAIL": detail,
        "RECOMMENDED_ACTION": action,
    }


def run_data_validation(data: dict) -> pd.DataFrame:
    results = []
    dm_subjects = set()
    study_ids = set()

    for dom in REQUIRED_DOMAINS:
        df = data.get(dom, pd.DataFrame())
        required = VALIDATION_REQUIRED.get(dom, [])
        recommended = VALIDATION_RECOMMENDED.get(dom, [])
        if dom in VALIDATION_REQUIRED and df.empty:
            results.append(_result(f"{dom.upper()}001", dom, "Required domain present", "Critical", "Fail", f"{dom.upper()} dataset is missing or empty.", 0, f"Upload a valid {dom.upper()} dataset."))
            continue
        if df.empty:
            results.append(_result(f"{dom.upper()}001", dom, "Optional domain present", "Info", "Not Run", f"{dom.upper()} dataset was not supplied.", 0, "Upload only when required by active rules."))
            continue

        missing_req = [c for c in required if c not in df.columns]
        results.append(_result(f"{dom.upper()}002", dom, "Required columns present", "Critical", "Fail" if missing_req else "Pass", ", ".join(missing_req) if missing_req else "All required columns are present.", len(missing_req), "Add or correctly name the missing variables." if missing_req else ""))

        missing_rec = [c for c in recommended if c not in df.columns]
        results.append(_result(f"{dom.upper()}003", dom, "Recommended columns present", "Warning", "Warning" if missing_rec else "Pass", ", ".join(missing_rec) if missing_rec else "All recommended columns are present.", len(missing_rec), "Confirm whether active rules require these variables." if missing_rec else ""))

        if "USUBJID" in df.columns:
            blank_subject = df["USUBJID"].isna() | df["USUBJID"].astype(str).str.strip().isin(["", "NAN", "<NA>"])
            results.append(_result(f"{dom.upper()}004", dom, "Subject identifier populated", "Critical", "Fail" if blank_subject.any() else "Pass", f"{blank_subject.sum()} records have missing USUBJID." if blank_subject.any() else "USUBJID is populated.", blank_subject.sum(), "Correct missing subject identifiers." if blank_subject.any() else ""))

        if "STUDYID" in df.columns:
            ids = set(df["STUDYID"].dropna().astype(str).str.strip()) - {""}
            study_ids.update(ids)

        seq_candidates = [c for c in [f"{dom.upper()}SEQ", "SEQ"] if c in df.columns]
        key_cols = [c for c in ["STUDYID", "USUBJID"] + seq_candidates[:1] if c in df.columns]
        if len(key_cols) >= 2:
            dup = df.duplicated(key_cols, keep=False)
            results.append(_result(f"{dom.upper()}005", dom, "Record key uniqueness", "Warning", "Warning" if dup.any() else "Pass", f"{dup.sum()} records share the same key: {', '.join(key_cols)}." if dup.any() else f"No duplicate keys across {', '.join(key_cols)}.", dup.sum(), "Review duplicates and sequence-variable derivation." if dup.any() else ""))

        for date_col in DATE_COLS.get(dom, []):
            if date_col in df.columns:
                raw = df[date_col]
                nonblank = raw.notna() & ~raw.astype(str).str.strip().isin(["", "NAN", "<NA>"])
                parsed = pd.to_datetime(raw, errors="coerce")
                invalid = nonblank & parsed.isna()
                results.append(_result(f"{dom.upper()}D{date_col}", dom, f"{date_col} parseable", "Warning", "Warning" if invalid.any() else "Pass", f"{invalid.sum()} nonblank values could not be parsed as dates." if invalid.any() else "All nonblank values are parseable.", invalid.sum(), "Use valid ISO 8601 dates or implement approved partial-date handling." if invalid.any() else ""))

        date_pairs = {"ex": ("EXSTDTC", "EXENDTC"), "cm": ("CMSTDTC", "CMENDTC")}
        if dom in date_pairs:
            start, end = date_pairs[dom]
            if start in df.columns and end in df.columns:
                sdt = pd.to_datetime(df[start], errors="coerce")
                edt = pd.to_datetime(df[end], errors="coerce")
                reversed_dates = sdt.notna() & edt.notna() & (sdt > edt)
                results.append(_result(f"{dom.upper()}006", dom, "Start date is not after end date", "Critical", "Fail" if reversed_dates.any() else "Pass", f"{reversed_dates.sum()} records have {start} after {end}." if reversed_dates.any() else "Date order is valid.", reversed_dates.sum(), "Correct source dates before rule execution." if reversed_dates.any() else ""))

        if dom == "dm" and "USUBJID" in df.columns:
            dm_subjects = set(df["USUBJID"].dropna().astype(str))

    if len(study_ids) > 1:
        results.append(_result("STUDY001", "", "Study ID consistency", "Critical", "Fail", f"Multiple STUDYID values were found: {', '.join(sorted(study_ids))}.", len(study_ids), "Upload datasets from one study or explicitly configure a multi-study review."))
    elif len(study_ids) == 1:
        results.append(_result("STUDY001", "", "Study ID consistency", "Critical", "Pass", f"All supplied domains resolve to STUDYID {next(iter(study_ids))}."))
    else:
        results.append(_result("STUDY001", "", "Study ID consistency", "Critical", "Fail", "No populated STUDYID was found.", 0, "Populate STUDYID in required datasets."))

    if dm_subjects:
        for dom in ["ex", "cm", "ae", "dv", "ds", "lb", "vs"]:
            df = data.get(dom, pd.DataFrame())
            if not df.empty and "USUBJID" in df.columns:
                orphan = ~df["USUBJID"].astype(str).isin(dm_subjects)
                results.append(_result(f"{dom.upper()}007", dom, "Subjects reconcile to DM", "Critical", "Fail" if orphan.any() else "Pass", f"{orphan.sum()} records reference subjects absent from DM." if orphan.any() else "All subjects are represented in DM.", orphan.sum(), "Correct USUBJID or upload the matching DM records." if orphan.any() else ""))

    cm = data.get("cm", pd.DataFrame())
    if not cm.empty:
        atc_cols = available_atc_columns(cm)
        status = "Pass" if atc_cols else "Warning"
        results.append(_result("CMATC001", "cm", "ATC hierarchy available", "Warning", status, f"Detected: {', '.join(atc_cols)}" if atc_cols else "No ATC Level 4-7 or supported legacy ATC columns were detected.", 0, "Add ATC4CD/ATC4 or higher supported hierarchy columns when ATC-based rules are active." if not atc_cols else ""))

    return pd.DataFrame(results)


def validation_has_blockers(validation_results: pd.DataFrame) -> bool:
    if validation_results.empty:
        return True
    return bool(((validation_results["SEVERITY"] == "Critical") & (validation_results["STATUS"] == "Fail")).any())


def _fields_for_rule(rule) -> list[str]:
    return [x.strip().upper() for x in str(rule.get("MATCH_FIELDS", "")).split("|") if x.strip()]


def assess_rule_readiness(rules: pd.DataFrame, data: dict, validation_results: pd.DataFrame) -> pd.DataFrame:
    readiness_columns = [
        "RULE_ID", "SOURCE", "SECTION", "RULE_NAME", "RULE_TYPE",
        "DOMAIN", "ENABLED", "READINESS", "EXECUTION", "DETAIL"
    ]
    if rules is None or not isinstance(rules, pd.DataFrame) or rules.empty:
        return pd.DataFrame(columns=readiness_columns)
    rows = []
    global_block = validation_has_blockers(validation_results)
    for _, rule in rules.iterrows():
        enabled = str(rule.get("ENABLED", "")).upper() in ["Y", "YES", "TRUE", "1"]
        rid = str(rule.get("RULE_ID", ""))
        rtype = str(rule.get("RULE_TYPE", "")).upper().strip()
        domain_expr = str(rule.get("DOMAIN", "")).lower().replace(" ", "")
        domains = [d for d in re.split(r"[+|,]", domain_expr) if d]
        domains = [d for d in domains if d in REQUIRED_DOMAINS]
        reasons = []
        missing_domains = [d.upper() for d in domains if data.get(d, pd.DataFrame()).empty]
        if missing_domains:
            reasons.append("Missing domain(s): " + ", ".join(missing_domains))

        available_cols = set()
        for d in domains:
            df = data.get(d, pd.DataFrame())
            available_cols.update(df.columns if isinstance(df, pd.DataFrame) else [])
        if not domains:
            for d in REQUIRED_DOMAINS:
                df = data.get(d, pd.DataFrame())
                available_cols.update(df.columns if isinstance(df, pd.DataFrame) else [])

        fields = _fields_for_rule(rule)
        generic_atc = {"ATC", "ATC_CODE", "ATC_CLASS", "ATC1", "ATC1CD", "ATC CODE", "ATC CLASS"}
        missing_fields = []
        for field in fields:
            if field in generic_atc:
                cm = data.get("cm", pd.DataFrame())
                if cm.empty or not available_atc_columns(cm):
                    missing_fields.append(field + " (no ATC4-7 hierarchy detected)")
            elif field.endswith("_DT"):
                base = field[:-3]
                if field not in available_cols and base not in available_cols and field not in {"TRTSDT", "TRTEDT"}:
                    missing_fields.append(field)
            elif field not in available_cols and field not in {"PROHMEDFL", "OVERLAPFL", "DV_MATCHFL", "TRTSDT", "TRTEDT", "RESTRICT_START", "RESTRICT_END"}:
                missing_fields.append(field)
        if missing_fields:
            reasons.append("Unavailable field(s): " + ", ".join(missing_fields))

        parameter = str(rule.get("PARAMETER", "")).strip()
        if rtype in {"MEDICATION_MATCH", "RESTRICTED_MED_APPROVAL_REVIEW", "WASHOUT_DAYS", "POST_TREATMENT_WINDOW_DAYS"} and not parameter:
            reasons.append("PARAMETER is required for this rule type")
        if not rid:
            reasons.append("RULE_ID is blank")
        if not rtype:
            reasons.append("RULE_TYPE is blank")

        if not enabled:
            status = "Disabled"
            execution = "Will not run"
        elif reasons:
            status = "Not Ready"
            execution = "Blocked"
        elif global_block:
            status = "Conditionally Ready"
            execution = "Blocked by critical data validation"
        else:
            status = "Ready"
            execution = "Can run"

        rows.append({
            "RULE_ID": rid,
            "SOURCE": rule.get("SOURCE", ""),
            "SECTION": rule.get("SECTION", ""),
            "RULE_NAME": rule.get("RULE_NAME", ""),
            "RULE_TYPE": rtype,
            "DOMAIN": rule.get("DOMAIN", ""),
            "ENABLED": rule.get("ENABLED", ""),
            "READINESS": status,
            "EXECUTION": execution,
            "DETAIL": "; ".join(reasons) if reasons else "All required domains, variables, and parameters are available.",
        })
    return pd.DataFrame(rows, columns=readiness_columns)


def available_atc_columns(df: pd.DataFrame) -> list[str]:
    """Return populated ATC level 4-7 columns, preserving hierarchy order."""
    cols = []
    for col in ATC_ALL_COLUMNS + ATC_LEGACY_ALIASES:
        if col in df.columns and not df[col].isna().all():
            cols.append(col)
    return cols

def atc_code_class_columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    code_cols = [c for c in ATC_CODE_COLUMNS if c in df.columns]
    class_cols = [c for c in ATC_CLASS_COLUMNS if c in df.columns]
    # Backward compatibility with older files.
    if not code_cols:
        code_cols = [c for c in ["ATC1CD", "ATC_CODE", "ATC CODE"] if c in df.columns]
    if not class_cols:
        class_cols = [c for c in ["ATC1", "ATC_CLASS", "ATC CLASS"] if c in df.columns]
    return code_cols, class_cols

def best_atc_category_column(df: pd.DataFrame):
    """Use the most detailed populated class column (ATC7 down to ATC4)."""
    for level in reversed(ATC_LEVELS):
        col = f"ATC{level}"
        if col in df.columns and not df[col].isna().all():
            return col
    for col in ["ATC4 CLASS", "ATC CLASS", "ATC1"]:
        if col in df.columns and not df[col].isna().all():
            return col
    return None

def expand_atc_match_fields(fields: list[str], df: pd.DataFrame) -> list[str]:
    """Expand generic/legacy ATC fields to every available ATC level 4-7 field."""
    expanded = []
    available = available_atc_columns(df)
    for field in fields:
        normalized = field.upper().strip()
        if normalized in {"ATC", "ATC_CODE", "ATC_CLASS", "ATC1", "ATC1CD", "ATC CODE", "ATC CLASS"}:
            expanded.extend(available)
        else:
            expanded.append(normalized)
    return list(dict.fromkeys(expanded))

def apply_metadata_medication_rules(review: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    out = review.copy()
    out["METADATA_MED_MATCHFL"] = "N"
    out["METADATA_MED_RULE_IDS"] = ""
    enabled = rules[
        rules["ENABLED"].astype(str).str.upper().isin(["Y", "YES", "TRUE", "1"])
        & rules["RULE_TYPE"].astype(str).str.upper().eq("MEDICATION_MATCH")
    ]
    if enabled.empty:
        return out
    ids_by_row = {idx: [] for idx in out.index}
    for _, rule in enabled.iterrows():
        fields = expand_atc_match_fields([x.strip().upper() for x in str(rule["MATCH_FIELDS"]).split("|") if x.strip()], out)
        terms = [x.strip().upper() for x in str(rule["PARAMETER"]).split("|") if x.strip()]
        if not fields or not terms:
            continue
        combined = pd.Series("", index=out.index, dtype="object")
        for field in fields:
            if field in out.columns:
                combined = combined + " " + out[field].fillna("").astype(str).str.upper()
        mask = pd.Series(False, index=out.index)
        for term in terms:
            mask = mask | combined.str.contains(re.escape(term), regex=True, na=False)
        for idx in out.index[mask]:
            ids_by_row[idx].append(str(rule["RULE_ID"]))
    for idx, ids in ids_by_row.items():
        if ids:
            out.at[idx, "METADATA_MED_MATCHFL"] = "Y"
            out.at[idx, "METADATA_MED_RULE_IDS"] = ", ".join(sorted(set(ids)))
    return out

def document_metadata(uploaded_file, document_type: str) -> dict:
    if uploaded_file is None:
        return {"Document Type": document_type, "File Name": "Not uploaded", "Version": "Not specified", "Date": "Not specified", "SHA-256": ""}
    content = uploaded_file.getvalue()
    return {
        "Document Type": document_type,
        "File Name": uploaded_file.name,
        "Version": "User supplied",
        "Date": datetime.now().strftime("%Y-%m-%d"),
        "SHA-256": hashlib.sha256(content).hexdigest()[:16],
    }


def evaluate_study_rules(review: pd.DataFrame, data: dict, rules: pd.DataFrame):
    findings = []
    if review.empty or rules.empty:
        return review, pd.DataFrame()

    enabled = rules[rules["ENABLED"].astype(str).str.upper().isin(["Y", "YES", "TRUE", "1"])].copy()
    dv = data.get("dv", pd.DataFrame()).copy()
    if not dv.empty:
        for col in ["USUBJID", "IMPORTANT", "DVCAT", "DVTERM"]:
            if col not in dv.columns:
                dv[col] = pd.NA

    def add_finding(idx, row, rule, observed, status="Triggered"):
        findings.append({
            "ROW_ID": idx,
            "STUDYID": row.get("STUDYID", ""),
            "USUBJID": row.get("USUBJID", ""),
            "CMSEQ": row.get("CMSEQ", ""),
            "CMTRT": row.get("CMTRT", ""),
            "RULE_ID": rule["RULE_ID"],
            "SOURCE": rule["SOURCE"],
            "SECTION": rule["SECTION"],
            "RULE_NAME": rule["RULE_NAME"],
            "SEVERITY": rule["SEVERITY"],
            "EXPECTED": rule["EXPECTED_VALUE"],
            "OBSERVED": observed,
            "FINDING_STATUS": status,
            "DESCRIPTION": rule["DESCRIPTION"],
        })

    for _, rule in enabled.iterrows():
        rtype = str(rule["RULE_TYPE"]).strip().upper()
        if rtype == "POST_TREATMENT_WINDOW_DAYS":
            continue
        for idx, row in review.iterrows():
            if rtype == "PROHIBITED_OVERLAP" and row.get("PROHMEDFL") == "Y" and row.get("OVERLAPFL") == "Y":
                add_finding(idx, row, rule, "Prohibited medication overlaps restricted window")
            elif rtype == "PROHIBITED_REQUIRES_DV" and row.get("PROHMEDFL") == "Y" and row.get("DV_RECON_STATUS") != "Matched in DV":
                add_finding(idx, row, rule, str(row.get("DV_RECON_STATUS", "Missing")))
            elif rtype == "BASELINE_PROHIBITED_REVIEW":
                cm_start = row.get("CMSTDTC_DT")
                trt_start = row.get("TRTSDT")
                if row.get("PROHMEDFL") == "Y" and pd.notna(cm_start) and pd.notna(trt_start) and cm_start <= trt_start:
                    add_finding(idx, row, rule, "Prohibited medication present at/before first dose")
            elif rtype == "RESTRICTED_MED_APPROVAL_REVIEW":
                parameter = str(rule.get("PARAMETER", "")).upper().strip()
                med = f"{row.get('CMTRT','')} {row.get('CMDECOD','')}".upper()
                if parameter and parameter in med and row.get("OVERLAPFL") == "Y":
                    add_finding(idx, row, rule, f"{parameter} overlaps restricted window; approval field unavailable")
            elif rtype == "MISSING_ATC_CODING" and row.get("PROHMEDFL") == "Y":
                code_cols, class_cols = atc_code_class_columns(review)
                code_present = any(str(row.get(c, "")).strip().lower() not in ["", "nan", "<na>"] for c in code_cols)
                class_present = any(str(row.get(c, "")).strip().lower() not in ["", "nan", "<na>"] for c in class_cols)
                if not code_present or not class_present:
                    expected = "ATC level 4-7 code and class"
                    add_finding(idx, row, rule, f"{expected} missing")
            elif rtype == "WASHOUT_DAYS" and row.get("PROHMEDFL") == "Y":
                cm_end = row.get("CMENDTC_DT")
                trt_start = row.get("TRTSDT")
                try:
                    required_days = int(float(rule.get("PARAMETER", 14) or 14))
                except Exception:
                    required_days = 14
                if pd.notna(cm_end) and pd.notna(trt_start) and cm_end < trt_start:
                    observed_days = (trt_start - cm_end).days
                    if observed_days < required_days:
                        add_finding(idx, row, rule, f"Observed washout {observed_days} days; required {required_days}")
            elif rtype == "MEDICATION_MATCH" and str(row.get("METADATA_MED_RULE_IDS", "")):
                if str(rule.get("RULE_ID", "")) in str(row.get("METADATA_MED_RULE_IDS", "")).split(", "):
                    add_finding(idx, row, rule, f"Medication matched metadata rule {rule.get('RULE_ID','')}")

        if rtype == "IMPORTANT_DV_VISIBLE" and not dv.empty:
            important = dv[dv["IMPORTANT"].astype(str).str.upper().isin(["Y", "YES", "IMPORTANT"])]
            visible_subjects = set(review.get("USUBJID", pd.Series(dtype=str)).astype(str))
            for _, drow in important.iterrows():
                if str(drow.get("USUBJID", "")) not in visible_subjects:
                    findings.append({
                        "ROW_ID": "", "STUDYID": drow.get("STUDYID", ""), "USUBJID": drow.get("USUBJID", ""),
                        "CMSEQ": "", "CMTRT": "", "RULE_ID": rule["RULE_ID"], "SOURCE": rule["SOURCE"],
                        "SECTION": rule["SECTION"], "RULE_NAME": rule["RULE_NAME"], "SEVERITY": rule["SEVERITY"],
                        "EXPECTED": rule["EXPECTED_VALUE"], "OBSERVED": "Important DV subject not represented in CM review",
                        "FINDING_STATUS": "Triggered", "DESCRIPTION": rule["DESCRIPTION"],
                    })

    findings_df = pd.DataFrame(findings)
    out = review.copy()
    out["RULE_COUNT"] = 0
    out["RULE_IDS"] = ""
    out["RULE_SUMMARY"] = ""
    if not findings_df.empty:
        row_findings = findings_df[findings_df["ROW_ID"].astype(str) != ""].copy()
        if not row_findings.empty:
            grouped = row_findings.groupby("ROW_ID").agg(
                RULE_COUNT=("RULE_ID", "size"),
                RULE_IDS=("RULE_ID", lambda x: ", ".join(sorted(set(map(str, x))))),
                RULE_SUMMARY=("RULE_NAME", lambda x: "; ".join(dict.fromkeys(map(str, x))))
            )
            for idx, vals in grouped.iterrows():
                if idx in out.index:
                    out.loc[idx, ["RULE_COUNT", "RULE_IDS", "RULE_SUMMARY"]] = [vals["RULE_COUNT"], vals["RULE_IDS"], vals["RULE_SUMMARY"]]
    out["RULE_COUNT"] = pd.to_numeric(out["RULE_COUNT"], errors="coerce").fillna(0).astype(int)
    return out, findings_df

def prepare_review_dataset(data, rules):
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
    for col in ["STUDYID", "USUBJID", "CMSEQ", "CMTRT", "CMDECOD", "CMSTDTC", "CMENDTC", "PROHFL"]:
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
    window_days = int(data.get("window_days", 30))
    review["RESTRICT_END"] = review["TRTEDT"] + pd.Timedelta(days=window_days)
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
    review = apply_metadata_medication_rules(review, rules)
    metadata_match = review["METADATA_MED_MATCHFL"].eq("Y")
    review["PROHMEDFL"] = (protocol_match | existing_proh | metadata_match).map({True: "Y", False: "N"})

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

st.markdown(
    """
    <style>
      .clinexa-shell {
        border: 1px solid #dbe5ef;
        border-radius: 16px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
        background: linear-gradient(135deg, #f7fbff 0%, #ffffff 65%);
        box-shadow: 0 4px 18px rgba(15, 76, 129, 0.08);
      }
      .clinexa-brand {
        color: #0F4C81;
        font-size: 1.05rem;
        font-weight: 750;
        letter-spacing: 0.02em;
        margin-bottom: 0.15rem;
      }
      .clinexa-platform {
        color: #64748b;
        font-size: 0.88rem;
        margin-bottom: 0.85rem;
      }
      .trialguard-title {
        color: #102a43;
        font-size: 2.15rem;
        line-height: 1.1;
        font-weight: 800;
        margin: 0;
      }
      .trialguard-subtitle {
        color: #334e68;
        font-size: 1.05rem;
        margin-top: 0.35rem;
      }
      .module-pill {
        display: inline-block;
        margin-top: 0.75rem;
        padding: 0.28rem 0.65rem;
        border-radius: 999px;
        background: #e8f3fb;
        color: #0F4C81;
        font-size: 0.78rem;
        font-weight: 700;
      }
    </style>
    <div class="clinexa-shell">
      <div class="clinexa-brand">Clinexa AI</div>
      <div class="clinexa-platform">Clinical Intelligence Platform</div>
      <div class="trialguard-title">🛡️ TrialGuard</div>
      <div class="trialguard-subtitle">Prohibited Medication &amp; Important Protocol Deviation Review</div>
      <div class="module-pill">Initial IPD Dashboard</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Clinexa AI · Study Inputs")
    st.caption("Upload each controlled input separately. Uploaded files override bundled dummy content for the current session.")

    with st.expander("1. Protocol Upload", expanded=True):
        protocol_file = st.file_uploader(
            "Upload approved study protocol",
            type=["docx", "pdf", "txt"],
            key="protocol",
            help="Used for document registration and traceability. Executable logic is supplied through the rule file.",
        )
        st.caption("Bundled default: Dummy_Oncology_Protocol_DUM_ONC_001.docx")

    with st.expander("2. SAP Upload", expanded=True):
        sap_file = st.file_uploader(
            "Upload approved Statistical Analysis Plan",
            type=["docx", "pdf", "txt"],
            key="sap",
            help="Used for SAP version traceability and study-specific analysis conventions.",
        )
        bundled_sap_path = os.path.join(DATA_DIR, "Documents", "Dummy_Oncology_SAP_DUM_ONC_001.docx")
        if os.path.exists(bundled_sap_path):
            with open(bundled_sap_path, "rb") as _sap:
                st.download_button("Download bundled dummy SAP", _sap.read(), file_name="Dummy_Oncology_SAP_DUM_ONC_001.docx")

    with st.expander("3. Rule File Upload", expanded=True):
        rules_file = st.file_uploader(
            "Upload executable study rules",
            type=["xlsx", "xlsm", "csv"],
            key="rules",
            help="Preferred: Excel workbook with a 'Rule Engine' sheet. CSV is also supported.",
        )
        if os.path.exists(RULES_XLSX_PATH):
            with open(RULES_XLSX_PATH, "rb") as _rules_xlsx:
                st.download_button("Download rule workbook with update instructions", _rules_xlsx.read(), file_name="Clinexa_Study_Rules_DUM_ONC_001_with_Instructions.xlsx")
        if os.path.exists(RULES_PATH):
            with open(RULES_PATH, "rb") as _rules:
                st.download_button("Download CSV rule template", _rules.read(), file_name="active_rule_engine.csv")

    with st.expander("4. Dataset Upload", expanded=True):
        mode = st.radio(
            "Dataset source",
            ["Use bundled dummy data", "Upload study package ZIP", "Upload individual datasets"],
            key="dataset_mode",
        )
        uploaded_zip = None
        uploaded_csvs = None
        if mode == "Upload study package ZIP":
            uploaded_zip = st.file_uploader("Upload study package ZIP", type=["zip"], key="dataset_zip", help="ZIP may contain CSV, SAS7BDAT, or XPT domains. SAS7BDAT is preferred when duplicate domain formats exist, followed by XPT and CSV.")
        elif mode == "Upload individual datasets":
            uploaded_csvs = st.file_uploader(
                "Upload SDTM datasets and terminology files",
                type=["csv", "xpt", "xport", "sas7bdat"],
                accept_multiple_files=True,
                key="dataset_files",
                help="Use domain filenames such as dm.xpt, cm.sas7bdat, dv.csv. Terminology files remain CSV.",
            )

try:
    if mode == "Upload study package ZIP" and uploaded_zip is not None:
        data = load_uploaded_zip(uploaded_zip)
    elif mode == "Upload individual datasets" and uploaded_csvs:
        data = load_uploaded_datasets(uploaded_csvs)
    else:
        data = load_default_data()

    rules = read_rules_file(rules_file, rules_file.name) if rules_file is not None else load_default_rules()
    window_rule = rules[rules["RULE_TYPE"].astype(str).str.upper().eq("POST_TREATMENT_WINDOW_DAYS")]
    if not window_rule.empty:
        try:
            data["window_days"] = int(float(window_rule.iloc[0]["PARAMETER"]))
        except Exception:
            data["window_days"] = 30
    validation_results = run_data_validation(data)
    rule_readiness = assess_rule_readiness(rules, data, validation_results)
    critical_validation_block = validation_has_blockers(validation_results)
    review, info = prepare_review_dataset(data, rules)
    if rule_readiness.empty or not {"READINESS", "RULE_ID"}.issubset(rule_readiness.columns):
        ready_rule_ids = set()
        executable_rules = rules.iloc[0:0].copy()
    else:
        ready_rule_ids = set(
            rule_readiness.loc[
                rule_readiness["READINESS"].isin(["Ready", "Conditionally Ready"]),
                "RULE_ID",
            ].astype(str)
        )
        executable_rules = rules[rules["RULE_ID"].astype(str).isin(ready_rule_ids)].copy()
    if critical_validation_block:
        executable_rules = executable_rules.iloc[0:0].copy()
    review, rule_findings = evaluate_study_rules(review, data, executable_rules)
except Exception as e:
    error_text = str(e)
    if "READINESS" in error_text:
        st.info("### Next step: Upload a rule file")
        st.write("Open **Rule File Upload**, upload the Clinexa rule workbook, and then return to **Rule Readiness & Compatibility**.")
    elif "CM" in error_text.upper() or "USUBJID" in error_text.upper():
        st.info("### Next step: Upload the required study datasets")
        st.write("Open **Dataset Upload** and provide at least **DM, EX, CM, and DV** in CSV, XPT/XPORT, SAS7BDAT, or a ZIP package.")
    else:
        st.info("### Complete the setup before continuing")
        st.write("Upload the **rule file** and required **DM, EX, CM, and DV datasets**, then review the Data Validation Center for the next required action.")
    with st.expander("Technical details for support", expanded=False):
        st.code(f"{type(e).__name__}: {e}")
    st.stop()

if info.get("error"):
    st.error(info["error"])
    st.stop()

with st.expander("Loaded domain summary", expanded=False):
    summary = []
    for k, df in data.items():
        if isinstance(df, pd.DataFrame):
            summary.append({"Dataset": k.upper(), "Rows": len(df), "Columns": len(df.columns), "Column Names": ", ".join(list(df.columns)[:20])})
    st.caption(f"Loaded formats: {data.get('source_formats', 'Unknown')}")
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
c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
with c1: render_metric("Subjects", review["USUBJID"].nunique() if "USUBJID" in review.columns else 0)
with c2: render_metric("CM Records", len(review))
with c3: render_metric("Prohibited Med Records", int((review["PROHMEDFL"] == "Y").sum()))
with c4: render_metric("Important PD Candidates", int((review["IPD_FL"] == "Y").sum()))
with c5: render_metric("Potential Missing DV", int((review["DV_RECON_STATUS"] == "Potential Missing DV").sum()))
with c6: render_metric("Critical Risk", int((review["RISK_LEVEL"] == "Critical").sum()))
with c7: render_metric("Rule Findings", len(rule_findings))

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "Executive Summary",
    "Subject Review",
    "DV Reconciliation",
    "Protocol Medication List",
    "Data Validation Center",
    "Rule Readiness",
    "Study Rules & Traceability",
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
        cat_col = best_atc_category_column(f)
        if cat_col and not f.empty:
            st.dataframe(f[f["PROHMEDFL"]=="Y"][cat_col].fillna("Missing").value_counts().reset_index().rename(columns={cat_col:"Category", "count":"Count"}), use_container_width=True)

with tab2:
    st.subheader("Subject-Level Prohibited Medication Review")
    display_cols = [
        "STUDYID", "USUBJID", "SUBJID", "SITEID", "COUNTRY", "ARM", "SEX", "AGE",
        "CMSEQ", "CMTRT", "CMDECOD", *ATC_ALL_COLUMNS, "CMSTDTC", "CMENDTC",
        "TRTSDT", "TRTEDT", "RESTRICT_START", "RESTRICT_END",
        "PROHMEDFL", "METADATA_MED_MATCHFL", "METADATA_MED_RULE_IDS", "OVERLAPFL", "IPD_FL", "RISK_LEVEL", "RULE_COUNT", "RULE_IDS", "RULE_SUMMARY",
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
    st.subheader("Data Validation Center")
    st.caption("Critical failures block clinical rule execution. Warnings allow execution but require review and documented acceptance.")

    status_counts = validation_results["STATUS"].value_counts() if not validation_results.empty else pd.Series(dtype=int)
    v1, v2, v3, v4 = st.columns(4)
    with v1: st.metric("Passed", int(status_counts.get("Pass", 0)))
    with v2: st.metric("Warnings", int(status_counts.get("Warning", 0)))
    with v3: st.metric("Critical Failures", int(((validation_results["SEVERITY"] == "Critical") & (validation_results["STATUS"] == "Fail")).sum()) if not validation_results.empty else 0)
    with v4: st.metric("Not Run", int(status_counts.get("Not Run", 0)))

    if critical_validation_block:
        st.info("### Complete the required data steps before rule execution")
        st.write("Use the **Action Required** column below to correct each critical validation item. Rules will start automatically after the required domains and variables are available.")
    else:
        st.success("No critical validation blockers were detected. Rules marked Ready may execute.")

    severity_filter = st.multiselect("Validation severity", ["Critical", "Warning", "Info"], default=["Critical", "Warning", "Info"], key="validation_severity")
    status_filter_validation = st.multiselect("Validation status", ["Fail", "Warning", "Pass", "Not Run"], default=["Fail", "Warning", "Pass", "Not Run"], key="validation_status")
    validation_view = validation_results[
        validation_results["SEVERITY"].isin(severity_filter) & validation_results["STATUS"].isin(status_filter_validation)
    ] if not validation_results.empty else validation_results
    st.dataframe(validation_view, use_container_width=True, hide_index=True)
    st.download_button("Download validation report", validation_results.to_csv(index=False).encode("utf-8"), file_name="clinexa_data_validation_report.csv", mime="text/csv")

    st.markdown("**Records requiring clinical/data review**")
    review_subset = review[(review["PROHMEDFL"] == "Y") & ((review["OVERLAPFL"] == "N") | (review["DV_MATCHFL"] == "N"))]
    st.dataframe(review_subset[[c for c in ["USUBJID", "CMTRT", "CMDECOD", "CMSTDTC", "CMENDTC", "OVERLAPFL", "IPD_FL", "DV_RECON_STATUS", "REVIEW_STATUS"] if c in review_subset.columns]], use_container_width=True, hide_index=True)


with tab6:
    st.subheader("Rule Readiness & Compatibility")
    st.caption("Each enabled rule is assessed against uploaded domains, variables, ATC hierarchy, parameters, and critical data-validation results before execution.")
    if rule_readiness.empty:
        st.info("### Upload a rule file to run Readiness")
        st.write("Go to **3. Rule File Upload**, upload the Clinexa Excel rule workbook or CSV rule file, and then return to this tab.")
        st.caption("Readiness starts after the app can identify executable rules from the Rule Engine sheet.")
    else:
        ready_counts = rule_readiness["READINESS"].value_counts()
        r1, r2, r3, r4 = st.columns(4)
        with r1: st.metric("Ready", int(ready_counts.get("Ready", 0)))
        with r2: st.metric("Conditionally Ready", int(ready_counts.get("Conditionally Ready", 0)))
        with r3: st.metric("Not Ready", int(ready_counts.get("Not Ready", 0)))
        with r4: st.metric("Disabled", int(ready_counts.get("Disabled", 0)))
        readiness_filter = st.multiselect("Readiness", ["Ready", "Conditionally Ready", "Not Ready", "Disabled"], default=["Ready", "Conditionally Ready", "Not Ready", "Disabled"], key="rule_readiness_filter")
        st.dataframe(rule_readiness[rule_readiness["READINESS"].isin(readiness_filter)], use_container_width=True, hide_index=True)
        st.download_button("Download rule-readiness report", rule_readiness.to_csv(index=False).encode("utf-8"), file_name="clinexa_rule_readiness_report.csv", mime="text/csv")
        not_ready = rule_readiness[rule_readiness["READINESS"] == "Not Ready"]
        if not not_ready.empty:
            st.warning(f"{len(not_ready)} enabled rule(s) cannot execute. Correct the listed domains, fields, or parameters before relying on results.")


with tab7:
    st.subheader("Protocol/SAP Rule Adoption and Traceability")
    st.info("Documents provide controlled provenance. Executable checks are maintained in the study-rules workbook/CSV so each rule is reviewable, versionable, testable, and traceable to a protocol or SAP section.")

    doc_rows = [
        document_metadata(protocol_file, "Protocol") if protocol_file is not None else {
            "Document Type": "Protocol", "File Name": "Dummy_Oncology_Protocol_DUM_ONC_001.docx (bundled source)",
            "Version": "Dummy protocol", "Date": "2026-07-08", "SHA-256": "Bundled package"
        },
        document_metadata(sap_file, "SAP") if sap_file is not None else {
            "Document Type": "SAP", "File Name": "Dummy_Oncology_SAP_DUM_ONC_001.docx (bundled source)",
            "Version": "1.0 (Dummy)", "Date": "2026-07-16", "SHA-256": "Bundled package"
        }
    ]
    st.markdown("**Document Register**")
    st.dataframe(pd.DataFrame(doc_rows), use_container_width=True, hide_index=True)

    st.markdown("**Executable Study Rules**")
    edited_rules = st.data_editor(
        rules,
        use_container_width=True,
        hide_index=True,
        disabled=["RULE_ID"],
        column_config={"ENABLED": st.column_config.SelectboxColumn("Enabled", options=["Y", "N"])},
        key="study_rule_editor",
    )
    st.download_button(
        "Download current study rules",
        edited_rules.to_csv(index=False).encode("utf-8"),
        file_name="active_rule_engine.csv",
        mime="text/csv",
    )

    st.markdown("**Triggered Rule Findings**")
    if rule_findings.empty:
        st.success("No enabled study rules triggered.")
    else:
        st.dataframe(rule_findings, use_container_width=True, hide_index=True)
        st.download_button(
            "Download rule findings",
            rule_findings.to_csv(index=False).encode("utf-8"),
            file_name="study_rule_findings.csv",
            mime="text/csv",
        )

    st.markdown("**Rule Governance Workflow**")
    st.markdown("1. Register the approved protocol and SAP versions.  2. Translate relevant sections into executable rules.  3. Obtain clinical, statistics, data-management, and programming approval.  4. Validate each rule using known positive and negative test cases.  5. Freeze and version the rule file for each data cut.  6. Retain rule ID, source section, result, reviewer decision, and audit evidence.")

st.caption("Clinexa AI · TrialGuard | Demonstration dashboard using dummy oncology SDTM-like data. Medical review and protocol interpretation must confirm final Important Protocol Deviation decisions.")
