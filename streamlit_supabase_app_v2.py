import io
import re
import math
import base64
import hashlib
import json
from datetime import datetime, date, time

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle

# Optional Plotly support for interactive tactical map
try:
    import plotly.express as px
    import plotly.graph_objects as go
except Exception:
    px = None
    go = None

# Optional PyDeck support
try:
    import pydeck as pdk
except Exception:
    pdk = None

# Optional Supabase support
try:
    from supabase import create_client
except Exception:
    create_client = None

st.set_page_config(page_title="Spectrum Planner V33 Better Map Views", layout="wide")

# ============================================================
# Spectrum Planner V34 — Tactical Ops Map + Offline Radius Map
# ============================================================
# Adds:
# - Offline Radius Map default: no internet tiles / no Mapbox required.
# - Plotly Coordinate Map option for interactive tile-free viewing.
# - PyDeck Map option with No Basemap / Carto light / Carto dark.
# - Radius circles using Coverage Radius.
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
    "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9",
    "#F0E442", "#000000", "#7E57C2", "#00838F", "#C62828", "#558B2F",
    "#6D4C41", "#AD1457", "#1565C0", "#EF6C00", "#2E7D32", "#5D4037",
    "#4527A0", "#0277BD", "#9E9D24", "#B71C1C", "#00695C", "#8E24AA",
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
    """Return a JSON-safe value: no NaN, Infinity, pandas NA, numpy scalars, or Excel time objects."""
    if x is None:
        return None

    # pandas / numpy NA
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass

    # numpy scalar to native Python
    try:
        if isinstance(x, np.generic):
            x = x.item()
    except Exception:
        pass

    # float guard
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        return float(x)

    # native safe primitives
    if isinstance(x, (str, bool, int)):
        return x

    # dates/times
    if isinstance(x, (pd.Timestamp, datetime, date, time)):
        return x.isoformat()

    # recursively clean containers
    if isinstance(x, dict):
        return {str(k): to_json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [to_json_safe(v) for v in x]

    # objects with isoformat
    if hasattr(x, "isoformat"):
        try:
            return x.isoformat()
        except Exception:
            pass

    # last resort
    try:
        return str(x)
    except Exception:
        return None

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



def dataframe_json_records(df):
    """Convert a DataFrame into strict JSON-safe records for Supabase."""
    if df is None:
        return []

    clean = df.copy()
    clean.columns = [str(c) for c in clean.columns]

    records = []
    for _, row in clean.iterrows():
        rec = {}
        for col in clean.columns:
            rec[str(col)] = to_json_safe(row.get(col))
        records.append(rec)

    # Validate: this fails if NaN/Infinity survives.
    json.dumps(records, allow_nan=False)
    return records


def workbook_to_jsonable(sheets):
    """Convert the entire workbook into strict JSON-safe Supabase payload."""
    payload = {}

    for name, df in sheets.items():
        clean = recalc_start_end_fast(df).copy()
        clean.columns = [str(c) for c in clean.columns]

        sheet_payload = {
            "columns": [str(c) for c in clean.columns],
            "records": dataframe_json_records(clean),
        }

        json.dumps(sheet_payload, allow_nan=False)
        payload[str(name)] = sheet_payload

    json.dumps(payload, allow_nan=False)
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

    try:
        row = {
            "project_id": str(project_id).strip(),
            "project_name": str(project_name).strip() or str(project_id).strip(),
            "workbook": workbook_to_jsonable(st.session_state["sheets"]),
            "png_exports": to_json_safe(st.session_state.get("saved_png_exports", {})),
            "updated_by": str(updated_by).strip() or "unknown",
            "updated_at": datetime.utcnow().isoformat(),
        }

        # Final validation before Supabase call.
        json.dumps(row, allow_nan=False)

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



def delete_project(project_id):
    client = get_supabase_client()
    if client is None:
        return False, "Supabase is not configured."
    if not str(project_id).strip():
        return False, "No Project ID selected."

    try:
        client.table("spectrum_projects").delete().eq("project_id", str(project_id).strip()).execute()

        if st.session_state.get("active_project_id") == str(project_id).strip():
            st.session_state.pop("active_project_id", None)
            st.session_state.pop("active_project_name", None)

        return True, f"Deleted project '{project_id}'."
    except Exception as exc:
        return False, f"Delete failed: {exc}"


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
    saved = recalc_start_end_fast(enforce_decimal_numeric_columns(df)).copy()
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
    palette_name = st.session_state.get("palette_name_v48", "Colorblind Distinct")
    return build_color_map_v48(df, color_by, palette_name=palette_name)

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
        ax.add_patch(Rectangle((center - bw / 2.0, start_time), bw, end_time - start_time, facecolor=color, edgecolor="#0F172A", linewidth=st.session_state.get("bar_outline_width_v48", 1.1), alpha=alpha))
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
        ax.add_patch(Rectangle((center - bw / 2.0, 0), bw, power, facecolor=color, edgecolor="#0F172A", linewidth=st.session_state.get("bar_outline_width_v48", 1.1), alpha=alpha))
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
    hex_color = str(hex_color).lstrip("#")
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


def radius_to_degrees_lat(radius_meters):
    return radius_meters / 111320.0


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
    tech_col = find_col(working, ["Tech"])
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
        color_hex = stable_color(group)
        rgb = hex_to_rgb(color_hex)
        radius_raw = row.get(radius_col) if radius_col else 0
        radius_m = radius_to_meters(radius_raw, radius_units) if radius_col else 0.0
        power = to_float(row.get(power_col), 1.0) if power_col else 1.0
        rows.append({
            "lat": lat,
            "lon": lon,
            "Latitude": lat,
            "Longitude": lon,
            "radius_m": radius_m,
            "radius_raw": radius_raw,
            "point_radius": max(40, min(300, 40 + (power or 0) * 10)),
            "marker_size": max(8, min(28, 8 + (power or 1) * 1.5)),
            "color_hex": color_hex,
            "color": rgb + [150],
            "fill_color": rgb + [55],
            "line_color": rgb + [190],
            "Equipment": row.get(equipment_col, "") if equipment_col else "",
            "Unit": row.get(unit_col, "") if unit_col else "",
            "Sponsor": row.get(sponsor_col, "") if sponsor_col else "",
            "Tech": row.get(tech_col, "") if tech_col else "",
            "Location": row.get(location_col, "") if location_col else "",
            "Frequency": f"{center:.3f} MHz" if center is not None else "",
            "Center MHz": center,
            "Time": f"{format_time_hhmm(t1)}-{format_time_hhmm(t2)}",
            "Power_W": power,
            "Radius_m": radius_m,
            "Radius": radius_raw,
            "Radius Units": radius_units,
            "Color_By": group,
        })
    out = pd.DataFrame(rows)
    if len(out) > max_rows:
        out = out.head(max_rows).copy()
    return out


def render_offline_radius_map(df, color_by="Equipment", radius_units="meters", max_rows=300, show_radius=True):
    map_df = build_map_df(df, color_by=color_by, radius_units=radius_units, max_rows=max_rows)
    fig, ax = plt.subplots(figsize=(14, 8))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#F8FAFC")
    if map_df.empty:
        ax.text(0.5, 0.5, "No valid Latitude/Longitude rows available for the map.", ha="center", va="center")
        ax.axis("off")
        st.pyplot(fig, use_container_width=True)
        return map_df, fig

    min_lat, max_lat = map_df["lat"].min(), map_df["lat"].max()
    min_lon, max_lon = map_df["lon"].min(), map_df["lon"].max()
    lat_span = max(max_lat - min_lat, 0.01)
    lon_span = max(max_lon - min_lon, 0.01)

    for _, row in map_df.iterrows():
        lat = row["lat"]
        lon = row["lon"]
        color = row["color_hex"]
        radius_m = row.get("radius_m", 0.0)
        if show_radius and radius_m and radius_m > 0:
            r_lat = radius_to_degrees_lat(radius_m)
            denom = 111320.0 * max(math.cos(math.radians(lat)), 0.15)
            r_lon = radius_m / denom
            r = max(r_lat, r_lon)
            ax.add_patch(Circle((lon, lat), radius=r, facecolor=color, edgecolor=color, linewidth=1.2, alpha=0.16))
        size = 40 + min(max(to_float(row.get("Power_W"), 1.0), 1.0), 50.0) * 3
        ax.scatter(lon, lat, s=size, c=color, edgecolors="black", linewidths=0.6, alpha=0.90, zorder=5)
        label = row.get("Equipment") or row.get("Unit") or ""
        if label:
            ax.text(lon, lat, str(label)[:18], fontsize=8, ha="left", va="bottom", zorder=6)

    pad_lat = max(lat_span * 0.25, 0.01)
    pad_lon = max(lon_span * 0.25, 0.01)
    ax.set_xlim(min_lon - pad_lon, max_lon + pad_lon)
    ax.set_ylim(min_lat - pad_lat, max_lat + pad_lat)
    ax.set_title("Offline Radius Map — Latitude / Longitude", fontsize=14, fontweight="bold")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, alpha=0.35)
    fig.tight_layout()
    st.pyplot(fig, use_container_width=True)
    st.caption(f"Map rows displayed: {len(map_df)}. Offline map does not use external map tiles.")
    return map_df, fig


def render_plotly_coordinate_map(df, color_by="Equipment", radius_units="meters", max_rows=300, show_radius=True):
    if px is None:
        st.warning("Plotly is not installed. Use Offline Radius Map instead.")
        return pd.DataFrame()
    map_df = build_map_df(df, color_by=color_by, radius_units=radius_units, max_rows=max_rows)
    if map_df.empty:
        st.info("No valid Latitude/Longitude rows available for the map.")
        return map_df
    hover = ["Equipment", "Unit", "Sponsor", "Tech", "Frequency", "Time", "Power_W", "Radius", "Radius Units"]
    fig = px.scatter_geo(
        map_df,
        lat="lat",
        lon="lon",
        color="Color_By",
        size="marker_size",
        hover_data=hover,
        projection="equirectangular",
        title="Plotly Coordinate Map",
    )
    fig.update_geos(
        fitbounds="locations",
        visible=True,
        showland=True,
        landcolor="rgb(245,245,245)",
        showcountries=True,
        countrycolor="rgb(180,180,180)",
        showsubunits=True,
        subunitcolor="rgb(200,200,200)",
    )
    fig.update_layout(height=650, margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(fig, use_container_width=True)
    if show_radius:
        st.caption("Plotly Coordinate Map uses marker size as a lightweight radius approximation. Use Offline Radius Map for drawn radius circles.")
    return map_df


def render_pydeck_map(df, color_by="Equipment", radius_units="meters", max_rows=300, show_radius=True, map_style_mode="No basemap"):
    if pdk is None:
        st.error("PyDeck is not available. Add pydeck to requirements.txt to use this map.")
        return pd.DataFrame()
    map_df = build_map_df(df, color_by=color_by, radius_units=radius_units, max_rows=max_rows)
    if map_df.empty:
        st.info("No valid Latitude/Longitude rows available for the map.")
        return map_df
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
        "html": "<b>{Equipment}</b><br/>Unit: {Unit}<br/>Sponsor: {Sponsor}<br/>Location: {Location}<br/>Freq: {Frequency}<br/>Time: {Time}<br/>Power: {Power_W} W<br/>Radius: {Radius} {Radius Units}<br/>Group: {Color_By}",
        "style": {"backgroundColor": "#111827", "color": "white"},
    }
    if map_style_mode == "Carto light":
        map_style = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
    elif map_style_mode == "Carto dark":
        map_style = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
    else:
        map_style = None
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=10, pitch=0),
        tooltip=tooltip,
        map_style=map_style,
    )
    st.pydeck_chart(deck, use_container_width=True)
    st.caption(f"Map rows displayed: {len(map_df)}. Use No basemap if your network blocks map tiles.")
    return map_df


# ============================================================
# V38 Plotly Import Fix
# ============================================================

def band_label(center_mhz):
    f = to_float(center_mhz)
    if f is None:
        return "Unknown"
    if f < 300:
        return "VHF"
    if f < 1000:
        return "UHF"
    if 1000 <= f < 2000:
        return "L-Band"
    if 2000 <= f < 4000:
        return "S-Band"
    if 4000 <= f < 8000:
        return "C-Band"
    return "High Band"


def band_color(center_mhz):
    colors = {
        "VHF": "#2563EB",
        "UHF": "#16A34A",
        "L-Band": "#F59E0B",
        "S-Band": "#DC2626",
        "C-Band": "#7C3AED",
        "High Band": "#0891B2",
        "Unknown": "#64748B",
    }
    return colors.get(band_label(center_mhz), "#64748B")


def tactical_marker(unit, equipment):
    text = f"{unit} {equipment}".upper()
    if any(k in text for k in ["UAS", "DRONE", "RQ", "VBAT"]):
        return "^"
    if any(k in text for k in ["TRILOS", "GDLT", "LINK", "RELAY"]):
        return "s"
    if any(k in text for k in ["MPU", "PRC", "RADIO"]):
        return "o"
    return "D"


def build_time_filtered_df(df, selected_hour=None, show_all_hours=True):
    if show_all_hours or selected_hour is None:
        return df
    working = recalc_start_end_fast(df).copy()
    start_col = find_col(working, ["Start Time", "StartTime", "Start"])
    end_col = find_col(working, ["End Time", "EndTime", "End"])
    keep = []
    for _, row in working.iterrows():
        t1, t2 = row_window(row, start_col, end_col)
        keep.append(t1 <= selected_hour < t2)
    return working[pd.Series(keep, index=working.index)].copy()


def circles_overlap_v35(row_a, row_b):
    lat1, lon1, r1 = row_a["lat"], row_a["lon"], to_float(row_a.get("radius_m"), 0.0)
    lat2, lon2, r2 = row_b["lat"], row_b["lon"], to_float(row_b.get("radius_m"), 0.0)
    if r1 <= 0 or r2 <= 0:
        return False
    mean_lat = math.radians((lat1 + lat2) / 2.0)
    dx = (lon2 - lon1) * 111320.0 * math.cos(mean_lat)
    dy = (lat2 - lat1) * 111320.0
    dist = math.sqrt(dx * dx + dy * dy)
    return dist <= (r1 + r2)


def make_map_df_v35(df, color_by="Equipment", radius_units="meters", max_rows=300, selected_hour=None, show_all_hours=True):
    filtered = build_time_filtered_df(df, selected_hour=selected_hour, show_all_hours=show_all_hours)
    out = build_map_df(filtered, color_by=color_by, radius_units=radius_units, max_rows=max_rows)
    if not out.empty:
        out["Band"] = out["Center MHz"].apply(band_label)
        out["Band_Color"] = out["Center MHz"].apply(band_color)
    return out


def tactical_ops_map_v35(
    map_df,
    map_layer="Offline Grid",
    show_radius=True,
    show_labels=True,
    show_unit_icons=True,
    color_mode="Frequency Band",
    show_overlap_warning=True,
    show_congestion_heat=True,
    show_grid=True,
    selected_hour=None,
    show_all_hours=True,
    map_theme="Light",
):
    dark = map_theme == "Dark"
    fig, ax = plt.subplots(figsize=(15, 9))
    fig.patch.set_facecolor("#0B1120" if dark else "white")
    ax.set_facecolor("#111827" if dark else "#F8FAFC")

    if map_df.empty:
        ax.text(0.5, 0.5, "No valid Latitude/Longitude rows available for the tactical map.", ha="center", va="center", color="white" if dark else "black")
        ax.axis("off")
        return fig

    working = map_df.copy()
    if "Band" not in working.columns:
        working["Band"] = working["Center MHz"].apply(band_label)

    min_lat, max_lat = working["lat"].min(), working["lat"].max()
    min_lon, max_lon = working["lon"].min(), working["lon"].max()
    lat_span = max(max_lat - min_lat, 0.01)
    lon_span = max(max_lon - min_lon, 0.01)

    # Offline map layer appearance. Street/Satellite/Topo are fallback renderings that do not need internet tiles.
    layer_note = ""
    if map_layer == "Offline Grid":
        ax.set_facecolor("#0F172A" if dark else "#F8FAFC")
        layer_note = "Offline grid; no external tiles."
    elif map_layer == "Street Map":
        ax.set_facecolor("#E0F2FE" if not dark else "#172554")
        layer_note = "Street-map style fallback; true street tiles require external access."
        ax.text(0.5, 0.96, "STREET MAP MODE — OFFLINE FALLBACK", transform=ax.transAxes, ha="center", fontsize=9, alpha=0.70, color="white" if dark else "#111827")
    elif map_layer == "Satellite":
        ax.set_facecolor("#1F2937")
        layer_note = "Satellite-style fallback; true imagery requires external access."
        ax.text(0.5, 0.96, "SATELLITE MODE — OFFLINE FALLBACK", transform=ax.transAxes, ha="center", fontsize=9, alpha=0.80, color="white")
    elif map_layer == "Military Topographic":
        ax.set_facecolor("#ECFCCB" if not dark else "#1A2E05")
        layer_note = "Topo-style fallback; true elevation requires DEM/DTED."
        for i in range(8):
            y = min_lat - lat_span * 0.25 + (i + 1) * (lat_span * 1.5 / 9)
            ax.plot([min_lon - lon_span, max_lon + lon_span], [y, y + 0.04 * lat_span * math.sin(i)], color="#64748B", alpha=0.28, linewidth=0.9, zorder=0)
        ax.text(0.5, 0.96, "MILITARY TOPO MODE — OFFLINE FALLBACK", transform=ax.transAxes, ha="center", fontsize=9, alpha=0.80, color="white" if dark else "#111827")

    if show_congestion_heat and len(working) >= 2:
        try:
            ax.hexbin(working["lon"], working["lat"], gridsize=18, cmap="Reds", alpha=0.25 if not dark else 0.36, mincnt=1, zorder=1)
        except Exception:
            pass

    overlap_count = 0
    if show_overlap_warning and show_radius:
        rows = list(working.to_dict(orient="records"))
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                ca = to_float(rows[i].get("Center MHz"))
                cb = to_float(rows[j].get("Center MHz"))
                freq_close = ca is not None and cb is not None and abs(ca - cb) <= 10.0
                if freq_close and circles_overlap_v35(rows[i], rows[j]):
                    overlap_count += 1
                    if overlap_count <= 300:
                        ax.plot([rows[i]["lon"], rows[j]["lon"]], [rows[i]["lat"], rows[j]["lat"]], color="#DC2626", linewidth=1.25, alpha=0.55, zorder=2)

    for _, row in working.iterrows():
        lat = row["lat"]
        lon = row["lon"]
        radius_m = to_float(row.get("radius_m"), 0.0)

        if color_mode == "Frequency Band":
            color = band_color(row.get("Center MHz"))
        elif color_mode == "Unit":
            color = stable_color(row.get("Unit", ""))
        elif color_mode == "Sponsor":
            color = stable_color(row.get("Sponsor", ""))
        elif color_mode == "Tech":
            color = stable_color(row.get("Tech", ""))
        else:
            color = row.get("color_hex", stable_color(row.get("Equipment", "")))

        if show_radius and radius_m > 0:
            r_lat = radius_to_degrees_lat(radius_m)
            denom = 111320.0 * max(math.cos(math.radians(lat)), 0.15)
            r_lon = radius_m / denom
            r = max(r_lat, r_lon)
            ax.add_patch(Circle((lon, lat), radius=r, facecolor=color, edgecolor=color, linewidth=1.0, alpha=0.14 if not dark else 0.22, zorder=3))

        marker = tactical_marker(row.get("Unit", ""), row.get("Equipment", "")) if show_unit_icons else "o"
        power = max(to_float(row.get("Power_W"), 1.0), 1.0)
        size = 70 + min(power, 50) * 3.5

        ax.scatter(lon, lat, s=size, marker=marker, c=color, edgecolors="black" if not dark else "white", linewidths=0.85, alpha=0.96, zorder=5)

        if show_labels:
            equip = str(row.get("Equipment", ""))[:16]
            unit = str(row.get("Unit", ""))[:10]
            freq = row.get("Center MHz")
            band = band_label(freq)
            freq_txt = f"{freq:.1f}" if isinstance(freq, (int, float)) and not math.isnan(freq) else ""
            label = f"{unit}\n{equip}\n{freq_txt} MHz {band}".strip()
            ax.text(lon, lat, label, fontsize=7, ha="left", va="bottom", color="white" if dark else "#111827", bbox=dict(boxstyle="round,pad=0.18", facecolor="#111827" if not dark else "#020617", edgecolor="none", alpha=0.60), zorder=6)

    pad_lat = max(lat_span * 0.25, 0.01)
    pad_lon = max(lon_span * 0.25, 0.01)
    ax.set_xlim(min_lon - pad_lon, max_lon + pad_lon)
    ax.set_ylim(min_lat - pad_lat, max_lat + pad_lat)

    if show_grid:
        ax.grid(True, alpha=0.35 if not dark else 0.22, linestyle="--")
    else:
        ax.grid(False)

    time_note = "All hours" if show_all_hours else f"{selected_hour:0.2f} hour"
    ax.set_title(f"V35 Tactical Map — {map_layer} — {time_note}", fontsize=15, fontweight="bold", color="white" if dark else "black")
    ax.set_xlabel("Longitude", color="white" if dark else "black")
    ax.set_ylabel("Latitude", color="white" if dark else "black")
    ax.tick_params(colors="white" if dark else "black")

    band_list = ", ".join(sorted(working["Band"].dropna().unique()))
    summary_text = (
        f"Rows: {len(working)} | Bands: {band_list}\n"
        f"Overlap warning links: {overlap_count} | Layer: {layer_note}\n"
        "Markers: ○ Radio / △ UAS / □ Link-Relay / ◆ Other"
    )
    ax.text(0.01, 0.01, summary_text, transform=ax.transAxes, fontsize=8, color="white" if dark else "#111827", bbox=dict(boxstyle="round,pad=0.25", facecolor="#020617" if dark else "white", edgecolor="#64748B", alpha=0.80), zorder=10)

    ax.text(0.99, 0.01, "LOS/Terrain: requires DEM/DTED\nControls included; true LOS is future upgrade", transform=ax.transAxes, fontsize=8, ha="right", va="bottom", color="white" if dark else "#111827", bbox=dict(boxstyle="round,pad=0.25", facecolor="#7F1D1D" if dark else "#FEE2E2", edgecolor="#DC2626", alpha=0.72), zorder=10)

    fig.tight_layout()
    return fig


def build_animation_frames_pngs(source_df, hours, map_options):
    exports = {}
    for hour in hours:
        frame_map_df = make_map_df_v35(
            source_df,
            color_by=map_options["map_color_by"],
            radius_units=map_options["radius_units"],
            max_rows=map_options["max_map_rows"],
            selected_hour=hour,
            show_all_hours=False,
        )
        fig = tactical_ops_map_v35(
            frame_map_df,
            map_layer=map_options["map_layer"],
            show_radius=map_options["show_radius"],
            show_labels=map_options["show_labels"],
            show_unit_icons=map_options["show_unit_icons"],
            color_mode=map_options["color_mode"],
            show_overlap_warning=map_options["show_overlap_warning"],
            show_congestion_heat=map_options["show_congestion_heat"],
            show_grid=map_options["show_grid"],
            selected_hour=hour,
            show_all_hours=False,
            map_theme=map_options["map_theme"],
        )
        exports[f"tactical_map_hour_{hour:04.1f}.png"] = base64.b64encode(fig_to_png_bytes(fig)).decode("utf-8")
        plt.close(fig)
    return exports



# ============================================================
# V38 Interactive Tactical LOS Map
# ============================================================

def los_group_value(row, match_by):
    if match_by == "Equipment":
        return label_value(row.get("Equipment", ""))
    if match_by == "Tech":
        return label_value(row.get("Tech", ""))
    if match_by == "Unit":
        return label_value(row.get("Unit", ""))
    if match_by == "Frequency Band":
        return band_label(row.get("Center MHz"))
    return label_value(row.get("Equipment", ""))


def selectable_system_label(row):
    equip = label_value(row.get("Equipment", ""))
    unit = label_value(row.get("Unit", ""))
    tech = label_value(row.get("Tech", ""))
    freq = row.get("Center MHz")
    freq_txt = f"{freq:.3f} MHz" if isinstance(freq, (int, float)) and not math.isnan(freq) else "No Freq"
    return f"{unit} | {equip} | {tech} | {freq_txt} | {row.get('lat'):.5f},{row.get('lon'):.5f}"


def build_los_pairs(map_df, match_by="Equipment", selected_labels=None, max_pairs=300):
    """Build LOS/link pairs only from user-selected systems and only between like systems.

    Important behavior:
    - No selected systems = no LOS/link lines.
    - One selected system = no LOS/link lines.
    - Two or more selected systems = draw only between selected systems that match by Equipment/Tech/Unit/Frequency Band.
    - This is a planning/link candidate line, not terrain-blocked LOS. True terrain LOS requires DEM/DTED.
    """
    if map_df.empty:
        return []

    if not selected_labels or len(selected_labels) < 2:
        return []

    working = map_df.copy()
    working["_system_label"] = working.apply(selectable_system_label, axis=1)
    working["_los_group"] = working.apply(lambda r: los_group_value(r, match_by), axis=1)
    working = working[working["_system_label"].isin(selected_labels)].copy()

    if len(working) < 2:
        return []

    rows = working.to_dict(orient="records")
    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if rows[i].get("_los_group") != rows[j].get("_los_group"):
                continue
            pairs.append((rows[i], rows[j]))
            if len(pairs) >= max_pairs:
                return pairs
    return pairs


def plotly_interactive_tactical_map_v38(
    map_df,
    map_layer="Offline Grid",
    show_radius=True,
    show_labels=True,
    color_mode="Frequency Band",
    show_overlap_warning=True,
    show_congestion_heat=True,
    selected_hour=None,
    show_all_hours=True,
    los_enabled=False,
    los_match_by="Equipment",
    selected_los_labels=None,
):
    plotly_go = globals().get("go", None)
    if plotly_go is None:
        st.warning("Plotly is not installed or did not import. Add plotly to requirements.txt, or use Tactical Offline Ops Map.")
        return None

    if map_df.empty:
        st.info("No valid Latitude/Longitude rows available for the interactive tactical map.")
        return None

    working = map_df.copy()
    if "Band" not in working.columns:
        working["Band"] = working["Center MHz"].apply(band_label)

    # Color selection
    if color_mode == "Frequency Band":
        working["_color"] = working["Center MHz"].apply(band_color)
        legend_group = "Band"
    elif color_mode == "Unit":
        working["_color"] = working["Unit"].apply(stable_color)
        legend_group = "Unit"
    elif color_mode == "Sponsor":
        working["_color"] = working["Sponsor"].apply(stable_color)
        legend_group = "Sponsor"
    elif color_mode == "Tech":
        working["_color"] = working["Tech"].apply(stable_color)
        legend_group = "Tech"
    else:
        working["_color"] = working["Equipment"].apply(stable_color)
        legend_group = "Equipment"

    working["_label"] = working.apply(selectable_system_label, axis=1)
    working["_hover"] = working.apply(
        lambda r: (
            f"<b>{r.get('Equipment','')}</b><br>"
            f"Unit: {r.get('Unit','')}<br>"
            f"Tech: {r.get('Tech','')}<br>"
            f"Band: {r.get('Band','')}<br>"
            f"Freq: {r.get('Center MHz','')} MHz<br>"
            f"Power: {r.get('Power_W','')} W<br>"
            f"Time: {r.get('Time','')}<br>"
            f"Radius: {r.get('Radius','')} {r.get('Radius Units','')}"
        ),
        axis=1,
    )

    fig = plotly_go.Figure()

    # Offline visual layer background.
    bg = "#F8FAFC"
    grid_color = "#CBD5E1"
    if map_layer == "Satellite":
        bg = "#1F2937"
        grid_color = "#64748B"
    elif map_layer == "Military Topographic":
        bg = "#ECFCCB"
        grid_color = "#84CC16"
    elif map_layer == "Street Map":
        bg = "#E0F2FE"
        grid_color = "#93C5FD"

    # Congestion heat as a density-like 2D histogram.
    if show_congestion_heat and len(working) >= 2:
        fig.add_trace(
            plotly_go.Histogram2dContour(
                x=working["lon"],
                y=working["lat"],
                colorscale="Reds",
                showscale=False,
                opacity=0.28,
                contours=dict(showlines=False),
                hoverinfo="skip",
                name="Congestion Heat",
            )
        )

    # RF coverage circles as Plotly shapes.
    shapes = []
    if show_radius:
        for _, row in working.iterrows():
            radius_m = to_float(row.get("radius_m"), 0.0)
            if radius_m <= 0:
                continue
            lat = row["lat"]
            lon = row["lon"]
            r_lat = radius_to_degrees_lat(radius_m)
            denom = 111320.0 * max(math.cos(math.radians(lat)), 0.15)
            r_lon = radius_m / denom
            color = row["_color"]
            shapes.append(
                dict(
                    type="circle",
                    xref="x",
                    yref="y",
                    x0=lon - r_lon,
                    x1=lon + r_lon,
                    y0=lat - r_lat,
                    y1=lat + r_lat,
                    fillcolor=color,
                    opacity=0.12,
                    line=dict(color=color, width=1),
                    layer="below",
                )
            )

    # Red overlap warning lines.
    if show_overlap_warning and show_radius:
        rows = working.to_dict(orient="records")
        shown = 0
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                ca = to_float(rows[i].get("Center MHz"))
                cb = to_float(rows[j].get("Center MHz"))
                freq_close = ca is not None and cb is not None and abs(ca - cb) <= 10.0
                if freq_close and circles_overlap_v35(rows[i], rows[j]):
                    fig.add_trace(
                        plotly_go.Scatter(
                            x=[rows[i]["lon"], rows[j]["lon"]],
                            y=[rows[i]["lat"], rows[j]["lat"]],
                            mode="lines",
                            line=dict(color="red", width=2),
                            opacity=0.55,
                            hoverinfo="skip",
                            showlegend=False,
                            name="Interference overlap",
                        )
                    )
                    shown += 1
                    if shown >= 300:
                        break
            if shown >= 300:
                break

    # LOS lines: only like systems, selectable.
    los_pairs = []
    if los_enabled:
        los_pairs = build_los_pairs(
            working,
            match_by=los_match_by,
            selected_labels=selected_los_labels,
            max_pairs=300,
        )
        for a, b in los_pairs:
            fig.add_trace(
                plotly_go.Scatter(
                    x=[a["lon"], b["lon"]],
                    y=[a["lat"], b["lat"]],
                    mode="lines",
                    line=dict(color="#22C55E", width=2, dash="dot"),
                    opacity=0.75,
                    hovertext=f"LOS candidate<br>{a.get('Equipment')} ↔ {b.get('Equipment')}<br>Matched by {los_match_by}: {los_group_value(a, los_match_by)}",
                    hoverinfo="text",
                    showlegend=False,
                    name="LOS candidate",
                )
            )

    # Points grouped for legend.
    for group_name, group_df in working.groupby(legend_group):
        fig.add_trace(
            plotly_go.Scatter(
                x=group_df["lon"],
                y=group_df["lat"],
                mode="markers+text" if show_labels else "markers",
                marker=dict(
                    size=group_df["Power_W"].apply(lambda x: max(10, min(28, 10 + to_float(x, 1.0) * 1.4))),
                    color=group_df["_color"],
                    line=dict(color="black", width=1),
                    symbol="circle",
                ),
                text=group_df.apply(lambda r: f"{r.get('Unit','')}<br>{r.get('Equipment','')}", axis=1) if show_labels else None,
                textposition="top center",
                hovertext=group_df["_hover"],
                hoverinfo="text",
                name=str(group_name),
            )
        )

    min_lat, max_lat = working["lat"].min(), working["lat"].max()
    min_lon, max_lon = working["lon"].min(), working["lon"].max()
    lat_span = max(max_lat - min_lat, 0.01)
    lon_span = max(max_lon - min_lon, 0.01)

    time_note = "All hours" if show_all_hours else f"{selected_hour:0.2f} hour"
    fig.update_layout(
        title=f"Interactive Tactical Map — {map_layer} — {time_note}",
        height=750,
        plot_bgcolor=bg,
        paper_bgcolor="white",
        shapes=shapes,
        legend=dict(orientation="v"),
        margin=dict(l=10, r=10, t=50, b=10),
        dragmode="pan",
    )
    fig.update_xaxes(
        title="Longitude",
        range=[min_lon - lon_span * 0.3, max_lon + lon_span * 0.3],
        showgrid=True,
        gridcolor=grid_color,
        zeroline=False,
    )
    fig.update_yaxes(
        title="Latitude",
        range=[min_lat - lat_span * 0.3, max_lat + lat_span * 0.3],
        showgrid=True,
        gridcolor=grid_color,
        scaleanchor="x",
        scaleratio=1,
        zeroline=False,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "scrollZoom": True,
            "displayModeBar": True,
            "modeBarButtonsToAdd": ["drawline", "drawrect", "eraseshape"],
            "toImageButtonOptions": {"format": "png", "filename": "interactive_tactical_map"},
        },
    )

    if los_enabled:
        st.caption(f"LOS/link lines displayed: {len(los_pairs)}. Lines are manually selected and limited to like systems matched by {los_match_by}. Terrain-blocked LOS still requires elevation data.")
    else:
        st.caption("Zoom/pan enabled. Use the camera button in the Plotly toolbar to export PNG.")

    return fig


def los_selection_controls(map_df, match_by):
    if map_df.empty:
        return []

    temp = map_df.copy()
    temp["_system_label"] = temp.apply(selectable_system_label, axis=1)
    temp["_los_group"] = temp.apply(lambda r: los_group_value(r, match_by), axis=1)

    groups = sorted(temp["_los_group"].dropna().unique().tolist())
    chosen_groups = st.multiselect(
        f"Filter LOS systems by {match_by} group",
        options=groups,
        default=[],
        help="Optional filter. Leave blank to see all systems, or choose one group to limit the list.",
    )

    if chosen_groups:
        filtered = temp[temp["_los_group"].isin(chosen_groups)].copy()
    else:
        filtered = temp.copy()

    labels = filtered["_system_label"].tolist()

    selected_labels = st.multiselect(
        "Choose systems to draw LOS/link lines",
        options=labels,
        default=[],
        help="No lines are drawn until you manually choose at least two systems. Lines are still limited to like systems.",
    )

    st.caption(f"Selected systems: {len(selected_labels)}. LOS/link lines will only draw between selected systems that match by {match_by}.")
    return selected_labels



# ============================================================
# Active Frequency Extract / User Handout
# ============================================================

ACTIVE_EXTRACT_DEFAULT_COLUMNS = [
    "Unit",
    "Sponsor",
    "Equipment",
    "Tech",
    "Start Time",
    "End Time",
    "Start Frequency (MHz)",
    "Center Frequency (MHz)",
    "End Frequency (MHz)",
    "Bandwidth (MHz)",
    "Power (W)",
    "Power (dBm)",
    "Location",
    "Site Name",
    "Notes",
]


def build_active_frequency_extract(df, selected_columns=None, include_locked_status=False):
    """Create a clean active-frequency handout table for users."""
    working = active_only(df, show_inactive=False)
    working = recalc_start_end_fast(working).copy()

    center_col = find_col(working, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    if center_col:
        working["_center_sort"] = pd.to_numeric(working[center_col], errors="coerce")
        working = working[working["_center_sort"].notna()].copy()
    else:
        working["_center_sort"] = range(len(working))

    available_defaults = [c for c in ACTIVE_EXTRACT_DEFAULT_COLUMNS if c in working.columns]
    if include_locked_status and "Locked" in working.columns:
        available_defaults = ["Locked"] + available_defaults

    if selected_columns:
        columns = [c for c in selected_columns if c in working.columns]
    else:
        columns = available_defaults

    out = working.sort_values(["_center_sort"]).copy()
    out = out[columns].copy() if columns else out.drop(columns=["_center_sort"], errors="ignore")

    for col in out.columns:
        if "Frequency" in col or "Bandwidth" in col:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(6)
        elif col in ["Power (W)", "Power (dBm)"]:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(3)

    return out.reset_index(drop=True)


def df_to_single_xlsx_bytes(df, sheet_name="Active Frequencies"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        safe_name = str(sheet_name)[:31] if str(sheet_name).strip() else "Active Frequencies"
        df.to_excel(writer, sheet_name=safe_name, index=False)
    output.seek(0)
    return output.read()


def active_frequency_text_summary(df, max_rows=200):
    if df.empty:
        return "No active frequencies available."

    lines = []
    lines.append("ACTIVE FREQUENCY EXTRACT")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    for idx, row in df.head(max_rows).iterrows():
        unit = row.get("Unit", "")
        equipment = row.get("Equipment", "")
        tech = row.get("Tech", "")
        center = row.get("Center Frequency (MHz)", "")
        start_f = row.get("Start Frequency (MHz)", "")
        end_f = row.get("End Frequency (MHz)", "")
        start_t = row.get("Start Time", "")
        end_t = row.get("End Time", "")
        bw = row.get("Bandwidth (MHz)", "")
        lines.append(
            f"{idx + 1}. Unit: {unit} | Equipment: {equipment} | Tech: {tech} | "
            f"Center: {center} MHz | Range: {start_f}-{end_f} MHz | BW: {bw} MHz | "
            f"Time: {start_t}-{end_t}"
        )

    if len(df) > max_rows:
        lines.append("")
        lines.append(f"Only first {max_rows} rows shown in text summary. Use CSV/XLSX for full extract.")

    return "\n".join(lines)



# ============================================================
# V48 Better Graph Colors
# ============================================================

DECIMAL_FREQUENCY_COLUMNS = [
    "Start Frequency (MHz)",
    "Center Frequency (MHz)",
    "End Frequency (MHz)",
    "Bandwidth (MHz)",
    "Power (W)",
    "Power (dBm)",
    "Latitude",
    "Longitude",
    "Coverage Radius",
    "Antenna Height",
]

def decimal_editor_config(df):
    """Make Streamlit data_editor accept decimal frequency values."""
    cfg = {}

    for col in df.columns:
        if col in ["Start Frequency (MHz)", "Center Frequency (MHz)", "End Frequency (MHz)"]:
            cfg[col] = st.column_config.NumberColumn(
                col,
                min_value=None,
                max_value=None,
                step=0.0001,
                format="%.4f",
                help="Decimal MHz allowed. Example: 2050.1250 or 396.9375",
            )
        elif col == "Bandwidth (MHz)":
            cfg[col] = st.column_config.NumberColumn(
                col,
                min_value=0.0001,
                max_value=None,
                step=0.0001,
                format="%.4f",
                help="Decimal MHz allowed. Example: 0.0250, 1.2000, 8.8000",
            )
        elif col in ["Power (W)", "Power (dBm)", "Latitude", "Longitude", "Coverage Radius", "Antenna Height"]:
            cfg[col] = st.column_config.NumberColumn(
                col,
                min_value=None,
                max_value=None,
                step=0.0001,
                format="%.4f",
            )
        elif col in ["Active", "Locked"]:
            cfg[col] = st.column_config.CheckboxColumn(col)
        elif col in ["Start Time", "End Time"]:
            cfg[col] = st.column_config.TextColumn(
                col,
                help="Use HH:MM or decimal hour. Example: 06:00 or 6.5",
            )

    return cfg


def enforce_decimal_numeric_columns(df):
    """Keep frequency and numeric planning columns as floats after editing."""
    out = df.copy()
    for col in DECIMAL_FREQUENCY_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out



# ============================================================
# V48 Better Graph Color Controls
# ============================================================

COLORBLIND_DISTINCT_PALETTE = [
    "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9",
    "#F0E442", "#000000", "#7E57C2", "#00838F", "#C62828", "#558B2F",
    "#6D4C41", "#AD1457", "#1565C0", "#EF6C00", "#2E7D32", "#5D4037",
    "#4527A0", "#0277BD", "#9E9D24", "#B71C1C", "#00695C", "#8E24AA",
]

HIGH_CONTRAST_PALETTE = [
    "#00429D", "#E66100", "#1A9850", "#D01C8B", "#FFD92F", "#5E3C99",
    "#A6761D", "#1B9E77", "#E7298A", "#66A61E", "#E6AB02", "#A6CEE3",
    "#B2DF8A", "#FB9A99", "#FDBF6F", "#CAB2D6", "#FFFF99", "#B15928",
]

TACTICAL_PALETTE = [
    "#00B4D8", "#F77F00", "#70E000", "#D00000", "#9D4EDD", "#FFD60A",
    "#2EC4B6", "#FF006E", "#8338EC", "#3A86FF", "#8AC926", "#FFCA3A",
    "#1982C4", "#6A4C93", "#BC6C25", "#588157", "#E63946", "#457B9D",
]


def get_palette_by_name(name):
    if name == "High Contrast":
        return HIGH_CONTRAST_PALETTE
    if name == "Tactical":
        return TACTICAL_PALETTE
    return COLORBLIND_DISTINCT_PALETTE


def color_distance(hex_a, hex_b):
    def rgb(h):
        h = str(h).replace("#", "")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    try:
        a = rgb(hex_a)
        b = rgb(hex_b)
        return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5
    except Exception:
        return 999


def build_distinct_color_map(labels, palette_name="Colorblind Distinct", min_distance=95):
    palette = get_palette_by_name(palette_name)
    clean_labels = []
    for label in labels:
        txt = label_value(label)
        if txt not in clean_labels:
            clean_labels.append(txt)

    color_map = {}
    used = []
    for idx, label in enumerate(clean_labels):
        candidates = palette[idx % len(palette):] + palette[:idx % len(palette)]
        chosen = candidates[0]
        for candidate in candidates:
            recent = used[-4:] if len(used) >= 4 else used
            if all(color_distance(candidate, old) >= min_distance for old in recent):
                chosen = candidate
                break
        color_map[label] = chosen
        used.append(chosen)
    return color_map


def build_color_map_v48(df, color_by, palette_name="Colorblind Distinct"):
    if df is None or df.empty or color_by is None or color_by not in df.columns:
        return {}
    labels = [label_value(v) for v in df[color_by].fillna("(blank)").astype(str).tolist()]
    min_distance = st.session_state.get("color_min_distance_v48", 95)
    return build_distinct_color_map(labels, palette_name=palette_name, min_distance=min_distance)


def add_color_palette_sidebar_controls():
    st.divider()
    st.header("Graph Colors")
    palette_name = st.selectbox(
        "Graph color palette",
        ["Colorblind Distinct", "High Contrast", "Tactical"],
        index=0,
        help="Use Colorblind Distinct when unit colors look too similar.",
    )
    min_distance = st.slider(
        "Color separation strength",
        min_value=50,
        max_value=160,
        value=95,
        step=5,
        help="Higher values force stronger color separation between nearby legend items.",
    )
    outline_width = st.slider(
        "Bar outline width",
        min_value=0.2,
        max_value=2.5,
        value=1.1,
        step=0.1,
        help="Thicker outlines make adjacent frequency boxes easier to see.",
    )
    st.session_state["palette_name_v48"] = palette_name
    st.session_state["color_min_distance_v48"] = min_distance
    st.session_state["bar_outline_width_v48"] = outline_width
    return palette_name, min_distance, outline_width


# ============================================================
# App UI
# ============================================================

st.title("Spectrum Planner — V34 Tactical Ops Map")
st.caption("Use Offline Radius Map on restricted networks; it does not require map tiles or Mapbox.")

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
            if ok:
                st.session_state["saved_project_list"] = list_projects()

    st.markdown("**Delete Saved Project**")
    delete_confirm = st.checkbox(
        "Confirm delete selected project",
        value=False,
        key="delete_project_confirm",
        help="This permanently deletes the selected project from Supabase.",
    )
    if st.button("🗑️ Delete Selected Project", disabled=(not delete_confirm or not str(project_id_input).strip()), use_container_width=True):
        ok, msg = delete_project(project_id_input)
        (st.success if ok else st.error)(msg)
        if ok:
            st.session_state["saved_project_list"] = list_projects()
            st.rerun()

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
    low = st.number_input("Search low MHz", value=2200.0, step=0.0001)
    high = st.number_input("Search high MHz", value=2300.0, step=0.0001)
    freq_step = st.number_input("Frequency step MHz", value=1.0, min_value=0.001, step=0.5)
    guard = st.number_input("Guard MHz", value=0.0, min_value=0.0, step=0.1, key="guard_mhz")
    max_passes = st.number_input("Max passes", value=5, min_value=1, max_value=20, step=0.0001)

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
edited_df = st.data_editor(
    current_df,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    column_config=decimal_editor_config(current_df),
    key=f"editor_{active_sheet}_{st.session_state.get('planner_applied_at', 'base')}",
)
edited_df = enforce_decimal_numeric_columns(edited_df)
edited_df = normalize_columns(enforce_decimal_numeric_columns(edited_df), add_missing=True)

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

st.divider()
st.subheader("Active Frequency Extract")
st.caption("Create a clean active-frequency handout to send to users. Only rows checked Active are included.")

# V44 fix: this extract section appears before visual_df is created later in the app,
# so it must read directly from the current saved workbook sheet.
extract_source_df = recalc_start_end_fast(st.session_state["sheets"][active_sheet].copy())

extract_col_options = [c for c in ACTIVE_EXTRACT_DEFAULT_COLUMNS if c in extract_source_df.columns]
extract_include_locked = st.checkbox("Include Locked status in extract", value=False)
if extract_include_locked and "Locked" in extract_source_df.columns and "Locked" not in extract_col_options:
    extract_col_options = ["Locked"] + extract_col_options

if not extract_col_options:
    st.warning("No matching extract columns were found in this sheet.")
    selected_extract_cols = []
else:
    selected_extract_cols = st.multiselect(
        "Columns to include in user extract",
        options=extract_col_options,
        default=extract_col_options,
        help="This does not change the workbook. It only controls the handout/export columns.",
    )

active_extract_df = build_active_frequency_extract(
    extract_source_df,
    selected_columns=selected_extract_cols,
    include_locked_status=extract_include_locked,
)

e1, e2, e3, e4 = st.columns(4)
e1.metric("Extract rows", len(active_extract_df))
e2.metric("Unique equipment", active_extract_df["Equipment"].nunique() if "Equipment" in active_extract_df.columns and not active_extract_df.empty else 0)
e3.metric("Unique units", active_extract_df["Unit"].nunique() if "Unit" in active_extract_df.columns and not active_extract_df.empty else 0)
e4.metric("Unique freqs", active_extract_df["Center Frequency (MHz)"].nunique() if "Center Frequency (MHz)" in active_extract_df.columns and not active_extract_df.empty else 0)

with st.expander("Preview active frequency extract", expanded=False):
    st.dataframe(active_extract_df, use_container_width=True, hide_index=True)

x1, x2, x3 = st.columns(3)
with x1:
    st.download_button(
        "Download Active Frequencies CSV",
        data=active_extract_df.to_csv(index=False).encode("utf-8"),
        file_name=f"active_frequencies_{active_sheet}_{timestamp_string()}.csv",
        mime="text/csv",
        use_container_width=True,
    )
with x2:
    st.download_button(
        "Download Active Frequencies XLSX",
        data=df_to_single_xlsx_bytes(active_extract_df, sheet_name="Active Frequencies"),
        file_name=f"active_frequencies_{active_sheet}_{timestamp_string()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
with x3:
    summary_text = active_frequency_text_summary(active_extract_df)
    st.download_button(
        "Download User Handout TXT",
        data=summary_text.encode("utf-8"),
        file_name=f"active_frequency_handout_{active_sheet}_{timestamp_string()}.txt",
        mime="text/plain",
        use_container_width=True,
    )


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
        st.subheader("Tactical Map Under Current Visual")
        st.caption("V36 controls are visible here: map layer, RF coverage, unit icons, frequency bands, red overlap warnings, congestion heat, hour replay, and PNG animation frames.")
        map_enabled = st.checkbox("Enable map rendering", value=False, key=f"map_enabled_{active_sheet}")
        if map_enabled:
            mc1, mc2, mc3, mc4 = st.columns(4)
            with mc1:
                map_mode = st.selectbox("Map mode", ["Interactive Tactical Map", "Tactical Offline Ops Map", "Offline Radius Map", "Plotly Coordinate Map", "PyDeck Map"], index=0)
            with mc2:
                map_color_by = st.selectbox("Map color by", ["Equipment", "Unit", "Sponsor", "Tech", "Tech Category"], index=0)
            with mc3:
                radius_units = st.selectbox("Coverage Radius units", ["meters", "kilometers", "miles"], index=0)
            with mc4:
                max_map_rows = st.number_input("Max map rows", value=DEFAULT_MAX_MAP_ROWS, min_value=25, max_value=2000, step=25)

            show_radius = st.checkbox("Show RF coverage circles", value=True)

            if map_mode == "Interactive Tactical Map":
                st.markdown("**Interactive Tactical Map Controls**")
                t1, t2, t3, t4 = st.columns(4)
                with t1:
                    map_layer = st.selectbox("Map layer", ["Offline Grid", "Street Map", "Satellite", "Military Topographic"], index=0)
                with t2:
                    color_mode = st.selectbox("Color by", ["Equipment", "Unit", "Sponsor", "Tech", "Frequency Band"], index=4)
                with t3:
                    show_labels = st.checkbox("Unit labels", value=True)
                with t4:
                    show_congestion_heat = st.checkbox("Congestion heat map", value=True)

                t5, t6, t7 = st.columns(3)
                with t5:
                    show_overlap_warning = st.checkbox("Interference overlap shown in red", value=True)
                with t6:
                    los_enabled = st.checkbox("Show LOS/link lines", value=False, help="Default is off. Turn on only when you want to manually draw selected point-to-point lines.")
                with t7:
                    los_match_by = st.selectbox("Only draw LOS/link between like systems by", ["Equipment", "Tech", "Unit", "Frequency Band"], index=0)

                time_control = st.checkbox("Hour-by-hour replay slider", value=False, key=f"interactive_time_{active_sheet}")
                if time_control:
                    selected_hour = st.slider("Replay exercise hour", 0.0, 24.0, 6.0, 0.25, key=f"interactive_hour_{active_sheet}")
                    show_all_hours = False
                else:
                    selected_hour = None
                    show_all_hours = True

                map_df = make_map_df_v35(
                    visual_df,
                    color_by=map_color_by,
                    radius_units=radius_units,
                    max_rows=int(max_map_rows),
                    selected_hour=selected_hour,
                    show_all_hours=show_all_hours,
                )

                selected_los_labels = []
                if los_enabled and not map_df.empty:
                    with st.expander("Select systems for LOS/link lines", expanded=True):
                        selected_los_labels = los_selection_controls(map_df, los_match_by)

                if globals().get("go", None) is None:
                    st.warning("Interactive Tactical Map requires Plotly. Add `plotly` to requirements.txt, then redeploy. Falling back to Tactical Offline Ops Map below.")
                    fallback_fig = tactical_ops_map_v35(
                        map_df,
                        map_layer=map_layer,
                        show_radius=show_radius,
                        show_labels=show_labels,
                        show_unit_icons=True,
                        color_mode=color_mode,
                        show_overlap_warning=show_overlap_warning,
                        show_congestion_heat=show_congestion_heat,
                        show_grid=True,
                        selected_hour=selected_hour,
                        show_all_hours=show_all_hours,
                        map_theme="Light",
                    )
                    st.pyplot(fallback_fig, use_container_width=True)
                else:
                    plotly_interactive_tactical_map_v38(
                        map_df,
                        map_layer=map_layer,
                        show_radius=show_radius,
                        show_labels=show_labels,
                        color_mode=color_mode,
                        show_overlap_warning=show_overlap_warning,
                        show_congestion_heat=show_congestion_heat,
                        selected_hour=selected_hour,
                        show_all_hours=show_all_hours,
                        los_enabled=los_enabled,
                        los_match_by=los_match_by,
                        selected_los_labels=selected_los_labels,
                    )

            elif map_mode == "Tactical Offline Ops Map":
                st.markdown("**Tactical Map Full Controls**")
                t1, t2, t3, t4 = st.columns(4)
                with t1:
                    map_layer = st.selectbox("Map layer", ["Offline Grid", "Street Map", "Satellite", "Military Topographic"], index=0)
                with t2:
                    color_mode = st.selectbox("Color by", ["Equipment", "Unit", "Sponsor", "Tech", "Frequency Band"], index=4)
                with t3:
                    map_theme = st.selectbox("Map theme", ["Light", "Dark"], index=0)
                with t4:
                    show_unit_icons = st.checkbox("Unit icons instead of plain dots", value=True)

                t5, t6, t7, t8 = st.columns(4)
                with t5:
                    show_labels = st.checkbox("Unit labels", value=True)
                with t6:
                    show_overlap_warning = st.checkbox("Interference overlap shown in red", value=True)
                with t7:
                    show_congestion_heat = st.checkbox("Heat map of spectrum congestion", value=True)
                with t8:
                    show_grid = st.checkbox("Grid/MGRS-style lines", value=True)

                time_control = st.checkbox("Hour-by-hour replay slider", value=False)
                if time_control:
                    selected_hour = st.slider("Replay exercise hour", 0.0, 24.0, 6.0, 0.25)
                    show_all_hours = False
                else:
                    selected_hour = None
                    show_all_hours = True

                map_df = make_map_df_v35(
                    visual_df,
                    color_by=map_color_by,
                    radius_units=radius_units,
                    max_rows=int(max_map_rows),
                    selected_hour=selected_hour,
                    show_all_hours=show_all_hours,
                )

                if map_df.empty:
                    st.info("No valid Latitude/Longitude rows available for the tactical map.")
                else:
                    map_fig = tactical_ops_map_v35(
                        map_df,
                        map_layer=map_layer,
                        show_radius=show_radius,
                        show_labels=show_labels,
                        show_unit_icons=show_unit_icons,
                        color_mode=color_mode,
                        show_overlap_warning=show_overlap_warning,
                        show_congestion_heat=show_congestion_heat,
                        show_grid=show_grid,
                        selected_hour=selected_hour,
                        show_all_hours=show_all_hours,
                        map_theme=map_theme,
                    )
                    st.pyplot(map_fig, use_container_width=True)
                    map_png = fig_to_png_bytes(map_fig)
                    st.download_button("Download tactical map PNG", data=map_png, file_name=f"tactical_ops_map_{timestamp_string()}.png", mime="image/png", use_container_width=True)

                    if st.button("Save tactical map PNG to project", use_container_width=True):
                        st.session_state.setdefault("saved_png_exports", {})[f"tactical_ops_map_{active_sheet}.png"] = base64.b64encode(map_png).decode("utf-8")
                        st.success("Tactical map PNG saved in project memory. Click Save Project to persist it.")

                    with st.expander("Animation / Hour-by-Hour Export", expanded=False):
                        st.caption("Generates separate PNG frames for each selected hour. No ZIP is used.")
                        ac1, ac2, ac3 = st.columns(3)
                        with ac1:
                            anim_start = st.number_input("Animation start hour", value=6.0, min_value=0.0, max_value=24.0, step=0.25)
                        with ac2:
                            anim_end = st.number_input("Animation end hour", value=18.0, min_value=0.0, max_value=24.0, step=0.25)
                        with ac3:
                            anim_step = st.number_input("Animation step hours", value=1.0, min_value=0.25, max_value=6.0, step=0.25)

                        if st.button("Generate hour-by-hour PNG frames", use_container_width=True):
                            hours = []
                            h = anim_start
                            while h <= anim_end + 1e-9:
                                hours.append(round(h, 2))
                                h += anim_step
                            map_options = {
                                "map_color_by": map_color_by,
                                "radius_units": radius_units,
                                "max_map_rows": int(max_map_rows),
                                "map_layer": map_layer,
                                "show_radius": show_radius,
                                "show_labels": show_labels,
                                "show_unit_icons": show_unit_icons,
                                "color_mode": color_mode,
                                "show_overlap_warning": show_overlap_warning,
                                "show_congestion_heat": show_congestion_heat,
                                "show_grid": show_grid,
                                "map_theme": map_theme,
                            }
                            st.session_state["animation_png_exports"] = build_animation_frames_pngs(visual_df, hours, map_options)
                            st.success(f"Generated {len(hours)} PNG frame(s).")

                        if st.session_state.get("animation_png_exports"):
                            for fname, b64 in st.session_state["animation_png_exports"].items():
                                st.download_button(f"Download {fname}", data=base64.b64decode(b64.encode("utf-8")), file_name=fname, mime="image/png", use_container_width=True)

                    with st.expander("LOS / Terrain Elevation", expanded=False):
                        st.warning("True LOS prediction and terrain elevation require elevation data such as DEM/DTED. This version includes the workflow controls but does not calculate terrain-blocked LOS yet.")
                        st.file_uploader("Future input: upload DEM/DTED elevation file", type=["tif", "tiff", "hgt", "dt0", "dt1", "dt2"], disabled=True)
                        st.checkbox("Future option: calculate line-of-sight between selected sites", value=False, disabled=True)
                        st.checkbox("Future option: terrain elevation profile", value=False, disabled=True)

                st.caption("Included: map layer selector, RF coverage circles, unit icons, color by frequency band, red overlap lines, congestion heat, hour replay slider, and animation frame export.")

            elif map_mode == "Offline Radius Map":
                map_df, map_fig = render_offline_radius_map(visual_df, color_by=map_color_by, radius_units=radius_units, max_rows=int(max_map_rows), show_radius=show_radius)
                if not map_df.empty:
                    st.download_button("Download map PNG", data=fig_to_png_bytes(map_fig), file_name=f"offline_radius_map_{timestamp_string()}.png", mime="image/png", use_container_width=True)
            elif map_mode == "Plotly Coordinate Map":
                render_plotly_coordinate_map(visual_df, color_by=map_color_by, radius_units=radius_units, max_rows=int(max_map_rows), show_radius=show_radius)
            else:
                pydeck_style = st.selectbox("PyDeck basemap", ["No basemap", "Carto light", "Carto dark"], index=0)
                render_pydeck_map(visual_df, color_by=map_color_by, radius_units=radius_units, max_rows=int(max_map_rows), show_radius=show_radius, map_style_mode=pydeck_style)
        else:
            st.info("Map is disabled for performance. Enable it when needed.")
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

st.caption("V34 note: Tactical Offline Ops Map is the default for restricted networks and does not require map tiles.")
