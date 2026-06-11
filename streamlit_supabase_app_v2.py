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

    rename = {}
    for col in out.columns:
        k = key_name(col)
        if k in RENAME_MAP:
            rename[col] = RENAME_MAP[k]

    out = out.rename(columns=rename)

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


def smart_frequency_deconflict(df: pd.DataFrame, low_mhz: float, high_mhz: float, step_mhz: float):
    out = active_only(df, show_inactive=True)

    center_col = find_col(out, ["Center Frequency (MHz)", "Center Frequency", "CenterF", "Frequency"])
    bw_col = find_col(out, ["Bandwidth (MHz)", "Bandwidth", "BW"])

    if center_col is None or bw_col is None:
        return out, pd.DataFrame([{"Message": "Center Frequency and Bandwidth columns are required."}])

    moves = []

    active_df = active_only(out, show_inactive=False)
    conflicts = detect_conflicts(active_df)

    if conflicts.empty:
        return out, pd.DataFrame([{"Message": "No conflicts detected."}])

    conflict_rows = set()
    for _, row in conflicts.iterrows():
        conflict_rows.add(int(row["Row A"]) - 1)
        conflict_rows.add(int(row["Row B"]) - 1)

    candidates = []
    x = low_mhz
    while x <= high_mhz:
        candidates.append(round(x, 6))
        x += step_mhz

    for idx in sorted(conflict_rows):
        if idx not in out.index:
            continue

        row = out.loc[idx]

        if not to_bool(row.get("Active"), True):
            continue

        if to_bool(row.get("Locked"), False):
            continue

        old_center = to_float(row.get(center_col))
        bw = to_float(row.get(bw_col))

        if old_center is None or bw is None or bw <= 0:
            continue

        for candidate in candidates:
            if candidate - bw / 2 < low_mhz or candidate + bw / 2 > high_mhz:
                continue

            test = out.copy()
            test.at[idx, center_col] = candidate
            test = recalc_start_end(test)

            if detect_conflicts(test).empty:
                out = test
                moves.append(
                    {
                        "Row": idx + 1,
                        "Old Center Frequency (MHz)": old_center,
                        "New Center Frequency (MHz)": candidate,
                        "Bandwidth (MHz)": bw,
                        "Action": "Moved frequency; time unchanged",
                    }
                )
                break

    return recalc_start_end(out), pd.DataFrame(moves)


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
    st.subheader("Smart Planner — Auto Deconflict by Frequency")
    st.caption("Moves unlocked active rows to open frequency spots. Time windows stay unchanged.")

    p1, p2, p3 = st.columns(3)
    low = p1.number_input("Search low MHz", value=2200.0, step=1.0)
    high = p2.number_input("Search high MHz", value=2300.0, step=1.0)
    step = p3.number_input("Step MHz", value=1.0, min_value=0.001, step=0.5)

    if st.button("Auto deconflict by frequency", type="primary", use_container_width=True):
        new_df, moves = smart_frequency_deconflict(edited_df, low, high, step)
        st.session_state["pending_planner_df"] = new_df
        st.session_state["pending_planner_moves"] = moves

    if "pending_planner_moves" in st.session_state:
        moves = st.session_state["pending_planner_moves"]
        if moves.empty:
            st.info("No moves were made.")
        else:
            st.dataframe(moves, use_container_width=True, hide_index=True)

        apply_moves = st.checkbox("I reviewed the changes and want to apply them")
        if st.button("Apply planner changes", use_container_width=True):
            if not apply_moves:
                st.warning("Check the review box first.")
            else:
                st.session_state["sheets"][active_sheet] = st.session_state["pending_planner_df"]
                del st.session_state["pending_planner_df"]
                del st.session_state["pending_planner_moves"]
                st.success("Applied planner changes.")
                st.rerun()
