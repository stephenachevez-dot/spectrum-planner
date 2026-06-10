# Core behavior:
# - Reads ALL request sheets, not just the first sheet.
# - Expands Channels Requested into one allocation row per channel.
# - Preserves the request Start Time / End Time 2-hour windows exactly.
# - Uses approved frequency centers where possible.
# - Keeps the same worksheet format: Dashboard, Master Allocation, band sheets,
#   NTC North/Central/South, Needs Review, Conflict Report, Frequency Reuse Matrix.
# - Preserves each request sheet's original column order for each band tab.
# - Adds planning fields only after the original columns.

from __future__ import annotations

from io import BytesIO
from datetime import datetime
import re
import traceback
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st


APP_TITLE = "PCC6 Spectrum Allocation Builder"
VERSION = "v50.0"


# -----------------------------
# Utility helpers
# -----------------------------

def norm_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", norm_text(value).lower())


def find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    if df is None or df.empty:
        return None
    lookup = {compact(c): c for c in df.columns}
    for candidate in candidates:
        key = compact(candidate)
        if key in lookup:
            return lookup[key]
    for candidate in candidates:
        key = compact(candidate)
        for k, col in lookup.items():
            if key and (key in k or k in key):
                return col
    return None


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return default
    except Exception:
        pass
    try:
        s = str(value).replace(",", "").strip().upper()
        # Remove common spectrum designators while keeping numeric value.
        s = s.replace("MHZ", "").replace("GHZ", "")
        match = re.search(r"-?\d+(?:\.\d+)?", s)
        if not match:
            return default
        return float(match.group(0))
    except Exception:
        return default


def to_int(value: Any, default: int = 1) -> int:
    n = to_float(value, None)
    if n is None:
        return default
    try:
        return max(1, int(round(n)))
    except Exception:
        return default


def clean_time(value: Any, default: str) -> Any:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass

    # Keep the exact value as the user supplied it. This preserves 0600-0800 etc.
    return value


def area_bucket(value: Any) -> str:
    s = norm_text(value).lower()
    if "north" in s and "central" in s and "south" in s:
        return "North/Central/South"
    if "north" in s and "central" in s:
        return "North/Central"
    if "central" in s and "south" in s:
        return "Central/South"
    if "north" in s:
        return "North"
    if "central" in s or "center" in s:
        return "Central"
    if "south" in s:
        return "South"
    if not s:
        return "NTC Ft Irwin"
    return norm_text(value)


def area_list(value: Any) -> List[str]:
    s = area_bucket(value)
    low = s.lower()
    out = []
    if "north" in low:
        out.append("North")
    if "central" in low or "center" in low:
        out.append("Central")
    if "south" in low:
        out.append("South")
    return out or ["NTC Ft Irwin"]


def band_limits_from_name(sheet_name: str) -> Tuple[Optional[float], Optional[float]]:
    s = str(sheet_name)
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if len(nums) >= 2:
        lo, hi = float(nums[0]), float(nums[1])
        return min(lo, hi), max(lo, hi)
    if "below" in s.lower() and nums:
        return 0.0, float(nums[-1])
    return None, None


def band_name_for_freq(freq: Optional[float]) -> str:
    if freq is None:
        return ""
    bands = [
        ("HF-VHF-UHF Below 1350", 0, 1350),
        ("1350-1390", 1350, 1390),
        ("1780-1850", 1780, 1850),
        ("2025-2110", 2025, 2110),
        ("2200-2300", 2200, 2300),
        ("2310-2360", 2310, 2360),
        ("2400-2490", 2400, 2490),
        ("4400-4940", 4400, 4940),
        ("5100-5900", 5100, 5900),
        ("9200-10000", 9200, 10000),
        ("14400-14830", 14400, 14830),
        ("15150-15350", 15150, 15350),
        ("15700-17700", 15700, 17700),
    ]
    for name, lo, hi in bands:
        if lo <= float(freq) <= hi:
            return name
    return ""


def parse_requested_range(value: Any) -> Tuple[Optional[float], Optional[float]]:
    """
    Handles values like:
      M1780-1850 (30)
      G1.35-1.39
      2200-2290 (22)
    """
    s = norm_text(value).upper()
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if len(nums) >= 2:
        a, b = float(nums[0]), float(nums[1])

        # Convert GHz-style entries like 1.35-1.39 to MHz.
        if a < 100 and b < 100:
            a *= 1000
            b *= 1000

        return min(a, b), max(a, b)
    return None, None


def center_in_range(center: float, lo: Optional[float], hi: Optional[float]) -> bool:
    if lo is None or hi is None:
        return True
    return float(lo) <= float(center) <= float(hi)


def equipment_match_score(req_equipment: Any, req_tech: Any, approved_equipment: Any) -> int:
    req = compact(str(req_equipment) + " " + str(req_tech))
    app = compact(approved_equipment)
    if not req or not app:
        return 0
    if app in req or req in app:
        return 100

    score = 0
    key_terms = [
        "mpu5", "silvus", "streamcaster", "trilos", "prc", "freewave", "redwolf",
        "ghost", "mesh", "raven", "scorpion", "magpie", "dronegun", "uas", "satcom"
    ]
    for term in key_terms:
        if term in req and term in app:
            score += 25
    return score


# -----------------------------
# Read inputs
# -----------------------------

REQUEST_SHEET_EXCLUDE = {
    "dashboard",
    "masterallocation",
    "ntcnorth",
    "ntccentral",
    "ntcsouth",
    "needsreview",
    "ntcneedsreview",
    "conflictreport",
    "frequencyreusematrix",
    "summary",
    "assumptions",
}


def read_request_workbook(file) -> Tuple[Dict[str, pd.DataFrame], Dict[str, List[str]]]:
    sheets = pd.read_excel(file, sheet_name=None)
    clean_sheets: Dict[str, pd.DataFrame] = {}
    original_columns: Dict[str, List[str]] = {}

    for sheet_name, raw in sheets.items():
        if compact(sheet_name) in REQUEST_SHEET_EXCLUDE:
            continue
        if raw is None or len(raw.columns) == 0:
            continue

        df = raw.dropna(axis=0, how="all").copy()
        if df.empty:
            continue

        # Require it to look like a request sheet.
        col_equipment = find_col(df, ["Equipment", "System", "Device", "Radio", "Platform"])
        col_bw = find_col(df, ["Bandwidth (MHz)", "Bandwidth", "BW", "BW MHz"])
        col_start = find_col(df, ["Start Time", "StartTime", "Start"])
        col_end = find_col(df, ["End Time", "EndTime", "End"])
        if not (col_equipment or col_bw or (col_start and col_end)):
            continue

        clean_sheets[sheet_name] = df
        original_columns[sheet_name] = list(df.columns)

    return clean_sheets, original_columns


def read_approved_frequencies(file) -> pd.DataFrame:
    sheets = pd.read_excel(file, sheet_name=None)
    frames = []
    for _, df in sheets.items():
        if df is None or df.empty:
            continue
        frames.append(df.dropna(axis=0, how="all").copy())

    if not frames:
        return pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True)

    col_equipment = find_col(raw, ["Equipment", "System", "Device", "Radio", "Platform"])
    col_center = find_col(raw, ["Center Frequency (MHz)", "Center Frequency", "Approved Frequency", "Frequency", "CenterF"])
    col_bw = find_col(raw, ["Bandwidth (MHz)", "Bandwidth", "BW", "BW MHz"])

    rows = []
    for _, r in raw.iterrows():
        center = to_float(r.get(col_center), None) if col_center else None
        bw = to_float(r.get(col_bw), None) if col_bw else None
        if center is None:
            continue
        rows.append(
            {
                "Approved Equipment": norm_text(r.get(col_equipment)) if col_equipment else "",
                "Center Frequency (MHz)": center,
                "Bandwidth (MHz)": bw if bw is not None else 0.0,
                "Band": band_name_for_freq(center),
            }
        )

    pool = pd.DataFrame(rows)
    if pool.empty:
        return pool

    return pool.sort_values(["Band", "Center Frequency (MHz)"]).reset_index(drop=True)


# -----------------------------
# Request expansion
# -----------------------------

STANDARD_OUTPUT_EXTRA_COLS = [
    "Channel Number",
    "Allocation Status",
    "Allocation Basis",
    "Source Sheet",
    "Source Row",
]


def extract_request_rows(
    request_sheets: Dict[str, pd.DataFrame],
    original_columns: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    all_requests = []

    for sheet_name, df in request_sheets.items():
        cols = original_columns.get(sheet_name, list(df.columns))

        col_start = find_col(df, ["Start Time", "StartTime", "Start"])
        col_end = find_col(df, ["End Time", "EndTime", "End"])
        col_unit = find_col(df, ["Unit", "Organization", "Org", "Requesting Unit"])
        col_sponsor = find_col(df, ["Sponsor", "Sponser", "Supported Unit", "Higher HQ"])
        col_equipment = find_col(df, ["Equipment", "System", "Device", "Radio", "Platform"])
        col_tech = find_col(df, ["Tech", "Technology", "System Type"])
        col_req_freq = find_col(df, ["Requested Frequency", "Request Frequency", "Frequency Requested"])
        col_req_band = find_col(df, ["Request Band", "Band", "Frequency Band", "Requested Band"])
        col_channels = find_col(df, ["Channels Requested", "Channel Count", "Number of Channels", "Qty", "Quantity", "Nets", "Number of Nets"])
        col_start_freq = find_col(df, ["Start Frequency (MHz)", "Start Frequency", "StartF"])
        col_center_freq = find_col(df, ["Center Frequency (MHz)", "Center Frequency", "CenterF"])
        col_end_freq = find_col(df, ["End Frequency (MHz)", "End Frequency", "EndF"])
        col_bw = find_col(df, ["Bandwidth (MHz)", "Bandwidth", "BW", "BW MHz"])
        col_power = find_col(df, ["Power (W)", "Power", "Watts"])
        col_location = find_col(df, ["Location", "NTC Location"])
        col_area = find_col(df, ["NTC Area", "Area", "Training Area", "North Central South"])
        col_notes = find_col(df, ["Notes", "Justification", "Comments", "Mission"])

        sheet_lo, sheet_hi = band_limits_from_name(sheet_name)

        for row_idx, r in df.iterrows():
            row_dict = {c: r.get(c) for c in cols}

            equipment = norm_text(r.get(col_equipment)) if col_equipment else ""
            tech = norm_text(r.get(col_tech)) if col_tech else ""
            unit = norm_text(r.get(col_unit)) if col_unit else ""
            sponsor = norm_text(r.get(col_sponsor)) if col_sponsor else ""

            # Skip blank/non-request rows.
            if not any([equipment, tech, unit, sponsor]):
                continue

            channels = to_int(r.get(col_channels), 1) if col_channels else 1
            bw = to_float(r.get(col_bw), None) if col_bw else None

            # Infer bandwidth from equipment/tech text if missing.
            if bw is None or bw <= 0:
                match = re.search(r"(\d+(?:\.\d+)?)\s*mhz", (equipment + " " + tech).lower())
                bw = float(match.group(1)) if match else 1.0

            req_lo, req_hi = parse_requested_range(r.get(col_req_freq)) if col_req_freq else (None, None)
            if req_lo is None:
                req_lo, req_hi = sheet_lo, sheet_hi

            request = {
                "__original": row_dict,
                "__sheet": sheet_name,
                "__source_row": int(row_idx) + 2,
                "__original_columns": cols,
                "Start Time": clean_time(r.get(col_start), "0600") if col_start else "0600",
                "End Time": clean_time(r.get(col_end), "0800") if col_end else "0800",
                "Unit": unit,
                "Sponsor": sponsor,
                "Equipment": equipment,
                "Tech": tech,
                "Requested Frequency": r.get(col_req_freq) if col_req_freq else None,
                "Request Band": r.get(col_req_band) if col_req_band else sheet_name,
                "Channels Requested": channels,
                "Start Frequency (MHz)": to_float(r.get(col_start_freq), None) if col_start_freq else None,
                "Center Frequency (MHz)": to_float(r.get(col_center_freq), None) if col_center_freq else None,
                "End Frequency (MHz)": to_float(r.get(col_end_freq), None) if col_end_freq else None,
                "Bandwidth (MHz)": bw,
                "Power (W)": to_float(r.get(col_power), None) if col_power else None,
                "Location": norm_text(r.get(col_location)) if col_location else "NTC Ft Irwin",
                "NTC Area": area_bucket(r.get(col_area)) if col_area else "NTC Ft Irwin",
                "Notes": norm_text(r.get(col_notes)) if col_notes else "",
                "__range_lo": req_lo,
                "__range_hi": req_hi,
            }

            all_requests.append(request)

    return all_requests


# -----------------------------
# Allocation algorithm
# -----------------------------

def candidate_pool_for_request(request: Dict[str, Any], approved_pool: pd.DataFrame) -> pd.DataFrame:
    if approved_pool is None or approved_pool.empty:
        return pd.DataFrame()

    lo = request.get("__range_lo")
    hi = request.get("__range_hi")
    bw = float(request.get("Bandwidth (MHz)") or 0.0)

    pool = approved_pool.copy()

    # Band/range filter first.
    if lo is not None and hi is not None:
        pool = pool[pool["Center Frequency (MHz)"].apply(lambda x: center_in_range(x, lo, hi))]

    # Equipment match preferred, but not required.
    pool["__match_score"] = pool["Approved Equipment"].apply(
        lambda x: equipment_match_score(request.get("Equipment"), request.get("Tech"), x)
    )

    # Bandwidth compatibility preferred. If too restrictive, fallback later.
    compatible = pool[(pool["Bandwidth (MHz)"].fillna(0) >= bw) | (pool["Bandwidth (MHz)"].fillna(0) == 0)]
    if not compatible.empty:
        pool = compatible

    if pool.empty:
        return pool

    return pool.sort_values(["__match_score", "Center Frequency (MHz)"], ascending=[False, True]).reset_index(drop=True)


def ranges_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)


def times_overlap(a_start: Any, a_end: Any, b_start: Any, b_end: Any) -> bool:
    def to_minutes(value: Any) -> Optional[int]:
        s = norm_text(value).lower()
        if not s:
            return None
        try:
            if ":" in s:
                hh, mm = s.split(":")[:2]
                return int(hh) * 60 + int(mm)
            match = re.match(r"(\d+(?:\.\d+)?)(am|pm)?", s)
            if match:
                val = float(match.group(1))
                suffix = match.group(2)
                if val > 2400:
                    return None
                if val >= 100 and suffix is None:
                    hh = int(val // 100)
                    mm = int(val % 100)
                    return hh * 60 + mm
                if suffix == "pm" and val < 12:
                    val += 12
                if suffix == "am" and val == 12:
                    val = 0
                return int(val * 60)
        except Exception:
            return None
        return None

    a1, a2, b1, b2 = map(to_minutes, [a_start, a_end, b_start, b_end])
    if None in [a1, a2, b1, b2]:
        # If unsure, assume overlap to avoid hiding conflicts.
        return True
    return max(a1, b1) < min(a2, b2)


def can_reuse_in_area(req_area: Any, assigned_area: Any) -> bool:
    # PCC6 simplification: North/Central/South can geographically reuse.
    req_areas = set(area_list(req_area))
    assigned_areas = set(area_list(assigned_area))

    if "NTC Ft Irwin" in req_areas or "NTC Ft Irwin" in assigned_areas:
        return False

    return req_areas.isdisjoint(assigned_areas)


def is_candidate_available(
    request: Dict[str, Any],
    center: float,
    bandwidth: float,
    assigned_rows: List[Dict[str, Any]],
    guard_mhz: float = 0.0,
) -> bool:
    start = center - bandwidth / 2.0
    end = center + bandwidth / 2.0

    for assigned in assigned_rows:
        if can_reuse_in_area(request.get("NTC Area"), assigned.get("NTC Area")):
            continue

        if not times_overlap(
            request.get("Start Time"),
            request.get("End Time"),
            assigned.get("Start Time"),
            assigned.get("End Time"),
        ):
            continue

        a_start = to_float(assigned.get("Start Frequency (MHz)"), None)
        a_end = to_float(assigned.get("End Frequency (MHz)"), None)
        if a_start is None or a_end is None:
            continue

        if ranges_overlap(start - guard_mhz, end + guard_mhz, a_start, a_end):
            return False

    return True


def make_output_row(
    request: Dict[str, Any],
    channel_number: int,
    center: Optional[float],
    status: str,
    basis: str,
) -> Dict[str, Any]:
    row = dict(request.get("__original", {}))

    bw = float(request.get("Bandwidth (MHz)") or 0.0)

    if center is not None:
        start_freq = round(center - bw / 2.0, 6)
        end_freq = round(center + bw / 2.0, 6)
        center_freq = round(center, 6)
    else:
        start_freq = None
        end_freq = None
        center_freq = None

    updates = {
        "Start Time": request.get("Start Time"),
        "End Time": request.get("End Time"),
        "Unit": request.get("Unit"),
        "Sponsor": request.get("Sponsor"),
        "Equipment": request.get("Equipment"),
        "Tech": request.get("Tech"),
        "Requested Frequency": request.get("Requested Frequency"),
        "Channels Requested": request.get("Channels Requested"),
        "Request Band": request.get("Request Band"),
        "Start Frequency (MHz)": start_freq,
        "Center Frequency (MHz)": center_freq,
        "End Frequency (MHz)": end_freq,
        "Bandwidth (MHz)": bw,
        "Power (W)": request.get("Power (W)"),
        "Location": request.get("Location"),
        "NTC Area": request.get("NTC Area"),
        "Notes": request.get("Notes"),
        "Channel Number": channel_number,
        "Allocation Status": status,
        "Allocation Basis": basis,
        "Source Sheet": request.get("__sheet"),
        "Source Row": request.get("__source_row"),
    }

    row.update(updates)

    if status == "Allocated":
        original_note = norm_text(row.get("Notes"))
        suffix = f"CH {channel_number}/{request.get('Channels Requested')} | Channel {channel_number} of {request.get('Channels Requested')} | {basis}"
        row["Notes"] = (original_note + " | " + suffix).strip(" |")
    else:
        row["Notes"] = (
            f"Needs Review: no clean approved frequency found for channel {channel_number} of "
            f"{request.get('Channels Requested')}. {norm_text(row.get('Notes'))}"
        ).strip()

    return row


def build_allocation_plan(
    request_sheets: Dict[str, pd.DataFrame],
    original_columns: Dict[str, List[str]],
    approved_pool: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, pd.DataFrame], pd.DataFrame]:
    requests = extract_request_rows(request_sheets, original_columns)

    allocated_rows: List[Dict[str, Any]] = []
    needs_review_rows: List[Dict[str, Any]] = []
    conflict_rows: List[Dict[str, Any]] = []

    for request in requests:
        channels = int(request.get("Channels Requested") or 1)
        pool = candidate_pool_for_request(request, approved_pool)

        for ch in range(1, channels + 1):
            selected_center = None
            basis = "Approved frequency"

            # Use manually provided center first if the request already had one.
            manual_center = request.get("Center Frequency (MHz)")
            if manual_center is not None and not pd.isna(manual_center):
                if is_candidate_available(request, float(manual_center), float(request.get("Bandwidth (MHz)") or 0), allocated_rows):
                    selected_center = float(manual_center)
                    basis = "Request-provided frequency"

            # Then approved pool.
            if selected_center is None and not pool.empty:
                for _, cand in pool.iterrows():
                    center = float(cand["Center Frequency (MHz)"])
                    if is_candidate_available(request, center, float(request.get("Bandwidth (MHz)") or 0), allocated_rows):
                        selected_center = center
                        basis = "Approved frequency"
                        break

            if selected_center is not None:
                row = make_output_row(request, ch, selected_center, "Allocated", basis)
                allocated_rows.append(row)
            else:
                row = make_output_row(request, ch, None, "Needs Review", "No clean approved frequency available")
                needs_review_rows.append(row)

    master = pd.DataFrame(allocated_rows + needs_review_rows)
    needs = pd.DataFrame(needs_review_rows)

    # Band tabs use original request sheet format plus the allocation values.
    band_tabs: Dict[str, pd.DataFrame] = {}
    for sheet_name in request_sheets.keys():
        rows = master[master["Source Sheet"] == sheet_name].copy() if not master.empty else pd.DataFrame()
        original_cols = list(original_columns.get(sheet_name, []))
        extra_cols = [c for c in STANDARD_OUTPUT_EXTRA_COLS if c in rows.columns]
        ordered = original_cols + [c for c in extra_cols if c not in original_cols]
        if not rows.empty:
            for col in ordered:
                if col not in rows.columns:
                    rows[col] = None
            rows = rows[ordered + [c for c in rows.columns if c not in ordered]]
        band_tabs[sheet_name] = rows

    # Conflict report
    conflict_df = detect_conflicts(master)

    return master, needs, band_tabs, conflict_df


def detect_conflicts(master: pd.DataFrame) -> pd.DataFrame:
    if master is None or master.empty:
        return pd.DataFrame(columns=["Conflict Type", "Allocation A", "Allocation B", "Reason"])

    allocated = master[master.get("Allocation Status", "") == "Allocated"].copy()
    conflicts = []

    for i in range(len(allocated)):
        a = allocated.iloc[i]
        for j in range(i + 1, len(allocated)):
            b = allocated.iloc[j]

            if can_reuse_in_area(a.get("NTC Area"), b.get("NTC Area")):
                continue
            if not times_overlap(a.get("Start Time"), a.get("End Time"), b.get("Start Time"), b.get("End Time")):
                continue

            a_start = to_float(a.get("Start Frequency (MHz)"), None)
            a_end = to_float(a.get("End Frequency (MHz)"), None)
            b_start = to_float(b.get("Start Frequency (MHz)"), None)
            b_end = to_float(b.get("End Frequency (MHz)"), None)

            if None in [a_start, a_end, b_start, b_end]:
                continue

            if ranges_overlap(a_start, a_end, b_start, b_end):
                conflicts.append(
                    {
                        "Conflict Type": "Frequency/Time/Area Overlap",
                        "Allocation A": f"{a.get('Unit')} | {a.get('Equipment')} | {a.get('Center Frequency (MHz)')}",
                        "Allocation B": f"{b.get('Unit')} | {b.get('Equipment')} | {b.get('Center Frequency (MHz)')}",
                        "Unit A": a.get("Unit"),
                        "Unit B": b.get("Unit"),
                        "Equipment A": a.get("Equipment"),
                        "Equipment B": b.get("Equipment"),
                        "Center A": a.get("Center Frequency (MHz)"),
                        "Center B": b.get("Center Frequency (MHz)"),
                        "NTC Area A": a.get("NTC Area"),
                        "NTC Area B": b.get("NTC Area"),
                        "Reason": "Overlapping frequency range in same/restricted NTC area and overlapping time window.",
                    }
                )

    return pd.DataFrame(conflicts)


# -----------------------------
# Workbook export
# -----------------------------

def safe_sheet_name(name: str) -> str:
    s = re.sub(r"[\[\]\:\*\?\/\\]", "-", str(name))[:31]
    return s or "Sheet"


def build_dashboard(master: pd.DataFrame, needs: pd.DataFrame, conflicts: pd.DataFrame) -> pd.DataFrame:
    allocated = int((master.get("Allocation Status", pd.Series(dtype=str)) == "Allocated").sum()) if not master.empty else 0
    needs_count = len(needs) if needs is not None else 0
    total = len(master) if master is not None else 0
    unique_units = master["Unit"].nunique() if master is not None and "Unit" in master.columns else 0
    unique_sponsors = master["Sponsor"].nunique() if master is not None and "Sponsor" in master.columns else 0

    rows = [
        ["PCC6 Allocation Plan", ""],
        ["Generated", datetime.now().strftime("%Y-%m-%d %H:%M")],
        ["2-hour window preserved", "Yes - Start/End Time retained from request tracker"],
        ["Total allocation rows", total],
        ["Allocated rows", allocated],
        ["Needs Review rows", needs_count],
        ["Conflict rows", len(conflicts) if conflicts is not None else 0],
        ["Unique Units", unique_units],
        ["Unique Sponsors", unique_sponsors],
        ["Location", "NTC Ft Irwin"],
        ["Allocation Philosophy", "One row per requested channel; approved frequencies used when available; North/Central/South reuse permitted"],
    ]
    return pd.DataFrame(rows[1:], columns=rows[0])


def build_reuse_matrix(master: pd.DataFrame) -> pd.DataFrame:
    if master is None or master.empty:
        return pd.DataFrame(columns=["Reuse Group ID", "Center Frequency (MHz)", "Bandwidth (MHz)", "Tech", "Reuse Count", "NTC Areas", "Units", "Sponsors", "Reuse Risk"])

    df = master[master.get("Allocation Status", "") == "Allocated"].copy()
    if df.empty:
        return pd.DataFrame(columns=["Reuse Group ID", "Center Frequency (MHz)", "Bandwidth (MHz)", "Tech", "Reuse Count", "NTC Areas", "Units", "Sponsors", "Reuse Risk"])

    group_cols = ["Center Frequency (MHz)", "Bandwidth (MHz)", "Tech"]
    rows = []
    for key, grp in df.groupby(group_cols, dropna=False):
        center, bw, tech = key
        count = len(grp)
        areas = sorted(set(norm_text(x) for x in grp.get("NTC Area", []) if norm_text(x)))
        units = sorted(set(norm_text(x) for x in grp.get("Unit", []) if norm_text(x)))
        sponsors = sorted(set(norm_text(x) for x in grp.get("Sponsor", []) if norm_text(x)))
        risk = "Low" if len(areas) > 1 else ("High" if count > 1 else "Low")
        rows.append(
            {
                "Reuse Group ID": f"RG-{abs(hash((center, bw, tech))) % 100000:05d}",
                "Center Frequency (MHz)": center,
                "Bandwidth (MHz)": bw,
                "Tech": tech,
                "Reuse Count": count,
                "NTC Areas": ", ".join(areas),
                "Units": ", ".join(units),
                "Sponsors": ", ".join(sponsors),
                "Reuse Risk": risk,
            }
        )
    return pd.DataFrame(rows)


def write_allocation_workbook(
    master: pd.DataFrame,
    needs: pd.DataFrame,
    band_tabs: Dict[str, pd.DataFrame],
    conflicts: pd.DataFrame,
) -> bytes:
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        build_dashboard(master, needs, conflicts).to_excel(writer, sheet_name="Dashboard", index=False)
        master.to_excel(writer, sheet_name="Master Allocation", index=False)

        for sheet_name, df in band_tabs.items():
            df.to_excel(writer, sheet_name=safe_sheet_name(sheet_name), index=False)

        # Area tabs
        for area in ["North", "Central", "South"]:
            if master is not None and not master.empty and "NTC Area" in master.columns:
                mask = master["NTC Area"].astype(str).str.contains(area, case=False, na=False)
                area_df = master[mask].copy()
            else:
                area_df = pd.DataFrame()
            area_df.to_excel(writer, sheet_name=f"NTC {area}", index=False)

        needs.to_excel(writer, sheet_name="Needs Review", index=False)
        conflicts.to_excel(writer, sheet_name="Conflict Report", index=False)
        build_reuse_matrix(master).to_excel(writer, sheet_name="Frequency Reuse Matrix", index=False)

        # Basic formatting.
        wb = writer.book
        for ws in wb.worksheets:
            ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = cell.font.copy(bold=True, color="FFFFFF")
                cell.fill = cell.fill.copy(fill_type="solid", fgColor="1F4E78")
            for col_cells in ws.columns:
                max_len = 10
                col_letter = col_cells[0].column_letter
                for cell in col_cells[:200]:
                    try:
                        max_len = max(max_len, len(str(cell.value)) if cell.value is not None else 0)
                    except Exception:
                        pass
                ws.column_dimensions[col_letter].width = min(max_len + 2, 32)

    return output.getvalue()


# -----------------------------
# Streamlit UI
# -----------------------------

def run_app() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(f"{APP_TITLE} {VERSION}")
    st.caption("Builds one allocation row per requested channel while preserving each 2-hour request window.")

    with st.sidebar:
        st.header("Inputs")
        st.write("Upload the request tracker and approved frequencies workbook.")
        show_preview = st.toggle("Show preview tables", value=True)

    req_file = st.file_uploader("Request Tracker (.xlsx)", type=["xlsx"], key="req_tracker")
    freq_file = st.file_uploader("Approved Frequencies (.xlsx)", type=["xlsx"], key="approved_freqs")

    if req_file is None or freq_file is None:
        st.info("Upload both files to build the allocation plan.")
        return

    try:
        request_sheets, original_columns = read_request_workbook(req_file)
        approved_pool = read_approved_frequencies(freq_file)

        total_request_rows = sum(len(df) for df in request_sheets.values())
        total_requested_channels = 0
        for req in extract_request_rows(request_sheets, original_columns):
            total_requested_channels += int(req.get("Channels Requested") or 1)

        k1, k2, k3 = st.columns(3)
        k1.metric("Request sheets read", len(request_sheets))
        k2.metric("Request rows", total_request_rows)
        k3.metric("Requested channels", total_requested_channels)

        if approved_pool.empty:
            st.error("No approved frequencies could be read from the approved frequencies workbook.")
            return

        st.metric("Approved frequency records", len(approved_pool))

        if show_preview:
            with st.expander("Request sheets found", expanded=False):
                st.write(list(request_sheets.keys()))
            with st.expander("Approved frequency preview", expanded=False):
                st.dataframe(approved_pool.head(100), use_container_width=True)

        if st.button("Build Allocation Plan", type="primary", use_container_width=True):
            master, needs, band_tabs, conflicts = build_allocation_plan(request_sheets, original_columns, approved_pool)
            workbook_bytes = write_allocation_workbook(master, needs, band_tabs, conflicts)

            allocated_count = int((master["Allocation Status"] == "Allocated").sum()) if not master.empty else 0
            needs_count = len(needs)

            st.success(f"Allocation plan built: {allocated_count} allocated, {needs_count} needs review, {len(master)} total channel rows.")

            c1, c2, c3 = st.columns(3)
            c1.metric("Allocated", allocated_count)
            c2.metric("Needs Review", needs_count)
            c3.metric("Conflicts", len(conflicts))

            st.download_button(
                "Download Allocation Plan XLSX",
                data=workbook_bytes,
                file_name="PCC6_Allocation_Plan_App_Built.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            with st.expander("Master Allocation Preview", expanded=True):
                st.dataframe(master.head(300), use_container_width=True, hide_index=True)

            if needs_count:
                with st.expander("Needs Review Preview", expanded=False):
                    st.dataframe(needs.head(300), use_container_width=True, hide_index=True)

    except Exception as exc:
        st.error(f"Build failed: {type(exc).__name__}: {str(exc)}")
        st.code(traceback.format_exc())


if __name__ == "__main__":
    run_app()
