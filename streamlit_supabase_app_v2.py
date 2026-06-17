import streamlit as st
st.set_page_config(page_title="Spectrum Planner", layout="wide")

# - V15: Performance optimized workflow. No heavy recalculation while editing.
# - V14: Adds new user sign-up account creation for Supabase Authentication.
# - V13: Adds persistent login using browser cookies and Supabase session restore.
# - V12: Adds Supabase login + shared collaborative workbook persistence.

try:
    from streamlit_cookies_manager import EncryptedCookieManager
except Exception:
    EncryptedCookieManager = None

try:
    from supabase import create_client
except Exception:
    create_client = None


# - V11: True lower-power foreground visual mode with draw controls.
# - V9: Fixes lower-power foreground drawing with controlled z-order, transparency, and label priority.
# - V8: Adds workbook backup/restore and safer autosave-to-session workflow.
# - V7: Adds visual extraction/export buttons for PNG and all-visuals PDF.
# - V6: Smart Planner moved from tab into sidebar controls.
# - V5: Horizontal frequency labels + lower-power systems drawn in front.
import io
import re
import hashlib
import time
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_pdf import PdfPages


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




def sort_for_visual_front(df: pd.DataFrame) -> pd.DataFrame:
    """
    True visual draw order only. Data is not changed for saving.

    Matplotlib draws later rows on top. For 'Lower power in front':
      - high power rows are sorted first
      - low power rows are sorted last
    """
    out = df.copy()

    power_col = find_col(out, ["Power (W)", "PowerW", "Power"])
    bw_col = find_col(out, ["Bandwidth (MHz)", "Bandwidth", "BW"])

    out["_PlotPower"] = out[power_col].apply(lambda v: to_float(v, 0.0)) if power_col else 0.0
    out["_PlotBandwidth"] = out[bw_col].apply(lambda v: to_float(v, 0.0)) if bw_col else 0.0
    out["_OriginalOrder"] = range(len(out))

    draw_mode = st.session_state.get("visual_draw_order", "Lower power in front")

    if draw_mode == "Lower power in front":
        # High power first/background, low power last/foreground.
        out = out.sort_values(
            by=["_PlotPower", "_PlotBandwidth", "_OriginalOrder"],
            ascending=[False, False, True],
            kind="mergesort",
        )
    elif draw_mode == "Higher power in front":
        # Low power first/background, high power last/foreground.
        out = out.sort_values(
            by=["_PlotPower", "_PlotBandwidth", "_OriginalOrder"],
            ascending=[True, True, True],
            kind="mergesort",
        )
    else:
        out = out.sort_values("_OriginalOrder", kind="mergesort")

    return out.drop(columns=["_PlotPower", "_PlotBandwidth", "_OriginalOrder"], errors="ignore")


def visual_zorder_and_alpha(power_value, max_power):
    """
    Controlled z-order/alpha:
    - Lower power in front means low power gets higher zorder and stronger opacity.
    - High power becomes a transparent background layer.
    """
    draw_mode = st.session_state.get("visual_draw_order", "Lower power in front")

    high_alpha = float(st.session_state.get("high_power_alpha", 0.35))
    low_alpha = float(st.session_state.get("low_power_alpha", 0.95))

    power = to_float(power_value, 0.0)
    max_power = max(to_float(max_power, 1.0), 1.0)
    ratio = max(0.0, min(power / max_power, 1.0))

    if draw_mode == "Lower power in front":
        # High power: ratio near 1 -> low zorder, high transparency.
        # Low power: ratio near 0 -> high zorder, high opacity.
        alpha = high_alpha + (1.0 - ratio) * (low_alpha - high_alpha)
        zorder = 10 + int((1.0 - ratio) * 1000)
    elif draw_mode == "Higher power in front":
        alpha = low_alpha + ratio * (high_alpha - low_alpha)
        zorder = 10 + int(ratio * 1000)
    else:
        alpha = 0.78
        zorder = 100

    return zorder, max(0.05, min(alpha, 1.0))



def should_label_row(row, power_col, max_power, total_rows):
    """
    Label foreground rows more aggressively.
    In lower-power foreground mode, low-power rows keep labels.
    """
    if total_rows <= 80:
        return True

    power = to_float(row.get(power_col), 0.0) if power_col else 0.0
    max_power = max(to_float(max_power, 1.0), 1.0)
    ratio = power / max_power if max_power else 0.0

    draw_mode = st.session_state.get("visual_draw_order", "Lower power in front")

    if draw_mode == "Lower power in front":
        return ratio <= 0.70
    if draw_mode == "Higher power in front":
        return ratio >= 0.30

    return total_rows <= 120


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
    plot_df = sort_for_visual_front(plot_df)

    color_by = color_by if color_by in plot_df.columns else pick_color_field(plot_df, color_by)
    color_map = build_color_map(plot_df, color_by)

    center_col = find_col(plot_df, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(plot_df, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_time_col = find_col(plot_df, ["Start Time", "StartTime", "Start"])
    end_time_col = find_col(plot_df, ["End Time", "EndTime", "End"])
    power_col = find_col(plot_df, ["Power (W)", "PowerW", "Power"])

    max_power = 1.0
    if power_col is not None and len(plot_df):
        max_power = max([to_float(v, 0.0) for v in plot_df[power_col].tolist()] + [1.0])

    fig, ax = plt.subplots(figsize=(16, 7))
    fig.patch.set_facecolor("#111827" if dark else "white")
    ax.set_facecolor("#111827" if dark else "white")

    rows_drawn = 0
    total_rows = len(plot_df)

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

        zorder, alpha = visual_zorder_and_alpha(row.get(power_col) if power_col else 0.0, max_power)

        ax.add_patch(
            Rectangle(
                (center - bw / 2.0, start_time),
                bw,
                end_time - start_time,
                facecolor=color,
                edgecolor="#0F172A",
                linewidth=0.9,
                alpha=alpha,
                zorder=zorder,
            )
        )

        if should_label_row(row, power_col, max_power, total_rows):
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
    ax.set_title(title or f"Time × Frequency — by {color_by}", color="white" if dark else "black", fontsize=15, fontweight="bold")
    ax.set_xlabel("Frequency (MHz)", color="white" if dark else "black")
    ax.set_ylabel("Time (hours)", color="white" if dark else "black")
    ax.tick_params(colors="white" if dark else "black")
    ax.grid(True, alpha=0.18, zorder=0)

    add_legend(ax, color_by, color_map, dark=dark)
    fig.tight_layout()

    return fig, plot_df, rows_drawn


def power_chart(df: pd.DataFrame, color_by="Tech", dark=True):
    plot_df = active_only(df, show_inactive=st.session_state.get("show_inactive_rows", False))
    plot_df = sort_for_visual_front(plot_df)

    color_by = color_by if color_by in plot_df.columns else pick_color_field(plot_df, color_by)
    color_map = build_color_map(plot_df, color_by)

    center_col = find_col(plot_df, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(plot_df, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    power_col = find_col(plot_df, ["Power (W)", "PowerW", "Power"])

    max_power = 1.0
    if power_col is not None and len(plot_df):
        max_power = max([to_float(v, 0.0) for v in plot_df[power_col].tolist()] + [1.0])

    fig, ax = plt.subplots(figsize=(16, 7))
    fig.patch.set_facecolor("#111827" if dark else "white")
    ax.set_facecolor("#111827" if dark else "white")

    total_rows = len(plot_df)

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

        zorder, alpha = visual_zorder_and_alpha(power, max_power)

        ax.add_patch(
            Rectangle(
                (center - bw / 2.0, 0),
                bw,
                power,
                facecolor=color,
                edgecolor="#0F172A",
                linewidth=0.9,
                alpha=alpha,
                zorder=zorder,
            )
        )

        if should_label_row(row, power_col, max_power, total_rows):
            ax.text(
                center,
                power / 2.0,
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

    ax.autoscale()
    ax.set_title(f"Frequency Allocation vs Power — by {color_by}", color="white" if dark else "black", fontsize=15, fontweight="bold")
    ax.set_xlabel("Frequency (MHz)", color="white" if dark else "black")
    ax.set_ylabel("Power (W)", color="white" if dark else "black")
    ax.tick_params(colors="white" if dark else "black")
    ax.grid(True, alpha=0.18, zorder=0)

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



def timestamp_string():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def update_active_sheet_in_session(sheet_name, df):
    """Save the edited sheet into Streamlit session immediately."""
    if "sheets" not in st.session_state:
        st.session_state["sheets"] = {}
    st.session_state["sheets"][sheet_name] = normalize_columns(recalc_start_end(df), add_missing=True)
    st.session_state["last_autosave_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_backup_workbook_bytes():
    """Create a backup workbook from the current session sheets."""
    sheets = st.session_state.get("sheets", {})
    return dataframe_to_xlsx(sheets)


def restore_backup_file(uploaded_backup):
    """Restore workbook sheets from a user-uploaded backup XLSX/CSV."""
    restored = load_file(uploaded_backup)
    st.session_state["sheets"] = restored
    st.session_state["last_autosave_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return restored


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

    starting_conflicts = len(detect_conflicts_fast(df))

    time_df, time_moves = smart_time_deconflict(
        df,
        day_start=day_start,
        day_end=day_end,
        step_minutes=time_step_minutes,
        guard_mhz=guard_mhz,
        max_passes=max_passes,
    )

    after_time_conflicts = len(detect_conflicts_fast(time_df))

    freq_df, freq_moves = smart_frequency_deconflict(
        time_df,
        low_mhz=low_mhz,
        high_mhz=high_mhz,
        step_mhz=freq_step_mhz,
        guard_mhz=guard_mhz,
        max_passes=max_passes,
    )

    final_conflicts = len(detect_conflicts_fast(freq_df))

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





def figure_to_png_bytes(fig, dpi=220):
    """Convert a matplotlib figure to PNG bytes for download."""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    buffer.seek(0)
    return buffer.getvalue()


def figures_to_pdf_bytes(figures):
    """Convert multiple matplotlib figures into a single PDF bytes object."""
    buffer = io.BytesIO()
    with PdfPages(buffer) as pdf:
        for fig in figures:
            pdf.savefig(fig, bbox_inches="tight", facecolor=fig.get_facecolor())
    buffer.seek(0)
    return buffer.getvalue()


def safe_filename(text):
    text = str(text or "visual").strip()
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "visual"


def visual_download_button(fig, label, filename, key):
    """Standard single visual PNG export button."""
    png_bytes = figure_to_png_bytes(fig)
    st.download_button(
        label=label,
        data=png_bytes,
        file_name=filename,
        mime="image/png",
        use_container_width=True,
        key=key,
    )


def build_all_visuals_for_export(df, dark=True):
    """
    Builds the main briefing visuals without displaying them:
    - Time x Frequency by Tech
    - Power View by Tech
    - Equipment Deconfliction
    - Unit Deconfliction
    - Sponsor Deconfliction
    """
    figures = []

    fig1, _, _ = time_frequency_chart(df, color_by="Tech", dark=dark, title="Time x Frequency - by Tech")
    figures.append(fig1)

    fig2, _ = power_chart(df, color_by="Tech", dark=dark)
    figures.append(fig2)

    fig3, _, _ = time_frequency_chart(df, color_by="Equipment", dark=dark, title="Time x Frequency - by Equipment")
    figures.append(fig3)

    fig4, _, _ = time_frequency_chart(df, color_by="Unit", dark=dark, title="Time x Frequency - by Unit")
    figures.append(fig4)

    fig5, _, _ = time_frequency_chart(df, color_by="Sponsor", dark=dark, title="Time x Frequency - by Sponsor")
    figures.append(fig5)

    return figures



# ============================================================
# V12 Supabase Collaboration Helpers
# ============================================================

DEFAULT_PROJECT_ID = "main_spectrum_workbook"

def get_secret_value(*names, default=None):
    for name in names:
        try:
            if name in st.secrets:
                return st.secrets[name]
        except Exception:
            pass

        try:
            value = st.secrets
            for part in name.split("."):
                value = value[part]
            return value
        except Exception:
            pass

    return default



# ============================================================
# V13 Persistent Login Helpers
# ============================================================

def get_cookie_password():
    return str(get_secret_value("COOKIE_PASSWORD", "cookie.password", default="change-this-cookie-password-spectrum-planner"))


def get_login_cookies():
    if EncryptedCookieManager is None:
        return None

    if "login_cookies" in st.session_state:
        return st.session_state["login_cookies"]

    cookies = EncryptedCookieManager(
        prefix="spectrum_planner/",
        password=get_cookie_password(),
    )
    st.session_state["login_cookies"] = cookies
    return cookies


def cookies_ready_or_stop():
    cookies = get_login_cookies()
    if cookies is None:
        return None

    if not cookies.ready():
        st.stop()

    return cookies


def save_login_cookie(email, access_token=None, refresh_token=None):
    cookies = get_login_cookies()
    if cookies is None:
        return

    cookies["remembered_email"] = str(email or "")

    if access_token:
        cookies["sb_access_token"] = str(access_token)

    if refresh_token:
        cookies["sb_refresh_token"] = str(refresh_token)

    cookies.save()


def clear_login_cookie():
    cookies = get_login_cookies()
    if cookies is None:
        return

    for key in ["remembered_email", "sb_access_token", "sb_refresh_token"]:
        try:
            del cookies[key]
        except Exception:
            pass

    cookies.save()


def restore_login_from_cookie():
    if "sb_user_email" in st.session_state:
        return True

    cookies = get_login_cookies()
    if cookies is None:
        return False

    if not cookies.ready():
        st.stop()

    access_token = cookies.get("sb_access_token")
    refresh_token = cookies.get("sb_refresh_token")
    remembered_email = cookies.get("remembered_email")

    if not access_token or not refresh_token:
        return False

    client = get_supabase_client()
    if client is None:
        return False

    try:
        client.auth.set_session(access_token, refresh_token)
        st.session_state["sb_user_email"] = remembered_email or "remembered_user"
        st.session_state["sb_session_restored"] = True
        return True
    except Exception:
        clear_login_cookie()
        return False


def supabase_configured():
    url = get_secret_value("SUPABASE_URL", "supabase.url")
    key = get_secret_value("SUPABASE_ANON_KEY", "supabase.anon_key")
    return bool(url and key and create_client is not None)


def get_supabase_client():
    if "supabase_client" in st.session_state:
        return st.session_state["supabase_client"]

    url = get_secret_value("SUPABASE_URL", "supabase.url")
    key = get_secret_value("SUPABASE_ANON_KEY", "supabase.anon_key")

    if not url or not key or create_client is None:
        return None

    client = create_client(url, key)
    st.session_state["supabase_client"] = client
    return client


def workbook_to_jsonable(sheets: dict):
    payload = {}
    for sheet_name, df in sheets.items():
        safe_df = normalize_columns(recalc_start_end(df), add_missing=True)
        safe_df = safe_df.where(pd.notnull(safe_df), None)
        payload[str(sheet_name)] = safe_df.to_dict(orient="records")
    return payload


def workbook_from_jsonable(payload):
    sheets = {}
    if not isinstance(payload, dict):
        return sheets

    for sheet_name, records in payload.items():
        try:
            df = pd.DataFrame(records if isinstance(records, list) else [])
            sheets[str(sheet_name)] = normalize_columns(df, add_missing=True)
        except Exception:
            sheets[str(sheet_name)] = normalize_columns(pd.DataFrame(), add_missing=True)

    return sheets


def login_supabase(email, password):
    client = get_supabase_client()
    if client is None:
        return False, "Supabase is not configured."

    try:
        res = client.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state["sb_user_email"] = email
        st.session_state["sb_session"] = res

        access_token = None
        refresh_token = None

        try:
            access_token = res.session.access_token
            refresh_token = res.session.refresh_token
        except Exception:
            pass

        save_login_cookie(email, access_token, refresh_token)

        return True, "Logged in. Your login will stay active after refresh."
    except Exception as exc:
        return False, f"Login failed: {exc}"



def signup_supabase(email, password):
    client = get_supabase_client()
    if client is None:
        return False, "Supabase is not configured."

    if not email or not password:
        return False, "Email and password are required."

    if len(password) < 6:
        return False, "Password must be at least 6 characters."

    try:
        res = client.auth.sign_up({"email": email, "password": password})

        # If email confirmation is disabled, Supabase can return a session immediately.
        try:
            if getattr(res, "session", None):
                st.session_state["sb_user_email"] = email
                st.session_state["sb_session"] = res
                save_login_cookie(
                    email,
                    getattr(res.session, "access_token", None),
                    getattr(res.session, "refresh_token", None),
                )
                return True, "Account created and logged in."
        except Exception:
            pass

        return True, "Account created. If email confirmation is enabled, check your email before logging in."
    except Exception as exc:
        return False, f"Account creation failed: {exc}"


def logout_supabase():
    client = get_supabase_client()
    try:
        if client is not None:
            client.auth.sign_out()
    except Exception:
        pass

    clear_login_cookie()

    for key in ["sb_user_email", "sb_session", "sb_session_restored"]:
        if key in st.session_state:
            del st.session_state[key]


def ensure_shared_workbook_table_note():
    return """
Supabase table required:

```sql
create table if not exists shared_workbooks (
  project_id text primary key,
  workbook jsonb not null,
  updated_by text,
  updated_at timestamptz default now()
);
```

Add `SUPABASE_URL` and `SUPABASE_ANON_KEY` to Streamlit secrets.
Users can create accounts in the app. In Supabase Authentication settings, choose whether email confirmation is required.
"""


def load_shared_workbook(project_id=DEFAULT_PROJECT_ID):
    client = get_supabase_client()
    if client is None:
        return False, "Supabase is not configured."

    try:
        result = client.table("shared_workbooks").select("*").eq("project_id", project_id).limit(1).execute()
        rows = result.data or []

        if not rows:
            return False, "No shared workbook exists yet. Upload a workbook and click Save shared."

        payload = rows[0].get("workbook", {})
        st.session_state["sheets"] = workbook_from_jsonable(payload)
        st.session_state["shared_project_id"] = project_id
        st.session_state["shared_last_loaded"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state["shared_last_updated_by"] = rows[0].get("updated_by")
        st.session_state["shared_last_updated_at"] = rows[0].get("updated_at")
        return True, f"Loaded shared workbook '{project_id}'."
    except Exception as exc:
        return False, f"Load failed: {exc}"


def save_shared_workbook(project_id=DEFAULT_PROJECT_ID):
    client = get_supabase_client()
    if client is None:
        return False, "Supabase is not configured."

    sheets = st.session_state.get("sheets", {})
    if not sheets:
        return False, "No workbook sheets are loaded."

    payload = workbook_to_jsonable(sheets)
    email = st.session_state.get("sb_user_email", "unknown")

    try:
        row = {
            "project_id": project_id,
            "workbook": payload,
            "updated_by": email,
            "updated_at": datetime.utcnow().isoformat(),
        }

        client.table("shared_workbooks").upsert(row, on_conflict="project_id").execute()
        st.session_state["shared_project_id"] = project_id
        st.session_state["shared_last_saved"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return True, f"Saved shared workbook '{project_id}'."
    except Exception as exc:
        return False, f"Save failed: {exc}"


def collaborative_mode_enabled():
    return bool(st.session_state.get("sb_user_email")) and supabase_configured()



# ============================================================
# V15 Performance / Stability Helpers
# ============================================================

MAX_CONFLICTS_DISPLAY = 2500
MAX_PLANNER_ROWS = 1200
MAX_VISUAL_ROWS_WARNING = 800

def recalc_start_end_fast(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fast vectorized Start/End Frequency calculation.
    This replaces slow row-by-row recalculation.
    """
    out = normalize_columns(df, add_missing=True)

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

    centers = pd.to_numeric(out[center_col], errors="coerce")
    bws = pd.to_numeric(out[bw_col], errors="coerce")
    valid = centers.notna() & bws.notna() & (bws > 0)

    out.loc[valid, start_col] = (centers[valid] - bws[valid] / 2.0).round(6)
    out.loc[valid, end_col] = (centers[valid] + bws[valid] / 2.0).round(6)

    return normalize_columns(out, add_missing=True)


def detect_conflicts_fast(df: pd.DataFrame, max_conflicts=MAX_CONFLICTS_DISPLAY):
    """
    Faster conflict detection:
    - Active rows only.
    - Sorts by frequency start.
    - Stops after max_conflicts to prevent freezing.
    """
    working = active_only(df, show_inactive=False)

    center_col = find_col(working, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(working, ["Bandwidth (MHz)", "Bandwidth", "BW"])
    start_time_col = find_col(working, ["Start Time", "StartTime", "Start"])
    end_time_col = find_col(working, ["End Time", "EndTime", "End"])
    equipment_col = find_col(working, ["Equipment"])
    unit_col = find_col(working, ["Unit"])
    tech_col = find_col(working, ["Tech"])

    if center_col is None or bw_col is None or working.empty:
        return pd.DataFrame()

    records = []
    for idx, row in working.iterrows():
        center = to_float(row.get(center_col))
        bw = to_float(row.get(bw_col))

        if center is None or bw is None or bw <= 0:
            continue

        t1 = time_to_hours(row.get(start_time_col)) if start_time_col else None
        t2 = time_to_hours(row.get(end_time_col)) if end_time_col else None

        if t1 is None:
            t1 = 0.0
        if t2 is None or t2 <= t1:
            t2 = t1 + 2.0

        records.append(
            {
                "index": idx,
                "row_number": int(idx) + 1,
                "center": center,
                "bw": bw,
                "f1": center - bw / 2.0,
                "f2": center + bw / 2.0,
                "t1": t1,
                "t2": t2,
                "equipment": row.get(equipment_col, "") if equipment_col else "",
                "unit": row.get(unit_col, "") if unit_col else "",
                "tech": row.get(tech_col, "") if tech_col else "",
            }
        )

    records = sorted(records, key=lambda r: r["f1"])
    conflicts = []

    for i, a in enumerate(records):
        for b in records[i + 1:]:
            if b["f1"] >= a["f2"]:
                break

            time_overlap = max(a["t1"], b["t1"]) < min(a["t2"], b["t2"])
            if not time_overlap:
                continue

            conflicts.append(
                {
                    "Row A": a["row_number"],
                    "Row B": b["row_number"],
                    "Equipment A": a["equipment"],
                    "Equipment B": b["equipment"],
                    "Unit A": a["unit"],
                    "Unit B": b["unit"],
                    "Tech A": a["tech"],
                    "Tech B": b["tech"],
                    "Center A": a["center"],
                    "Center B": b["center"],
                    "Bandwidth A": a["bw"],
                    "Bandwidth B": b["bw"],
                    "Reason": "Frequency and time overlap",
                }
            )

            if len(conflicts) >= max_conflicts:
                conflicts.append(
                    {
                        "Row A": "",
                        "Row B": "",
                        "Equipment A": "",
                        "Equipment B": "",
                        "Unit A": "",
                        "Unit B": "",
                        "Tech A": "",
                        "Tech B": "",
                        "Center A": "",
                        "Center B": "",
                        "Bandwidth A": "",
                        "Bandwidth B": "",
                        "Reason": f"Stopped at {max_conflicts} conflicts to prevent app freeze. Filter to a smaller band/sheet or run planner in smaller sections.",
                    }
                )
                return pd.DataFrame(conflicts)

    return pd.DataFrame(conflicts)


def sheet_state_key(sheet_name, suffix):
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", str(sheet_name))
    return f"{clean}_{suffix}"


def store_analysis(sheet_name, conflict_df):
    st.session_state[sheet_state_key(sheet_name, "conflicts")] = conflict_df
    st.session_state[sheet_state_key(sheet_name, "analysis_time")] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_stored_analysis(sheet_name):
    return st.session_state.get(sheet_state_key(sheet_name, "conflicts"), pd.DataFrame())


def clear_stored_analysis(sheet_name):
    for suffix in ["conflicts", "analysis_time"]:
        key = sheet_state_key(sheet_name, suffix)
        if key in st.session_state:
            del st.session_state[key]


def store_visual_ready_sheet(sheet_name, df):
    st.session_state[sheet_state_key(sheet_name, "visual_df")] = recalc_start_end_fast(df)
    st.session_state[sheet_state_key(sheet_name, "visual_time")] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_visual_ready_sheet(sheet_name, fallback_df):
    return st.session_state.get(sheet_state_key(sheet_name, "visual_df"), fallback_df)


# ============================================================
# UI
# ============================================================

st.title("Spectrum Planner")

if collaborative_mode_enabled():
    st.success(f"Collaborative mode active — logged in as {st.session_state.get('sb_user_email')}. Use Save shared changes to publish edits.")
else:
    st.warning("Upload/download mode active. Log in through the sidebar to use the shared collaborative workbook.")

st.caption("Presentation-safe version: no dashboard, Active filtering enforced, matching legend colors, horizontal frequency labels, Smart Planner in Controls.")
st.warning("Important: Download a backup workbook before logging out. Session-only changes can be lost if the app closes or reloads.")

with st.sidebar:
    st.header("Login / Collaboration")
    st.caption("Login is remembered after page refresh when cookies are available.")

    if not supabase_configured():
        st.warning("Collaboration is not configured yet. Upload/download mode still works.")
        with st.expander("Supabase setup SQL"):
            st.markdown(ensure_shared_workbook_table_note())
    else:
        if "sb_user_email" not in st.session_state:
            auth_mode = st.radio(
                "Account option",
                ["Log in", "Create new user"],
                key="auth_mode",
            )

            login_email = st.text_input("Email", key="login_email")
            login_password = st.text_input("Password", type="password", key="login_password")

            if auth_mode == "Log in":
                if st.button("Log in", use_container_width=True):
                    ok, msg = login_supabase(login_email, login_password)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

            else:
                login_password_confirm = st.text_input(
                    "Confirm password",
                    type="password",
                    key="login_password_confirm",
                )

                if st.button("Create account", use_container_width=True):
                    if login_password != login_password_confirm:
                        st.error("Passwords do not match.")
                    else:
                        ok, msg = signup_supabase(login_email, login_password)
                        if ok:
                            st.success(msg)
                            if "sb_user_email" in st.session_state:
                                st.rerun()
                        else:
                            st.error(msg)

                st.caption("If Supabase email confirmation is enabled, users must confirm their email before logging in.")
        else:
            st.success(f"Logged in: {st.session_state['sb_user_email']}")
            if st.session_state.get("sb_session_restored"):
                st.caption("Session restored from browser cookie.")

            if st.button("Log out", use_container_width=True):
                logout_supabase()
                st.rerun()

            project_id = st.text_input(
                "Shared workbook ID",
                value=st.session_state.get("shared_project_id", DEFAULT_PROJECT_ID),
                key="shared_project_id_input",
            )

            c_load, c_save = st.columns(2)
            with c_load:
                if st.button("Load shared", use_container_width=True):
                    ok, msg = load_shared_workbook(project_id)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

            with c_save:
                if st.button("Save shared", use_container_width=True):
                    ok, msg = save_shared_workbook(project_id)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

            if "shared_last_loaded" in st.session_state:
                st.caption(f"Loaded: {st.session_state['shared_last_loaded']}")
            if "shared_last_saved" in st.session_state:
                st.caption(f"Saved: {st.session_state['shared_last_saved']}")
            if st.session_state.get("shared_last_updated_by"):
                st.caption(f"Last updated by: {st.session_state.get('shared_last_updated_by')}")

    st.divider()

    st.header("Controls")
    uploaded = st.file_uploader("Upload allocation workbook or CSV", type=["xlsx", "csv"])
    show_inactive = st.checkbox("Show inactive frequencies", value=False, key="show_inactive_rows")
    dark = st.checkbox("Dark visuals", value=True)
    st.divider()
    st.caption("Inactive rows are excluded from visuals, conflicts, maps, and planner unless Show inactive is enabled.")

    st.divider()
    st.header("Performance")
    st.caption("Large workbook mode is enabled.")
    st.caption("Edits do not trigger automatic conflict analysis or visual rebuilds.")
    st.caption("Use the numbered workflow buttons after editing.")


    st.divider()
    st.header("Visual Layering")
    draw_mode = st.selectbox(
        "Draw order",
        [
            "Lower power in front",
            "Higher power in front",
            "Original row order",
        ],
        index=0,
        key="visual_draw_order",
    )
    high_power_alpha = st.slider(
        "High-power background transparency",
        min_value=0.15,
        max_value=0.95,
        value=0.35,
        step=0.05,
        key="high_power_alpha",
    )
    low_power_alpha = st.slider(
        "Low-power foreground opacity",
        min_value=0.30,
        max_value=1.00,
        value=0.95,
        step=0.05,
        key="low_power_alpha",
    )


    st.divider()
    st.header("Backup / Restore")
    st.warning("Download a backup before logging out. Streamlit sessions can clear when you leave the app.")

    if st.session_state.get("sheets"):
        backup_bytes = build_backup_workbook_bytes()
        st.download_button(
            "Download Backup Workbook",
            data=backup_bytes,
            file_name=f"spectrum_planner_backup_{timestamp_string()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="sidebar_backup_download",
        )

    restore_file = st.file_uploader(
        "Restore from backup",
        type=["xlsx", "csv"],
        key="restore_backup_file",
    )

    if restore_file is not None:
        restore_backup_file(restore_file)
        st.success("Backup restored.")
        st.rerun()

    if "last_autosave_time" in st.session_state:
        st.caption(f"Last session save: {st.session_state['last_autosave_time']}")


if "sheets" not in st.session_state:
    st.session_state["sheets"] = {}

if uploaded is not None:
    st.session_state["sheets"] = load_file(uploaded)
    st.success(f"Loaded {len(st.session_state['sheets'])} workbook tab(s). Dashboard sheets are intentionally skipped.")

if not st.session_state["sheets"]:
    st.info("Log in and click Load shared, or upload a workbook to begin. After uploading, click Save shared in the sidebar to make it the working collaborative file.")
    st.stop()

sheet_names = list(st.session_state["sheets"].keys())
active_sheet = st.selectbox("Active sheet for plots/deconfliction", sheet_names)

current_df = st.session_state["sheets"][active_sheet].copy()
current_df = normalize_columns(current_df, add_missing=True)
current_df = recalc_start_end(current_df)

st.info("Large sheet performance note: this version will not recalculate conflicts or visuals while you type. Use the Performance Workflow buttons below.")
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

# V15 performance:
# Do NOT recalculate Start/End Frequency automatically on every cell edit.
# This prevents freezing when changing Bandwidth on large PCC 6 workbooks.
# Use the buttons below to save, recalculate, analyze, or generate visuals.

c1, c2, c3 = st.columns([1, 1, 1])

with c1:
    if st.button("💾 Save shared changes", type="primary", use_container_width=True):
        update_active_sheet_in_session(active_sheet, edited_df)
        msg = "Saved changes in this session."
        if collaborative_mode_enabled():
            ok, shared_msg = save_shared_workbook(st.session_state.get("shared_project_id_input", DEFAULT_PROJECT_ID))
            if ok:
                msg += " Also saved to the shared collaborative workbook."
            else:
                st.warning(shared_msg)
        st.success(msg)

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
    checkpoint_bytes = build_backup_workbook_bytes()
    st.download_button(
        "Save version checkpoint",
        data=checkpoint_bytes,
        file_name=f"spectrum_planner_checkpoint_{timestamp_string()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key="main_checkpoint_download",
    )

c4 = st.container()

with c4:
    if st.button("Recalculate Start/End Frequency", use_container_width=True):
        st.session_state["sheets"][active_sheet] = recalc_start_end(edited_df)
        st.success("Recalculated Start/End Frequency from Center Frequency and Bandwidth.")
        st.rerun()


# ============================================================
# Manual performance workflow
# ============================================================

st.subheader("Performance Workflow")
st.caption("For large PCC 6 workbooks: edit first, then manually save, recalculate, analyze, and generate visuals.")

w1, w2, w3, w4 = st.columns(4)

with w1:
    if st.button("1. Save edits", type="primary", use_container_width=True):
        update_active_sheet_in_session(active_sheet, edited_df)
        clear_stored_analysis(active_sheet)
        st.success("Edits saved to session. Analysis cache cleared.")

with w2:
    if st.button("2. Recalculate frequencies", use_container_width=True):
        recalculated = recalc_start_end_fast(edited_df)
        update_active_sheet_in_session(active_sheet, recalculated)
        clear_stored_analysis(active_sheet)
        st.success("Start/End Frequency recalculated from Center Frequency and Bandwidth.")
        st.rerun()

with w3:
    if st.button("3. Analyze conflicts", use_container_width=True):
        with st.spinner("Analyzing conflicts..."):
            analysis_df = recalc_start_end_fast(edited_df)
            conflict_results = detect_conflicts_fast(analysis_df)
            store_analysis(active_sheet, conflict_results)
        st.success(f"Conflict analysis complete: {len(conflict_results)} rows.")

with w4:
    if st.button("4. Generate visuals", use_container_width=True):
        store_visual_ready_sheet(active_sheet, edited_df)
        st.success("Visuals updated from the current saved sheet.")

visual_df = get_visual_ready_sheet(active_sheet, edited_df)
conflict_df = get_stored_analysis(active_sheet)


operational_df = active_only(visual_df, show_inactive=show_inactive)
conflict_df = get_stored_analysis(active_sheet)

m1, m2, m3 = st.columns(3)
m1.metric("Active rows in visuals", len(operational_df))
m2.metric("Inactive rows hidden", int((normalize_columns(edited_df)["Active"] == False).sum()))
m3.metric("Equipment conflicts", len(conflict_df) if isinstance(conflict_df, pd.DataFrame) and not conflict_df.empty else "Not analyzed")

with st.expander("Extract / Export Visuals", expanded=False):
    st.caption("Export briefing visuals as PNG or one combined PDF. Exports use the active sheet and current Active filters.")
    e1, e2 = st.columns(2)

    with e1:
        if st.button("Prepare all visuals for PDF", use_container_width=True):
            st.session_state["export_visual_figures"] = build_all_visuals_for_export(visual_df, dark=dark)
            st.success("All visuals prepared. Use the PDF download button.")

    with e2:
        if "export_visual_figures" in st.session_state:
            pdf_bytes = figures_to_pdf_bytes(st.session_state["export_visual_figures"])
            st.download_button(
                "Download all visuals PDF",
                data=pdf_bytes,
                file_name=f"{safe_filename(active_sheet)}_all_visuals.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="download_all_visuals_pdf",
            )
        else:
            st.info("Click Prepare all visuals for PDF first.")



# ============================================================
# Smart Planner moved into Controls
# ============================================================

with st.sidebar.expander("Smart Planner", expanded=False):
    st.caption("Recommended: run time first, then frequency. Locked rows will not move. Inactive rows are ignored.")

    planner_mode = st.radio(
        "Planner mode",
        [
            "Auto deconflict by time",
            "Auto deconflict by frequency",
            "Run full smart deconfliction",
        ],
        key="sidebar_planner_mode",
    )

    st.markdown("**Time settings**")
    day_start = st.number_input(
        "Operating day start hour",
        value=6.0,
        min_value=0.0,
        max_value=23.75,
        step=0.5,
        key="sidebar_day_start",
    )
    day_end = st.number_input(
        "Operating day end hour",
        value=20.0,
        min_value=0.25,
        max_value=24.0,
        step=0.5,
        key="sidebar_day_end",
    )
    time_step = st.number_input(
        "Time step minutes",
        value=30,
        min_value=5,
        max_value=120,
        step=5,
        key="sidebar_time_step",
    )

    st.markdown("**Frequency settings**")
    low = st.number_input("Search low MHz", value=2200.0, step=1.0, key="sidebar_low_mhz")
    high = st.number_input("Search high MHz", value=2300.0, step=1.0, key="sidebar_high_mhz")
    freq_step = st.number_input(
        "Frequency step MHz",
        value=1.0,
        min_value=0.001,
        step=0.5,
        key="sidebar_freq_step",
    )
    guard = st.number_input(
        "Guard MHz",
        value=0.0,
        min_value=0.0,
        step=0.1,
        key="sidebar_guard_mhz",
    )
    max_passes = st.number_input(
        "Max passes",
        value=5,
        min_value=1,
        max_value=20,
        step=1,
        key="sidebar_max_passes",
    )

    if st.button("Run Smart Planner", type="primary", use_container_width=True):
        if len(edited_df) > MAX_PLANNER_ROWS:
            st.error(f"Planner stopped to prevent freezing: {len(edited_df)} rows loaded. Run planner by band/sheet or reduce below {MAX_PLANNER_ROWS} rows.")
            st.stop()
        if planner_mode == "Auto deconflict by time":
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
                        "Starting Conflicts": len(conflict_df),
                        "Final Conflicts": len(detect_conflicts_fast(new_df)),
                        "Move Rows": len(moves),
                    }
                ]
            )

        elif planner_mode == "Auto deconflict by frequency":
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
                        "Starting Conflicts": len(conflict_df),
                        "Final Conflicts": len(detect_conflicts_fast(new_df)),
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
        st.session_state["planner_panel_open"] = True
        st.success("Planner complete. Review results below the workbook.")




if "pending_planner_summary" in st.session_state:
    st.subheader("Smart Planner Results")

    st.markdown("**Summary**")
    st.dataframe(st.session_state["pending_planner_summary"], use_container_width=True, hide_index=True)

    if "pending_planner_moves" in st.session_state:
        moves = st.session_state["pending_planner_moves"]

        st.markdown("**Move Report**")
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

        apply_moves = st.checkbox("I reviewed the Smart Planner changes and want to apply them")
        a1, a2 = st.columns(2)

        with a1:
            if st.button("Apply Smart Planner changes", type="primary", use_container_width=True):
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

        with a2:
            if st.button("Clear Smart Planner results", use_container_width=True):
                for k in ["pending_planner_df", "pending_planner_moves", "pending_planner_summary"]:
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()


tabs = st.tabs(
    [
        "Time × Frequency",
        "Power View",
        "Equipment Deconfliction",
        "Unit Deconfliction",
        "Sponsor Deconfliction",
        "Conflict Tables",
    ]
)

with tabs[0]:
    color_by = st.selectbox("Color boxes by", ["Tech", "Equipment", "Unit", "Sponsor"], index=0, key="tf_color")
    fig, plotted, rows_drawn = time_frequency_chart(visual_df, color_by=color_by, dark=dark)
    st.pyplot(fig, use_container_width=True)
    st.caption(f"Showing {len(plotted)} active row(s). Frequency labels are horizontal. High-power systems are transparent in the background; lower-power systems are drawn in front.")
    visual_download_button(
        fig,
        "Download Time x Frequency PNG",
        f"{safe_filename(active_sheet)}_time_frequency.png",
        "download_time_frequency_png",
    )

with tabs[1]:
    color_by = st.selectbox("Color boxes by", ["Tech", "Equipment", "Unit", "Sponsor"], index=0, key="power_color")
    fig, plotted = power_chart(visual_df, color_by=color_by, dark=dark)
    st.pyplot(fig, use_container_width=True)
    st.caption(f"Showing {len(plotted)} active row(s). Legend colors match box colors. High-power systems are transparent in the background; lower-power systems are drawn in front.")
    visual_download_button(
        fig,
        "Download Power View PNG",
        f"{safe_filename(active_sheet)}_power_view.png",
        "download_power_view_png",
    )

with tabs[2]:
    fig, plotted, _ = time_frequency_chart(visual_df, color_by="Equipment", dark=dark, title="Time × Frequency — by Equipment")
    st.pyplot(fig, use_container_width=True)
    visual_download_button(
        fig,
        "Download Equipment Deconfliction PNG",
        f"{safe_filename(active_sheet)}_equipment_deconfliction.png",
        "download_equipment_deconfliction_png",
    )

with tabs[3]:
    fig, plotted, _ = time_frequency_chart(visual_df, color_by="Unit", dark=dark, title="Time × Frequency — by Unit")
    st.pyplot(fig, use_container_width=True)
    visual_download_button(
        fig,
        "Download Unit Deconfliction PNG",
        f"{safe_filename(active_sheet)}_unit_deconfliction.png",
        "download_unit_deconfliction_png",
    )

with tabs[4]:
    fig, plotted, _ = time_frequency_chart(visual_df, color_by="Sponsor", dark=dark, title="Time × Frequency — by Sponsor")
    st.pyplot(fig, use_container_width=True)
    visual_download_button(
        fig,
        "Download Sponsor Deconfliction PNG",
        f"{safe_filename(active_sheet)}_sponsor_deconfliction.png",
        "download_sponsor_deconfliction_png",
    )

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
