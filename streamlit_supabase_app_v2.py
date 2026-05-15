# streamlit_supabase_app_v2.py
# Spectrum Planner — Streamlit + Supabase
# JSON-backed, polished, and safer deconfliction.
# Fixes:
# - Avoids Supabase column mismatch by saving allocation rows in row_data JSONB.
# - Power plot center-frequency labels are near the top inside boxes.
# - Deconfliction labels are inside boxes.
# - Improved scheduler only separates rows that actually overlap in frequency.
# - Requires username/password login before loading the app.

import io
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
from supabase import create_client

st.set_page_config(page_title="Spectrum Planner", page_icon="📡", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
.block-container {padding-top: 1rem; padding-bottom: 2rem;}
.stTabs [data-baseweb="tab-list"] {gap: .75rem;}
.stTabs [data-baseweb="tab"] {height: 2.4rem; white-space: nowrap;}
</style>
""", unsafe_allow_html=True)

st.title("📡 Spectrum Planner")
st.caption("Collaborative frequency, power, and time deconfliction workspace")


def require_login():
    """Simple app-level login using Streamlit secrets.

    In Streamlit Cloud secrets, add:

    [auth]
    username = "admin"
    password = "change-this-password"
    """
    if st.session_state.get("authenticated"):
        return st.session_state.get("auth_user", "user")

    st.markdown("### 🔐 Login required")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", type="primary")

    if submitted:
        expected_user = st.secrets.get("auth", {}).get("username", "")
        expected_pass = st.secrets.get("auth", {}).get("password", "")

        if not expected_user or not expected_pass:
            st.error("Login is not configured. Add [auth] username and password to Streamlit secrets.")
            st.stop()

        if username == expected_user and password == expected_pass:
            st.session_state["authenticated"] = True
            st.session_state["auth_user"] = username
            st.rerun()
        else:
            st.error("Invalid username or password.")

    st.stop()


logged_in_user = require_login()

@st.cache_resource
def get_supabase():
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

sb = get_supabase()

APP_COLUMNS = [
    "Start Time", "End Time", "Equipment", "Center Frequency (MHz)",
    "Start Frequency (MHz)", "End Frequency (MHz)", "Bandwidth (MHz)",
    "Power (W)", "Power (dBm)", "Tech", "Unit", "Notes"
]

STANDARD_RENAME = {
    "StartTime":"Start Time", "EndTime":"End Time", "Start Time":"Start Time", "End Time":"End Time",
    "Equipment":"Equipment", "Tech":"Tech", "Unit":"Unit", "Notes":"Notes",
    "CenterF":"Center Frequency (MHz)", "Center Frequency":"Center Frequency (MHz)", "Center Frequency (MHz)":"Center Frequency (MHz)",
    "StartF":"Start Frequency (MHz)", "Start Frequency":"Start Frequency (MHz)", "Start Frequency (MHz)":"Start Frequency (MHz)",
    "EndF":"End Frequency (MHz)", "End Frequency":"End Frequency (MHz)", "End Frequency (MHz)":"End Frequency (MHz)",
    "BW":"Bandwidth (MHz)", "Bandwidth":"Bandwidth (MHz)", "Bandwidth (MHz)":"Bandwidth (MHz)",
    "PowerW":"Power (W)", "Power (W)":"Power (W)", "PowerdBm":"Power (dBm)", "Power (dBm)":"Power (dBm)"
}

INTERNAL_RENAME = {
    "Start Time":"StartTime", "End Time":"EndTime", "Equipment":"Equipment",
    "Center Frequency (MHz)":"CenterF", "Start Frequency (MHz)":"StartF", "End Frequency (MHz)":"EndF",
    "Bandwidth (MHz)":"BW", "Power (W)":"PowerW", "Power (dBm)":"PowerdBm",
    "Tech":"Tech", "Unit":"Unit", "Notes":"Notes"
}

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def safe_group(s):
    s = s.astype("string").fillna("(blank)").str.strip()
    return s.replace("", "(blank)")

def parse_number_series(series):
    if series is None:
        return pd.Series(dtype="float64")
    return (series.astype("string")
            .str.replace(",", "", regex=False)
            .str.extract(r"([-+]?\d*\.?\d+)", expand=False)
            .astype(float))

def parse_time_one(x):
    """Return seconds since midnight. Robust for Excel values and messy text like '6am, 6 AM, 0600, 6:00'."""
    if pd.isna(x):
        return np.nan
    if isinstance(x, pd.Timestamp):
        return float(x.hour*3600 + x.minute*60 + x.second)
    if isinstance(x, (int, float, np.integer, np.floating)):
        xx = float(x)
        if math.isfinite(xx):
            if 0 <= xx < 1.5:      # Excel fraction of day
                return xx * 86400.0
            if 0 <= xx <= 2400 and float(xx).is_integer():
                # Treat 600/0600/1730 as HHMM, but keep small values 0-23 as hours.
                if xx <= 23:
                    return xx * 3600.0
                hh = int(xx) // 100
                mm = int(xx) % 100
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    return float(hh*3600 + mm*60)
            if 0 <= xx <= 86400:
                return xx
        return np.nan

    y = str(x).strip().lower()
    if not y or y in {"nan", "none", "null"}:
        return np.nan

    # Remove common spreadsheet artifacts.
    y = y.replace("'", "").replace('"', "")
    y = y.replace("a.m.", "am").replace("p.m.", "pm").replace("a.m", "am").replace("p.m", "pm")
    y = y.replace(" am", "am").replace(" pm", "pm")
    y = y.strip()

    # HHMM strings such as 0600 or 1730
    if y.isdigit() and len(y) in (3, 4):
        val = int(y)
        hh, mm = val // 100, val % 100
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return float(hh*3600 + mm*60)

    from datetime import datetime as dt
    for fmt in ["%I%p", "%I:%M%p", "%I:%M:%S%p", "%H", "%H:%M", "%H:%M:%S"]:
        try:
            d = dt.strptime(y, fmt)
            return float(d.hour*3600 + d.minute*60 + d.second)
        except Exception:
            pass
    return np.nan

def fmt_hhmm(sec):
    if pd.isna(sec):
        return ""
    return f"{int((sec % 86400)//3600):02d}:{int(((sec % 86400)%3600)//60):02d}"

def ticks_value(x):
    try:
        v = float(x)
        return v if math.isfinite(v) and v > 0 else None
    except Exception:
        return None

def normalize_uploaded_df(df):
    """Normalize uploaded/pasted data and infer columns when a file has weak or shifted headers."""
    out = df.copy()
    out.columns = [STANDARD_RENAME.get(str(c).strip(), str(c).strip()) for c in out.columns]

    # Drop fully empty rows/columns.
    out = out.dropna(how="all").dropna(axis=1, how="all")

    # If required columns are missing or mostly empty, infer them from the data.
    cols = list(out.columns)

    def mostly_empty(colname):
        return colname not in out.columns or out[colname].isna().all() or (out[colname].astype("string").str.strip().replace("", pd.NA).isna().mean() > 0.85)

    # Time columns: first two columns that parse like times.
    time_scores = []
    for c in cols:
        parsed = out[c].apply(parse_time_one)
        score = parsed.notna().mean() if len(parsed) else 0
        if score >= 0.50:
            time_scores.append((c, score))
    if mostly_empty("Start Time") and len(time_scores) >= 1:
        out["Start Time"] = out[time_scores[0][0]]
    if mostly_empty("End Time") and len(time_scores) >= 2:
        out["End Time"] = out[time_scores[1][0]]

    # Numeric frequency/power candidates.
    numeric_candidates = []
    for c in cols:
        nums = parse_number_series(out[c])
        score = nums.notna().mean() if len(nums) else 0
        med = nums.median(skipna=True)
        numeric_candidates.append((c, score, med))

    # Center frequency: frequency-like column, usually values > 20 MHz and not power.
    freq_like = [(c, s, m) for c, s, m in numeric_candidates if s >= 0.50 and pd.notna(m) and m > 20]
    if mostly_empty("Center Frequency (MHz)") and freq_like:
        # Prefer column names containing center/frequency/freq, otherwise the first freq-like column.
        named = [x for x in freq_like if any(k in str(x[0]).lower() for k in ["center", "frequency", "freq"])]
        out["Center Frequency (MHz)"] = out[(named or freq_like)[0][0]]

    # Equipment: text column that is not a time column and has repeated non-numeric values.
    if mostly_empty("Equipment"):
        time_cols = {x[0] for x in time_scores}
        text_scores = []
        for c in cols:
            if c in time_cols:
                continue
            as_text = out[c].astype("string").str.strip()
            nonblank = as_text.replace("", pd.NA).notna().mean()
            numeric_score = parse_number_series(out[c]).notna().mean()
            if nonblank >= 0.50 and numeric_score < 0.50:
                text_scores.append((c, nonblank))
        if text_scores:
            out["Equipment"] = out[text_scores[0][0]]

    # Bandwidth and Power defaults if absent.
    if mostly_empty("Bandwidth (MHz)"):
        out["Bandwidth (MHz)"] = None
    if mostly_empty("Power (W)"):
        out["Power (W)"] = 1

    for c in APP_COLUMNS:
        if c not in out.columns:
            out[c] = None

    return out[APP_COLUMNS].reset_index(drop=True)

def app_to_internal(df):
    out = df.copy()
    out.columns = [INTERNAL_RENAME.get(str(c), str(c)) for c in out.columns]
    return out

def derive_power_w(df):
    out = df.copy()
    if "PowerW" not in out.columns and "PowerdBm" in out.columns:
        pdbm = parse_number_series(out["PowerdBm"])
        out["PowerW"] = (10 ** (pdbm / 10.0)) / 1000.0
    elif "PowerW" in out.columns:
        out["PowerW"] = parse_number_series(out["PowerW"])
    return out

def fill_from_center_bw(df):
    out = df.copy()
    if "CenterF" not in out.columns or "BW" not in out.columns:
        return out
    cf = parse_number_series(out["CenterF"])
    bw = parse_number_series(out["BW"])
    half = bw / 2.0
    if "StartF" not in out.columns:
        out["StartF"] = np.nan
    if "EndF" not in out.columns:
        out["EndF"] = np.nan
    sf = parse_number_series(out["StartF"])
    ef = parse_number_series(out["EndF"])
    out.loc[sf.isna(), "StartF"] = cf[sf.isna()] - half[sf.isna()]
    out.loc[ef.isna(), "EndF"] = cf[ef.isna()] + half[ef.isna()]
    return out

def prep_df(app_df):
    out = app_to_internal(app_df)
    out = derive_power_w(out)
    out = fill_from_center_bw(out)
    for c in ["CenterF", "StartF", "EndF", "BW", "PowerW", "PowerdBm"]:
        if c in out.columns:
            out[c] = parse_number_series(out[c])
    for c in ["Equipment", "Tech", "Unit"]:
        if c not in out.columns:
            out[c] = "(blank)"
        out[c] = safe_group(out[c])
    for c in ["StartTime", "EndTime"]:
        if c not in out.columns:
            out[c] = ""
    for c in ["StartF", "EndF", "PowerW"]:
        if c not in out.columns:
            out[c] = np.nan
    out = out.loc[out["StartF"].notna() & out["EndF"].notna() & out["PowerW"].notna() & (out["EndF"] > out["StartF"])].copy()
    if "CenterF" not in out.columns:
        out["CenterF"] = (out["StartF"] + out["EndF"]) / 2
    else:
        out["CenterF"] = out["CenterF"].fillna((out["StartF"] + out["EndF"]) / 2)
    out["LabelY"] = out["PowerW"] / 2
    out["PointY"] = out["PowerW"]
    out[".row_id"] = np.arange(1, len(out) + 1)
    return out.reset_index(drop=True)

def make_palette(levels):
    cmap = plt.get_cmap("tab20")
    return {lev: cmap(i % 20) for i, lev in enumerate(levels)}

def unittech_field(df):
    if "Unit" in df.columns and (safe_group(df["Unit"]) != "(blank)").any():
        return "Unit"
    if "Tech" in df.columns and (safe_group(df["Tech"]) != "(blank)").any():
        return "Tech"
    return "Equipment"

def fig_to_png_bytes(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    buf.seek(0)
    return buf.getvalue()

# ---------------- Supabase JSON-backed operations ----------------
def list_projects():
    return sb.table("projects").select("*").order("updated_at", desc=True).execute().data or []

def create_project(name, description):
    res = sb.table("projects").insert({"name": name, "description": description, "updated_at": now_iso()}).execute()
    return res.data[0]

def get_project_rows(project_id):
    res = (sb.table("allocation_rows")
           .select("id,project_id,row_order,row_data,updated_at,updated_by")
           .eq("project_id", project_id)
           .order("row_order")
           .execute())
    rows = res.data or []
    if not rows:
        return pd.DataFrame(columns=APP_COLUMNS)
    data = [(r.get("row_data") or {}) for r in rows]
    df = pd.DataFrame(data)
    for c in APP_COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[APP_COLUMNS].reset_index(drop=True)

def replace_project_rows(project_id, df, user):
    sb.table("allocation_rows").delete().eq("project_id", project_id).execute()
    clean = normalize_uploaded_df(df)
    payloads = []
    for i, row in clean.reset_index(drop=True).iterrows():
        row_data = {}
        for c in APP_COLUMNS:
            val = row.get(c, None)
            if pd.isna(val):
                val = None
            elif isinstance(val, (np.integer, np.floating)):
                val = float(val)
            elif not isinstance(val, (int, float)):
                val = str(val)
            row_data[c] = val
        payloads.append({"project_id": project_id, "row_order": int(i), "row_data": row_data, "updated_by": user, "updated_at": now_iso()})
    if payloads:
        sb.table("allocation_rows").insert(payloads).execute()
    sb.table("projects").update({"updated_at": now_iso()}).eq("id", project_id).execute()

def next_version_no(project_id):
    res = (sb.table("allocation_versions").select("version_no")
           .eq("project_id", project_id).order("version_no", desc=True).limit(1).execute())
    return 1 if not res.data else int(res.data[0]["version_no"]) + 1

def save_version(project_id, df, user, note):
    clean = normalize_uploaded_df(df)
    snap = clean.where(pd.notna(clean), None).to_dict(orient="records")
    vno = next_version_no(project_id)
    sb.table("allocation_versions").insert({"project_id": project_id, "version_no": vno, "snapshot": snap, "saved_by": user, "save_note": note, "created_at": now_iso()}).execute()
    sb.table("save_events").insert({"project_id": project_id, "event_type": "save_version", "event_by": user, "event_note": note, "created_at": now_iso()}).execute()
    return vno

def list_versions(project_id):
    return (sb.table("allocation_versions")
            .select("id,version_no,saved_by,save_note,created_at")
            .eq("project_id", project_id).order("version_no", desc=True).execute().data or [])

def load_version(version_id):
    return sb.table("allocation_versions").select("*").eq("id", version_id).single().execute().data

# ---------------- Conflict/deconfliction ----------------
def freq_overlap(a0, a1, b0, b1, guard=0.0):
    return min(a1, b1) > max(a0, b0) - guard

def time_overlap(a0, a1, b0, b1):
    return min(a1, b1) > max(a0, b0)

def detect_conflicts_generic(df, group_field, guard_mhz=0.0):
    req = {"StartF", "EndF", "StartTime", "EndTime", group_field}
    if not req.issubset(df.columns):
        return None
    d = df.copy()
    d["Group"] = d[group_field].astype(str)
    d["StartSec"] = d["StartTime"].apply(parse_time_one)
    d["EndSec"] = d["EndTime"].apply(parse_time_one)
    d = d.loc[d["StartSec"].notna() & d["EndSec"].notna()].copy()
    if d.empty:
        return None
    d["EndSecUnwrapped"] = np.where(d["EndSec"] < d["StartSec"], d["EndSec"] + 86400, d["EndSec"])
    d = d.reset_index(drop=True)
    rows = []
    for i in range(len(d)-1):
        for j in range(i+1, len(d)):
            if d.loc[i, "Group"] == d.loc[j, "Group"]:
                continue
            f_left = max(d.loc[i, "StartF"], d.loc[j, "StartF"])
            f_right = min(d.loc[i, "EndF"], d.loc[j, "EndF"])
            if f_right <= f_left - guard_mhz:
                continue
            t_start = max(d.loc[i, "StartSec"], d.loc[j, "StartSec"])
            t_end = min(d.loc[i, "EndSecUnwrapped"], d.loc[j, "EndSecUnwrapped"])
            if t_end <= t_start:
                continue
            rows.append({"FreqLeft": f_left, "FreqRight": f_right, "StartOverlap": t_start, "EndOverlap": t_end,
                         "GroupA": d.loc[i, "Group"], "GroupB": d.loc[j, "Group"], "OverlapMin": (t_end-t_start)/60})
    if not rows:
        return None
    out = pd.DataFrame(rows)
    out["OverlapStartHM"] = out["StartOverlap"].apply(fmt_hhmm)
    out["OverlapEndHM"] = out["EndOverlap"].apply(fmt_hhmm)
    return out.sort_values(["FreqLeft", "StartOverlap"]).reset_index(drop=True)

def placement_is_valid(candidate, item, placed, pad_sec, guard_mhz):
    end = candidate + item["DurationSec"]
    for p in placed:
        if not freq_overlap(item["StartF"], item["EndF"], p["StartF"], p["EndF"], guard_mhz):
            continue
        if time_overlap(candidate, end, p["PlacedStartSec"] - pad_sec, p["PlacedEndSec"] + pad_sec):
            return False
    return True

def auto_deconflict_smart(df, max_shift_sec, pad_sec, anchor_sec, guard_mhz=0.0, allow_earlier=True, priority_mode="Power + Original Time"):
    req = {"StartTime", "EndTime", "StartF", "EndF", "PowerW"}
    if not req.issubset(df.columns):
        return df.copy()
    d = df.copy()
    d["OrigStartSec"] = d["StartTime"].apply(parse_time_one)
    d["OrigEndSec"] = d["EndTime"].apply(parse_time_one)
    d = d.loc[d["OrigStartSec"].notna() & d["OrigEndSec"].notna()].copy()
    if d.empty:
        return df.copy()
    d["OrigEndSec"] = np.where(d["OrigEndSec"] < d["OrigStartSec"], d["OrigEndSec"] + 86400, d["OrigEndSec"])
    d["DurationSec"] = d["OrigEndSec"] - d["OrigStartSec"]
    if priority_mode == "Highest Power First":
        d = d.sort_values(["PowerW", "OrigStartSec"], ascending=[False, True])
    elif priority_mode == "Shortest Duration First":
        d = d.sort_values(["DurationSec", "OrigStartSec"], ascending=[True, True])
    else:
        d = d.sort_values(["OrigStartSec", "PowerW"], ascending=[True, False])
    placed, out_rows = [], []
    horizon_end = max(24*3600, float(d["OrigEndSec"].max()) + max_shift_sec)
    for _, row in d.iterrows():
        item = row.to_dict()
        req_start = item["OrigStartSec"]
        dur = item["DurationSec"]
        earliest = anchor_sec if allow_earlier else max(anchor_sec, req_start)
        latest = min(horizon_end - dur, req_start + max_shift_sec)
        candidates = {req_start, max(earliest, req_start)}
        if allow_earlier:
            candidates.add(anchor_sec)
        for p in placed:
            if freq_overlap(item["StartF"], item["EndF"], p["StartF"], p["EndF"], guard_mhz):
                candidates.add(p["PlacedEndSec"] + pad_sec)
                candidates.add(p["PlacedStartSec"] - pad_sec - dur)
        # 5-minute backup scan to catch real gaps
        if latest >= earliest:
            candidates.update(np.arange(earliest, latest + 1, 5*60))
        candidates = sorted(float(c) for c in candidates if np.isfinite(c) and c >= earliest and c <= latest)
        if req_start in candidates:
            candidates = [req_start] + [c for c in candidates if abs(c-req_start) > 1e-6]
        chosen, ok = req_start, False
        for cand in candidates:
            if placement_is_valid(cand, item, placed, pad_sec, guard_mhz):
                chosen, ok = cand, True
                break
        item["PlacedStartSec"] = chosen
        item["PlacedEndSec"] = chosen + dur
        item["ShiftSec"] = chosen - req_start
        item["Placed"] = ok
        item["StartTimeDC"] = fmt_hhmm(chosen)
        item["EndTimeDC"] = fmt_hhmm(chosen + dur)
        placed.append(item)
        out_rows.append(item)
    out = pd.DataFrame(out_rows).sort_values(".row_id")
    keep = [".row_id", "PlacedStartSec", "PlacedEndSec", "ShiftSec", "Placed", "StartTimeDC", "EndTimeDC"]
    return df.merge(out[keep], on=".row_id", how="left")

def conflict_summary(conflicts):
    if conflicts is None or conflicts.empty:
        return pd.DataFrame({"Message": ["No conflicts."]})
    return pd.DataFrame({
        "Freq Start (MHz)": conflicts["FreqLeft"].round(3),
        "Freq End (MHz)": conflicts["FreqRight"].round(3),
        "Window": conflicts["OverlapStartHM"] + " – " + conflicts["OverlapEndHM"],
        "Overlap (min)": conflicts["OverlapMin"].round(1),
        "Group A": conflicts["GroupA"], "Group B": conflicts["GroupB"]
    })

# ---------------- Plotting ----------------
def style_axes(ax, dark=False):
    if dark:
        ax.set_facecolor("black"); ax.figure.patch.set_facecolor("black")
        ax.tick_params(colors="white"); ax.xaxis.label.set_color("white"); ax.yaxis.label.set_color("white"); ax.title.set_color("white")
        ax.grid(True, linestyle="--", linewidth=.4, color="gray", alpha=.5)
        for sp in ax.spines.values(): sp.set_color("white")
    else:
        ax.grid(True, linestyle="--", linewidth=.4, color="gray", alpha=.4)

def thin_labels_df(df, group_field, min_gap_mhz):
    out = df.copy()
    if "CenterF" not in out.columns or min_gap_mhz is None or min_gap_mhz <= 0:
        out[".__keep_label"] = True; return out
    out[".__keep_label"] = False
    tmp = out.sort_values([group_field, "CenterF"], na_position="last")
    last, keep = {}, []
    for idx, row in tmp.iterrows():
        grp, cf = str(row[group_field]), row["CenterF"]
        if pd.isna(cf): continue
        if grp not in last or (cf - last[grp]) >= min_gap_mhz:
            keep.append(idx); last[grp] = cf
    out.loc[keep, ".__keep_label"] = True
    return out

def build_power_plot(df, group_field, dark, alpha_val, tick_major, tick_minor, label_digits, palette, auto_thin, min_label_gap, high_power_top, power_style, outline_lwd, show_center_labels):
    d = df.copy().sort_values(["PowerW", "StartF", "EndF"], ascending=[True if high_power_top else False, True, True])
    has_center = "CenterF" in d.columns and d["CenterF"].notna().any()
    d = thin_labels_df(d, group_field, min_label_gap) if auto_thin and has_center else d.assign(**{".__keep_label": True})
    x_min, x_max = min(d["StartF"].min(), d["EndF"].min()), max(d["StartF"].max(), d["EndF"].max())
    if tick_minor:
        x_min = math.floor(x_min/tick_minor)*tick_minor; x_max = math.ceil(x_max/tick_minor)*tick_minor
    y_max = float(d["PowerW"].max()); y_pad = max(1.0, .12*y_max)
    fig, ax = plt.subplots(figsize=(14,7), dpi=150)
    for _, row in d.iterrows():
        col = palette.get(str(row[group_field]), "#1f77b4")
        x, w, h = row["StartF"], row["EndF"]-row["StartF"], row["PowerW"]
        if power_style == "outline":
            ax.add_patch(Rectangle((x,0), w,h, fill=False, edgecolor=col, linewidth=outline_lwd))
        elif power_style == "outline_fill":
            ax.add_patch(Rectangle((x,0), w,h, facecolor=col, edgecolor=col, alpha=alpha_val, linewidth=outline_lwd))
        else:
            ax.add_patch(Rectangle((x,0), w,h, facecolor=col, edgecolor="black", alpha=alpha_val, linewidth=.25))
            ax.add_line(Line2D([row["StartF"], row["EndF"]], [h,h], color=col, linewidth=.9))
    if has_center and show_center_labels:
        label_color = "white" if dark else "black"
        for _, row in d.loc[d[".__keep_label"] & d["CenterF"].notna()].iterrows():
            ax.text(
                row["CenterF"],
                max(0.02, row["PowerW"] - max(0.12, row["PowerW"] * 0.05)),
                f"{row['CenterF']:.{label_digits}f} MHz",
                rotation=90,
                fontsize=8,
                ha="center",
                va="top",
                color=label_color,
                fontweight="bold",
                clip_on=True,
            )
    ax.set_xlim(x_min, x_max); ax.set_ylim(0, y_max+y_pad)
    ax.set_xlabel("Frequency (MHz)"); ax.set_ylabel("Power (W)")
    ax.set_title(f"Frequency Allocation vs Power — by {group_field}", fontweight="bold")
    if tick_major: ax.set_xticks(np.arange(x_min, x_max+tick_major, tick_major))
    if tick_minor:
        ax.set_xticks(np.arange(x_min, x_max+tick_minor, tick_minor), minor=True); ax.grid(which="minor", linestyle=":", linewidth=.25, alpha=.25)
    style_axes(ax, dark); plt.tight_layout(); return fig

def build_deconflict_plot(d0, grp_field, palette, dark, tick_major, tick_minor, show_box_labels, min_label_height_min, show_shift_label, moved_outline_thickness, conflicts_df):
    d = d0.copy(); d["Group"] = d[grp_field].astype(str)
    d["StartSec"] = d["StartTime"].apply(parse_time_one); d["EndSec"] = d["EndTime"].apply(parse_time_one)
    d = d.loc[d["StartSec"].notna() & d["EndSec"].notna()].copy()
    if d.empty:
        fig, ax = plt.subplots(figsize=(14, 4), dpi=150)
        ax.axis("off")
        ax.text(0.02, 0.70, "No time values could be parsed for this deconfliction plot.", fontsize=14, fontweight="bold", transform=ax.transAxes)
        ax.text(0.02, 0.52, "Check that your uploaded sheet has Start Time and End Time columns, or values like 6am, 08:00, 1300.", fontsize=11, transform=ax.transAxes)
        ax.text(0.02, 0.36, "Tip: re-upload the file after this update; the importer now auto-detects time columns.", fontsize=11, transform=ax.transAxes)
        return fig
    d["EndSecUnwrapped"] = np.where(d["EndSec"] < d["StartSec"], d["EndSec"]+86400, d["EndSec"])
    d["BoxHeightMin"] = (d["EndSecUnwrapped"]-d["StartSec"])/60
    d["Moved"] = d["ShiftSec"].fillna(0).abs() > 0 if "ShiftSec" in d.columns else False
    x_min, x_max = min(d["StartF"].min(), d["EndF"].min()), max(d["StartF"].max(), d["EndF"].max())
    if tick_minor:
        x_min = math.floor(x_min/tick_minor)*tick_minor; x_max = math.ceil(x_max/tick_minor)*tick_minor
    fig, ax = plt.subplots(figsize=(14,7), dpi=150)
    for _, row in d.iterrows():
        col = palette.get(str(row["Group"]), "#1f77b4")
        x0, w = row["StartF"], row["EndF"]-row["StartF"]
        y0, h = row["StartSec"]/3600, (row["EndSecUnwrapped"]-row["StartSec"])/3600
        ax.add_patch(Rectangle((x0,y0), w,h, facecolor=col, edgecolor="black", alpha=.6, linewidth=.2))
        if moved_outline_thickness > 0 and bool(row["Moved"]):
            ax.add_patch(Rectangle((x0,y0), w,h, facecolor="none", edgecolor="black", linewidth=moved_outline_thickness))
        if show_box_labels and row["BoxHeightMin"] >= float(min_label_height_min):
            label = str(row["Group"]); label = label if len(label) <= 24 else label[:21] + "..."
            ax.text(x0+w/2, y0+h/2, label, ha="center", va="center", fontsize=8, fontweight="bold", color=("white" if dark else "black"), clip_on=True)
        if show_shift_label and "ShiftSec" in d.columns and row["BoxHeightMin"] >= float(min_label_height_min):
            shift = row.get("ShiftSec", np.nan)
            if pd.notna(shift) and abs(shift) > 0:
                ax.text(x0+w/2, min(y0+h-.2, y0+.2), f"Δ {round(shift/60):.0f}m", ha="center", va="center", fontsize=7, fontweight="bold", color=("white" if dark else "black"), clip_on=True)
    if conflicts_df is not None and not conflicts_df.empty:
        for _, row in conflicts_df.iterrows():
            y1, y2 = (row["StartOverlap"]%86400)/3600, (row["EndOverlap"]%86400)/3600
            ax.add_patch(Rectangle((row["FreqLeft"], y1), row["FreqRight"]-row["FreqLeft"], y2-y1, facecolor="red", edgecolor="red", alpha=.15, linewidth=.8))
    ax.set_xlim(x_min, x_max); ax.set_ylim(0,24)
    ax.set_xlabel("Frequency (MHz)"); ax.set_ylabel("Time (hours)")
    ax.set_title(f"Time × Frequency — by {grp_field}", fontweight="bold")
    if tick_major: ax.set_xticks(np.arange(x_min, x_max+tick_major, tick_major))
    if tick_minor:
        ax.set_xticks(np.arange(x_min, x_max+tick_minor, tick_minor), minor=True); ax.grid(which="minor", linestyle=":", linewidth=.25, alpha=.25)
    style_axes(ax, dark); plt.tight_layout(); return fig

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Workspace")
    user_name = logged_in_user
    st.success(f"Logged in as: {user_name}")
    if st.button("Log out", use_container_width=True):
        st.session_state["authenticated"] = False
        st.session_state.pop("auth_user", None)
        st.rerun()
    projects = list_projects(); project_names = [p["name"] for p in projects]
    create_new = st.toggle("Create new project", value=False)
    if create_new:
        new_name = st.text_input("New project name"); new_desc = st.text_area("Description", height=80)
        if st.button("Create project", type="primary", use_container_width=True):
            if not new_name.strip(): st.error("Project name is required.")
            else:
                proj = create_project(new_name.strip(), new_desc.strip()); st.session_state["project_id"] = proj["id"]; st.rerun()
    else:
        if projects:
            selected_name = st.selectbox("Project", project_names, index=0)
            st.session_state["project_id"] = next(p for p in projects if p["name"] == selected_name)["id"]
        else: st.info("Create your first project.")
    st.divider(); st.header("Plot controls")
    dark = st.checkbox("Dark theme", value=False)
    power_style = st.selectbox("Power plot style", ["outline_fill", "filled", "outline"], index=0, format_func=lambda x: {"outline_fill":"Outline + light fill", "filled":"Filled bands", "outline":"Outline only"}[x])
    alpha_val = st.slider("Fill transparency", 0.0, 1.0, 0.45, 0.05)
    high_power_top = st.checkbox("Draw HIGH power on top", value=True)
    outline_lwd = st.slider("Outline thickness", 0.2, 2.0, 0.6, 0.1)
    auto_thin = st.checkbox("Auto thin center-frequency labels", value=False)
    show_center_labels = st.checkbox("Show center-frequency labels inside boxes", value=True)
    label_gap = st.number_input("Min label gap (MHz)", min_value=0.0, value=2.0, step=0.5)
    label_digits = st.number_input("Label decimals", min_value=0, max_value=6, value=2, step=1)
    tick_major = ticks_value(st.text_input("Major tick (MHz)", value="")); tick_minor = ticks_value(st.text_input("Minor grid (MHz)", value=""))
    st.divider(); st.header("Auto deconflict")
    auto_dc = st.checkbox("Auto deconflict by time", value=False)
    dc_start = st.text_input("Anchor", value="6am")
    dc_window = st.selectbox("Max shift window (hours)", [2,4,6,8,10,12,16,20,24], index=3)
    dc_pad_min = st.number_input("Min separation (minutes)", min_value=0.0, value=1.0, step=0.5)
    guard_mhz = st.number_input("Frequency guard band (MHz)", min_value=0.0, value=0.0, step=0.1)
    allow_earlier = st.checkbox("Allow moving earlier into open gaps", value=True)
    priority_mode = st.selectbox("Scheduling priority", ["Power + Original Time", "Highest Power First", "Shortest Duration First"], index=0)
    st.divider(); st.header("Box labels")
    box_labels = st.checkbox("Show label inside boxes", value=True)
    box_label_min_height_min = st.number_input("Min box height for label (min)", min_value=0.0, value=15.0, step=5.0)
    show_shift_label = st.checkbox("Show Δ minutes for moved boxes", value=False)
    moved_outline = st.slider("Moved outline thickness", 0.0, 2.5, 0.0, 0.1)

project_id = st.session_state.get("project_id")
if not project_id:
    st.info("Create or select a project to begin."); st.stop()

current_df = get_project_rows(project_id)
cols = st.columns(4)
cols[0].metric("Rows", len(current_df)); cols[1].metric("Project", next((p["name"] for p in projects if p["id"] == project_id), "Selected")); cols[2].metric("User", user_name); cols[3].metric("Storage", "Supabase JSON")

with st.expander("Import / replace table from file or pasted CSV", expanded=(len(current_df)==0)):
    c1, c2 = st.columns(2)
    with c1:
        uploaded = st.file_uploader("Upload CSV/XLSX", type=["csv", "xlsx", "xls"])
        if uploaded is not None:
            suffix = Path(uploaded.name).suffix.lower()
            try:
                if suffix in [".xlsx", ".xls"]:
                    xl = pd.ExcelFile(uploaded); sheet = st.selectbox("Sheet", xl.sheet_names); upload_df = pd.read_excel(uploaded, sheet_name=sheet)
                else: upload_df = pd.read_csv(uploaded)
                tmp = normalize_uploaded_df(upload_df); st.dataframe(tmp.head(20), use_container_width=True)
                if st.button("Replace with uploaded data", type="primary"):
                    replace_project_rows(project_id, tmp, user_name); save_version(project_id, tmp, user_name, "Imported file"); st.success("Uploaded data saved."); st.rerun()
            except Exception as e: st.error(f"Upload failed: {e}")
    with c2:
        pasted = st.text_area("Paste CSV", height=180, placeholder="Start Time,End Time,Equipment,Center Frequency (MHz),Bandwidth (MHz),Power (W),Tech,Unit")
        if pasted.strip():
            try:
                tmp = normalize_uploaded_df(pd.read_csv(io.StringIO(pasted))); st.dataframe(tmp.head(20), use_container_width=True)
                if st.button("Replace with pasted CSV", type="primary"):
                    replace_project_rows(project_id, tmp, user_name); save_version(project_id, tmp, user_name, "Pasted CSV"); st.success("Pasted data saved."); st.rerun()
            except Exception as e: st.error(f"Could not parse pasted CSV: {e}")

st.subheader("Shared allocation table")
edited_df = st.data_editor(current_df, use_container_width=True, height=330, num_rows="dynamic", key="editor")
s1, s2, s3 = st.columns([1,1,1.6])
with s1:
    if st.button("💾 Save shared changes", type="primary", use_container_width=True):
        replace_project_rows(project_id, edited_df, user_name); st.success("Saved."); st.rerun()
with s2: version_note = st.text_input("Version note", value="Manual save", label_visibility="collapsed")
with s3:
    if st.button("📌 Save version snapshot", use_container_width=True):
        st.success(f"Saved version {save_version(project_id, edited_df, user_name, version_note)}.")
with st.expander("Version history / restore"):
    versions = list_versions(project_id)
    if not versions: st.info("No versions saved yet.")
    else:
        st.dataframe(pd.DataFrame(versions)[["version_no", "saved_by", "save_note", "created_at"]], use_container_width=True)
        selected_v = st.selectbox("Restore version", versions, format_func=lambda v: f"v{v['version_no']} — {v.get('save_note') or ''} — {v.get('saved_by') or ''}")
        if st.button("Restore selected version"):
            v = load_version(selected_v["id"]); restored = normalize_uploaded_df(pd.DataFrame(v["snapshot"])); replace_project_rows(project_id, restored, user_name); save_version(project_id, restored, user_name, f"Restored v{selected_v['version_no']}"); st.success("Restored."); st.rerun()

try:
    df_ready = prep_df(edited_df)
except Exception as e:
    st.error(f"Could not prepare table for plots: {e}"); st.stop()
if df_ready.empty:
    st.warning("No valid plot rows. Need Start/End Frequency and Power."); st.stop()

grp_ut = unittech_field(df_ready)
pal_equipment = make_palette(sorted(safe_group(df_ready["Equipment"]).unique().tolist()))
pal_unittech = make_palette(sorted(safe_group(df_ready[grp_ut]).unique().tolist()))
ss, ee = df_ready["StartTime"].apply(parse_time_one), df_ready["EndTime"].apply(parse_time_one)
bad_count = int((ss.isna() | ee.isna()).sum())
base_conf_eq = detect_conflicts_generic(df_ready, "Equipment", guard_mhz)
base_conf_ut = detect_conflicts_generic(df_ready, grp_ut, guard_mhz)
m1, m2, m3 = st.columns(3)
m1.metric("Time parse issues", bad_count); m2.metric("Equipment conflicts", 0 if base_conf_eq is None else len(base_conf_eq)); m3.metric(f"{grp_ut} conflicts", 0 if base_conf_ut is None else len(base_conf_ut))
if bad_count:
    with st.expander("Rows with time parse issues"):
        st.dataframe(df_ready.loc[ss.isna() | ee.isna()], use_container_width=True)

plot_df_conf = df_ready.copy()
if auto_dc:
    anchor = parse_time_one(dc_start)
    if pd.isna(anchor): st.error("Deconflict anchor is invalid. Use HH:MM or 12am/7am."); st.stop()
    plot_df_conf = auto_deconflict_smart(df_ready, float(dc_window)*3600, float(dc_pad_min)*60, float(anchor), float(guard_mhz), allow_earlier, priority_mode)
    if "StartTimeDC" in plot_df_conf.columns:
        plot_df_conf["StartTimeOrig"] = plot_df_conf["StartTime"]; plot_df_conf["EndTimeOrig"] = plot_df_conf["EndTime"]
        plot_df_conf["StartTime"] = np.where(plot_df_conf["StartTimeDC"].notna(), plot_df_conf["StartTimeDC"], plot_df_conf["StartTime"])
        plot_df_conf["EndTime"] = np.where(plot_df_conf["EndTimeDC"].notna(), plot_df_conf["EndTimeDC"], plot_df_conf["EndTime"])
conf_eq = detect_conflicts_generic(plot_df_conf, "Equipment", guard_mhz)
conf_ut = detect_conflicts_generic(plot_df_conf, grp_ut, guard_mhz)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Equipment Power", "Equipment Deconfliction", f"{grp_ut} Power", f"{grp_ut} Deconfliction", "Conflict Tables"])
with tab1:
    fig = build_power_plot(df_ready, "Equipment", dark, alpha_val, tick_major, tick_minor, int(label_digits), pal_equipment, auto_thin, float(label_gap), high_power_top, power_style, float(outline_lwd), show_center_labels)
    st.pyplot(fig, use_container_width=True); st.download_button("Download PNG", fig_to_png_bytes(fig), "equipment_power.png", "image/png")
with tab2:
    fig = build_deconflict_plot(plot_df_conf, "Equipment", pal_equipment, dark, tick_major, tick_minor, box_labels, box_label_min_height_min, show_shift_label, moved_outline, conf_eq)
    st.pyplot(fig, use_container_width=True); st.download_button("Download PNG", fig_to_png_bytes(fig), "equipment_deconfliction.png", "image/png")
with tab3:
    fig = build_power_plot(df_ready, grp_ut, dark, alpha_val, tick_major, tick_minor, int(label_digits), pal_unittech, auto_thin, float(label_gap), high_power_top, power_style, float(outline_lwd), show_center_labels)
    st.pyplot(fig, use_container_width=True); st.download_button("Download PNG", fig_to_png_bytes(fig), f"{grp_ut.lower()}_power.png", "image/png")
with tab4:
    fig = build_deconflict_plot(plot_df_conf, grp_ut, pal_unittech, dark, tick_major, tick_minor, box_labels, box_label_min_height_min, show_shift_label, moved_outline, conf_ut)
    st.pyplot(fig, use_container_width=True); st.download_button("Download PNG", fig_to_png_bytes(fig), f"{grp_ut.lower()}_deconfliction.png", "image/png")
with tab5:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Equipment conflicts"); st.dataframe(conflict_summary(conf_eq), use_container_width=True)
    with c2:
        st.markdown(f"#### {grp_ut} conflicts"); st.dataframe(conflict_summary(conf_ut), use_container_width=True)
    if auto_dc and "ShiftSec" in plot_df_conf.columns:
        st.markdown("#### Auto-deconflict moves")
        moves = plot_df_conf.copy(); moves["ShiftMin"] = moves["ShiftSec"].fillna(0)/60
        moves = moves.loc[abs(moves["ShiftMin"]) > .001]
        cols = [c for c in ["Equipment", "Tech", "Unit", "StartF", "EndF", "StartTimeOrig", "EndTimeOrig", "StartTimeDC", "EndTimeDC", "ShiftMin", "Placed"] if c in moves.columns]
        st.dataframe(moves[cols] if not moves.empty else pd.DataFrame({"Message":["No rows were moved."]}), use_container_width=True)
