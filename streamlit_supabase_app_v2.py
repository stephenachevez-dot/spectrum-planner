import io
import re
import math
import json
import base64
import hashlib
from datetime import datetime, date, time

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

try:
    import pydeck as pdk
except Exception:
    pdk = None

try:
    from supabase import create_client
except Exception:
    create_client = None

st.set_page_config(page_title="Spectrum Planner V32 Map Radius", layout="wide")

# ============================================================
# Spectrum Planner V32 — Map Radius + Performance Controls
# ============================================================
# Adds:
# - Map displayed under the current Time x Frequency view, not as a new tab.
# - Radius circles using Coverage Radius.
# - Radius unit selector: meters / kilometers / miles.
# - Map performance controls so the app does not lag as much.
# - PyDeck map is optional and only renders when enabled.
# - Keeps project save/load, saved-project dropdown, planner, visual exports,
#   label orientation, label hide/show, and transparency controls.
# ============================================================

APP_COLUMNS = [
    "Active", "Locked", "Start Time", "End Time", "Unit", "Sponsor", "Equipment", "Tech",
    "Start Frequency (MHz)", "Center Frequency (MHz)", "End Frequency (MHz)", "Bandwidth (MHz)",
    "Power (W)", "Power (dBm)", "Tech Category", "Latitude", "Longitude", "Location",
    "System/Platform", "Antenna Height", "Coverage Radius", "Site Name", "MGRS", "USNG", "Notes",
]

PALETTE = [
    "#2563EB", "#F97316", "#22C55E", "#EAB308", "#A855F7", "#EF4444", "#06B6D4", "#84CC16",
    "#EC4899", "#8B5CF6", "#14B8A6", "#F59E0B", "#0EA5E9", "#F43F5E", "#64748B", "#6366F1",
    "#15803D", "#C2410C", "#A16207", "#7C3AED", "#0F766E", "#B45309", "#0369A1", "#BE185D",
    "#334155",
]

RENAME_MAP = {
    "enabled": "Active", "inuse": "Active", "use": "Active", "include": "Active", "active": "Active",
    "lock": "Locked", "locked": "Locked", "lockfrequency": "Locked", "lockboth": "Locked",
    "starttime": "Start Time", "start": "Start Time", "begintime": "Start Time",
    "endtime": "End Time", "end": "End Time", "stoptime": "End Time",
    "unit": "Unit", "sponsor": "Sponsor", "sponser": "Sponsor",
    "equipment": "Equipment", "system": "Equipment", "device": "Equipment", "radio": "Equipment",
    "tech": "Tech", "technology": "Tech",
    "startf": "Start Frequency (MHz)", "startfrequency": "Start Frequency (MHz)",
    "startfrequencymhz": "Start Frequency (MHz)", "startfreq": "Start Frequency (MHz)",
    "centerf": "Center Frequency (MHz)", "centerfrequency": "Center Frequency (MHz)",
    "centerfrequencymhz": "Center Frequency (MHz)", "centerfreq": "Center Frequency (MHz)",
    "frequency": "Center Frequency (MHz)", "freq": "Center Frequency (MHz)",
    "endf": "End Frequency (MHz)", "endfrequency": "End Frequency (MHz)",
    "endfrequencymhz": "End Frequency (MHz)", "endfreq": "End Frequency (MHz)",
    "bw": "Bandwidth (MHz)", "bandwidth": "Bandwidth (MHz)", "bandwidthmhz": "Bandwidth (MHz)",
    "power": "Power (W)", "powerw": "Power (W)", "powerwatts": "Power (W)",
    "powerdbm": "Power (dBm)", "dbm": "Power (dBm)",
    "techcategory": "Tech Category", "category": "Tech Category",
    "lat": "Latitude", "latitude": "Latitude", "lon": "Longitude", "lng": "Longitude",
    "long": "Longitude", "longitude": "Longitude", "location": "Location",
    "systemplatform": "System/Platform", "platform": "System/Platform",
    "antennaheight": "Antenna Height", "coverageradius": "Coverage Radius", "radius": "Coverage Radius",
    "sitename": "Site Name", "site": "Site Name", "mgrs": "MGRS", "usng": "USNG",
    "notes": "Notes", "note": "Notes", "comments": "Notes",
}

MAX_CONFLICTS_DISPLAY = 2500
MAX_PLANNER_ROWS = 1200
DEFAULT_MAX_MAP_ROWS = 300

# ============================================================
# General helpers
# ============================================================

def key_name(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def to_json_safe(x):
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, (pd.Timestamp, datetime, date, time)):
        return x.isoformat()
    if hasattr(x, "isoformat"):
        try:
            return x.isoformat()
        except Exception:
            pass
    return x


def to_bool(value, default=True) -> bool:
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "t", "yes", "y", "1", "on", "active", "checked", "x"}:
        return True
    if text in {"false", "f", "no", "n", "0", "off", "inactive", "unchecked", "", "none", "nan"}:
        return False
    return default


def to_float(value, default=None):
    try:
        if value is None or pd.isna(value):
            return default
    except Exception:
        pass
    try:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
        return float(match.group(0)) if match else default
    except Exception:
        return default


def find_col(df: pd.DataFrame, names):
    lookup = {key_name(c): c for c in df.columns}
    for name in names:
        k = key_name(name)
        if k in lookup:
            return lookup[k]
    for name in names:
        k = key_name(name)
        for found, original in lookup.items():
            if k and (k in found or found in k):
                return original
    return None


def normalize_columns(df: pd.DataFrame, add_missing=True) -> pd.DataFrame:
    out = df.copy()
    out = out.loc[:, [c for c in out.columns if not str(c).lower().startswith("unnamed")]]
    rename = {}
    for col in out.columns:
        k = key_name(col)
        if k in RENAME_MAP:
            rename[col] = RENAME_MAP[k]
    out = out.rename(columns=rename)
    out = out.loc[:, ~pd.Index(out.columns).duplicated(keep="first")].copy()
    if add_missing:
        for col in APP_COLUMNS:
            if col not in out.columns:
                if col == "Active":
                    out[col] = True
                elif col == "Locked":
                    out[col] = False
                else:
                    out[col] = None
    if "Active" in out.columns:
        out["Active"] = out["Active"].apply(lambda v: to_bool(v, True))
    if "Locked" in out.columns:
        out["Locked"] = out["Locked"].apply(lambda v: to_bool(v, False))
    preferred = [c for c in APP_COLUMNS if c in out.columns]
    extras = [c for c in out.columns if c not in preferred]
    return out[preferred + extras]


def time_to_hours(value):
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return float(value.hour) + float(value.minute) / 60.0
    text = str(value or "").strip().lower()
    if not text or text in {"none", "nan"}:
        return None
    try:
        if ":" in text:
            parts = text.split(":")
            return float(parts[0]) + float(parts[1]) / 60.0
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return None
        val = float(match.group(0))
        if val >= 100:
            return int(val // 100) + (val % 100) / 60.0
        return val
    except Exception:
        return None


def format_time_hhmm(hours_float):
    hours_float = float(hours_float) % 24.0
    hh = int(hours_float)
    mm = int(round((hours_float - hh) * 60))
    if mm >= 60:
        hh = (hh + 1) % 24
        mm = 0
    return f"{hh:02d}:{mm:02d}"


def timestamp_string():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def label_value(value) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "blank", "(blank)"}:
        return "(blank)"
    return text


def stable_color(label: str) -> str:
    digest = hashlib.md5(label_value(label).encode("utf-8")).hexdigest()
    return PALETTE[int(digest[:8], 16) % len(PALETTE)]


def frequency_display_value(value):
    val = to_float(value)
    if val is None:
        return None
    return f"{val:.3f} MHz"


def recalc_start_end_fast(df: pd.DataFrame) -> pd.DataFrame:
    out = normalize_columns(df, add_missing=True)
    center_col = find_col(out, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(out, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_col = find_col(out, ["Start Frequency (MHz)", "Start Frequency", "StartF"])
    end_col = find_col(out, ["End Frequency (MHz)", "End Frequency", "EndF"])
    if center_col is None or bw_col is None:
        return out
    centers = pd.to_numeric(out[center_col], errors="coerce")
    bws = pd.to_numeric(out[bw_col], errors="coerce")
    valid = centers.notna() & bws.notna() & (bws > 0)
    out.loc[valid, start_col] = (centers[valid] - bws[valid] / 2.0).round(6)
    out.loc[valid, end_col] = (centers[valid] + bws[valid] / 2.0).round(6)
    return normalize_columns(out, add_missing=True)


def active_only(df: pd.DataFrame, show_inactive=False) -> pd.DataFrame:
    out = recalc_start_end_fast(df)
    if not show_inactive and "Active" in out.columns:
        out = out[out["Active"] == True].copy()
    return out.reset_index(drop=True)


def row_window(row, start_time_col, end_time_col):
    t1 = time_to_hours(row.get(start_time_col)) if start_time_col else None
    t2 = time_to_hours(row.get(end_time_col)) if end_time_col else None
    if t1 is None:
        t1 = 0.0
    if t2 is None or t2 <= t1:
        t2 = t1 + 2.0
    return t1, t2


def row_frequency_interval(row, center_col, bw_col):
    center = to_float(row.get(center_col))
    bw = to_float(row.get(bw_col))
    if center is None or bw is None or bw <= 0:
        return None, None, None, None
    return center, bw, center - bw / 2.0, center + bw / 2.0


def intervals_overlap(a1, a2, b1, b2) -> bool:
    return max(a1, b1) < min(a2, b2)

# ============================================================
# Supabase collaboration
# ============================================================

def supabase_configured():
    return bool(st.secrets.get("SUPABASE_URL", "")) and bool(st.secrets.get("SUPABASE_ANON_KEY", "")) and create_client is not None


@st.cache_resource(show_spinner=False)
def get_supabase_client():
    if not supabase_configured():
        return None
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])


def workbook_to_jsonable(sheets):
    payload = {}
    for name, df in sheets.items():
        clean = recalc_start_end_fast(df).copy()
        for col in clean.columns:
            clean[col] = clean[col].map(to_json_safe)
        records = json.loads(json.dumps(clean.to_dict(orient="records"), allow_nan=False))
        payload[name] = {"columns": list(clean.columns), "records": records}
    return payload


def workbook_from_jsonable(payload):
    sheets = {}
    for name, obj in payload.items():
        records = obj.get("records", [])
        columns = obj.get("columns", None)
        df = pd.DataFrame(records)
        if columns:
            for col in columns:
                if col not in df.columns:
                    df[col] = None
            df = df[columns]
        sheets[name] = normalize_columns(df, add_missing=True)
    return sheets


def save_project(project_id, project_name, updated_by):
    client = get_supabase_client()
    if client is None:
        return False, "Supabase is not configured."
    if not st.session_state.get("sheets"):
        return False, "No workbook is loaded."
    row = {
        "project_id": project_id.strip(),
        "project_name": project_name.strip() or project_id.strip(),
        "workbook": workbook_to_jsonable(st.session_state["sheets"]),
        "png_exports": st.session_state.get("saved_png_exports", {}),
        "updated_by": updated_by.strip() or "unknown",
        "updated_at": datetime.utcnow().isoformat(),
    }
    try:
        client.table("spectrum_projects").upsert(row, on_conflict="project_id").execute()
        return True, f"Saved project '{row['project_name']}'."
    except Exception as exc:
        return False, f"Save failed: {exc}"


def load_project(project_id):
    client = get_supabase_client()
    if client is None:
        return False, "Supabase is not configured."
    try:
        result = client.table("spectrum_projects").select("*").eq("project_id", project_id.strip()).limit(1).execute()
        rows = result.data or []
        if not rows:
            return False, "Project not found."
        row = rows[0]
        st.session_state["sheets"] = workbook_from_jsonable(row.get("workbook", {}))
        st.session_state["saved_png_exports"] = row.get("png_exports", {}) or {}
        st.session_state["active_project_id"] = row.get("project_id")
        st.session_state["active_project_name"] = row.get("project_name")
        st.session_state["loaded_upload_sig"] = None
        st.session_state["analysis_cache"] = {}
        st.session_state["hidden_visual_labels"] = {}
        st.session_state["visual_version"] = st.session_state.get("visual_version", 0) + 1
        return True, f"Loaded project '{row.get('project_name') or row.get('project_id')}'."
    except Exception as exc:
        return False, f"Load failed: {exc}"


def list_projects():
    client = get_supabase_client()
    if client is None:
        return []
    try:
        result = client.table("spectrum_projects").select("project_id,project_name,updated_by,updated_at").order("updated_at", desc=True).execute()
        return result.data or []
    except Exception:
        return []


def duplicate_project_as(new_project_id, new_project_name, updated_by):
    return save_project(new_project_id, new_project_name, updated_by)

# ============================================================
# Conflict detection / Smart Planner
# ============================================================

def detect_conflicts_fast(df: pd.DataFrame, max_conflicts=MAX_CONFLICTS_DISPLAY, guard_mhz=0.0):
    working = active_only(df, show_inactive=False)
    center_col = find_col(working, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(working, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_time_col = find_col(working, ["Start Time", "StartTime", "Start"])
    end_time_col = find_col(working, ["End Time", "EndTime", "End"])
    equipment_col = find_col(working, ["Equipment"])
    unit_col = find_col(working, ["Unit"])
    tech_col = find_col(working, ["Tech"])
    sponsor_col = find_col(working, ["Sponsor"])
    if center_col is None or bw_col is None or working.empty:
        return pd.DataFrame()
    rows = []
    numeric = []
    for pos, row in working.iterrows():
        center, bw, f1, f2 = row_frequency_interval(row, center_col, bw_col)
        if center is None:
            continue
        t1, t2 = row_window(row, start_time_col, end_time_col)
        numeric.append((pos, row, center, bw, f1 - guard_mhz, f2 + guard_mhz, t1, t2))
    numeric.sort(key=lambda x: x[4])
    for a_idx in range(len(numeric)):
        pos_a, row_a, ac, abw, af1, af2, at1, at2 = numeric[a_idx]
        for b_idx in range(a_idx + 1, len(numeric)):
            pos_b, row_b, bc, bbw, bf1, bf2, bt1, bt2 = numeric[b_idx]
            if bf1 >= af2:
                break
            if intervals_overlap(af1, af2, bf1, bf2) and intervals_overlap(at1, at2, bt1, bt2):
                rows.append({
                    "Row A": pos_a + 1, "Row B": pos_b + 1,
                    "Equipment A": row_a.get(equipment_col, "") if equipment_col else "",
                    "Equipment B": row_b.get(equipment_col, "") if equipment_col else "",
                    "Unit A": row_a.get(unit_col, "") if unit_col else "",
                    "Unit B": row_b.get(unit_col, "") if unit_col else "",
                    "Tech A": row_a.get(tech_col, "") if tech_col else "",
                    "Tech B": row_b.get(tech_col, "") if tech_col else "",
                    "Sponsor A": row_a.get(sponsor_col, "") if sponsor_col else "",
                    "Sponsor B": row_b.get(sponsor_col, "") if sponsor_col else "",
                    "Center A": ac, "Center B": bc,
                    "Bandwidth A": abw, "Bandwidth B": bbw,
                    "Time A": f"{format_time_hhmm(at1)}-{format_time_hhmm(at2)}",
                    "Time B": f"{format_time_hhmm(bt1)}-{format_time_hhmm(bt2)}",
                    "Reason": "Frequency and time overlap",
                })
                if len(rows) >= max_conflicts:
                    return pd.DataFrame(rows)
    return pd.DataFrame(rows)


def time_slot_is_open(df, moving_index, new_start, new_end, center_col, bw_col, start_time_col, end_time_col, guard_mhz=0.0):
    moving = df.loc[moving_index]
    _, _, moving_f1, moving_f2 = row_frequency_interval(moving, center_col, bw_col)
    if moving_f1 is None:
        return False
    for idx, other in df.iterrows():
        if idx == moving_index or not to_bool(other.get("Active"), True):
            continue
        _, _, of1, of2 = row_frequency_interval(other, center_col, bw_col)
        if of1 is None:
            continue
        ot1, ot2 = row_window(other, start_time_col, end_time_col)
        if intervals_overlap(moving_f1 - guard_mhz, moving_f2 + guard_mhz, of1, of2) and intervals_overlap(new_start, new_end, ot1, ot2):
            return False
    return True


def frequency_is_open(candidate_center, candidate_bw, moving_index, df, center_col, bw_col, start_time_col, end_time_col, guard_mhz):
    candidate_start = candidate_center - candidate_bw / 2.0 - guard_mhz
    candidate_end = candidate_center + candidate_bw / 2.0 + guard_mhz
    moving_t1, moving_t2 = row_window(df.loc[moving_index], start_time_col, end_time_col)
    for idx, other in df.iterrows():
        if idx == moving_index or not to_bool(other.get("Active"), True):
            continue
        _, _, other_start, other_end = row_frequency_interval(other, center_col, bw_col)
        if other_start is None:
            continue
        other_t1, other_t2 = row_window(other, start_time_col, end_time_col)
        if intervals_overlap(moving_t1, moving_t2, other_t1, other_t2) and intervals_overlap(candidate_start, candidate_end, other_start, other_end):
            return False
    return True


def build_candidate_time_slots(day_start, day_end, window_hours, step_minutes, old_start=None):
    slots = []
    step_hours = max(float(step_minutes) / 60.0, 1.0 / 60.0)
    x = float(day_start)
    last = float(day_end) - float(window_hours)
    while x <= last + 1e-9:
        slots.append((round(x, 6), round(x + window_hours, 6)))
        x += step_hours
    if old_start is not None:
        slots = sorted(slots, key=lambda s: (abs(s[0] - old_start), s[0]))
    return slots


def build_candidate_centers(low_mhz, high_mhz, step_mhz, bw_mhz, old_center=None):
    centers = []
    x = low_mhz + bw_mhz / 2.0
    last = high_mhz - bw_mhz / 2.0
    while x <= last + 1e-9:
        centers.append(round(x, 6))
        x += step_mhz
    if old_center is not None:
        centers = sorted(centers, key=lambda c: (abs(c - old_center), c))
    return centers


def smart_time_deconflict(df, day_start=6.0, day_end=20.0, step_minutes=30, guard_mhz=0.0, max_passes=5):
    out = recalc_start_end_fast(df).copy()
    center_col = find_col(out, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(out, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_col = find_col(out, ["Start Time", "StartTime", "Start"])
    end_col = find_col(out, ["End Time", "EndTime", "End"])
    if center_col is None or bw_col is None:
        return out, pd.DataFrame()
    moves = []
    for _ in range(int(max_passes)):
        conflicts = detect_conflicts_fast(out, guard_mhz=guard_mhz)
        if conflicts.empty:
            break
        moved_any = False
        candidate_rows = []
        for _, c in conflicts.iterrows():
            for label in ["Row B", "Row A"]:
                idx = int(c[label]) - 1
                if idx not in candidate_rows:
                    candidate_rows.append(idx)
        for idx in candidate_rows:
            if idx not in out.index:
                continue
            row = out.loc[idx]
            if not to_bool(row.get("Active"), True) or to_bool(row.get("Locked"), False):
                continue
            old_start, old_end = row_window(row, start_col, end_col)
            window = max(old_end - old_start, 0.25)
            for ns, ne in build_candidate_time_slots(day_start, day_end, window, step_minutes, old_start=old_start):
                if abs(ns - old_start) < 1e-9 and abs(ne - old_end) < 1e-9:
                    continue
                if time_slot_is_open(out, idx, ns, ne, center_col, bw_col, start_col, end_col, guard_mhz):
                    out.at[idx, start_col] = format_time_hhmm(ns)
                    out.at[idx, end_col] = format_time_hhmm(ne)
                    moves.append({"Row": idx + 1, "Move Type": "Time", "Old Start": format_time_hhmm(old_start), "Old End": format_time_hhmm(old_end), "New Start": format_time_hhmm(ns), "New End": format_time_hhmm(ne)})
                    moved_any = True
                    break
        if not moved_any:
            break
    return recalc_start_end_fast(out), pd.DataFrame(moves)


def smart_frequency_deconflict(df, low_mhz=2200.0, high_mhz=2300.0, step_mhz=1.0, guard_mhz=0.0, max_passes=5):
    out = recalc_start_end_fast(df).copy()
    center_col = find_col(out, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(out, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_col = find_col(out, ["Start Time", "StartTime", "Start"])
    end_col = find_col(out, ["End Time", "EndTime", "End"])
    if center_col is None or bw_col is None:
        return out, pd.DataFrame()
    moves = []
    for _ in range(int(max_passes)):
        conflicts = detect_conflicts_fast(out, guard_mhz=guard_mhz)
        if conflicts.empty:
            break
        moved_any = False
        candidate_rows = []
        for _, c in conflicts.iterrows():
            for label in ["Row B", "Row A"]:
                idx = int(c[label]) - 1
                if idx not in candidate_rows:
                    candidate_rows.append(idx)
        for idx in candidate_rows:
            if idx not in out.index:
                continue
            row = out.loc[idx]
            if not to_bool(row.get("Active"), True) or to_bool(row.get("Locked"), False):
                continue
            old_center = to_float(row.get(center_col))
            bw = to_float(row.get(bw_col), 1.0)
            if old_center is None or bw is None or bw <= 0:
                continue
            for candidate in build_candidate_centers(low_mhz, high_mhz, step_mhz, bw, old_center=old_center):
                if abs(candidate - old_center) < 1e-9:
                    continue
                if frequency_is_open(candidate, bw, idx, out, center_col, bw_col, start_col, end_col, guard_mhz):
                    out.at[idx, center_col] = candidate
                    moves.append({"Row": idx + 1, "Move Type": "Frequency", "Old Center": old_center, "New Center": candidate})
                    out = recalc_start_end_fast(out)
                    moved_any = True
                    break
        if not moved_any:
            break
    return recalc_start_end_fast(out), pd.DataFrame(moves)

# ============================================================
# Session and files
# ============================================================

def store_analysis(sheet_name, conflict_df):
    st.session_state.setdefault("analysis_cache", {})[sheet_name] = conflict_df


def get_stored_analysis(sheet_name):
    return st.session_state.get("analysis_cache", {}).get(sheet_name, pd.DataFrame())


def clear_stored_analysis(sheet_name):
    st.session_state.setdefault("analysis_cache", {}).pop(sheet_name, None)


def update_active_sheet_in_session(sheet_name, df):
    saved = recalc_start_end_fast(df).copy()
    st.session_state["sheets"][sheet_name] = saved
    st.session_state["last_autosave_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state["visual_version"] = st.session_state.get("visual_version", 0) + 1
    return saved


def apply_planner_results_to_active_sheet(sheet_name):
    pending = st.session_state.get("pending_planner_df")
    if pending is None or len(pending) == 0:
        return False, "No planner results are waiting to apply."
    applied = recalc_start_end_fast(pending).copy()
    st.session_state["sheets"][sheet_name] = applied
    store_analysis(sheet_name, detect_conflicts_fast(applied, guard_mhz=st.session_state.get("guard_mhz", 0.0)))
    st.session_state["planner_applied_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state["visual_version"] = st.session_state.get("visual_version", 0) + 1
    st.session_state.pop("pending_planner_df", None)
    st.session_state.pop("pending_planner_moves", None)
    st.session_state.pop("pending_planner_summary", None)
    return True, "Planner results applied."


def dataframe_to_xlsx(sheets: dict) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in sheets.items():
            safe_name = str(name)[:31] if str(name).strip() else "Sheet"
            recalc_start_end_fast(df).to_excel(writer, sheet_name=safe_name, index=False)
    output.seek(0)
    return output.read()


def load_file(uploaded_file):
    name = getattr(uploaded_file, "name", "").lower()
    if name.endswith(".csv"):
        return {"Imported": normalize_columns(pd.read_csv(uploaded_file), add_missing=True)}
    excel = pd.ExcelFile(uploaded_file)
    sheets = {}
    for sheet in excel.sheet_names:
        if str(sheet).strip().lower() == "dashboard":
            continue
        sheets[sheet] = normalize_columns(pd.read_excel(excel, sheet_name=sheet), add_missing=True)
    return sheets

# ============================================================
# Visual helpers
# ============================================================

def get_hidden_label_frequencies(sheet_name):
    return set(st.session_state.setdefault("hidden_visual_labels", {}).get(sheet_name, []))


def set_hidden_label_frequencies(sheet_name, values):
    clean = sorted(set([v for v in values if v]), key=lambda x: to_float(x, 0.0))
    st.session_state.setdefault("hidden_visual_labels", {})[sheet_name] = clean
    st.session_state["visual_version"] = st.session_state.get("visual_version", 0) + 1


def visual_frequency_options(df):
    working = active_only(df, show_inactive=st.session_state.get("show_inactive_rows", False))
    center_col = find_col(working, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    if center_col is None or working.empty:
        return []
    labels = []
    for value in working[center_col].tolist():
        label = frequency_display_value(value)
        if label and label not in labels:
            labels.append(label)
    return sorted(labels, key=lambda x: to_float(x, 0.0))


def build_color_map(df: pd.DataFrame, color_by: str) -> dict:
    if color_by is None or color_by not in df.columns:
        return {}
    labels = []
    for value in df[color_by].fillna("(blank)").astype(str).tolist():
        lab = label_value(value)
        if lab not in labels:
            labels.append(lab)
    return {lab: stable_color(lab) for lab in labels}


def pick_color_field(df: pd.DataFrame, preferred="Equipment"):
    for col in [preferred, "Equipment", "Tech", "Unit", "Sponsor", "Tech Category", "Location"]:
        if col in df.columns:
            return col
    return df.columns[0] if len(df.columns) else None


def add_legend(ax, color_by, color_map, dark=True):
    if not color_map:
        return
    handles = [plt.Line2D([0], [0], marker="s", linestyle="", markerfacecolor=color, markeredgecolor=color, markersize=9, label=label) for label, color in color_map.items()]
    legend = ax.legend(handles=handles, title=color_by, loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=True)
    legend.get_frame().set_facecolor("#111827" if dark else "white")
    legend.get_frame().set_edgecolor("#CBD5E1")
    plt.setp(legend.get_texts(), color="white" if dark else "black", fontsize=8)
    plt.setp(legend.get_title(), color="white" if dark else "black", fontsize=9, fontweight="bold")


def sorted_for_draw_order(plot_df, power_col, draw_order):
    if power_col is None or plot_df.empty:
        return plot_df
    temp = plot_df.copy()
    temp["_draw_power"] = temp[power_col].apply(lambda x: to_float(x, 0.0))
    if draw_order == "High power in back":
        return temp.sort_values("_draw_power", ascending=False).drop(columns=["_draw_power"])
    if draw_order == "Low power in back":
        return temp.sort_values("_draw_power", ascending=True).drop(columns=["_draw_power"])
    return plot_df


def row_alpha(row, power_col, max_power, high_alpha, low_alpha):
    if power_col is None:
        return 0.80
    power = to_float(row.get(power_col), 0.0)
    ratio = max(0.0, min(power / max_power, 1.0)) if max_power else 0.0
    return low_alpha + ratio * (high_alpha - low_alpha)


def estimate_freq_gap(plot_df, center_col):
    if center_col is None:
        return 999
    centers = sorted([to_float(v) for v in plot_df[center_col].tolist() if to_float(v) is not None])
    if len(centers) < 2:
        return 999
    gaps = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
    return min([g for g in gaps if g > 0] or [999])


def choose_label_rotation(label_mode, bw, idx, freq_gap_mhz):
    if label_mode == "Horizontal":
        return 0
    if label_mode == "Vertical":
        return 90
    if label_mode == "Staggered":
        return 90 if idx % 2 else 0
    if bw < 8 or freq_gap_mhz < 7:
        return 90
    return 0


def time_frequency_chart(df, color_by="Equipment", dark=True, title=None, sheet_name=None, label_preview=False, draw_order="High power in back", high_power_alpha=0.95, low_power_alpha=0.95, label_mode="Auto"):
    plot_df = active_only(df, show_inactive=st.session_state.get("show_inactive_rows", False))
    hidden_labels = set() if label_preview or not sheet_name else get_hidden_label_frequencies(sheet_name)
    color_by = color_by if color_by in plot_df.columns else pick_color_field(plot_df, color_by)
    color_map = build_color_map(plot_df, color_by)
    center_col = find_col(plot_df, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(plot_df, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_time_col = find_col(plot_df, ["Start Time", "StartTime", "Start"])
    end_time_col = find_col(plot_df, ["End Time", "EndTime", "End"])
    power_col = find_col(plot_df, ["Power (W)", "PowerW", "Power"])
    fig, ax = plt.subplots(figsize=(16, 7))
    fig.patch.set_facecolor("#111827" if dark else "white")
    ax.set_facecolor("#111827" if dark else "white")
    rows_drawn = 0
    all_times = []
    max_power = 1.0
    if power_col is not None and len(plot_df):
        max_power = max([to_float(v, 0.0) for v in plot_df[power_col].tolist()] + [1.0])
    freq_gap = estimate_freq_gap(plot_df, center_col)
    plot_df = sorted_for_draw_order(plot_df, power_col, draw_order)
    for draw_idx, (_, row) in enumerate(plot_df.iterrows()):
        center = to_float(row.get(center_col)) if center_col else None
        bw = to_float(row.get(bw_col), 1.0) if bw_col else 1.0
        if center is None:
            continue
        if bw is None or bw <= 0:
            bw = 1.0
        start_time, end_time = row_window(row, start_time_col, end_time_col)
        if end_time <= start_time:
            continue
        all_times.extend([start_time, end_time])
        group_label = label_value(row.get(color_by, "(blank)")) if color_by else "(blank)"
        color = color_map.get(group_label, stable_color(group_label))
        alpha = row_alpha(row, power_col, max_power, high_power_alpha, low_power_alpha)
        ax.add_patch(Rectangle((center - bw / 2.0, start_time), bw, end_time - start_time, facecolor=color, edgecolor="#0F172A", linewidth=0.9, alpha=alpha))
        freq_label = frequency_display_value(center)
        if freq_label not in hidden_labels and len(plot_df) <= 180:
            rotation = choose_label_rotation(label_mode, bw, draw_idx, freq_gap)
            ax.text(center, start_time + (end_time - start_time) / 2.0, f"{center:.3f} MHz", rotation=rotation, ha="center", va="center", fontsize=7, fontweight="bold", color="white", bbox=dict(boxstyle="round,pad=0.12", facecolor="#111827", edgecolor="none", alpha=0.55), clip_on=True)
        rows_drawn += 1
    ax.autoscale()
    if all_times:
        ymin = min(all_times)
        ymax = max(all_times)
        pad = max(0.25, (ymax - ymin) * 0.08)
        ax.set_ylim(max(0, ymin - pad), min(24, ymax + pad))
    ax.set_title(title or f"Time × Frequency — by {color_by}", color="white" if dark else "black", fontsize=15, fontweight="bold")
    ax.set_xlabel("Frequency (MHz)", color="white" if dark else "black")
    ax.set_ylabel("Time (hours)", color="white" if dark else "black")
    ax.tick_params(colors="white" if dark else "black")
    ax.grid(True, alpha=0.18, zorder=0)
    add_legend(ax, color_by, color_map, dark=dark)
    fig.tight_layout()
    return fig, plot_df, rows_drawn


def power_chart(df, color_by="Equipment", dark=True, sheet_name=None, draw_order="High power in back", high_power_alpha=0.95, low_power_alpha=0.95, label_mode="Auto"):
    plot_df = active_only(df, show_inactive=st.session_state.get("show_inactive_rows", False))
    hidden_labels = set() if not sheet_name else get_hidden_label_frequencies(sheet_name)
    color_by = color_by if color_by in plot_df.columns else pick_color_field(plot_df, color_by)
    color_map = build_color_map(plot_df, color_by)
    center_col = find_col(plot_df, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(plot_df, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    power_col = find_col(plot_df, ["Power (W)", "PowerW", "Power"])
    fig, ax = plt.subplots(figsize=(16, 7))
    fig.patch.set_facecolor("#111827" if dark else "white")
    ax.set_facecolor("#111827" if dark else "white")
    max_power = 1.0
    if power_col is not None and len(plot_df):
        max_power = max([to_float(v, 0.0) for v in plot_df[power_col].tolist()] + [1.0])
    freq_gap = estimate_freq_gap(plot_df, center_col)
    plot_df = sorted_for_draw_order(plot_df, power_col, draw_order)
    for draw_idx, (_, row) in enumerate(plot_df.iterrows()):
        center = to_float(row.get(center_col)) if center_col else None
        bw = to_float(row.get(bw_col), 1.0) if bw_col else 1.0
        power = to_float(row.get(power_col), 1.0) if power_col else 1.0
        if center is None:
            continue
        if bw is None or bw <= 0:
            bw = 1.0
        if power is None or power <= 0:
            power = 1.0
        group_label = label_value(row.get(color_by, "(blank)")) if color_by else "(blank)"
        color = color_map.get(group_label, stable_color(group_label))
        alpha = row_alpha(row, power_col, max_power, high_power_alpha, low_power_alpha)
        ax.add_patch(Rectangle((center - bw / 2.0, 0), bw, power, facecolor=color, edgecolor="#0F172A", linewidth=0.9, alpha=alpha))
        freq_label = frequency_display_value(center)
        if freq_label not in hidden_labels and len(plot_df) <= 180:
            rotation = choose_label_rotation(label_mode, bw, draw_idx, freq_gap)
            ax.text(center, power / 2.0, f"{center:.3f} MHz", rotation=rotation, ha="center", va="center", fontsize=7, fontweight="bold", color="white", bbox=dict(boxstyle="round,pad=0.12", facecolor="#111827", edgecolor="none", alpha=0.55), clip_on=True)
    ax.autoscale()
    ax.set_title(f"Frequency Allocation vs Power — by {color_by}", color="white" if dark else "black", fontsize=15, fontweight="bold")
    ax.set_xlabel("Frequency (MHz)", color="white" if dark else "black")
    ax.set_ylabel("Power (W)", color="white" if dark else "black")
    ax.tick_params(colors="white" if dark else "black")
    ax.grid(True, alpha=0.18, zorder=0)
    add_legend(ax, color_by, color_map, dark=dark)
    fig.tight_layout()
    return fig, plot_df


def fig_to_png_bytes(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    buf.seek(0)
    return buf.read()


def time_debug_table(df):
    working = active_only(df, show_inactive=st.session_state.get("show_inactive_rows", False))
    start_col = find_col(working, ["Start Time", "StartTime", "Start"])
    end_col = find_col(working, ["End Time", "EndTime", "End"])
    center_col = find_col(working, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    equipment_col = find_col(working, ["Equipment"])
    unit_col = find_col(working, ["Unit"])
    rows = []
    for idx, row in working.iterrows():
        t1, t2 = row_window(row, start_col, end_col)
        rows.append({"Row": idx + 1, "Equipment": row.get(equipment_col, "") if equipment_col else "", "Unit": row.get(unit_col, "") if unit_col else "", "Center MHz": to_float(row.get(center_col)) if center_col else None, "Raw Start": row.get(start_col, "") if start_col else "", "Raw End": row.get(end_col, "") if end_col else "", "Plotted Start Hour": t1, "Plotted End Hour": t2})
    return pd.DataFrame(rows)

# ============================================================
# Map helpers
# ============================================================

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return [int(hex_color[i:i + 2], 16) for i in (0, 2, 4)]


def radius_to_meters(value, units):
    r = to_float(value, 0.0)
    if r is None or r <= 0:
        return 0.0
    if units == "miles":
        return r * 1609.344
    if units == "kilometers":
        return r * 1000.0
    return r


def build_map_df(df, color_by="Equipment", radius_units="meters", max_rows=300):
    working = active_only(df, show_inactive=st.session_state.get("show_inactive_rows", False))
    lat_col = find_col(working, ["Latitude", "Lat"])
    lon_col = find_col(working, ["Longitude", "Lon", "Long", "Lng"])
    radius_col = find_col(working, ["Coverage Radius", "Radius", "CoverageRadius"])
    center_col = find_col(working, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    start_col = find_col(working, ["Start Time", "StartTime", "Start"])
    end_col = find_col(working, ["End Time", "EndTime", "End"])
    power_col = find_col(working, ["Power (W)", "PowerW", "Power"])
    equipment_col = find_col(working, ["Equipment"])
    unit_col = find_col(working, ["Unit"])
    sponsor_col = find_col(working, ["Sponsor"])
    location_col = find_col(working, ["Location", "Site Name", "Site"])
    color_col = find_col(working, [color_by, "Equipment", "Unit", "Sponsor", "Tech"])
    if lat_col is None or lon_col is None or working.empty:
        return pd.DataFrame()
    rows = []
    for _, row in working.iterrows():
        lat = to_float(row.get(lat_col))
        lon = to_float(row.get(lon_col))
        if lat is None or lon is None:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        t1, t2 = row_window(row, start_col, end_col)
        center = to_float(row.get(center_col)) if center_col else None
        group = label_value(row.get(color_col, "(blank)")) if color_col else "(blank)"
        rgb = hex_to_rgb(stable_color(group))
        radius_m = radius_to_meters(row.get(radius_col), radius_units) if radius_col else 0.0
        power = to_float(row.get(power_col), 1.0) if power_col else 1.0
        rows.append({
            "lat": lat,
            "lon": lon,
            "radius_m": radius_m,
            "point_radius": max(40, min(300, 40 + (power or 0) * 10)),
            "color": rgb + [150],
            "fill_color": rgb + [55],
            "line_color": rgb + [190],
            "Equipment": row.get(equipment_col, "") if equipment_col else "",
            "Unit": row.get(unit_col, "") if unit_col else "",
            "Sponsor": row.get(sponsor_col, "") if sponsor_col else "",
            "Location": row.get(location_col, "") if location_col else "",
            "Frequency": f"{center:.3f} MHz" if center is not None else "",
            "Time": f"{format_time_hhmm(t1)}-{format_time_hhmm(t2)}",
            "Power_W": power,
            "Radius_m": radius_m,
            "Color_By": group,
        })
    out = pd.DataFrame(rows)
    if len(out) > max_rows:
        out = out.head(max_rows).copy()
    return out


def render_radius_map(df, color_by="Equipment", radius_units="meters", max_rows=300, show_radius=True):
    if pdk is None:
        st.error("PyDeck is not available. Add pydeck to requirements.txt to use radius circles.")
        return
    map_df = build_map_df(df, color_by=color_by, radius_units=radius_units, max_rows=max_rows)
    if map_df.empty:
        st.info("No valid Latitude/Longitude rows available for the map.")
        return
    center_lat = float(map_df["lat"].mean())
    center_lon = float(map_df["lon"].mean())
    layers = []
    if show_radius:
        radius_df = map_df[map_df["radius_m"] > 0].copy()
        if not radius_df.empty:
            layers.append(pdk.Layer(
                "ScatterplotLayer",
                data=radius_df,
                get_position="[lon, lat]",
                get_radius="radius_m",
                get_fill_color="fill_color",
                get_line_color="line_color",
                stroked=True,
                filled=True,
                line_width_min_pixels=1,
                radius_min_pixels=2,
                pickable=True,
            ))
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=map_df,
        get_position="[lon, lat]",
        get_radius="point_radius",
        get_fill_color="color",
        get_line_color="[15, 23, 42, 220]",
        stroked=True,
        filled=True,
        radius_min_pixels=5,
        radius_max_pixels=30,
        pickable=True,
    ))
    tooltip = {
        "html": "<b>{Equipment}</b><br/>Unit: {Unit}<br/>Sponsor: {Sponsor}<br/>Location: {Location}<br/>Freq: {Frequency}<br/>Time: {Time}<br/>Power: {Power_W} W<br/>Radius: {Radius_m} m<br/>Group: {Color_By}",
        "style": {"backgroundColor": "#111827", "color": "white"},
    }
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=10, pitch=0),
        tooltip=tooltip,
        map_style="mapbox://styles/mapbox/light-v9",
    )
    st.pydeck_chart(deck, use_container_width=True)
    st.caption(f"Map rows displayed: {len(map_df)}. Radius circles use Coverage Radius in {radius_units}.")

# ============================================================
# App UI
# ============================================================

st.title("Spectrum Planner — V32 Map Radius + Performance")
st.caption("Map radius circles are optional and render only when enabled to reduce lag.")

with st.sidebar:
    st.header("Workbook")
    uploaded = st.file_uploader("Upload allocation workbook or CSV", type=["xlsx", "csv"])
    show_inactive = st.checkbox("Show inactive rows in visuals", value=False, key="show_inactive_rows")
    dark = st.checkbox("Dark visuals", value=False)

    st.divider()
    st.header("Collaborative Projects")
    if not supabase_configured():
        st.caption("Supabase not configured. Local workbook mode is active.")
    else:
        st.caption("Supabase collaboration is configured.")
    if st.button("Refresh Saved Projects", use_container_width=True):
        st.session_state["saved_project_list"] = list_projects()
    project_rows = st.session_state.get("saved_project_list", [])
    project_labels = [f"{r.get('project_name') or r.get('project_id')}  —  {r.get('project_id')}" for r in project_rows]
    selected_project_label = st.selectbox("Saved projects", options=[""] + project_labels, index=0)
    if selected_project_label and project_rows:
        selected_index = project_labels.index(selected_project_label)
        selected_project_id = project_rows[selected_index]["project_id"]
    else:
        selected_project_id = st.session_state.get("active_project_id", "pcc6-working-project")
    project_id_input = st.text_input("Project ID", value=selected_project_id)
    project_name_input = st.text_input("Project name", value=st.session_state.get("active_project_name", "PCC6 Working Project"))
    updated_by_input = st.text_input("Your name/email", value="")
    pc1, pc2 = st.columns(2)
    with pc1:
        if st.button("Load Selected", use_container_width=True):
            ok, msg = load_project(project_id_input)
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()
    with pc2:
        if st.button("Save Project", type="primary", use_container_width=True):
            ok, msg = save_project(project_id_input, project_name_input, updated_by_input)
            (st.success if ok else st.error)(msg)
    duplicate_id = st.text_input("Duplicate as Project ID", value="")
    if st.button("Duplicate Current Project as New Day", use_container_width=True):
        if not duplicate_id.strip():
            st.error("Enter a new Project ID first.")
        else:
            ok, msg = duplicate_project_as(duplicate_id, duplicate_id, updated_by_input)
            (st.success if ok else st.error)(msg)

    st.divider()
    st.header("Planner Mode")
    planner_mode = st.radio("Planner mode", ["Auto deconflict by time", "Auto deconflict by frequency", "Run full smart deconfliction"], index=0)
    st.subheader("Time settings")
    day_start = st.number_input("Operating day start hour", value=6.0, min_value=0.0, max_value=24.0, step=0.25)
    day_end = st.number_input("Operating day end hour", value=20.0, min_value=0.0, max_value=24.0, step=0.25)
    time_step = st.number_input("Time step minutes", value=30, min_value=1, max_value=240, step=5)
    st.subheader("Frequency settings")
    low = st.number_input("Search low MHz", value=2200.0, step=1.0)
    high = st.number_input("Search high MHz", value=2300.0, step=1.0)
    freq_step = st.number_input("Frequency step MHz", value=1.0, min_value=0.001, step=0.5)
    guard = st.number_input("Guard MHz", value=0.0, min_value=0.0, step=0.1, key="guard_mhz")
    max_passes = st.number_input("Max passes", value=5, min_value=1, max_value=20, step=1)

if "sheets" not in st.session_state:
    st.session_state["sheets"] = {}

if uploaded is not None:
    uploaded_bytes = uploaded.getvalue()
    upload_sig = hashlib.md5(uploaded_bytes).hexdigest()
    if st.session_state.get("loaded_upload_sig") != upload_sig:
        buffer = io.BytesIO(uploaded_bytes)
        buffer.name = uploaded.name
        st.session_state["sheets"] = load_file(buffer)
        st.session_state["loaded_upload_sig"] = upload_sig
        st.session_state["analysis_cache"] = {}
        st.session_state["hidden_visual_labels"] = {}
        st.session_state["visual_version"] = st.session_state.get("visual_version", 0) + 1
        st.success(f"Loaded {len(st.session_state['sheets'])} workbook tab(s). Dashboard sheets are intentionally skipped.")

if not st.session_state["sheets"]:
    st.info("Upload a workbook or load a collaborative project to begin.")
    st.stop()

sheet_names = list(st.session_state["sheets"].keys())
active_sheet = st.selectbox("Active sheet for plots/deconfliction", sheet_names)
st.session_state["active_sheet"] = active_sheet
current_df = recalc_start_end_fast(st.session_state["sheets"][active_sheet].copy())

st.subheader("Shared allocation workbook")
st.caption("Use Active to turn rows on/off. Use Locked to prevent Smart Planner from moving that row.")
editor_key = f"editor_{active_sheet}_{st.session_state.get('planner_applied_at', 'base')}_{st.session_state.get('visual_version', 0)}"
edited_df = st.data_editor(current_df, use_container_width=True, hide_index=True, num_rows="dynamic", key=editor_key)
edited_df = normalize_columns(edited_df, add_missing=True)

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("💾 Save edits", type="primary", use_container_width=True):
        update_active_sheet_in_session(active_sheet, edited_df)
        clear_stored_analysis(active_sheet)
        st.success("Edits saved to session.")
with c2:
    xlsx_bytes = dataframe_to_xlsx(st.session_state["sheets"])
    st.download_button("Download workbook XLSX", data=xlsx_bytes, file_name=f"spectrum_planner_workbook_{timestamp_string()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
with c3:
    if st.button("Recalculate Start/End Frequency", use_container_width=True):
        recalculated = recalc_start_end_fast(edited_df)
        update_active_sheet_in_session(active_sheet, recalculated)
        clear_stored_analysis(active_sheet)
        st.success("Start/End Frequency recalculated.")
        st.rerun()

st.subheader("Performance Workflow")
w1, w2, w3, w4 = st.columns(4)
with w1:
    if st.button("1. Save edits", type="primary", use_container_width=True):
        update_active_sheet_in_session(active_sheet, edited_df)
        clear_stored_analysis(active_sheet)
        st.success("Edits saved.")
with w2:
    if st.button("2. Recalculate frequencies", use_container_width=True):
        recalculated = recalc_start_end_fast(edited_df)
        update_active_sheet_in_session(active_sheet, recalculated)
        clear_stored_analysis(active_sheet)
        st.success("Frequencies recalculated.")
        st.rerun()
with w3:
    if st.button("3. Analyze conflicts", use_container_width=True):
        with st.spinner("Analyzing conflicts..."):
            analysis_df = recalc_start_end_fast(st.session_state["sheets"][active_sheet])
            conflict_results = detect_conflicts_fast(analysis_df, guard_mhz=guard)
            store_analysis(active_sheet, conflict_results)
        st.success(f"Conflict analysis complete: {len(conflict_results)} conflicts.")
with w4:
    if st.button("4. Generate visuals", use_container_width=True):
        st.session_state["visual_version"] = st.session_state.get("visual_version", 0) + 1
        st.success("Visuals updated directly from the current workbook sheet.")
        st.rerun()

metric_df = active_only(st.session_state["sheets"][active_sheet], show_inactive=False)
conflict_df = get_stored_analysis(active_sheet)
if conflict_df.empty:
    conflict_df = detect_conflicts_fast(metric_df, guard_mhz=guard)
    store_analysis(active_sheet, conflict_df)

m1, m2, m3 = st.columns(3)
m1.metric("Active rows in visuals", len(metric_df))
m2.metric("Inactive rows hidden", len(st.session_state["sheets"][active_sheet]) - len(metric_df))
m3.metric("Equipment conflicts", len(conflict_df))

if st.sidebar.button("Run Smart Planner", type="primary", use_container_width=True):
    planner_input = recalc_start_end_fast(st.session_state["sheets"][active_sheet])
    if len(planner_input) > MAX_PLANNER_ROWS:
        st.error(f"Planner stopped to prevent freezing: {len(planner_input)} rows loaded. Reduce below {MAX_PLANNER_ROWS} rows or run one band/sheet at a time.")
        st.stop()
    starting_conflicts = len(detect_conflicts_fast(planner_input, guard_mhz=guard))
    with st.spinner("Running Smart Planner..."):
        if planner_mode == "Auto deconflict by time":
            new_df, moves = smart_time_deconflict(planner_input, day_start=day_start, day_end=day_end, step_minutes=int(time_step), guard_mhz=guard, max_passes=int(max_passes))
        elif planner_mode == "Auto deconflict by frequency":
            new_df, moves = smart_frequency_deconflict(planner_input, low_mhz=low, high_mhz=high, step_mhz=freq_step, guard_mhz=guard, max_passes=int(max_passes))
        else:
            time_df, time_moves = smart_time_deconflict(planner_input, day_start=day_start, day_end=day_end, step_minutes=int(time_step), guard_mhz=guard, max_passes=int(max_passes))
            new_df, freq_moves = smart_frequency_deconflict(time_df, low_mhz=low, high_mhz=high, step_mhz=freq_step, guard_mhz=guard, max_passes=int(max_passes))
            moves = pd.concat([time_moves, freq_moves], ignore_index=True)
    final_conflicts = len(detect_conflicts_fast(new_df, guard_mhz=guard))
    summary = pd.DataFrame([{"Planner Mode": planner_mode, "Starting Conflicts": starting_conflicts, "Final Conflicts": final_conflicts, "Move Rows": len(moves)}])
    st.session_state["pending_planner_df"] = new_df.copy()
    st.session_state["pending_planner_moves"] = moves.copy()
    st.session_state["pending_planner_summary"] = summary.copy()
    st.success("Planner complete. Review results below, preview the visual, then click Apply Planner Results.")

if "pending_planner_summary" in st.session_state:
    st.subheader("Smart Planner Results")
    st.dataframe(st.session_state["pending_planner_summary"], use_container_width=True, hide_index=True)
    moves = st.session_state.get("pending_planner_moves", pd.DataFrame())
    if moves is not None and not moves.empty:
        st.markdown("**Proposed Moves**")
        st.dataframe(moves, use_container_width=True, hide_index=True)
    else:
        st.warning("Planner did not find movable rows.")
    with st.expander("Preview Planner Visual Before Apply", expanded=True):
        preview_df = st.session_state.get("pending_planner_df")
        if preview_df is not None:
            preview_fig, _, preview_rows = time_frequency_chart(preview_df, color_by="Equipment", dark=dark, sheet_name=None, title="Preview: Smart Planner Result", label_preview=True, label_mode="Auto")
            st.pyplot(preview_fig, use_container_width=True)
            st.caption(f"Previewing {preview_rows} planned row(s).")
    a1, a2 = st.columns(2)
    with a1:
        if st.button("✅ Apply Planner Results", type="primary", use_container_width=True):
            ok, msg = apply_planner_results_to_active_sheet(active_sheet)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
    with a2:
        if st.button("Discard Planner Results", use_container_width=True):
            st.session_state.pop("pending_planner_df", None)
            st.session_state.pop("pending_planner_moves", None)
            st.session_state.pop("pending_planner_summary", None)
            st.info("Planner results discarded.")
            st.rerun()

visual_df = recalc_start_end_fast(st.session_state["sheets"][active_sheet].copy())

st.divider()
st.subheader("Frequency Label Controls")
st.caption("Hide/show only the MHz label inside each box. The colored bars stay visible.")
frequency_options = visual_frequency_options(visual_df)
hidden_now = get_hidden_label_frequencies(active_sheet)
visible_options = [f for f in frequency_options if f not in hidden_now]
hidden_options = [f for f in frequency_options if f in hidden_now]
fc1, fc2 = st.columns(2)
with fc1:
    st.markdown("**Frequency labels currently showing inside boxes**")
    selected_hide = []
    with st.container(border=True):
        for label in visible_options:
            if st.checkbox(label, value=False, key=f"hide_{active_sheet}_{label}_{st.session_state.get('visual_version', 0)}"):
                selected_hide.append(label)
    if st.button("➖ Hide selected MHz labels inside boxes", use_container_width=True):
        set_hidden_label_frequencies(active_sheet, list(hidden_now.union(selected_hide)))
        st.success(f"Hid {len(selected_hide)} selected MHz label(s). Bars stay visible.")
        st.rerun()
with fc2:
    st.markdown("**Frequency labels currently hidden inside boxes**")
    selected_show = []
    with st.container(border=True):
        for label in hidden_options:
            if st.checkbox(label, value=False, key=f"show_{active_sheet}_{label}_{st.session_state.get('visual_version', 0)}"):
                selected_show.append(label)
    sc1, sc2 = st.columns(2)
    with sc1:
        if st.button("➕ Show selected labels", use_container_width=True):
            set_hidden_label_frequencies(active_sheet, list(hidden_now.difference(selected_show)))
            st.success(f"Showed {len(selected_show)} selected MHz label(s).")
            st.rerun()
    with sc2:
        if st.button("♻️ Show all labels", use_container_width=True):
            set_hidden_label_frequencies(active_sheet, [])
            st.success("All MHz labels are visible again.")
            st.rerun()

st.divider()
with st.expander("Extract / Export Visuals", expanded=True):
    st.subheader("Draw order, transparency, label orientation, and map")
    ec1, ec2, ec3, ec4 = st.columns(4)
    with ec1:
        draw_order = st.selectbox("Draw order", ["High power in back", "Low power in back", "Workbook row order"], index=0)
    with ec2:
        high_power_alpha = st.slider("High-power background transparency", 0.05, 1.0, 0.95, 0.05)
    with ec3:
        low_power_alpha = st.slider("Low-power foreground transparency", 0.05, 1.0, 0.95, 0.05)
    with ec4:
        label_mode = st.selectbox("MHz label orientation", ["Auto", "Horizontal", "Vertical", "Staggered"], index=0)

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["Time × Frequency", "Power View", "Equipment Deconfliction", "Unit Deconfliction", "Sponsor Deconfliction", "Conflict Tables", "Time Debug"])
    with tab1:
        color_by = st.selectbox("Color boxes by", ["Equipment", "Tech", "Unit", "Sponsor", "Tech Category"], index=0)
        fig, plot_df, rows_drawn = time_frequency_chart(visual_df, color_by=color_by, dark=dark, sheet_name=active_sheet, draw_order=draw_order, high_power_alpha=high_power_alpha, low_power_alpha=low_power_alpha, label_mode=label_mode)
        st.pyplot(fig, use_container_width=True)
        png = fig_to_png_bytes(fig)
        st.download_button("Download this visual PNG", data=png, file_name=f"time_frequency_{timestamp_string()}.png", mime="image/png", use_container_width=True)
        if st.button("Save this PNG to project", use_container_width=True):
            st.session_state.setdefault("saved_png_exports", {})[f"time_frequency_{active_sheet}.png"] = base64.b64encode(png).decode("utf-8")
            st.success("PNG saved in project memory. Click Save Project to persist it to Supabase.")

        st.divider()
        st.subheader("Map View under current visual")
        st.caption("Map rendering can lag because every Streamlit click reruns the script and redraws map tiles/layers. Keep the map disabled until needed, cap map rows, and use radius circles only when needed.")
        map_enabled = st.checkbox("Enable map rendering", value=False, key=f"map_enabled_{active_sheet}")
        if map_enabled:
            mc1, mc2, mc3, mc4 = st.columns(4)
            with mc1:
                map_color_by = st.selectbox("Map color by", ["Equipment", "Unit", "Sponsor", "Tech", "Tech Category"], index=0)
            with mc2:
                radius_units = st.selectbox("Coverage Radius units", ["meters", "kilometers", "miles"], index=0)
            with mc3:
                show_radius = st.checkbox("Show radius circles", value=True)
            with mc4:
                max_map_rows = st.number_input("Max map rows", value=DEFAULT_MAX_MAP_ROWS, min_value=25, max_value=2000, step=25)
            render_radius_map(visual_df, color_by=map_color_by, radius_units=radius_units, max_rows=int(max_map_rows), show_radius=show_radius)
        else:
            st.info("Map is disabled for performance. Enable it when you need to view locations/radius.")
    with tab2:
        pfig, _ = power_chart(visual_df, color_by="Equipment", dark=dark, sheet_name=active_sheet, draw_order=draw_order, high_power_alpha=high_power_alpha, low_power_alpha=low_power_alpha, label_mode=label_mode)
        st.pyplot(pfig, use_container_width=True)
        st.download_button("Download this visual PNG", data=fig_to_png_bytes(pfig), file_name=f"power_view_{timestamp_string()}.png", mime="image/png", use_container_width=True)
    with tab3:
        fig, _, _ = time_frequency_chart(visual_df, color_by="Equipment", dark=dark, title="Equipment Deconfliction", sheet_name=active_sheet, draw_order=draw_order, high_power_alpha=high_power_alpha, low_power_alpha=low_power_alpha, label_mode=label_mode)
        st.pyplot(fig, use_container_width=True)
        st.download_button("Download this visual PNG", data=fig_to_png_bytes(fig), file_name=f"equipment_deconfliction_{timestamp_string()}.png", mime="image/png", use_container_width=True)
    with tab4:
        fig, _, _ = time_frequency_chart(visual_df, color_by="Unit", dark=dark, title="Unit Deconfliction", sheet_name=active_sheet, draw_order=draw_order, high_power_alpha=high_power_alpha, low_power_alpha=low_power_alpha, label_mode=label_mode)
        st.pyplot(fig, use_container_width=True)
        st.download_button("Download this visual PNG", data=fig_to_png_bytes(fig), file_name=f"unit_deconfliction_{timestamp_string()}.png", mime="image/png", use_container_width=True)
    with tab5:
        fig, _, _ = time_frequency_chart(visual_df, color_by="Sponsor", dark=dark, title="Sponsor Deconfliction", sheet_name=active_sheet, draw_order=draw_order, high_power_alpha=high_power_alpha, low_power_alpha=low_power_alpha, label_mode=label_mode)
        st.pyplot(fig, use_container_width=True)
        st.download_button("Download this visual PNG", data=fig_to_png_bytes(fig), file_name=f"sponsor_deconfliction_{timestamp_string()}.png", mime="image/png", use_container_width=True)
    with tab6:
        latest_conflicts = detect_conflicts_fast(visual_df, guard_mhz=guard)
        store_analysis(active_sheet, latest_conflicts)
        st.warning(f"{len(latest_conflicts)} active conflicts detected.")
        st.dataframe(latest_conflicts, use_container_width=True, hide_index=True)
        st.download_button("Download conflicts CSV", data=latest_conflicts.to_csv(index=False).encode("utf-8"), file_name=f"conflicts_{timestamp_string()}.csv", mime="text/csv", use_container_width=True)
    with tab7:
        debug_df = time_debug_table(visual_df)
        st.dataframe(debug_df, use_container_width=True, hide_index=True)
        st.download_button("Download time debug CSV", data=debug_df.to_csv(index=False).encode("utf-8"), file_name=f"time_debug_{timestamp_string()}.csv", mime="text/csv", use_container_width=True)

    if st.session_state.get("saved_png_exports"):
        st.subheader("Saved PNGs in project memory")
        for name, b64 in st.session_state["saved_png_exports"].items():
            st.download_button(f"Download saved {name}", data=base64.b64decode(b64.encode("utf-8")), file_name=name, mime="image/png", use_container_width=True)

st.caption("V32 note: map lag is reduced by making PyDeck optional, limiting displayed map rows, and rendering radius circles only when enabled.")
