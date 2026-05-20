# streamlit_supabase_app_v2.py
# Spectrum Planner — Streamlit + Supabase
# JSON-backed, polished, and safer deconfliction.
# Fixes:
# - Avoids Supabase column mismatch by saving allocation rows in row_data JSONB.
# - Power plot center-frequency labels are near the top inside boxes.
# - Deconfliction labels are inside boxes.
# - Improved scheduler only separates rows that actually overlap in frequency.
# - Uses Supabase Auth login/signup instead of one shared password.
# - Adds admin user management with roles: admin, editor, viewer, disabled.
# - Adds legends to every plot tab.
# - Keeps uploaded preview data in session state until saved.
# - Cleans Excel/Pandas values before saving versions to Supabase JSON.
# - Adds Map View tab using Latitude/Longitude and optional coverage circles.
# - Adds stronger thin black outlines to separate overlapping visual bands.
# - Saves original uploaded CSV/XLSX files to Supabase Storage for download after logout/login.
# - Adds admin-only buttons to delete version history and clear the shared allocation table.
# - Saves/restores all Excel workbook sheets as project tabs.
# - Adds download buttons for map HTML and map data CSV.
# - Restores admin-only buttons to delete version history and clear shared allocation table.
# - Fixes Auto Deconflict Anchor so changing the anchor time repacks the schedule.
# - Shows workbook-tab persistence status and saves all tabs permanently to Supabase.
# - Fixes NaN/Inf JSON errors when saving workbook sheets.

import io
import math
import mimetypes
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import pydeck as pdk
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

STORAGE_BUCKET = "spectrum-files"



@st.cache_resource
def get_supabase():
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])


@st.cache_resource
def get_supabase_admin():
    service_key = st.secrets.get("supabase", {}).get("service_role_key", "")
    if not service_key:
        return None
    return create_client(st.secrets["supabase"]["url"], service_key)


sb = get_supabase()
sb_admin = get_supabase_admin()

APP_COLUMNS = [
    "Start Time", "End Time", "Equipment", "Center Frequency (MHz)",
    "Start Frequency (MHz)", "End Frequency (MHz)", "Bandwidth (MHz)",
    "Power (W)", "Power (dBm)", "Tech", "Unit", "Notes",
    "Latitude", "Longitude", "Location",
    "Antenna Height", "Coverage Radius", "Site Name",
]

STANDARD_RENAME = {
    "StartTime": "Start Time",
    "EndTime": "End Time",
    "Start Time": "Start Time",
    "End Time": "End Time",

    "Equipment": "Equipment",
    "Equip": "Equipment",
    "Tech": "Tech",
    "Unit": "Unit",
    "Notes": "Notes",

    "CenterF": "Center Frequency (MHz)",
    "Center Frequency": "Center Frequency (MHz)",
    "Center Frequency (MHz)": "Center Frequency (MHz)",
    "Center Freq": "Center Frequency (MHz)",
    "Center Freq (MHz)": "Center Frequency (MHz)",

    "StartF": "Start Frequency (MHz)",
    "Start Frequency": "Start Frequency (MHz)",
    "Start Frequency (MHz)": "Start Frequency (MHz)",
    "Start Freq": "Start Frequency (MHz)",
    "Start Freq (MHz)": "Start Frequency (MHz)",

    "EndF": "End Frequency (MHz)",
    "End Frequency": "End Frequency (MHz)",
    "End Frequency (MHz)": "End Frequency (MHz)",
    "End Freq": "End Frequency (MHz)",
    "End Freq (MHz)": "End Frequency (MHz)",

    "BW": "Bandwidth (MHz)",
    "Bandwidth": "Bandwidth (MHz)",
    "Bandwidth (MHz)": "Bandwidth (MHz)",

    "PowerW": "Power (W)",
    "Power (W)": "Power (W)",
    "PowerdBm": "Power (dBm)",
    "Power (dBm)": "Power (dBm)",

    "Latitude": "Latitude",
    "Lat": "Latitude",
    "LAT": "Latitude",
    "latitude": "Latitude",

    "Longitude": "Longitude",
    "Long": "Longitude",
    "Lon": "Longitude",
    "Lng": "Longitude",
    "LON": "Longitude",
    "longitude": "Longitude",

    "Location": "Location",
    "location": "Location",

    "Antenna Height": "Antenna Height",
    "AntennaHeight": "Antenna Height",
    "Antenna Height (ft)": "Antenna Height",
    "Antenna Height (m)": "Antenna Height",

    "Coverage Radius": "Coverage Radius",
    "CoverageRadius": "Coverage Radius",
    "Coverage Radius (mi)": "Coverage Radius",
    "Coverage Radius (km)": "Coverage Radius",
    "Coverage Radius (NM)": "Coverage Radius",

    "Site Name": "Site Name",
    "SiteName": "Site Name",
    "Site": "Site Name",
}

INTERNAL_RENAME = {
    "Start Time": "StartTime",
    "End Time": "EndTime",
    "Equipment": "Equipment",
    "Center Frequency (MHz)": "CenterF",
    "Start Frequency (MHz)": "StartF",
    "End Frequency (MHz)": "EndF",
    "Bandwidth (MHz)": "BW",
    "Power (W)": "PowerW",
    "Power (dBm)": "PowerdBm",
    "Tech": "Tech",
    "Unit": "Unit",
    "Notes": "Notes",
    "Latitude": "Latitude",
    "Longitude": "Longitude",
    "Location": "Location",
    "Antenna Height": "AntennaHeight",
    "Coverage Radius": "CoverageRadius",
    "Site Name": "SiteName",
}

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def json_safe_value(value):
    """Convert Excel/Pandas/Numpy values into Supabase JSON-safe values."""
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()

    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (np.floating,)):
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, (np.bool_, bool)):
        return bool(value)

    if isinstance(value, (int, str)):
        return value

    return str(value)


def json_safe_df(df):
    """Return a copy of df containing only JSON-safe scalar values."""
    safe = df.copy().astype("object")
    safe = safe.where(pd.notnull(safe), None)
    safe = safe.replace({np.nan: None, np.inf: None, -np.inf: None, pd.NaT: None})

    for col in safe.columns:
        safe[col] = safe[col].map(json_safe_value).astype("object")

    safe = safe.where(pd.notnull(safe), None)
    return safe


def json_safe_records(df):
    """Return list-of-dicts guaranteed to contain no NaN/Inf values."""
    safe = json_safe_df(df)
    records = []
    for row in safe.to_dict(orient="records"):
        clean_row = {}
        for key, value in row.items():
            clean_row[str(key)] = json_safe_value(value)
        records.append(clean_row)
    return records

def obj_get(obj, key, default=None):
    """Read from Supabase response objects or dicts."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def user_id_from_user(user):
    return obj_get(user, "id", "")


def user_email_from_user(user):
    return obj_get(user, "email", "")


def count_user_roles():
    try:
        rows = sb.table("user_roles").select("user_id").execute().data or []
        return len(rows)
    except Exception:
        return 0


def get_user_role(user_id, email=None):
    try:
        rows = sb.table("user_roles").select("*").eq("user_id", user_id).limit(1).execute().data or []
        if rows:
            return rows[0]
    except Exception:
        pass

    # First authenticated user becomes admin; later users default to viewer.
    role = "admin" if count_user_roles() == 0 else "viewer"
    rec = {
        "user_id": user_id,
        "email": email or "",
        "role": role,
        "full_name": "",
        "updated_at": now_iso(),
    }
    try:
        sb.table("user_roles").upsert(rec, on_conflict="user_id").execute()
    except Exception:
        pass
    return rec


def update_user_role(user_id, email, role, full_name="", updated_by=""):
    rec = {
        "user_id": user_id,
        "email": email or "",
        "role": role,
        "full_name": full_name or "",
        "updated_by": updated_by,
        "updated_at": now_iso(),
    }
    return sb.table("user_roles").upsert(rec, on_conflict="user_id").execute()


def list_app_users():
    try:
        return sb.table("user_roles").select("*").order("email").execute().data or []
    except Exception:
        return []


def admin_create_user(email, password, role, full_name, created_by):
    if sb_admin is None:
        raise RuntimeError("Missing supabase.service_role_key in Streamlit secrets.")

    response = sb_admin.auth.admin.create_user(
        {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"full_name": full_name or ""},
        }
    )
    user = obj_get(response, "user", None)
    if user is None:
        user = obj_get(obj_get(response, "data", None), "user", None)

    user_id = user_id_from_user(user)
    if not user_id:
        raise RuntimeError("User was created, but Supabase did not return a user id.")

    update_user_role(user_id, email, role, full_name, created_by)
    return user_id


def admin_delete_user(user_id):
    if sb_admin is None:
        raise RuntimeError("Missing supabase.service_role_key in Streamlit secrets.")
    return sb_admin.auth.admin.delete_user(user_id)


def require_login():
    """Supabase Auth login/signup."""
    if st.session_state.get("auth_user") and st.session_state.get("auth_role"):
        role = st.session_state.get("auth_role", "viewer")
        if role == "disabled":
            st.error("Your account is disabled. Contact an administrator.")
            st.stop()
        return st.session_state["auth_user"], role

    st.markdown("### 🔐 Spectrum Planner Login")
    st.caption("Use your assigned account, or create an account if sign-up is enabled.")

    login_tab, signup_tab = st.tabs(["Login", "Create Account"])

    with login_tab:
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Login", type="primary")

        if submitted:
            try:
                response = sb.auth.sign_in_with_password({"email": email.strip(), "password": password})
                user = obj_get(response, "user", None)
                if user is None:
                    user = obj_get(obj_get(response, "data", None), "user", None)

                user_id = user_id_from_user(user)
                user_email = user_email_from_user(user) or email.strip()
                role_rec = get_user_role(user_id, user_email)
                role = role_rec.get("role", "viewer")

                if role == "disabled":
                    st.error("Your account is disabled. Contact an administrator.")
                    st.stop()

                st.session_state["auth_user"] = user_email
                st.session_state["auth_user_id"] = user_id
                st.session_state["auth_role"] = role
                st.session_state["auth_full_name"] = role_rec.get("full_name", "")
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {e}")

    with signup_tab:
        allow_signup = st.secrets.get("auth", {}).get("allow_signup", True)
        if not allow_signup:
            st.info("Self sign-up is disabled. Ask an administrator to create your account.")
        else:
            with st.form("signup_form", clear_on_submit=False):
                full_name = st.text_input("Full name", key="signup_full_name")
                email = st.text_input("Email", key="signup_email")
                password = st.text_input("Password", type="password", key="signup_password")
                password2 = st.text_input("Confirm password", type="password", key="signup_password2")
                submitted = st.form_submit_button("Create account", type="primary")

            if submitted:
                if not email.strip() or not password:
                    st.error("Email and password are required.")
                elif password != password2:
                    st.error("Passwords do not match.")
                elif len(password) < 8:
                    st.error("Password must be at least 8 characters.")
                else:
                    try:
                        response = sb.auth.sign_up(
                            {
                                "email": email.strip(),
                                "password": password,
                                "options": {"data": {"full_name": full_name.strip()}},
                            }
                        )
                        user = obj_get(response, "user", None)
                        if user is None:
                            user = obj_get(obj_get(response, "data", None), "user", None)

                        user_id = user_id_from_user(user)
                        if user_id:
                            role = "admin" if count_user_roles() == 0 else "viewer"
                            update_user_role(user_id, email.strip(), role, full_name.strip(), "self_signup")

                        st.success("Account created. If email confirmation is enabled in Supabase, confirm your email before logging in.")
                    except Exception as e:
                        st.error(f"Account creation failed: {e}")

    st.stop()


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
    for c in ["CenterF", "StartF", "EndF", "BW", "PowerW", "PowerdBm", "Latitude", "Longitude", "AntennaHeight", "CoverageRadius"]:
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

def safe_storage_filename(name):
    """Make a file name safe for Supabase Storage paths."""
    base = Path(str(name or "uploaded_file")).name
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip()
    return base or "uploaded_file"


def guess_content_type(file_name):
    content_type, _ = mimetypes.guess_type(file_name)
    return content_type or "application/octet-stream"


def upload_original_file(project_id, file_name, file_bytes, user):
    """Upload original CSV/XLSX file to Supabase Storage and track it in project_files."""
    if not project_id or not file_name or not file_bytes:
        return None

    safe_name = safe_storage_filename(file_name)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    storage_path = f"{project_id}/{stamp}_{uuid.uuid4().hex[:8]}_{safe_name}"
    content_type = guess_content_type(safe_name)

    # Upload the original file to private bucket.
    sb.storage.from_(STORAGE_BUCKET).upload(
        storage_path,
        file_bytes,
        file_options={
            "content-type": content_type,
            "upsert": "false",
        },
    )

    rec = {
        "project_id": project_id,
        "file_name": safe_name,
        "storage_path": storage_path,
        "uploaded_by": user,
        "uploaded_at": now_iso(),
    }
    data = sb.table("project_files").insert(rec).execute().data
    return data[0] if data else rec


def list_project_files(project_id):
    """Return uploaded file records for this project."""
    try:
        return (
            sb.table("project_files")
            .select("*")
            .eq("project_id", project_id)
            .order("uploaded_at", desc=True)
            .execute()
            .data
            or []
        )
    except Exception:
        return []


def download_original_file(storage_path):
    """Download an original file from Supabase Storage."""
    return sb.storage.from_(STORAGE_BUCKET).download(storage_path)


def save_project_sheets(project_id, sheets_dict, user):
    """Save every workbook sheet for the selected project."""
    if not sheets_dict:
        return 0

    sb.table("project_sheets").delete().eq("project_id", project_id).execute()

    payloads = []
    order_no = 0
    for sheet_name, df_sheet in sheets_dict.items():
        order_no += 1
        clean = normalize_uploaded_df(df_sheet)
        payloads.append({
            "project_id": project_id,
            "sheet_name": str(sheet_name),
            "sheet_order": order_no,
            "sheet_data": json_safe_records(clean),
            "uploaded_by": user,
            "updated_at": now_iso(),
        })

    if payloads:
        sb.table("project_sheets").insert(payloads).execute()

    return len(payloads)


def load_project_sheets(project_id):
    """Load saved workbook sheets for the selected project."""
    try:
        rows = (
            sb.table("project_sheets")
            .select("*")
            .eq("project_id", project_id)
            .order("sheet_order")
            .execute()
            .data
            or []
        )
    except Exception as e:
        st.warning(f"Workbook tabs could not be loaded from Supabase. Run the v17 SQL setup if you have not already. Details: {e}")
        return {}

    sheets = {}
    for row in rows:
        name = row.get("sheet_name", "Sheet")
        data = row.get("sheet_data", []) or []
        try:
            sheets[name] = normalize_uploaded_df(pd.DataFrame(data))
        except Exception:
            sheets[name] = pd.DataFrame(data)

    return sheets


def read_uploaded_workbook(uploaded, selected_sheet=None):
    """Read CSV/XLS/XLSX and return sheets dict, active sheet, file bytes."""
    file_bytes = uploaded.getvalue()
    ext = Path(uploaded.name).suffix.lower()

    if ext == ".csv":
        df = pd.read_csv(io.BytesIO(file_bytes))
        return {"CSV": normalize_uploaded_df(df)}, "CSV", file_bytes

    excel = pd.ExcelFile(io.BytesIO(file_bytes))
    sheets = {}
    for sheet_name in excel.sheet_names:
        sheets[sheet_name] = normalize_uploaded_df(pd.read_excel(excel, sheet_name=sheet_name))

    active = selected_sheet if selected_sheet in sheets else excel.sheet_names[0]
    return sheets, active, file_bytes


def workbook_to_xlsx_bytes(sheets_dict):
    """Create a downloadable XLSX from saved workbook sheets."""
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for sheet_name, df_sheet in sheets_dict.items():
            safe_name = str(sheet_name)[:31] or "Sheet"
            df_sheet.to_excel(writer, sheet_name=safe_name, index=False)
    bio.seek(0)
    return bio.getvalue()


def deck_to_html_bytes(deck):
    """Create a downloadable standalone HTML map."""
    try:
        html = deck.to_html(as_string=True, notebook_display=False)
    except TypeError:
        html = deck.to_html(as_string=True)
    return html.encode("utf-8")


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

    clean = normalize_uploaded_df(df).reset_index(drop=True)
    safe_rows = json_safe_records(clean)
    payloads = []
    for i, row_data in enumerate(safe_rows):
        row_data = {c: json_safe_value(row_data.get(c, None)) for c in APP_COLUMNS}
        payloads.append({
            "project_id": project_id,
            "row_order": int(i),
            "row_data": row_data,
            "updated_by": user,
            "updated_at": now_iso(),
        })

    if payloads:
        sb.table("allocation_rows").insert(payloads).execute()

    sb.table("projects").update({"updated_at": now_iso()}).eq("id", project_id).execute()

def next_version_no(project_id):
    res = (sb.table("allocation_versions").select("version_no")
           .eq("project_id", project_id).order("version_no", desc=True).limit(1).execute())
    return 1 if not res.data else int(res.data[0]["version_no"]) + 1

def save_version(project_id, df, user, note):
    clean = normalize_uploaded_df(df)
    snap = json_safe_records(clean)
    vno = next_version_no(project_id)

    sb.table("allocation_versions").insert({
        "project_id": project_id,
        "version_no": vno,
        "snapshot": snap,
        "saved_by": user,
        "save_note": note,
        "created_at": now_iso(),
    }).execute()

    sb.table("save_events").insert({
        "project_id": project_id,
        "event_type": "save_version",
        "event_by": user,
        "event_note": note,
        "created_at": now_iso(),
    }).execute()

    return vno

def list_versions(project_id):
    return (sb.table("allocation_versions")
            .select("id,version_no,saved_by,save_note,created_at")
            .eq("project_id", project_id).order("version_no", desc=True).execute().data or [])

def load_version(version_id):
    return sb.table("allocation_versions").select("*").eq("id", version_id).single().execute().data

def delete_all_versions(project_id):
    """Delete all saved version snapshots for the selected project."""
    return sb.table("allocation_versions").delete().eq("project_id", project_id).execute()


def clear_shared_allocation_table(project_id, user):
    """Delete all allocation rows for the selected project, leaving the project itself intact."""
    sb.table("allocation_rows").delete().eq("project_id", project_id).execute()
    sb.table("save_events").insert({
        "project_id": project_id,
        "event_type": "clear_allocation_rows",
        "event_by": user,
        "event_note": "Admin cleared shared allocation table",
        "created_at": now_iso(),
    }).execute()
    sb.table("projects").update({"updated_at": now_iso()}).eq("id", project_id).execute()


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
    """
    Time deconfliction that actually honors the Anchor field.

    Previous behavior preferred the original start time first. That made the
    sidebar Anchor look like it was not changing anything. This version packs
    conflicting rows from the selected anchor forward, while still respecting
    max_shift_sec and frequency guard band rules.
    """
    req = {"StartTime", "EndTime", "StartF", "EndF", "PowerW"}
    if not req.issubset(df.columns):
        return df.copy()

    d = df.copy()
    d["OrigStartSec"] = d["StartTime"].apply(parse_time_one)
    d["OrigEndSec"] = d["EndTime"].apply(parse_time_one)
    d = d.loc[d["OrigStartSec"].notna() & d["OrigEndSec"].notna()].copy()

    if d.empty:
        return df.copy()

    d["OrigEndSec"] = np.where(
        d["OrigEndSec"] < d["OrigStartSec"],
        d["OrigEndSec"] + 86400,
        d["OrigEndSec"],
    )
    d["DurationSec"] = d["OrigEndSec"] - d["OrigStartSec"]

    if priority_mode == "Highest Power First":
        d = d.sort_values(["PowerW", "OrigStartSec"], ascending=[False, True])
    elif priority_mode == "Shortest Duration First":
        d = d.sort_values(["DurationSec", "OrigStartSec"], ascending=[True, True])
    else:
        d = d.sort_values(["PowerW", "OrigStartSec"], ascending=[False, True])

    placed, out_rows = [], []
    anchor_sec = float(anchor_sec)
    horizon_end = max(24 * 3600, anchor_sec + float(max_shift_sec), float(d["OrigEndSec"].max()) + float(max_shift_sec))

    for _, row in d.iterrows():
        item = row.to_dict()
        req_start = float(item["OrigStartSec"])
        dur = float(item["DurationSec"])

        # If earlier moves are allowed, pack from the anchor.
        # If earlier moves are not allowed, never place before the original requested time or anchor.
        earliest = anchor_sec if allow_earlier else max(anchor_sec, req_start)
        latest = min(horizon_end - dur, req_start + float(max_shift_sec))

        # If the original row is before the selected anchor, allow it to move forward at least to the anchor.
        if latest < earliest:
            latest = earliest

        candidates = set()

        # Always try the anchor/earliest first so changing Anchor visibly changes the schedule.
        candidates.add(earliest)

        # Try just after any already-placed conflicting block.
        for p in placed:
            if freq_overlap(item["StartF"], item["EndF"], p["StartF"], p["EndF"], guard_mhz):
                candidates.add(float(p["PlacedEndSec"]) + float(pad_sec))
                if allow_earlier:
                    candidates.add(float(p["PlacedStartSec"]) - float(pad_sec) - dur)

        # Backup scan. One-minute granularity gives better packing than five minutes.
        if latest >= earliest:
            candidates.update(np.arange(earliest, latest + 1, 60))

        # Only legal finite candidates.
        candidates = [
            float(c)
            for c in candidates
            if np.isfinite(c) and c >= earliest and c <= latest
        ]

        # Sort from anchor/earliest forward. This is the key anchor fix.
        candidates = sorted(candidates, key=lambda c: (abs(c - earliest), c))

        chosen, ok = earliest, False
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


def add_group_legend(ax, palette, title, dark=False, max_items=30):
    """Add a right-side legend to matplotlib plots."""
    if not palette:
        return
    items = list(palette.items())[:max_items]
    handles = [
        Rectangle((0, 0), 1, 1, facecolor=col, edgecolor=("white" if dark else "black"), alpha=0.75)
        for _, col in items
    ]
    labels = [str(name) for name, _ in items]
    leg = ax.legend(
        handles,
        labels,
        title=title,
        loc="center left",
        bbox_to_anchor=(1.01, 0.5),
        frameon=True,
        fontsize=8,
        title_fontsize=9,
        borderaxespad=0.0,
    )
    if dark:
        leg.get_frame().set_facecolor("black")
        leg.get_frame().set_edgecolor("white")
        leg.get_title().set_color("white")
        for txt in leg.get_texts():
            txt.set_color("white")

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


def color_to_rgba(color, alpha=180):
    """Convert a matplotlib color to pydeck RGBA."""
    try:
        rgba = plt.matplotlib.colors.to_rgba(color)
        return [int(rgba[0] * 255), int(rgba[1] * 255), int(rgba[2] * 255), int(alpha)]
    except Exception:
        return [31, 119, 180, int(alpha)]


def prep_map_df(df, group_field):
    """Prepare valid map rows from decimal-degree Latitude/Longitude."""
    if "Latitude" not in df.columns or "Longitude" not in df.columns:
        return pd.DataFrame()

    m = df.copy()
    m["Latitude"] = pd.to_numeric(m["Latitude"], errors="coerce")
    m["Longitude"] = pd.to_numeric(m["Longitude"], errors="coerce")
    m = m[
        m["Latitude"].between(-90, 90, inclusive="both")
        & m["Longitude"].between(-180, 180, inclusive="both")
    ].copy()

    if m.empty:
        return m

    for col in ["Location", "SiteName"]:
        if col not in m.columns:
            m[col] = ""
    for col in ["CoverageRadius", "AntennaHeight"]:
        if col not in m.columns:
            m[col] = np.nan

    m["Group"] = m[group_field].astype(str) if group_field in m.columns else m["Equipment"].astype(str)
    return m


def build_map_deck(df, group_field, palette, radius_units="miles", show_coverage=True, map_style="light"):
    """Build an interactive map with black-outlined points and optional coverage circles."""
    m = prep_map_df(df, group_field)
    if m.empty:
        return None, m

    m["PowerW"] = pd.to_numeric(m.get("PowerW", 1), errors="coerce").fillna(1)
    m["CoverageRadius"] = pd.to_numeric(m.get("CoverageRadius", np.nan), errors="coerce")

    if radius_units == "kilometers":
        m["coverage_m"] = m["CoverageRadius"] * 1000.0
    elif radius_units == "nautical miles":
        m["coverage_m"] = m["CoverageRadius"] * 1852.0
    else:
        m["coverage_m"] = m["CoverageRadius"] * 1609.344

    m["coverage_m"] = m["coverage_m"].fillna(0).clip(lower=0)
    m["color"] = m["Group"].map(lambda g: color_to_rgba(palette.get(str(g), "#1f77b4"), 220))
    m["fill_color"] = m["Group"].map(lambda g: color_to_rgba(palette.get(str(g), "#1f77b4"), 55))
    m["point_radius"] = (m["PowerW"].clip(lower=0.1) ** 0.5 * 55).clip(lower=55, upper=350)

    layers = []

    if show_coverage and (m["coverage_m"] > 0).any():
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=m[m["coverage_m"] > 0],
                get_position="[Longitude, Latitude]",
                get_radius="coverage_m",
                get_fill_color="fill_color",
                get_line_color=[0, 0, 0, 170],
                line_width_min_pixels=1,
                stroked=True,
                filled=True,
                pickable=True,
            )
        )

    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=m,
            get_position="[Longitude, Latitude]",
            get_radius="point_radius",
            get_fill_color="color",
            get_line_color=[0, 0, 0, 255],
            line_width_min_pixels=1.5,
            stroked=True,
            filled=True,
            pickable=True,
        )
    )

    # Use free CARTO basemap styles so the map works without a Mapbox/Google/Bing token.
    # The previous Mapbox styles can render blank on Streamlit Cloud if no Mapbox token is configured.
    if map_style == "dark":
        style = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
    elif map_style == "satellite":
        # Free no-token fallback. True satellite requires a provider token, such as Mapbox, Google, Bing, or Esri.
        style = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json"
    else:
        style = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=float(m["Latitude"].mean()),
            longitude=float(m["Longitude"].mean()),
            zoom=8 if len(m) > 1 else 11,
            pitch=0,
        ),
        map_style=style,
        tooltip={
            "html": "<b>{Equipment}</b><br/>Group: {Group}<br/>Site: {SiteName}<br/>Location: {Location}<br/>Freq: {CenterF} MHz<br/>Power: {PowerW} W<br/>Time: {StartTime} - {EndTime}",
            "style": {"backgroundColor": "white", "color": "black"},
        },
    )
    return deck, m


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
            ax.add_patch(Rectangle((x,0), w,h, fill=False, edgecolor="black", linewidth=max(outline_lwd, 0.8)))
        elif power_style == "outline_fill":
            ax.add_patch(Rectangle((x,0), w,h, facecolor=col, edgecolor="black", alpha=alpha_val, linewidth=max(outline_lwd, 0.8)))
        else:
            ax.add_patch(Rectangle((x,0), w,h, facecolor=col, edgecolor="black", alpha=alpha_val, linewidth=0.8))
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
    style_axes(ax, dark)
    add_group_legend(ax, palette, group_field, dark)
    plt.tight_layout(rect=[0, 0, 0.84, 1])
    return fig

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
        ax.add_patch(Rectangle((x0,y0), w,h, facecolor=col, edgecolor="black", alpha=.6, linewidth=0.8))
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
    style_axes(ax, dark)
    add_group_legend(ax, palette, grp_field, dark)
    plt.tight_layout(rect=[0, 0, 0.84, 1])
    return fig


logged_in_user, current_role = require_login()
current_user_id = st.session_state.get("auth_user_id", "")
is_admin = current_role == "admin"
can_edit = current_role in ["admin", "editor"]

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Workspace")
    user_name = logged_in_user
    st.success(f"Logged in as: {user_name}")
    st.caption(f"Role: {current_role}")
    if st.button("Log out", use_container_width=True):
        for k in ["auth_user", "auth_user_id", "auth_role", "auth_full_name"]:
            st.session_state.pop(k, None)
        try:
            sb.auth.sign_out()
        except Exception:
            pass
        st.rerun()
    projects = list_projects(); project_names = [p["name"] for p in projects]
    create_new = st.toggle("Create new project", value=False, disabled=not can_edit)
    if create_new:
        new_name = st.text_input("New project name"); new_desc = st.text_area("Description", height=80)
        if st.button("Create project", type="primary", use_container_width=True, disabled=not can_edit):
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
    dc_start = st.text_input(
        "Anchor",
        value=st.session_state.get("dc_anchor_time", "6am"),
        key="dc_anchor_time",
        help="Deconfliction will pack moved rows starting at this time. Examples: 4am, 0730, 13:00, 1:30pm.",
    )
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

    st.divider()
    st.header("Map controls")
    map_group_by = st.selectbox("Map color by", ["Equipment", "Unit", "Tech"], index=0)
    radius_units = st.selectbox("Coverage radius units", ["miles", "kilometers", "nautical miles"], index=0)
    show_coverage = st.checkbox("Show coverage circles", value=True)
    map_style_choice = st.selectbox("Map style", ["light", "dark", "satellite"], index=0)

project_id = st.session_state.get("project_id")
if not project_id:
    st.info("Create or select a project to begin."); st.stop()

current_df = get_project_rows(project_id)

# Restore saved workbook sheets. If there are no saved sheets yet, use the shared allocation table as a single Working sheet.
saved_sheets = load_project_sheets(project_id)
if saved_sheets:
    if st.session_state.get("workbook_project_id") != project_id:
        st.session_state["workbook_sheets"] = saved_sheets
        st.session_state["active_sheet_name"] = list(saved_sheets.keys())[0]
        st.session_state["workbook_project_id"] = project_id
else:
    if st.session_state.get("workbook_project_id") != project_id or "workbook_sheets" not in st.session_state:
        st.session_state["workbook_sheets"] = {"Working": normalize_uploaded_df(current_df)}
        st.session_state["active_sheet_name"] = "Working"
        st.session_state["workbook_project_id"] = project_id

st.session_state.setdefault("pending_upload_df", None)
st.session_state.setdefault("pending_upload_sheets_dict", None)
st.session_state.setdefault("pending_upload_sheet", None)
st.session_state.setdefault("pending_upload_name", None)
st.session_state.setdefault("pending_upload_bytes", None)

# Workbook persistence status.
try:
    _saved_sheet_count = len(load_project_sheets(project_id))
except Exception:
    _saved_sheet_count = 0
if _saved_sheet_count == 0 and len(st.session_state.get("workbook_sheets", {})) > 1:
    st.warning("Workbook tabs are visible in this session, but they have not been confirmed saved in Supabase yet. Click Save shared changes, or run the v17 SQL setup if saving fails.")

cols = st.columns(4)
cols[0].metric("Rows", len(current_df)); cols[1].metric("Project", next((p["name"] for p in projects if p["id"] == project_id), "Selected")); cols[2].metric("User", user_name); cols[3].metric("Storage", "Supabase JSON")


if is_admin:
    with st.expander("Admin: User management", expanded=False):
        st.caption("Admins can create users, change roles, disable accounts, or delete auth users. Deleting requires the Supabase service role key.")

        users = list_app_users()
        if users:
            st.dataframe(pd.DataFrame(users), use_container_width=True)
        else:
            st.info("No users are listed yet. The first authenticated user becomes admin automatically.")

        st.markdown("#### Create user")
        with st.form("admin_create_user_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                new_email = st.text_input("New user email")
                new_full_name = st.text_input("Full name")
            with c2:
                new_password = st.text_input("Temporary password", type="password")
                new_role = st.selectbox("Role", ["viewer", "editor", "admin"], index=0)
            submitted_create_user = st.form_submit_button("Create user", type="primary")

        if submitted_create_user:
            try:
                if not new_email.strip() or not new_password:
                    st.error("Email and temporary password are required.")
                elif len(new_password) < 8:
                    st.error("Temporary password must be at least 8 characters.")
                else:
                    uid = admin_create_user(new_email.strip(), new_password, new_role, new_full_name.strip(), logged_in_user)
                    st.success(f"Created user {new_email.strip()} as {new_role}.")
                    st.rerun()
            except Exception as e:
                st.error(f"Could not create user: {e}")

        st.markdown("#### Change role / disable / remove user")
        users = list_app_users()
        if users:
            user_labels = [f"{u.get('email','')} — {u.get('role','viewer')} — {u.get('user_id','')}" for u in users]
            selected_label = st.selectbox("Select user", user_labels)
            selected_user = users[user_labels.index(selected_label)]

            valid_roles = ["viewer", "editor", "admin", "disabled"]
            current_selected_role = selected_user.get("role", "viewer")
            if current_selected_role not in valid_roles:
                current_selected_role = "viewer"

            role_choice = st.selectbox(
                "New role",
                valid_roles,
                index=valid_roles.index(current_selected_role),
            )

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Update selected user role", use_container_width=True):
                    try:
                        update_user_role(
                            selected_user["user_id"],
                            selected_user.get("email", ""),
                            role_choice,
                            selected_user.get("full_name", ""),
                            logged_in_user,
                        )
                        st.success("User role updated.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not update role: {e}")
            with c2:
                if st.button("Delete selected auth user", use_container_width=True):
                    try:
                        update_user_role(
                            selected_user["user_id"],
                            selected_user.get("email", ""),
                            "disabled",
                            selected_user.get("full_name", ""),
                            logged_in_user,
                        )
                        admin_delete_user(selected_user["user_id"])
                        st.success("User deleted from Supabase Auth and disabled in app roles.")
                        st.rerun()
                    except Exception as e:
                        st.warning(f"User was disabled in app roles, but auth delete failed or is unavailable: {e}")
                        st.rerun()



if is_admin:
    with st.expander("Admin: Delete data", expanded=False):
        st.warning("These actions affect the selected project only. They cannot be undone.")

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("#### Delete all version history")
            st.caption("Deletes every saved snapshot for this project. Current workbook/table rows stay untouched.")
            confirm_versions = st.checkbox(
                "I understand: delete all version history",
                key=f"confirm_delete_versions_{project_id}",
            )
            if st.button(
                "Delete all version history",
                type="primary",
                use_container_width=True,
                disabled=not confirm_versions,
                key=f"btn_delete_versions_{project_id}",
            ):
                try:
                    delete_all_versions(project_id)
                    st.success("All version history for this project was deleted.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not delete version history: {e}")

        with col_b:
            st.markdown("#### Clear shared allocation table")
            st.caption("Deletes current allocation rows and saved workbook tabs. Project, users, uploaded files, and versions remain.")
            confirm_table = st.checkbox(
                "I understand: clear shared allocation table",
                key=f"confirm_clear_table_{project_id}",
            )
            if st.button(
                "Clear shared allocation table",
                type="primary",
                use_container_width=True,
                disabled=not confirm_table,
                key=f"btn_clear_table_{project_id}",
            ):
                try:
                    clear_shared_allocation_table(project_id, logged_in_user)
                    st.session_state.pop("editor", None)
                    st.session_state.pop("workbook_sheets", None)
                    st.session_state.pop("active_sheet_name", None)
                    st.session_state.pop("workbook_project_id", None)
                    st.success("Shared allocation table and workbook tabs were cleared.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not clear shared allocation table: {e}")


with st.expander("Import / replace table from file or pasted CSV", expanded=(len(current_df)==0)):
    c1, c2 = st.columns(2)

    with c1:
        uploaded = st.file_uploader("Upload CSV/XLSX", type=["csv", "xlsx", "xls"], key="upload_file_widget")

        if uploaded is not None:
            try:
                file_bytes = uploaded.getvalue()
                file_sig = f"{uploaded.name}-{len(file_bytes)}"

                if st.session_state.get("pending_upload_sig") != file_sig:
                    sheets_dict, active_sheet, file_bytes = read_uploaded_workbook(uploaded)
                    st.session_state["pending_upload_sheets_dict"] = sheets_dict
                    st.session_state["pending_upload_sheet"] = active_sheet
                    st.session_state["pending_upload_df"] = sheets_dict[active_sheet]
                    st.session_state["pending_upload_name"] = uploaded.name
                    st.session_state["pending_upload_bytes"] = file_bytes
                    st.session_state["pending_upload_sig"] = file_sig

            except Exception as e:
                st.error(f"Upload failed: {e}")

        if st.session_state.get("pending_upload_sheets_dict") is not None:
            sheets_dict = st.session_state["pending_upload_sheets_dict"]
            sheet_names = list(sheets_dict.keys())

            if len(sheet_names) > 1:
                current_sheet = st.selectbox(
                    "Workbook sheet preview",
                    sheet_names,
                    index=sheet_names.index(st.session_state.get("pending_upload_sheet", sheet_names[0]))
                    if st.session_state.get("pending_upload_sheet", sheet_names[0]) in sheet_names else 0,
                    key="pending_upload_sheet_select",
                )
                st.session_state["pending_upload_sheet"] = current_sheet
                st.session_state["pending_upload_df"] = sheets_dict[current_sheet]
            else:
                current_sheet = sheet_names[0]

            st.caption(f"Pending upload: {st.session_state.get('pending_upload_name', 'uploaded file')} — {len(sheet_names)} sheet(s)")
            st.dataframe(st.session_state["pending_upload_df"].head(20), use_container_width=True)

            b1, b2 = st.columns(2)
            with b1:
                if st.button("Replace with uploaded workbook/data", type="primary", use_container_width=True, disabled=not can_edit):
                    sheets_dict = st.session_state["pending_upload_sheets_dict"]
                    active_sheet = st.session_state.get("pending_upload_sheet") or list(sheets_dict.keys())[0]
                    tmp = normalize_uploaded_df(sheets_dict[active_sheet].copy())

                    # Save active sheet to the main shared allocation table for plots/deconfliction.
                    replace_project_rows(project_id, tmp, user_name)
                    save_version(project_id, tmp, user_name, f"Imported file — active sheet: {active_sheet}")

                    # Save every sheet so workbook tabs survive logout/login.
                    try:
                        save_project_sheets(project_id, sheets_dict, user_name)
                    except Exception as e:
                        st.warning(f"Main table was saved, but workbook sheets could not be saved: {e}")

                    # Save original file.
                    try:
                        upload_original_file(
                            project_id,
                            st.session_state.get("pending_upload_name", "uploaded_file"),
                            st.session_state.get("pending_upload_bytes"),
                            user_name,
                        )
                    except Exception as e:
                        st.warning(f"Rows were saved, but the original file could not be saved to Storage: {e}")

                    st.session_state["workbook_sheets"] = sheets_dict
                    st.session_state["active_sheet_name"] = active_sheet
                    st.session_state["pending_upload_df"] = None
                    st.session_state["pending_upload_sheets_dict"] = None
                    st.session_state["pending_upload_name"] = None
                    st.session_state["pending_upload_bytes"] = None
                    st.session_state["pending_upload_sig"] = None
                    st.success("Uploaded workbook/data saved.")
                    st.rerun()
            with b2:
                if st.button("Clear pending upload", use_container_width=True):
                    st.session_state["pending_upload_df"] = None
                    st.session_state["pending_upload_sheets_dict"] = None
                    st.session_state["pending_upload_name"] = None
                    st.session_state["pending_upload_bytes"] = None
                    st.session_state["pending_upload_sig"] = None
                    st.session_state["pending_upload_sheet"] = None
                    st.rerun()

    with c2:
        pasted = st.text_area("Paste CSV", height=180, placeholder="Start Time,End Time,Equipment,Center Frequency (MHz),Bandwidth (MHz),Power (W),Tech,Unit")
        if pasted.strip():
            try:
                tmp = normalize_uploaded_df(pd.read_csv(io.StringIO(pasted)))
                st.dataframe(tmp.head(20), use_container_width=True)
                if st.button("Replace with pasted CSV", type="primary", disabled=not can_edit):
                    replace_project_rows(project_id, tmp, user_name)
                    save_version(project_id, tmp, user_name, "Pasted CSV")
                    save_project_sheets(project_id, {"CSV": tmp}, user_name)
                    st.session_state["workbook_sheets"] = {"CSV": tmp}
                    st.session_state["active_sheet_name"] = "CSV"
                    st.success("Pasted CSV saved.")
                    st.rerun()
            except Exception as e:
                st.error(f"Could not parse pasted CSV: {e}")


st.subheader("Shared allocation workbook")

workbook_sheets = st.session_state.get("workbook_sheets") or {"Working": normalize_uploaded_df(current_df)}
sheet_names = list(workbook_sheets.keys())
saved_sheet_count_now = len(load_project_sheets(project_id))
st.caption(f"Workbook tabs in app: {len(sheet_names)} | Workbook tabs saved in Supabase: {saved_sheet_count_now}")

if len(sheet_names) > 1:
    st.caption("Each Excel worksheet is preserved as a tab. Choose the active plotting sheet before saving.")
else:
    st.caption("Single-sheet project. Upload an XLSX with multiple sheets to preserve workbook tabs.")

active_sheet_name = st.selectbox(
    "Active sheet for plots/deconfliction",
    sheet_names,
    index=sheet_names.index(st.session_state.get("active_sheet_name", sheet_names[0]))
    if st.session_state.get("active_sheet_name", sheet_names[0]) in sheet_names else 0,
    key="active_sheet_selector",
)
st.session_state["active_sheet_name"] = active_sheet_name

sheet_tabs = st.tabs(sheet_names)
edited_sheets = {}
for i, sheet_name in enumerate(sheet_names):
    with sheet_tabs[i]:
        edited_sheets[sheet_name] = st.data_editor(
            workbook_sheets[sheet_name],
            use_container_width=True,
            height=330,
            num_rows="dynamic",
            key=f"sheet_editor_{project_id}_{sheet_name}",
            disabled=not can_edit,
        )

edited_df = normalize_uploaded_df(edited_sheets[active_sheet_name])

s1, s2, s3, s4 = st.columns([1, 1, 1.2, 1.2])
with s1:
    if st.button("💾 Save shared changes", type="primary", use_container_width=True, disabled=not can_edit):
        try:
            # Save all workbook tabs and also save active sheet to main allocation table.
            saved_tabs = save_project_sheets(project_id, edited_sheets, user_name)
            replace_project_rows(project_id, edited_df, user_name)
            st.session_state["workbook_sheets"] = edited_sheets
            st.success(f"Saved active sheet and {saved_tabs} workbook tab(s) permanently.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not save workbook tabs. Make sure you ran the v17 SQL setup. Details: {e}")

with s2:
    version_note = st.text_input("Version note", value="Manual save", label_visibility="collapsed")

with s3:
    if st.button("📌 Save version snapshot", use_container_width=True, disabled=not can_edit):
        st.success(f"Saved version {save_version(project_id, edited_df, user_name, version_note)}.")

with s4:
    try:
        st.download_button(
            "Download workbook XLSX",
            data=workbook_to_xlsx_bytes(edited_sheets),
            file_name="spectrum_planner_workbook.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except Exception as e:
        st.warning(f"Workbook download unavailable: {e}")

with st.expander("Version history / restore"):
    versions = list_versions(project_id)
    if not versions:
        st.info("No versions saved yet.")
    else:
        st.dataframe(pd.DataFrame(versions)[["version_no", "saved_by", "save_note", "created_at"]], use_container_width=True)
        selected_v = st.selectbox("Restore version", versions, format_func=lambda v: f"v{v['version_no']} — {v.get('save_note') or ''} — {v.get('saved_by') or ''}")
        if st.button("Restore selected version", disabled=not can_edit):
            v = load_version(selected_v["id"])
            restored = normalize_uploaded_df(pd.DataFrame(v["snapshot"]))
            replace_project_rows(project_id, restored, user_name)
            save_project_sheets(project_id, {"Restored": restored}, user_name)
            save_version(project_id, restored, user_name, f"Restored v{selected_v['version_no']}")
            st.session_state["workbook_sheets"] = {"Restored": restored}
            st.session_state["active_sheet_name"] = "Restored"
            st.success("Restored.")
            st.rerun()

try:
    df_ready = prep_df(edited_df)
except Exception as e:
    st.error(f"Could not prepare table for plots: {e}"); st.stop()
if df_ready.empty:
    st.warning("No valid plot rows. Need Start/End Frequency and Power."); st.stop()

grp_ut = unittech_field(df_ready)
pal_equipment = make_palette(sorted(safe_group(df_ready["Equipment"]).unique().tolist()))
pal_unittech = make_palette(sorted(safe_group(df_ready[grp_ut]).unique().tolist()))
map_group_field = map_group_by if map_group_by in df_ready.columns else "Equipment"
pal_map = make_palette(sorted(safe_group(df_ready[map_group_field]).unique().tolist()))
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
    if pd.isna(anchor):
        st.error("Deconflict anchor is invalid. Use examples like 4am, 0730, 13:00, or 1:30pm.")
        st.stop()
    st.caption(f"Auto-deconflict anchor applied: {fmt_hhmm(float(anchor))}")
    plot_df_conf = auto_deconflict_smart(
        df_ready,
        float(dc_window) * 3600,
        float(dc_pad_min) * 60,
        float(anchor),
        float(guard_mhz),
        allow_earlier,
        priority_mode,
    )
    if "StartTimeDC" in plot_df_conf.columns:
        plot_df_conf["StartTimeOrig"] = plot_df_conf["StartTime"]; plot_df_conf["EndTimeOrig"] = plot_df_conf["EndTime"]
        plot_df_conf["StartTime"] = np.where(plot_df_conf["StartTimeDC"].notna(), plot_df_conf["StartTimeDC"], plot_df_conf["StartTime"])
        plot_df_conf["EndTime"] = np.where(plot_df_conf["EndTimeDC"].notna(), plot_df_conf["EndTimeDC"], plot_df_conf["EndTime"])
conf_eq = detect_conflicts_generic(plot_df_conf, "Equipment", guard_mhz)
conf_ut = detect_conflicts_generic(plot_df_conf, grp_ut, guard_mhz)

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Equipment Power",
    "Equipment Deconfliction",
    f"{grp_ut} Power",
    f"{grp_ut} Deconfliction",
    "Map View",
    "Conflict Tables",
])

with tab1:
    fig = build_power_plot(df_ready, "Equipment", dark, alpha_val, tick_major, tick_minor, int(label_digits), pal_equipment, auto_thin, float(label_gap), high_power_top, power_style, float(outline_lwd), show_center_labels)
    st.pyplot(fig, use_container_width=True)
    st.download_button("Download PNG", fig_to_png_bytes(fig), "equipment_power.png", "image/png")

with tab2:
    fig = build_deconflict_plot(plot_df_conf, "Equipment", pal_equipment, dark, tick_major, tick_minor, box_labels, box_label_min_height_min, show_shift_label, moved_outline, conf_eq)
    st.pyplot(fig, use_container_width=True)
    st.download_button("Download PNG", fig_to_png_bytes(fig), "equipment_deconfliction.png", "image/png")

with tab3:
    fig = build_power_plot(df_ready, grp_ut, dark, alpha_val, tick_major, tick_minor, int(label_digits), pal_unittech, auto_thin, float(label_gap), high_power_top, power_style, float(outline_lwd), show_center_labels)
    st.pyplot(fig, use_container_width=True)
    st.download_button("Download PNG", fig_to_png_bytes(fig), f"{grp_ut.lower()}_power.png", "image/png")

with tab4:
    fig = build_deconflict_plot(plot_df_conf, grp_ut, pal_unittech, dark, tick_major, tick_minor, box_labels, box_label_min_height_min, show_shift_label, moved_outline, conf_ut)
    st.pyplot(fig, use_container_width=True)
    st.download_button("Download PNG", fig_to_png_bytes(fig), f"{grp_ut.lower()}_deconfliction.png", "image/png")

with tab5:
    st.markdown("#### Map View")
    st.caption("Uses decimal-degree Latitude and Longitude columns. Coverage Radius draws circles using the selected units. Basemap uses free CARTO tiles; no Mapbox/Google token required.")
    deck, map_df = build_map_deck(
        df_ready,
        map_group_field,
        pal_map,
        radius_units=radius_units,
        show_coverage=show_coverage,
        map_style=map_style_choice,
    )

    if deck is None:
        st.info("No valid map rows found. Add Latitude and Longitude columns with decimal-degree values, for example 31.12345 and -97.12345.")
        st.dataframe(
            pd.DataFrame({
                "Required": ["Latitude", "Longitude"],
                "Recommended": ["Location", "Site Name"],
                "Optional": ["Coverage Radius", "Antenna Height"],
            }),
            use_container_width=True,
        )
    else:
        st.pydeck_chart(deck, use_container_width=True)

        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "Download map HTML",
                data=deck_to_html_bytes(deck),
                file_name="spectrum_map.html",
                mime="text/html",
                use_container_width=True,
            )
        with d2:
            st.download_button(
                "Download map data CSV",
                data=map_df.to_csv(index=False).encode("utf-8"),
                file_name="spectrum_map_data.csv",
                mime="text/csv",
                use_container_width=True,
            )

        st.markdown("#### Map rows")
        display_cols = [c for c in ["Equipment", "Tech", "Unit", "Latitude", "Longitude", "Location", "SiteName", "CoverageRadius", "AntennaHeight", "CenterF", "PowerW", "StartTime", "EndTime"] if c in map_df.columns]
        st.dataframe(map_df[display_cols], use_container_width=True)

with tab6:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Equipment conflicts")
        st.dataframe(conflict_summary(conf_eq), use_container_width=True)
    with c2:
        st.markdown(f"#### {grp_ut} conflicts")
        st.dataframe(conflict_summary(conf_ut), use_container_width=True)

    if auto_dc and "ShiftSec" in plot_df_conf.columns:
        st.markdown("#### Auto-deconflict moves")
        moves = plot_df_conf.copy()
        moves["ShiftMin"] = moves["ShiftSec"].fillna(0) / 60
        moves = moves.loc[abs(moves["ShiftMin"]) > .001]
        cols = [c for c in ["Equipment", "Tech", "Unit", "StartF", "EndF", "StartTimeOrig", "EndTimeOrig", "StartTimeDC", "EndTimeDC", "ShiftMin", "Placed"] if c in moves.columns]
        st.dataframe(moves[cols] if not moves.empty else pd.DataFrame({"Message": ["No rows were moved."]}), use_container_width=True)
