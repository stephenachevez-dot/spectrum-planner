import streamlit as st
import io
import re
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# ============================================================
# Spectrum Planner — Presentation Safe Full App
# ============================================================
# Purpose:
# - No dashboard.
# - Active unchecked rows DO NOT show in visuals, conflicts, maps, or planners.
# - Legend colors and box colors always match.
# - Frequency labels display vertically.
# - Start/End Frequency automatically calculate from Center Frequency and Bandwidth.
# - Locked rows are protected from automatic frequency moves.
# ============================================================


st.set_page_config(page_title="Spectrum Planner", layout="wide")


APP_COLUMNS = [
    "Active",
    "Locked",
    "Start Time",
    "End Time",
    "Unit",
    "Sponsor",
    "Equipment",
    "Tech",
    "Start Frequency (MHz)",
    "Center Frequency (MHz)",
    "End Frequency (MHz)",
    "Bandwidth (MHz)",
    "Power (W)",
    "Power (dBm)",
    "Tech Category",
    "Latitude",
    "Longitude",
    "Location",
    "System/Platform",
    "Antenna Height",
    "Coverage Radius",
    "Site Name",
    "MGRS",
    "USNG",
    "Notes",
]

PALETTE = [
    "#2563EB", "#F97316", "#22C55E", "#EAB308", "#A855F7",
    "#EF4444", "#06B6D4", "#84CC16", "#EC4899", "#8B5CF6",
    "#14B8A6", "#F59E0B", "#0EA5E9", "#F43F5E", "#64748B",
    "#6366F1", "#15803D", "#C2410C", "#A16207", "#7C3AED",
    "#0F766E", "#B45309", "#0369A1", "#BE185D", "#334155",
]

RENAME_MAP = {
    "enabled": "Active",
    "inuse": "Active",
    "use": "Active",
    "include": "Active",
    "active": "Active",
    "lock": "Locked",
    "locked": "Locked",
    "lockfrequency": "Locked",
    "lockboth": "Locked",
    "starttime": "Start Time",
    "start": "Start Time",
    "endtime": "End Time",
    "end": "End Time",
    "unit": "Unit",
    "sponsor": "Sponsor",
    "sponser": "Sponsor",
    "equipment": "Equipment",
    "system": "Equipment",
    "device": "Equipment",
    "radio": "Equipment",
    "tech": "Tech",
    "technology": "Tech",
    "startf": "Start Frequency (MHz)",
    "startfrequency": "Start Frequency (MHz)",
    "startfrequencymhz": "Start Frequency (MHz)",
    "startfreq": "Start Frequency (MHz)",
    "centerf": "Center Frequency (MHz)",
    "centerfrequency": "Center Frequency (MHz)",
    "centerfrequencymhz": "Center Frequency (MHz)",
    "centerfreq": "Center Frequency (MHz)",
    "frequency": "Center Frequency (MHz)",
    "endf": "End Frequency (MHz)",
    "endfrequency": "End Frequency (MHz)",
    "endfrequencymhz": "End Frequency (MHz)",
    "endfreq": "End Frequency (MHz)",
    "bw": "Bandwidth (MHz)",
    "bandwidth": "Bandwidth (MHz)",
    "bandwidthmhz": "Bandwidth (MHz)",
    "power": "Power (W)",
    "powerw": "Power (W)",
    "powerwatts": "Power (W)",
    "powerdbm": "Power (dBm)",
    "dbm": "Power (dBm)",
    "techcategory": "Tech Category",
    "category": "Tech Category",
    "lat": "Latitude",
    "latitude": "Latitude",
    "lon": "Longitude",
    "lng": "Longitude",
    "long": "Longitude",
    "longitude": "Longitude",
    "location": "Location",
    "systemplatform": "System/Platform",
    "platform": "System/Platform",
    "antennaheight": "Antenna Height",
    "coverageradius": "Coverage Radius",
    "sitename": "Site Name",
    "site": "Site Name",
    "mgrs": "MGRS",
    "usng": "USNG",
    "notes": "Notes",
    "note": "Notes",
    "comments": "Notes",
}


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

    # Remove blank Excel columns such as Unnamed: 0.
    out = out.loc[:, [c for c in out.columns if not str(c).lower().startswith("unnamed")]]

    rename = {}
    for col in out.columns:
        k = key_name(col)
        if k in RENAME_MAP:
            rename[col] = RENAME_MAP[k]

    out = out.rename(columns=rename)

    # CRITICAL FIX:
    # Streamlit st.data_editor crashes if duplicate column names exist.
    # After renaming, columns like Power, PowerW, Power (W) can all become Power (W).
    # Keep the first one and drop duplicate column names.
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

    # Final duplicate protection before st.data_editor.
    out = out.loc[:, ~pd.Index(out.columns).duplicated(keep="first")].copy()

    preferred = [c for c in APP_COLUMNS if c in out.columns]
    extras = [c for c in out.columns if c not in preferred]
    out = out[preferred + extras]

    return out

def recalc_start_end(df: pd.DataFrame) -> pd.DataFrame:
    out = normalize_columns(df, add_missing=False)

    center_col = find_col(out, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(out, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_col = find_col(out, ["Start Frequency (MHz)", "Start Frequency", "StartF"])
    end_col = find_col(out, ["End Frequency (MHz)", "End Frequency", "EndF"])

    if center_col is None or bw_col is None:
        return out

    if start_col is None:
        out["Start Frequency (MHz)"] = None
        start_col = "Start Frequency (MHz)"

    if end_col is None:
        out["End Frequency (MHz)"] = None
        end_col = "End Frequency (MHz)"

    for idx, row in out.iterrows():
        center = to_float(row.get(center_col))
        bw = to_float(row.get(bw_col))
        if center is None or bw is None or bw <= 0:
            continue
        out.at[idx, start_col] = round(center - bw / 2.0, 6)
        out.at[idx, end_col] = round(center + bw / 2.0, 6)

    return normalize_columns(out, add_missing=False)


def active_only(df: pd.DataFrame, show_inactive=False) -> pd.DataFrame:
    out = recalc_start_end(df)
    if not show_inactive and "Active" in out.columns:
        out = out[out["Active"] == True].copy()
    return out.reset_index(drop=True)


def label_value(value) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "blank", "(blank)"}:
        return "(blank)"
    return text


def stable_color(label: str) -> str:
    label = label_value(label)
    digest = hashlib.md5(label.encode("utf-8")).hexdigest()
    return PALETTE[int(digest[:8], 16) % len(PALETTE)]


def build_color_map(df: pd.DataFrame, color_by: str) -> dict:
    if color_by is None or color_by not in df.columns:
        return {}

    labels = []
    for value in df[color_by].fillna("(blank)").astype(str).tolist():
        lab = label_value(value)
        if lab not in labels:
            labels.append(lab)

    return {lab: stable_color(lab) for lab in labels}


def pick_color_field(df: pd.DataFrame, preferred="Tech"):
    for col in [preferred, "Tech", "Equipment", "Unit", "Sponsor", "Tech Category", "Location"]:
        if col in df.columns:
            return col
    return df.columns[0] if len(df.columns) else None


def time_to_hours(value):
    text = str(value or "").strip().lower()
    if not text or text in {"none", "nan"}:
        return None

    try:
        if ":" in text:
            h, m = text.split(":")[:2]
            return float(h) + float(m) / 60.0

        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return None

        value = float(match.group(0))

        if value >= 100:
            return int(value // 100) + (value % 100) / 60.0

        return value
    except Exception:
        return None


def add_legend(ax, color_by, color_map, dark=True):
    if not color_map:
        return

    handles = [
        plt.Line2D(
            [0], [0],
            marker="s",
            linestyle="",
            markerfacecolor=color,
            markeredgecolor=color,
            markersize=9,
            label=label,
        )
        for label, color in color_map.items()
    ]

    legend = ax.legend(
        handles=handles,
        title=color_by,
        loc="center left",
        bbox_to_anchor=(1.01, 0.5),
        frameon=True,
    )

    legend.get_frame().set_facecolor("#111827" if dark else "white")
    legend.get_frame().set_edgecolor("#CBD5E1")
    plt.setp(legend.get_texts(), color="white" if dark else "black", fontsize=8)
    plt.setp(legend.get_title(), color="white" if dark else "black", fontsize=9, fontweight="bold")


def time_frequency_chart(df: pd.DataFrame, color_by="Tech", dark=True, title=None):
    plot_df = active_only(df, show_inactive=st.session_state.get("show_inactive_rows", False))
    color_by = color_by if color_by in plot_df.columns else pick_color_field(plot_df, color_by)
    color_map = build_color_map(plot_df, color_by)

    center_col = find_col(plot_df, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(plot_df, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_time_col = find_col(plot_df, ["Start Time", "StartTime", "Start"])
    end_time_col = find_col(plot_df, ["End Time", "EndTime", "End"])

    fig, ax = plt.subplots(figsize=(16, 7))
    fig.patch.set_facecolor("#111827" if dark else "white")
    ax.set_facecolor("#111827" if dark else "white")

    rows_drawn = 0

    for _, row in plot_df.iterrows():
        center = to_float(row.get(center_col)) if center_col else None
        bw = to_float(row.get(bw_col), 1.0) if bw_col else 1.0

        if center is None:
            continue

        if bw is None or bw <= 0:
            bw = 1.0

        start_time = time_to_hours(row.get(start_time_col)) if start_time_col else None
        end_time = time_to_hours(row.get(end_time_col)) if end_time_col else None

        if start_time is None:
            start_time = 0.0

        if end_time is None or end_time <= start_time:
            end_time = start_time + 2.0

        group_label = label_value(row.get(color_by, "(blank)")) if color_by else "(blank)"
        color = color_map.get(group_label, stable_color(group_label))

        ax.add_patch(
            Rectangle(
                (center - bw / 2.0, start_time),
                bw,
                end_time - start_time,
                facecolor=color,
                edgecolor="#0F172A",
                linewidth=1.0,
                alpha=0.95,
            )
        )

        ax.text(
            center,
            start_time + (end_time - start_time) / 2.0,
            f"{center:.3f} MHz",
            rotation=90,
            ha="center",
            va="center",
            fontsize=8,
            fontweight="bold",
            color="white",
            clip_on=True,
        )

        rows_drawn += 1

    ax.autoscale()
    ax.set_title(title or f"Time × Frequency — by {color_by}", color="white" if dark else "black", fontsize=15, fontweight="bold")
    ax.set_xlabel("Frequency (MHz)", color="white" if dark else "black")
    ax.set_ylabel("Time (hours)", color="white" if dark else "black")
    ax.tick_params(colors="white" if dark else "black")
    ax.grid(True, alpha=0.18)

    add_legend(ax, color_by, color_map, dark=dark)
    fig.tight_layout()

    return fig, plot_df, rows_drawn


def power_chart(df: pd.DataFrame, color_by="Tech", dark=True):
    plot_df = active_only(df, show_inactive=st.session_state.get("show_inactive_rows", False))
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

        ax.add_patch(
            Rectangle(
                (center - bw / 2.0, 0),
                bw,
                power,
                facecolor=color,
                edgecolor="#0F172A",
                linewidth=1.0,
                alpha=0.95,
            )
        )

        ax.text(
            center,
            power / 2.0,
            f"{center:.3f} MHz",
            rotation=90,
            ha="center",
            va="center",
            fontsize=8,
            fontweight="bold",
            color="white",
            clip_on=True,
        )

    ax.autoscale()
    ax.set_title(f"Frequency Allocation vs Power — by {color_by}", color="white" if dark else "black", fontsize=15, fontweight="bold")
    ax.set_xlabel("Frequency (MHz)", color="white" if dark else "black")
    ax.set_ylabel("Power (W)", color="white" if dark else "black")
    ax.tick_params(colors="white" if dark else "black")
    ax.grid(True, alpha=0.18)

    add_legend(ax, color_by, color_map, dark=dark)
    fig.tight_layout()

    return fig, plot_df


def detect_conflicts(df: pd.DataFrame):
    plot_df = active_only(df, show_inactive=False)

    center_col = find_col(plot_df, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(plot_df, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_time_col = find_col(plot_df, ["Start Time", "StartTime", "Start"])
    end_time_col = find_col(plot_df, ["End Time", "EndTime", "End"])
    equipment_col = find_col(plot_df, ["Equipment"])
    unit_col = find_col(plot_df, ["Unit"])

    conflicts = []

    if center_col is None or bw_col is None:
        return pd.DataFrame()

    for i in range(len(plot_df)):
        a = plot_df.iloc[i]
        ac = to_float(a.get(center_col))
        abw = to_float(a.get(bw_col))
        if ac is None or abw is None:
            continue

        a1 = ac - abw / 2.0
        a2 = ac + abw / 2.0
        at1 = time_to_hours(a.get(start_time_col)) if start_time_col else None
        at2 = time_to_hours(a.get(end_time_col)) if end_time_col else None

        if at1 is None:
            at1 = 0.0
        if at2 is None or at2 <= at1:
            at2 = at1 + 2.0

        for j in range(i + 1, len(plot_df)):
            b = plot_df.iloc[j]
            bc = to_float(b.get(center_col))
            bbw = to_float(b.get(bw_col))
            if bc is None or bbw is None:
                continue

            b1 = bc - bbw / 2.0
            b2 = bc + bbw / 2.0
            bt1 = time_to_hours(b.get(start_time_col)) if start_time_col else None
            bt2 = time_to_hours(b.get(end_time_col)) if end_time_col else None

            if bt1 is None:
                bt1 = 0.0
            if bt2 is None or bt2 <= bt1:
                bt2 = bt1 + 2.0

            freq_overlap = max(a1, b1) < min(a2, b2)
            time_overlap = max(at1, bt1) < min(at2, bt2)

            if freq_overlap and time_overlap:
                conflicts.append(
                    {
                        "Row A": i + 1,
                        "Row B": j + 1,
                        "Equipment A": a.get(equipment_col, "") if equipment_col else "",
                        "Equipment B": b.get(equipment_col, "") if equipment_col else "",
                        "Unit A": a.get(unit_col, "") if unit_col else "",
                        "Unit B": b.get(unit_col, "") if unit_col else "",
                        "Center A": ac,
                        "Center B": bc,
                        "Bandwidth A": abw,
                        "Bandwidth B": bbw,
                        "Reason": "Frequency and time overlap",
                    }
                )

    return pd.DataFrame(conflicts)


def dataframe_to_xlsx(sheets: dict) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in sheets.items():
            safe_name = str(name)[:31] if str(name).strip() else "Sheet"
            normalize_columns(df, add_missing=True).to_excel(writer, sheet_name=safe_name, index=False)
    output.seek(0)
    return output.read()


def load_file(uploaded_file):
    name = uploaded_file.name.lower()

    if name.endswith(".csv"):
        return {"Imported": normalize_columns(pd.read_csv(uploaded_file), add_missing=True)}

    excel = pd.ExcelFile(uploaded_file)
    sheets = {}
    for sheet in excel.sheet_names:
        # Skip Dashboard on purpose.
        if str(sheet).strip().lower() == "dashboard":
            continue
        sheets[sheet] = normalize_columns(pd.read_excel(excel, sheet_name=sheet), add_missing=True)
    return sheets


def intervals_overlap(a1, a2, b1, b2) -> bool:
    return max(a1, b1) < min(a2, b2)


def format_time_hhmm(hours_float):
    hours_float = float(hours_float) % 24.0
    hh = int(hours_float)
    mm = int(round((hours_float - hh) * 60))
    if mm >= 60:
        hh = (hh + 1) % 24
        mm = 0
    return f"{hh:02d}{mm:02d}"


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


def frequency_rows_conflict(row_a, row_b, center_col, bw_col, start_time_col, end_time_col, guard_mhz=0.0):
    ac, abw, af1, af2 = row_frequency_interval(row_a, center_col, bw_col)
    bc, bbw, bf1, bf2 = row_frequency_interval(row_b, center_col, bw_col)

    if ac is None or bc is None:
        return False

    at1, at2 = row_window(row_a, start_time_col, end_time_col)
    bt1, bt2 = row_window(row_b, start_time_col, end_time_col)

    freq_overlap = intervals_overlap(af1 - guard_mhz, af2 + guard_mhz, bf1, bf2)
    time_overlap = intervals_overlap(at1, at2, bt1, bt2)

    return freq_overlap and time_overlap


def get_conflict_row_indexes(df: pd.DataFrame, guard_mhz=0.0):
    working = active_only(df, show_inactive=False)

    center_col = find_col(working, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(working, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_time_col = find_col(working, ["Start Time", "StartTime", "Start"])
    end_time_col = find_col(working, ["End Time", "EndTime", "End"])

    if center_col is None or bw_col is None:
        return set()

    conflict_indexes = set()

    for i in range(len(working)):
        row_a = working.iloc[i]
        for j in range(i + 1, len(working)):
            row_b = working.iloc[j]
            if frequency_rows_conflict(row_a, row_b, center_col, bw_col, start_time_col, end_time_col, guard_mhz):
                conflict_indexes.add(working.index[i])
                conflict_indexes.add(working.index[j])

    return conflict_indexes


def time_slot_is_open(df, moving_index, new_start, new_end, center_col, bw_col, start_time_col, end_time_col, guard_mhz=0.0):
    moving = df.loc[moving_index]
    moving_center, moving_bw, moving_f1, moving_f2 = row_frequency_interval(moving, center_col, bw_col)

    if moving_center is None:
        return False

    for idx, other in df.iterrows():
        if idx == moving_index:
            continue
        if not to_bool(other.get("Active"), True):
            continue

        oc, obw, of1, of2 = row_frequency_interval(other, center_col, bw_col)
        if oc is None:
            continue

        ot1, ot2 = row_window(other, start_time_col, end_time_col)

        # If frequencies do not overlap, time can overlap.
        if not intervals_overlap(moving_f1 - guard_mhz, moving_f2 + guard_mhz, of1, of2):
            continue

        # If frequencies overlap, new time cannot overlap.
        if intervals_overlap(new_start, new_end, ot1, ot2):
            return False

    return True


def frequency_is_open(candidate_center, candidate_bw, moving_index, df, center_col, bw_col, start_time_col, end_time_col, guard_mhz):
    candidate_start = candidate_center - candidate_bw / 2.0 - guard_mhz
    candidate_end = candidate_center + candidate_bw / 2.0 + guard_mhz

    moving_row = df.loc[moving_index]
    moving_t1, moving_t2 = row_window(moving_row, start_time_col, end_time_col)

    for idx, other in df.iterrows():
        if idx == moving_index:
            continue

        if not to_bool(other.get("Active"), True):
            continue

        other_center, other_bw, other_start, other_end = row_frequency_interval(other, center_col, bw_col)
        if other_center is None:
            continue

        other_t1, other_t2 = row_window(other, start_time_col, end_time_col)

        if not intervals_overlap(moving_t1, moving_t2, other_t1, other_t2):
            continue

        if intervals_overlap(candidate_start, candidate_end, other_start, other_end):
            return False

    return True


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


def smart_time_deconflict(df: pd.DataFrame, day_start: float = 6.0, day_end: float = 20.0, step_minutes: int = 30, guard_mhz: float = 0.0, max_passes: int = 5):
    """
    Time-first deconfliction.

    - Moves only Start Time / End Time.
    - Keeps center frequency and bandwidth unchanged.
    - Preserves original window length, defaulting to 2 hours.
    - Moves only active, unlocked rows.
    """

    out = normalize_columns(df, add_missing=True)
    out = recalc_start_end(out)

    center_col = find_col(out, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(out, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_time_col = find_col(out, ["Start Time", "StartTime", "Start"])
    end_time_col = find_col(out, ["End Time", "EndTime", "End"])
    equipment_col = find_col(out, ["Equipment"])
    unit_col = find_col(out, ["Unit"])
    tech_col = find_col(out, ["Tech"])

    if center_col is None or bw_col is None or start_time_col is None or end_time_col is None:
        return out, pd.DataFrame([{"Message": "Center, Bandwidth, Start Time, and End Time columns are required."}])

    moves = []
    previous_conflict_count = None

    for pass_number in range(1, max_passes + 1):
        conflict_table = detect_conflicts(out)
        conflict_count = len(conflict_table)

        if conflict_count == 0:
            break

        if previous_conflict_count is not None and conflict_count >= previous_conflict_count:
            break

        previous_conflict_count = conflict_count
        conflict_indexes = get_conflict_row_indexes(out, guard_mhz=guard_mhz)

        if not conflict_indexes:
            break

        ranked = []
        for idx in conflict_indexes:
            if idx not in out.index:
                continue

            row = out.loc[idx]

            if not to_bool(row.get("Active"), True):
                continue
            if to_bool(row.get("Locked"), False):
                continue

            old_start, old_end = row_window(row, start_time_col, end_time_col)
            window_hours = max(old_end - old_start, 0.25)
            ranked.append((idx, window_hours, old_start, old_end))

        ranked = sorted(ranked, key=lambda x: (-x[1], x[2]))

        moved_this_pass = 0

        for idx, window_hours, old_start, old_end in ranked:
            row = out.loc[idx]

            candidates = build_candidate_time_slots(
                day_start=day_start,
                day_end=day_end,
                window_hours=window_hours,
                step_minutes=step_minutes,
                old_start=old_start,
            )

            best_slot = None
            best_conflict_count = None

            for new_start, new_end in candidates:
                if abs(new_start - old_start) < 1e-9 and abs(new_end - old_end) < 1e-9:
                    continue

                if not time_slot_is_open(
                    df=out,
                    moving_index=idx,
                    new_start=new_start,
                    new_end=new_end,
                    center_col=center_col,
                    bw_col=bw_col,
                    start_time_col=start_time_col,
                    end_time_col=end_time_col,
                    guard_mhz=guard_mhz,
                ):
                    continue

                test = out.copy()
                test.at[idx, start_time_col] = format_time_hhmm(new_start)
                test.at[idx, end_time_col] = format_time_hhmm(new_end)
                test_conflicts = len(detect_conflicts(test))

                if best_conflict_count is None or test_conflicts < best_conflict_count:
                    best_conflict_count = test_conflicts
                    best_slot = (new_start, new_end)

                if test_conflicts < conflict_count:
                    break

            if best_slot is not None:
                before_conflicts = len(detect_conflicts(out))
                new_start, new_end = best_slot

                out.at[idx, start_time_col] = format_time_hhmm(new_start)
                out.at[idx, end_time_col] = format_time_hhmm(new_end)

                after_conflicts = len(detect_conflicts(out))

                moves.append(
                    {
                        "Pass": pass_number,
                        "Row": int(idx) + 1,
                        "Unit": row.get(unit_col, "") if unit_col else "",
                        "Equipment": row.get(equipment_col, "") if equipment_col else "",
                        "Tech": row.get(tech_col, "") if tech_col else "",
                        "Old Start Time": format_time_hhmm(old_start),
                        "Old End Time": format_time_hhmm(old_end),
                        "New Start Time": format_time_hhmm(new_start),
                        "New End Time": format_time_hhmm(new_end),
                        "Window Hours": round(window_hours, 3),
                        "Conflicts Before": before_conflicts,
                        "Conflicts After": after_conflicts,
                        "Action": "Moved time window; frequency unchanged",
                    }
                )

                moved_this_pass += 1

        if moved_this_pass == 0:
            break

    remaining_conflicts = len(detect_conflicts(out))

    if not moves:
        return out, pd.DataFrame(
            [
                {
                    "Message": "No safe time move found. Try widening the operating day, lowering step minutes, or unlocking rows.",
                    "Remaining Conflicts": remaining_conflicts,
                    "Day Start": day_start,
                    "Day End": day_end,
                    "Step Minutes": step_minutes,
                    "Guard MHz": guard_mhz,
                }
            ]
        )

    moves_df = pd.DataFrame(moves)
    moves_df["Remaining Conflicts After Time Planner"] = remaining_conflicts
    return out, moves_df


def smart_frequency_deconflict(df: pd.DataFrame, low_mhz: float, high_mhz: float, step_mhz: float, guard_mhz: float = 0.0, max_passes: int = 5):
    """
    Frequency deconfliction.

    - Uses ONLY active rows for conflict detection.
    - Inactive rows stay saved but are ignored.
    - Locked rows are not moved.
    - Start/End Time remain unchanged.
    - Bandwidth remains unchanged.
    - Moves center frequency to the nearest open slot inside the search range.
    """

    out = normalize_columns(df, add_missing=True)
    out = recalc_start_end(out)

    center_col = find_col(out, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(out, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_time_col = find_col(out, ["Start Time", "StartTime", "Start"])
    end_time_col = find_col(out, ["End Time", "EndTime", "End"])
    equipment_col = find_col(out, ["Equipment"])
    unit_col = find_col(out, ["Unit"])
    tech_col = find_col(out, ["Tech"])

    if center_col is None or bw_col is None:
        return out, pd.DataFrame([{"Message": "Center Frequency and Bandwidth columns are required."}])

    if step_mhz <= 0:
        return out, pd.DataFrame([{"Message": "Step MHz must be greater than 0."}])

    moves = []
    previous_conflict_count = None

    for pass_number in range(1, max_passes + 1):
        conflict_table = detect_conflicts(out)
        conflict_count = len(conflict_table)

        if conflict_count == 0:
            break

        if previous_conflict_count is not None and conflict_count >= previous_conflict_count:
            break

        previous_conflict_count = conflict_count
        conflict_indexes = get_conflict_row_indexes(out, guard_mhz=guard_mhz)

        if not conflict_indexes:
            break

        ranked_indexes = []
        for idx in conflict_indexes:
            if idx not in out.index:
                continue
            row = out.loc[idx]

            if not to_bool(row.get("Active"), True):
                continue
            if to_bool(row.get("Locked"), False):
                continue

            center, bw, f1, f2 = row_frequency_interval(row, center_col, bw_col)
            if center is None:
                continue

            ranked_indexes.append((idx, bw, center))

        ranked_indexes = sorted(ranked_indexes, key=lambda x: (-x[1], x[2]))

        moved_this_pass = 0

        for idx, bw, old_center in ranked_indexes:
            row = out.loc[idx]

            candidates = build_candidate_centers(
                low_mhz=low_mhz,
                high_mhz=high_mhz,
                step_mhz=step_mhz,
                bw_mhz=bw,
                old_center=old_center,
            )

            best_candidate = None
            best_conflict_count = None

            for candidate in candidates:
                if not frequency_is_open(
                    candidate_center=candidate,
                    candidate_bw=bw,
                    moving_index=idx,
                    df=out,
                    center_col=center_col,
                    bw_col=bw_col,
                    start_time_col=start_time_col,
                    end_time_col=end_time_col,
                    guard_mhz=guard_mhz,
                ):
                    continue

                test = out.copy()
                test.at[idx, center_col] = candidate
                test = recalc_start_end(test)
                test_conflicts = len(detect_conflicts(test))

                if best_conflict_count is None or test_conflicts < best_conflict_count:
                    best_conflict_count = test_conflicts
                    best_candidate = candidate

                if test_conflicts < conflict_count:
                    break

            if best_candidate is not None:
                before_conflicts = len(detect_conflicts(out))

                out.at[idx, center_col] = best_candidate
                out = recalc_start_end(out)

                after_conflicts = len(detect_conflicts(out))

                moves.append(
                    {
                        "Pass": pass_number,
                        "Row": int(idx) + 1,
                        "Unit": row.get(unit_col, "") if unit_col else "",
                        "Equipment": row.get(equipment_col, "") if equipment_col else "",
                        "Tech": row.get(tech_col, "") if tech_col else "",
                        "Old Center Frequency (MHz)": old_center,
                        "New Center Frequency (MHz)": best_candidate,
                        "Bandwidth (MHz)": bw,
                        "Start Time": row.get(start_time_col, "") if start_time_col else "",
                        "End Time": row.get(end_time_col, "") if end_time_col else "",
                        "Conflicts Before": before_conflicts,
                        "Conflicts After": after_conflicts,
                        "Action": "Moved center frequency; time window preserved",
                    }
                )

                moved_this_pass += 1

        if moved_this_pass == 0:
            break

    out = recalc_start_end(out)
    remaining_conflicts = len(detect_conflicts(out))

    if not moves:
        return out, pd.DataFrame(
            [
                {
                    "Message": "No safe open frequency move found. Try widening the search range, lowering the step size, or unlocking rows.",
                    "Remaining Conflicts": remaining_conflicts,
                    "Search Low MHz": low_mhz,
                    "Search High MHz": high_mhz,
                    "Step MHz": step_mhz,
                    "Guard MHz": guard_mhz,
                }
            ]
        )

    moves_df = pd.DataFrame(moves)
    moves_df["Remaining Conflicts After Frequency Planner"] = remaining_conflicts
    return out, moves_df


def smart_full_deconflict(df: pd.DataFrame, day_start: float, day_end: float, time_step_minutes: int, low_mhz: float, high_mhz: float, freq_step_mhz: float, guard_mhz: float = 0.0, max_passes: int = 5):
    """
    Full smart deconfliction:
    1. Try time deconfliction first.
    2. Then run frequency deconfliction on remaining conflicts.
    """

    starting_conflicts = len(detect_conflicts(df))

    time_df, time_moves = smart_time_deconflict(
        df,
        day_start=day_start,
        day_end=day_end,
        step_minutes=time_step_minutes,
        guard_mhz=guard_mhz,
        max_passes=max_passes,
    )

    after_time_conflicts = len(detect_conflicts(time_df))

    freq_df, freq_moves = smart_frequency_deconflict(
        time_df,
        low_mhz=low_mhz,
        high_mhz=high_mhz,
        step_mhz=freq_step_mhz,
        guard_mhz=guard_mhz,
        max_passes=max_passes,
    )

    final_conflicts = len(detect_conflicts(freq_df))

    if not time_moves.empty:
        time_moves = time_moves.copy()
        time_moves["Planner Stage"] = "1 - Time"
    if not freq_moves.empty:
        freq_moves = freq_moves.copy()
        freq_moves["Planner Stage"] = "2 - Frequency"

    all_moves = pd.concat([time_moves, freq_moves], ignore_index=True, sort=False)

    summary = pd.DataFrame(
        [
            {
                "Starting Conflicts": starting_conflicts,
                "After Time Deconfliction": after_time_conflicts,
                "Final Conflicts": final_conflicts,
                "Total Move Rows": len(all_moves),
                "Planner Mode": "Time first, then Frequency",
            }
        ]
    )

    if all_moves.empty:
        all_moves = summary

    return freq_df, all_moves, summary




# ============================================================
# UI
# ============================================================

st.title("Spectrum Planner")
st.caption("Presentation-safe version: no dashboard, Active filtering enforced, matching legend colors, vertical frequency labels.")

with st.sidebar:
    st.header("Controls")
    uploaded = st.file_uploader("Upload allocation workbook or CSV", type=["xlsx", "csv"])
    show_inactive = st.checkbox("Show inactive frequencies", value=False, key="show_inactive_rows")
    dark = st.checkbox("Dark visuals", value=True)
    st.divider()
    st.caption("Inactive rows are excluded from visuals, conflicts, maps, and planner unless Show inactive is enabled.")

if "sheets" not in st.session_state:
    st.session_state["sheets"] = {}

if uploaded is not None:
    st.session_state["sheets"] = load_file(uploaded)
    st.success(f"Loaded {len(st.session_state['sheets'])} workbook tab(s). Dashboard sheets are intentionally skipped.")

if not st.session_state["sheets"]:
    st.info("Upload your allocation workbook to begin.")
    st.stop()

sheet_names = list(st.session_state["sheets"].keys())
active_sheet = st.selectbox("Active sheet for plots/deconfliction", sheet_names)

current_df = st.session_state["sheets"][active_sheet].copy()
current_df = normalize_columns(current_df, add_missing=True)
current_df = recalc_start_end(current_df)

st.subheader("Shared allocation workbook")
st.caption("Use Active to turn rows on/off. Use Locked to prevent the auto-planner from moving a frequency.")

current_df = current_df.loc[:, ~pd.Index(current_df.columns).duplicated(keep="first")].copy()

edited_df = st.data_editor(
    current_df,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    key=f"editor_{active_sheet}",
)

edited_df = normalize_columns(edited_df, add_missing=True)
edited_df = recalc_start_end(edited_df)

c1, c2, c3 = st.columns([1, 1, 1])

with c1:
    if st.button("💾 Save shared changes", type="primary", use_container_width=True):
        st.session_state["sheets"][active_sheet] = edited_df
        st.success("Saved changes in this session.")

with c2:
    xlsx_bytes = dataframe_to_xlsx(st.session_state["sheets"])
    st.download_button(
        "Download workbook XLSX",
        data=xlsx_bytes,
        file_name="spectrum_planner_workbook.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

with c3:
    if st.button("Recalculate Start/End Frequency", use_container_width=True):
        st.session_state["sheets"][active_sheet] = recalc_start_end(edited_df)
        st.success("Recalculated Start/End Frequency from Center Frequency and Bandwidth.")
        st.rerun()

operational_df = active_only(edited_df, show_inactive=show_inactive)
conflict_df = detect_conflicts(edited_df)

m1, m2, m3 = st.columns(3)
m1.metric("Active rows in visuals", len(operational_df))
m2.metric("Inactive rows hidden", int((normalize_columns(edited_df)["Active"] == False).sum()))
m3.metric("Equipment conflicts", len(conflict_df))

tabs = st.tabs(
    [
        "Time × Frequency",
        "Power View",
        "Equipment Deconfliction",
        "Unit Deconfliction",
        "Sponsor Deconfliction",
        "Conflict Tables",
        "Smart Planner",
    ]
)

with tabs[0]:
    color_by = st.selectbox("Color boxes by", ["Tech", "Equipment", "Unit", "Sponsor"], index=0, key="tf_color")
    fig, plotted, rows_drawn = time_frequency_chart(edited_df, color_by=color_by, dark=dark)
    st.pyplot(fig, use_container_width=True)
    st.caption(f"Showing {len(plotted)} active row(s). Frequency labels are vertical.")

with tabs[1]:
    color_by = st.selectbox("Color boxes by", ["Tech", "Equipment", "Unit", "Sponsor"], index=0, key="power_color")
    fig, plotted = power_chart(edited_df, color_by=color_by, dark=dark)
    st.pyplot(fig, use_container_width=True)
    st.caption(f"Showing {len(plotted)} active row(s). Legend colors match box colors.")

with tabs[2]:
    fig, plotted, _ = time_frequency_chart(edited_df, color_by="Equipment", dark=dark, title="Time × Frequency — by Equipment")
    st.pyplot(fig, use_container_width=True)

with tabs[3]:
    fig, plotted, _ = time_frequency_chart(edited_df, color_by="Unit", dark=dark, title="Time × Frequency — by Unit")
    st.pyplot(fig, use_container_width=True)

with tabs[4]:
    fig, plotted, _ = time_frequency_chart(edited_df, color_by="Sponsor", dark=dark, title="Time × Frequency — by Sponsor")
    st.pyplot(fig, use_container_width=True)

with tabs[5]:
    st.subheader("Conflict Tables")
    if conflict_df.empty:
        st.success("No active equipment conflicts detected.")
    else:
        st.warning(f"{len(conflict_df)} active conflicts detected.")
        st.dataframe(conflict_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download conflicts CSV",
            data=conflict_df.to_csv(index=False).encode("utf-8"),
            file_name="conflict_table.csv",
            mime="text/csv",
            use_container_width=True,
        )

with tabs[6]:
    st.subheader("Smart Planner — Time First, Then Frequency")
    st.caption("Recommended workflow: deconflict by time first, then move frequencies only for conflicts that remain.")

    mode = st.radio(
        "Planner mode",
        [
            "Auto deconflict by time",
            "Auto deconflict by frequency",
            "Run full smart deconfliction",
        ],
        horizontal=True,
    )

    st.markdown("### Time Settings")
    t1, t2, t3 = st.columns(3)
    day_start = t1.number_input("Operating day start hour", value=6.0, min_value=0.0, max_value=23.75, step=0.5)
    day_end = t2.number_input("Operating day end hour", value=20.0, min_value=0.25, max_value=24.0, step=0.5)
    time_step = t3.number_input("Time step minutes", value=30, min_value=5, max_value=120, step=5)

    st.markdown("### Frequency Settings")
    p1, p2, p3, p4, p5 = st.columns(5)
    low = p1.number_input("Search low MHz", value=2200.0, step=1.0)
    high = p2.number_input("Search high MHz", value=2300.0, step=1.0)
    freq_step = p3.number_input("Frequency step MHz", value=1.0, min_value=0.001, step=0.5)
    guard = p4.number_input("Guard MHz", value=0.0, min_value=0.0, step=0.1)
    max_passes = p5.number_input("Max passes", value=5, min_value=1, max_value=20, step=1)

    if st.button("Run selected planner", type="primary", use_container_width=True):
        if mode == "Auto deconflict by time":
            new_df, moves = smart_time_deconflict(
                edited_df,
                day_start=day_start,
                day_end=day_end,
                step_minutes=int(time_step),
                guard_mhz=guard,
                max_passes=int(max_passes),
            )
            summary = pd.DataFrame(
                [
                    {
                        "Planner Mode": "Time Only",
                        "Final Conflicts": len(detect_conflicts(new_df)),
                        "Move Rows": len(moves),
                    }
                ]
            )

        elif mode == "Auto deconflict by frequency":
            new_df, moves = smart_frequency_deconflict(
                edited_df,
                low_mhz=low,
                high_mhz=high,
                step_mhz=freq_step,
                guard_mhz=guard,
                max_passes=int(max_passes),
            )
            summary = pd.DataFrame(
                [
                    {
                        "Planner Mode": "Frequency Only",
                        "Final Conflicts": len(detect_conflicts(new_df)),
                        "Move Rows": len(moves),
                    }
                ]
            )

        else:
            new_df, moves, summary = smart_full_deconflict(
                edited_df,
                day_start=day_start,
                day_end=day_end,
                time_step_minutes=int(time_step),
                low_mhz=low,
                high_mhz=high,
                freq_step_mhz=freq_step,
                guard_mhz=guard,
                max_passes=int(max_passes),
            )

        st.session_state["pending_planner_df"] = new_df
        st.session_state["pending_planner_moves"] = moves
        st.session_state["pending_planner_summary"] = summary

    if "pending_planner_summary" in st.session_state:
        st.markdown("### Planner Summary")
        st.dataframe(st.session_state["pending_planner_summary"], use_container_width=True, hide_index=True)

    if "pending_planner_moves" in st.session_state:
        st.markdown("### Planner Move Report")
        moves = st.session_state["pending_planner_moves"]

        if moves.empty:
            st.info("No moves were made.")
        else:
            st.dataframe(moves, use_container_width=True, hide_index=True)
            st.download_button(
                "Download planner move report CSV",
                data=moves.to_csv(index=False).encode("utf-8"),
                file_name="planner_move_report.csv",
                mime="text/csv",
                use_container_width=True,
            )

        apply_moves = st.checkbox("I reviewed the changes and want to apply them")
        if st.button("Apply planner changes", use_container_width=True):
            if not apply_moves:
                st.warning("Check the review box first.")
            else:
                st.session_state["sheets"][active_sheet] = st.session_state["pending_planner_df"]
                del st.session_state["pending_planner_df"]
                del st.session_state["pending_planner_moves"]
                if "pending_planner_summary" in st.session_state:
                    del st.session_state["pending_planner_summary"]
                st.success("Applied planner changes.")
                st.rerun()
