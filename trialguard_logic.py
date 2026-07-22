import re
import pandas as pd

def is_partial_iso_date(value):
    if pd.isna(value): return False
    return bool(re.fullmatch(r"\d{4}|\d{4}-\d{2}", str(value).strip()))

def analysis_end_date(end_date, ongoing, cutoff):
    end=pd.to_datetime(end_date, errors="coerce")
    if pd.notna(end): return end, "COMPLETE"
    if str(ongoing).upper() in {"Y","YES","ONGOING","1","TRUE"}: return pd.Timestamp(cutoff), "ONGOING"
    return pd.NaT, "MISSING_UNRESOLVED"

def overlap_flag(start, end, restrict_start, restrict_end, eligible=True):
    vals=[pd.to_datetime(x, errors="coerce") for x in [start,end,restrict_start,restrict_end]]
    if not eligible or any(pd.isna(x) for x in vals): return "U"
    s,e,rs,re_=vals
    return "Y" if s <= re_ and e >= rs else "N"

def ae_linked(cm_start, ae_date, serious=False, window=14):
    c=pd.to_datetime(cm_start, errors="coerce"); a=pd.to_datetime(ae_date, errors="coerce")
    return bool(serious or (pd.notna(c) and pd.notna(a) and abs((a-c).days)<=window))

def dv_term_match(text, terms):
    norm=' '.join(str(text).upper().split())
    return any(str(t).upper() in norm for t in terms)
