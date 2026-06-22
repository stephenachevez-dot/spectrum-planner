import io
import re
import hashlib
from datetime import datetime

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

st.set_page_config(page_title="Spectrum Planner V18", layout="wide")

# ============================================================
# Spectrum Planner V18
# ============================================================
# Baseline: V17 Visual Frequency Controls
#
# Fixed/changed in V18:
# - Smart Planner Apply updates the live workbook sheet.
# - Visuals draw directly from the live workbook sheet, not a stale visual cache.
# - Time x Frequency Y-axis is forced to the actual plotted Start/End Time range.
# - Frequency controls now hide/show the MHz label inside the box only.
# - Frequency controls DO NOT remove the bar/box from the visual.
# - Added Time Debug tab to prove what Start/End times are being plotted.
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
    "frequency": "Center Frequency (MHz)",
    "endf": "End Frequency (MHz)", "endfrequency": "End Frequency (MHz)",
    "endfrequencymhz": "End Frequency (MHz)", "endfreq": "End Frequency (MHz)",
    "bw": "Bandwidth (MHz)", "bandwidth": "Bandwidth (MHz)", "bandwidthmhz": "Bandwidth (MHz)",
    "power": "Power (W)", "powerw": "Power (W)", "powerwatts": "Power (W)",
    "powerdbm": "Power (dBm)", "dbm": "Power (dBm)",
    "techcategory": "Tech Category", "category": "Tech Category",
    "lat": "Latitude", "latitude": "Latitude", "lon": "Longitude", "lng": "Longitude",
    "long": "Longitude", "longitude": "Longitude", "location": "Location",
    "systemplatform": "System/Platform", "platform": "System/Platform",
    "antennaheight": "Antenna Height", "coverageradius": "Coverage Radius",
    "sitename": "Site Name", "site": "Site Name", "mgrs": "MGRS", "usng": "USNG",
    "notes": "Notes", "note": "Notes", "comments": "Notes",
}

MAX_CONFLICTS_DISPLAY = 2500
MAX_PLANNER_ROWS = 1200


def key_name(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


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
    else:
        out["Active"] = True

    if "Locked" in out.columns:
        out["Locked"] = out["Locked"].apply(lambda v: to_bool(v, False))
    else:
        out["Locked"] = False

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


def intervals_overlap(a1, a2, b1, b2) -> bool:
    return max(a1, b1) < min(a2, b2)


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
                    "Row A": pos_a + 1,
                    "Row B": pos_b + 1,
                    "Equipment A": row_a.get(equipment_col, "") if equipment_col else "",
                    "Equipment B": row_b.get(equipment_col, "") if equipment_col else "",
                    "Unit A": row_a.get(unit_col, "") if unit_col else "",
                    "Unit B": row_b.get(unit_col, "") if unit_col else "",
                    "Tech A": row_a.get(tech_col, "") if tech_col else "",
                    "Tech B": row_b.get(tech_col, "") if tech_col else "",
                    "Sponsor A": row_a.get(sponsor_col, "") if sponsor_col else "",
                    "Sponsor B": row_b.get(sponsor_col, "") if sponsor_col else "",
                    "Center A": ac,
                    "Center B": bc,
                    "Bandwidth A": abw,
                    "Bandwidth B": bbw,
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
                    moves.append({
                        "Row": idx + 1,
                        "Move Type": "Time",
                        "Old Start": format_time_hhmm(old_start),
                        "Old End": format_time_hhmm(old_end),
                        "New Start": format_time_hhmm(ns),
                        "New End": format_time_hhmm(ne),
                    })
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
                    moves.append({
                        "Row": idx + 1,
                        "Move Type": "Frequency",
                        "Old Center": old_center,
                        "New Center": candidate,
                    })
                    out = recalc_start_end_fast(out)
                    moved_any = True
                    break

        if not moved_any:
            break

    return recalc_start_end_fast(out), pd.DataFrame(moves)


def smart_full_deconflict(df, day_start, day_end, time_step_minutes, low_mhz, high_mhz, freq_step_mhz, guard_mhz, max_passes):
    start_conflicts = len(detect_conflicts_fast(df, guard_mhz=guard_mhz))
    time_df, time_moves = smart_time_deconflict(df, day_start, day_end, time_step_minutes, guard_mhz, max_passes)
    after_time = len(detect_conflicts_fast(time_df, guard_mhz=guard_mhz))
    freq_df, freq_moves = smart_frequency_deconflict(time_df, low_mhz, high_mhz, freq_step_mhz, guard_mhz, max_passes)
    final_conflicts = len(detect_conflicts_fast(freq_df, guard_mhz=guard_mhz))

    moves = pd.concat([time_moves, freq_moves], ignore_index=True)
    summary = pd.DataFrame([{
        "Planner Mode": "Full",
        "Starting Conflicts": start_conflicts,
        "After Time Conflicts": after_time,
        "Final Conflicts": final_conflicts,
        "Move Rows": len(moves),
    }])
    return freq_df, moves, summary


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

    return True, "Planner results applied. Visuals now draw from the updated workbook sheet."


def dataframe_to_xlsx(sheets: dict) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in sheets.items():
            safe_name = str(name)[:31] if str(name).strip() else "Sheet"
            recalc_start_end_fast(df).to_excel(writer, sheet_name=safe_name, index=False)
    output.seek(0)
    return output.read()


def load_file(uploaded_file):
    name = uploaded_file.name.lower()
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
# Label-only hide/show controls
# ============================================================

def frequency_display_value(value):
    val = to_float(value)
    if val is None:
        return None
    return f"{val:.3f} MHz"


def get_hidden_frequency_labels(sheet_name):
    return set(st.session_state.setdefault("hidden_frequency_labels", {}).get(sheet_name, []))


def set_hidden_frequency_labels(sheet_name, values):
    clean = sorted(set([v for v in values if v]), key=lambda x: to_float(x, 0.0))
    st.session_state.setdefault("hidden_frequency_labels", {})[sheet_name] = clean
    st.session_state["visual_version"] = st.session_state.get("visual_version", 0) + 1


def visual_frequency_label_options(df):
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


def should_show_frequency_label(center_value, sheet_name):
    label = frequency_display_value(center_value)
    if label is None:
        return False
    return label not in get_hidden_frequency_labels(sheet_name)


# ============================================================
# Visuals
# ============================================================

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

    handles = [
        plt.Line2D([0], [0], marker="s", linestyle="", markerfacecolor=color,
                   markeredgecolor=color, markersize=9, label=label)
        for label, color in color_map.items()
    ]

    legend = ax.legend(handles=handles, title=color_by, loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=True)
    legend.get_frame().set_facecolor("#111827" if dark else "white")
    legend.get_frame().set_edgecolor("#CBD5E1")
    plt.setp(legend.get_texts(), color="white" if dark else "black", fontsize=8)
    plt.setp(legend.get_title(), color="white" if dark else "black", fontsize=9, fontweight="bold")


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
        rows.append({
            "Row": idx + 1,
            "Equipment": row.get(equipment_col, "") if equipment_col else "",
            "Unit": row.get(unit_col, "") if unit_col else "",
            "Center MHz": to_float(row.get(center_col)) if center_col else None,
            "Raw Start": row.get(start_col, "") if start_col else "",
            "Raw End": row.get(end_col, "") if end_col else "",
            "Plotted Start Hour": t1,
            "Plotted End Hour": t2,
        })
    return pd.DataFrame(rows)


def time_frequency_chart(df, color_by="Equipment", dark=True, title=None, sheet_name=None):
    plot_df = active_only(df.copy(), show_inactive=st.session_state.get("show_inactive_rows", False))

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
    labels_hidden = 0
    all_times = []

    max_power = 1.0
    if power_col is not None and len(plot_df):
        max_power = max([to_float(v, 0.0) for v in plot_df[power_col].tolist()] + [1.0])

    for _, row in plot_df.iterrows():
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

        power = to_float(row.get(power_col), 0.0) if power_col else 0.0
        ratio = max(0.0, min(power / max_power, 1.0)) if max_power else 0.0
        alpha = 0.45 + (1.0 - ratio) * 0.45
        zorder = 10 + int((1.0 - ratio) * 1000)

        # Always draw the bar/box.
        ax.add_patch(Rectangle(
            (center - bw / 2.0, start_time),
            bw,
            end_time - start_time,
            facecolor=color,
            edgecolor="#0F172A",
            linewidth=0.9,
            alpha=alpha,
            zorder=zorder,
        ))

        # Only the frequency text label is hidden/shown.
        show_label = True
        if sheet_name is not None:
            show_label = should_show_frequency_label(center, sheet_name)
        if not show_label:
            labels_hidden += 1

        if show_label and (len(plot_df) <= 160 or ratio <= 0.70):
            ax.text(
                center,
                start_time + (end_time - start_time) / 2.0,
                f"{center:.3f} MHz",
                rotation=0,
                ha="center",
                va="center",
                fontsize=7,
                fontweight="bold",
                color="white",
                bbox=dict(boxstyle="round,pad=0.12", facecolor="#111827", edgecolor="none", alpha=0.55),
                clip_on=True,
                zorder=zorder + 1,
            )

        rows_drawn += 1

    ax.autoscale()

    # Force Y axis to the actual time range so planner moves are visible.
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
    return fig, plot_df, rows_drawn, labels_hidden


def power_chart(df, color_by="Equipment", dark=True, sheet_name=None):
    plot_df = active_only(df.copy(), show_inactive=st.session_state.get("show_inactive_rows", False))

    color_by = color_by if color_by in plot_df.columns else pick_color_field(plot_df, color_by)
    color_map = build_color_map(plot_df, color_by)

    center_col = find_col(plot_df, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(plot_df, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    power_col = find_col(plot_df, ["Power (W)", "PowerW", "Power"])

    fig, ax = plt.subplots(figsize=(16, 7))
    fig.patch.set_facecolor("#111827" if dark else "white")
    ax.set_facecolor("#111827" if dark else "white")

    for _, row in plot_df.iterrows():
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

        ax.add_patch(Rectangle((center - bw / 2.0, 0), bw, power, facecolor=color,
                               edgecolor="#0F172A", linewidth=0.9, alpha=0.80))

    ax.autoscale()
    ax.set_title(f"Frequency Allocation vs Power — by {color_by}", color="white" if dark else "black", fontsize=15, fontweight="bold")
    ax.set_xlabel("Frequency (MHz)", color="white" if dark else "black")
    ax.set_ylabel("Power (W)", color="white" if dark else "black")
    ax.tick_params(colors="white" if dark else "black")
    ax.grid(True, alpha=0.18, zorder=0)
    add_legend(ax, color_by, color_map, dark=dark)
    fig.tight_layout()
    return fig, plot_df


# ============================================================
# App UI
# ============================================================

st.title("Spectrum Planner — V18 Visual Label Toggle + Time Fix")
st.caption("Frequency label controls hide the MHz text inside the box only. Bars/boxes stay visible.")

with st.sidebar:
    st.header("Workbook")
    uploaded = st.file_uploader("Upload allocation workbook or CSV", type=["xlsx", "csv"])
    show_inactive = st.checkbox("Show inactive rows in visuals", value=False, key="show_inactive_rows")
    dark = st.checkbox("Dark visuals", value=False)

    st.divider()
    st.header("Planner Mode")
    planner_mode = st.radio(
        "Planner mode",
        ["Auto deconflict by time", "Auto deconflict by frequency", "Run full smart deconfliction"],
        index=0,
    )

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

    st.caption("Locked rows will not be moved by the planner.")

if "sheets" not in st.session_state:
    st.session_state["sheets"] = {}

if uploaded is not None:
    st.session_state["sheets"] = load_file(uploaded)
    st.session_state["analysis_cache"] = {}
    st.session_state["hidden_frequency_labels"] = {}
    st.session_state["visual_version"] = st.session_state.get("visual_version", 0) + 1
    st.success(f"Loaded {len(st.session_state['sheets'])} workbook tab(s). Dashboard sheets are intentionally skipped.")

if not st.session_state["sheets"]:
    st.info("Upload a workbook or CSV to begin.")
    st.stop()

sheet_names = list(st.session_state["sheets"].keys())
active_sheet = st.selectbox("Active sheet for plots/deconfliction", sheet_names)

current_df = recalc_start_end_fast(st.session_state["sheets"][active_sheet].copy())

st.subheader("Shared allocation workbook")
st.caption("Use Active to turn rows on/off. Use Locked to prevent Smart Planner from moving that row.")

editor_key = f"editor_{active_sheet}_{st.session_state.get('planner_applied_at', 'base')}_{st.session_state.get('visual_version', 0)}"

edited_df = st.data_editor(
    current_df,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    key=editor_key,
)

edited_df = normalize_columns(edited_df, add_missing=True)

c1, c2, c3 = st.columns(3)

with c1:
    if st.button("💾 Save edits", type="primary", use_container_width=True):
        saved = update_active_sheet_in_session(active_sheet, edited_df)
        clear_stored_analysis(active_sheet)
        st.success("Edits saved to session.")

with c2:
    xlsx_bytes = dataframe_to_xlsx(st.session_state["sheets"])
    st.download_button(
        "Download workbook XLSX",
        data=xlsx_bytes,
        file_name=f"spectrum_planner_workbook_{timestamp_string()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

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
        saved = update_active_sheet_in_session(active_sheet, edited_df)
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
            new_df, moves = smart_time_deconflict(
                planner_input,
                day_start=day_start,
                day_end=day_end,
                step_minutes=int(time_step),
                guard_mhz=guard,
                max_passes=int(max_passes),
            )
            final_conflicts = len(detect_conflicts_fast(new_df, guard_mhz=guard))
            summary = pd.DataFrame([{
                "Planner Mode": "Time Only",
                "Starting Conflicts": starting_conflicts,
                "Final Conflicts": final_conflicts,
                "Move Rows": len(moves),
            }])
        elif planner_mode == "Auto deconflict by frequency":
            new_df, moves = smart_frequency_deconflict(
                planner_input,
                low_mhz=low,
                high_mhz=high,
                step_mhz=freq_step,
                guard_mhz=guard,
                max_passes=int(max_passes),
            )
            final_conflicts = len(detect_conflicts_fast(new_df, guard_mhz=guard))
            summary = pd.DataFrame([{
                "Planner Mode": "Frequency Only",
                "Starting Conflicts": starting_conflicts,
                "Final Conflicts": final_conflicts,
                "Move Rows": len(moves),
            }])
        else:
            new_df, moves, summary = smart_full_deconflict(
                planner_input,
                day_start=day_start,
                day_end=day_end,
                time_step_minutes=int(time_step),
                low_mhz=low,
                high_mhz=high,
                freq_step_mhz=freq_step,
                guard_mhz=guard,
                max_passes=int(max_passes),
            )

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
        st.warning("Planner did not find movable rows. Check that rows are Active, not Locked, and that the operating day/frequency range has enough space.")

    with st.expander("Preview Planner Visual Before Apply", expanded=True):
        preview_df = st.session_state.get("pending_planner_df")
        if preview_df is not None:
            preview_fig, _, preview_rows, preview_hidden = time_frequency_chart(
                preview_df,
                color_by="Equipment",
                dark=dark,
                sheet_name=None,
                title="Preview: Smart Planner Result",
            )
            st.pyplot(preview_fig, use_container_width=True)
            st.caption(f"Previewing {preview_rows} planned row(s). Labels hidden in live view do not affect this preview.")

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

# One live visual dataframe only. No stale cached visual dataframe.
visual_df = recalc_start_end_fast(st.session_state["sheets"][active_sheet].copy())

st.divider()
st.subheader("Frequency Label Controls")
st.caption("These buttons remove/add the MHz text label inside the box only. The colored bar/box stays visible and the workbook data is not changed.")

frequency_options = visual_frequency_label_options(visual_df)
hidden_now = get_hidden_frequency_labels(active_sheet)
visible_options = [f for f in frequency_options if f not in hidden_now]
hidden_options = [f for f in frequency_options if f in hidden_now]

fc1, fc2 = st.columns(2)

with fc1:
    remove_labels = st.multiselect(
        "Frequency labels currently showing inside boxes",
        options=visible_options,
        key=f"remove_labels_{active_sheet}_{st.session_state.get('visual_version', 0)}",
        placeholder="Select MHz labels to hide inside boxes",
    )
    if st.button("➖ Hide selected MHz labels inside boxes", use_container_width=True):
        set_hidden_frequency_labels(active_sheet, list(hidden_now.union(remove_labels)))
        st.success(f"Hid {len(remove_labels)} selected MHz label{'s' if len(remove_labels) != 1 else ''}. Bars/boxes remain visible.")
        st.rerun()

with fc2:
    add_labels = st.multiselect(
        "Frequency labels currently hidden inside boxes",
        options=hidden_options,
        key=f"add_labels_{active_sheet}_{st.session_state.get('visual_version', 0)}",
        placeholder="Select MHz labels to show again",
    )
    add_col1, add_col2 = st.columns(2)
    with add_col1:
        if st.button("➕ Show selected labels", use_container_width=True):
            set_hidden_frequency_labels(active_sheet, list(hidden_now.difference(add_labels)))
            st.success(f"Showed {len(add_labels)} selected MHz label{'s' if len(add_labels) != 1 else ''}.")
            st.rerun()
    with add_col2:
        if st.button("♻️ Show all labels", use_container_width=True):
            set_hidden_frequency_labels(active_sheet, [])
            st.success("All hidden MHz labels are showing again.")
            st.rerun()

if hidden_now:
    st.info(f"MHz labels hidden inside boxes on this sheet: {', '.join(sorted(hidden_now, key=lambda x: to_float(x, 0.0)))}")
else:
    st.info("No MHz labels are currently hidden inside boxes on this sheet.")

st.divider()

with st.expander("Extract / Export Visuals", expanded=True):
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "Time × Frequency",
        "Power View",
        "Equipment Deconfliction",
        "Unit Deconfliction",
        "Sponsor Deconfliction",
        "Conflict Tables",
        "Time Debug",
    ])

    with tab1:
        color_by = st.selectbox("Color boxes by", ["Equipment", "Tech", "Unit", "Sponsor", "Tech Category"], index=0)
        fig, plot_df, rows_drawn, labels_hidden = time_frequency_chart(visual_df, color_by=color_by, dark=dark, sheet_name=active_sheet)
        st.pyplot(fig, use_container_width=True)
        st.caption(f"Showing {rows_drawn} active row(s). Hidden MHz labels: {labels_hidden}. Bars/boxes stay visible.")

    with tab2:
        pfig, _ = power_chart(visual_df, color_by="Equipment", dark=dark, sheet_name=active_sheet)
        st.pyplot(pfig, use_container_width=True)

    with tab3:
        fig, _, rows, hidden = time_frequency_chart(visual_df, color_by="Equipment", dark=dark, title="Equipment Deconfliction", sheet_name=active_sheet)
        st.pyplot(fig, use_container_width=True)
        st.caption(f"Showing {rows} active row(s). Hidden MHz labels: {hidden}.")

    with tab4:
        fig, _, rows, hidden = time_frequency_chart(visual_df, color_by="Unit", dark=dark, title="Unit Deconfliction", sheet_name=active_sheet)
        st.pyplot(fig, use_container_width=True)
        st.caption(f"Showing {rows} active row(s). Hidden MHz labels: {hidden}.")

    with tab5:
        fig, _, rows, hidden = time_frequency_chart(visual_df, color_by="Sponsor", dark=dark, title="Sponsor Deconfliction", sheet_name=active_sheet)
        st.pyplot(fig, use_container_width=True)
        st.caption(f"Showing {rows} active row(s). Hidden MHz labels: {hidden}.")

    with tab6:
        latest_conflicts = detect_conflicts_fast(visual_df, guard_mhz=guard)
        store_analysis(active_sheet, latest_conflicts)
        st.warning(f"{len(latest_conflicts)} active conflicts detected.")
        st.dataframe(latest_conflicts, use_container_width=True, hide_index=True)
        st.download_button(
            "Download conflicts CSV",
            data=latest_conflicts.to_csv(index=False).encode("utf-8"),
            file_name=f"conflicts_{timestamp_string()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with tab7:
        st.markdown("**This table shows exactly what the visual is plotting for time.**")
        debug_df = time_debug_table(visual_df)
        st.dataframe(debug_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download time debug CSV",
            data=debug_df.to_csv(index=False).encode("utf-8"),
            file_name=f"time_debug_{timestamp_string()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

st.caption("V18 note: Frequency controls hide/show MHz labels inside boxes only. Visuals draw from the live workbook sheet every time.")
