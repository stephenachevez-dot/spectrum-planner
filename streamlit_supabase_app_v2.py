import io, re, hashlib, base64, math, json
from datetime import datetime, date, time
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

st.set_page_config(page_title='Spectrum Planner V27 Label Orientation', layout='wide')

APP_COLUMNS=['Active','Locked','Start Time','End Time','Unit','Sponsor','Equipment','Tech','Start Frequency (MHz)','Center Frequency (MHz)','End Frequency (MHz)','Bandwidth (MHz)','Power (W)','Power (dBm)','Tech Category','Latitude','Longitude','Location','System/Platform','Antenna Height','Coverage Radius','Site Name','MGRS','USNG','Notes']
PALETTE=['#2563EB','#F97316','#22C55E','#EAB308','#A855F7','#EF4444','#06B6D4','#84CC16','#EC4899','#8B5CF6','#14B8A6','#F59E0B','#0EA5E9','#F43F5E','#64748B','#6366F1','#15803D','#C2410C','#A16207','#7C3AED','#0F766E','#B45309','#0369A1','#BE185D','#334155']
RENAME_MAP={
 'enabled':'Active','inuse':'Active','use':'Active','include':'Active','active':'Active','lock':'Locked','locked':'Locked','lockfrequency':'Locked','lockboth':'Locked',
 'starttime':'Start Time','start':'Start Time','begintime':'Start Time','endtime':'End Time','end':'End Time','stoptime':'End Time',
 'unit':'Unit','sponsor':'Sponsor','sponser':'Sponsor','equipment':'Equipment','system':'Equipment','device':'Equipment','radio':'Equipment','tech':'Tech','technology':'Tech',
 'startf':'Start Frequency (MHz)','startfrequency':'Start Frequency (MHz)','startfrequencymhz':'Start Frequency (MHz)','startfreq':'Start Frequency (MHz)',
 'centerf':'Center Frequency (MHz)','centerfrequency':'Center Frequency (MHz)','centerfrequencymhz':'Center Frequency (MHz)','centerfreq':'Center Frequency (MHz)','frequency':'Center Frequency (MHz)',
 'endf':'End Frequency (MHz)','endfrequency':'End Frequency (MHz)','endfrequencymhz':'End Frequency (MHz)','endfreq':'End Frequency (MHz)',
 'bw':'Bandwidth (MHz)','bandwidth':'Bandwidth (MHz)','bandwidthmhz':'Bandwidth (MHz)','power':'Power (W)','powerw':'Power (W)','powerwatts':'Power (W)','powerdbm':'Power (dBm)','dbm':'Power (dBm)',
 'techcategory':'Tech Category','category':'Tech Category','lat':'Latitude','latitude':'Latitude','lon':'Longitude','lng':'Longitude','long':'Longitude','longitude':'Longitude','location':'Location',
 'systemplatform':'System/Platform','platform':'System/Platform','antennaheight':'Antenna Height','coverageradius':'Coverage Radius','sitename':'Site Name','site':'Site Name','mgrs':'MGRS','usng':'USNG','notes':'Notes','note':'Notes','comments':'Notes'}
MAX_CONFLICTS_DISPLAY=2500
MAX_PLANNER_ROWS=1200
try:
    from supabase import create_client
except Exception:
    create_client=None

def key_name(v): return re.sub(r'[^a-z0-9]+','',str(v or '').strip().lower())
def to_bool(v,default=True):
    try:
        if pd.isna(v): return default
    except Exception: pass
    if isinstance(v,bool): return v
    t=str(v).strip().lower()
    if t in {'true','t','yes','y','1','on','active','checked','x'}: return True
    if t in {'false','f','no','n','0','off','inactive','unchecked','','none','nan'}: return False
    return default

def to_float(v,default=None):
    try:
        if v is None or pd.isna(v): return default
    except Exception: pass
    try:
        m=re.search(r'-?\d+(?:\.\d+)?',str(v).replace(',',''))
        return float(m.group(0)) if m else default
    except Exception: return default

def find_col(df,names):
    lookup={key_name(c):c for c in df.columns}
    for n in names:
        if key_name(n) in lookup: return lookup[key_name(n)]
    for n in names:
        k=key_name(n)
        for found,orig in lookup.items():
            if k and (k in found or found in k): return orig
    return None

def normalize_columns(df,add_missing=True):
    out=df.copy()
    out=out.loc[:,[c for c in out.columns if not str(c).lower().startswith('unnamed')]]
    out=out.rename(columns={c:RENAME_MAP[key_name(c)] for c in out.columns if key_name(c) in RENAME_MAP})
    out=out.loc[:,~pd.Index(out.columns).duplicated(keep='first')].copy()
    if add_missing:
        for c in APP_COLUMNS:
            if c not in out.columns: out[c]=True if c=='Active' else False if c=='Locked' else None
    if 'Active' in out.columns: out['Active']=out['Active'].apply(lambda x: to_bool(x,True))
    if 'Locked' in out.columns: out['Locked']=out['Locked'].apply(lambda x: to_bool(x,False))
    pref=[c for c in APP_COLUMNS if c in out.columns]
    extra=[c for c in out.columns if c not in pref]
    return out[pref+extra]

def time_to_hours(v):
    try:
        if pd.isna(v): return None
    except Exception: pass
    if hasattr(v,'hour') and hasattr(v,'minute'): return float(v.hour)+float(v.minute)/60
    t=str(v or '').strip().lower()
    if not t or t in {'none','nan'}: return None
    try:
        if ':' in t:
            p=t.split(':'); return float(p[0])+float(p[1])/60
        m=re.search(r'\d+(?:\.\d+)?',t)
        if not m: return None
        val=float(m.group(0))
        return int(val//100)+(val%100)/60 if val>=100 else val
    except Exception: return None

def format_time_hhmm(h):
    h=float(h)%24; hh=int(h); mm=int(round((h-hh)*60))
    if mm>=60: hh=(hh+1)%24; mm=0
    return f'{hh:02d}:{mm:02d}'

def timestamp_string(): return datetime.now().strftime('%Y%m%d_%H%M%S')
def label_value(v):
    t=str(v or '').strip()
    return '(blank)' if not t or t.lower() in {'nan','none','blank','(blank)'} else t

def stable_color(label):
    d=hashlib.md5(label_value(label).encode()).hexdigest()
    return PALETTE[int(d[:8],16)%len(PALETTE)]

def frequency_display_value(v):
    val=to_float(v)
    return f'{val:.3f} MHz' if val is not None else None

def to_json_safe(x):
    """Return a value that is safe for strict JSON/Supabase jsonb.
    Handles NaN/Inf, pandas NA/NaT, Excel time/date objects, dicts, lists, and numpy scalars.
    """
    if x is None:
        return None

    # Recursively clean containers first.
    if isinstance(x, dict):
        return {str(k): to_json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [to_json_safe(v) for v in x]

    # pandas/numpy missing values, including NaN and NaT
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass

    # Python and numpy floating values.
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return None
    except Exception:
        pass

    # Datetime/date/time values from Excel/openpyxl/pandas.
    if isinstance(x, (pd.Timestamp, datetime, date, time)):
        return x.isoformat()
    if hasattr(x, 'isoformat'):
        try:
            return x.isoformat()
        except Exception:
            pass

    # Convert numpy scalar types to normal Python scalar types.
    if hasattr(x, 'item'):
        try:
            return to_json_safe(x.item())
        except Exception:
            pass

    return x

def json_strict_sanitize(obj):
    """Clean and validate JSON. Any remaining invalid float is converted to None."""
    clean = to_json_safe(obj)
    try:
        json.dumps(clean, allow_nan=False)
        return clean
    except ValueError:
        # Final defensive pass through JSON text after replacing non-compliant constants.
        text = json.dumps(clean, allow_nan=True)
        text = text.replace('NaN', 'null').replace('Infinity', 'null').replace('-Infinity', 'null')
        return json.loads(text)

def recalc_start_end_fast(df):
    out=normalize_columns(df,True)
    center=find_col(out,['Center Frequency (MHz)','Center Frequency','CenterF','Frequency'])
    bw=find_col(out,['Bandwidth (MHz)','Bandwidth','BW'])
    start=find_col(out,['Start Frequency (MHz)','Start Frequency','StartF'])
    end=find_col(out,['End Frequency (MHz)','End Frequency','EndF'])
    if center is None or bw is None: return out
    centers=pd.to_numeric(out[center],errors='coerce'); bws=pd.to_numeric(out[bw],errors='coerce')
    valid=centers.notna() & bws.notna() & (bws>0)
    out.loc[valid,start]=(centers[valid]-bws[valid]/2).round(6)
    out.loc[valid,end]=(centers[valid]+bws[valid]/2).round(6)
    return normalize_columns(out,True)

def active_only(df,show_inactive=False):
    out=recalc_start_end_fast(df)
    if not show_inactive and 'Active' in out.columns: out=out[out['Active']==True].copy()
    return out.reset_index(drop=True)

def intervals_overlap(a1,a2,b1,b2): return max(a1,b1)<min(a2,b2)
def row_window(row,start_col,end_col):
    t1=time_to_hours(row.get(start_col)) if start_col else None
    t2=time_to_hours(row.get(end_col)) if end_col else None
    if t1 is None: t1=0.0
    if t2 is None or t2<=t1: t2=t1+2.0
    return t1,t2

def row_frequency_interval(row,center_col,bw_col):
    c=to_float(row.get(center_col)); bw=to_float(row.get(bw_col))
    if c is None or bw is None or bw<=0: return None,None,None,None
    return c,bw,c-bw/2,c+bw/2

# Supabase

def supabase_configured(): return bool(st.secrets.get('SUPABASE_URL','')) and bool(st.secrets.get('SUPABASE_ANON_KEY','')) and create_client is not None
@st.cache_resource(show_spinner=False)
def get_supabase_client():
    return create_client(st.secrets['SUPABASE_URL'],st.secrets['SUPABASE_ANON_KEY']) if supabase_configured() else None

def workbook_to_jsonable(sheets):
    payload = {}
    for name, df in sheets.items():
        clean = recalc_start_end_fast(df).copy()

        # Critical fix: cast to object BEFORE replacing missing values.
        # Otherwise float columns convert None back to NaN.
        clean = clean.astype(object)
        records = []
        for rec in clean.to_dict(orient='records'):
            records.append(json_strict_sanitize(rec))

        payload[str(name)] = {
            'columns': [str(c) for c in clean.columns],
            'records': records,
        }

    return json_strict_sanitize(payload)

def workbook_from_jsonable(payload):
    sheets={}
    for name,obj in payload.items():
        df=pd.DataFrame(obj.get('records',[])); cols=obj.get('columns')
        if cols:
            for c in cols:
                if c not in df.columns: df[c]=None
            df=df[cols]
        sheets[name]=normalize_columns(df,True)
    return sheets

def save_project(project_id,project_name,updated_by):
    client=get_supabase_client()
    if client is None: return False,'Supabase is not configured.'
    if not st.session_state.get('sheets'): return False,'No workbook loaded.'

    row = {
        'project_id': project_id.strip(),
        'project_name': project_name.strip() or project_id.strip(),
        'workbook': workbook_to_jsonable(st.session_state['sheets']),
        'png_exports': json_strict_sanitize(st.session_state.get('saved_png_exports', {})),
        'updated_by': updated_by.strip() or 'unknown',
        'updated_at': datetime.utcnow().isoformat(),
    }
    row = json_strict_sanitize(row)

    try:
        # Last validation before Supabase. If this fails, it will be caught below.
        json.dumps(row, allow_nan=False)
        client.table('spectrum_projects').upsert(row,on_conflict='project_id').execute()
        return True,f"Saved project '{row['project_name']}'."
    except Exception as e:
        return False,f'Save failed: {e}'

def load_project(project_id):
    client=get_supabase_client()
    if client is None: return False,'Supabase is not configured.'
    try:
        r=client.table('spectrum_projects').select('*').eq('project_id',project_id.strip()).limit(1).execute(); rows=r.data or []
        if not rows: return False,'Project not found.'
        row=rows[0]
        st.session_state['sheets']=workbook_from_jsonable(row.get('workbook',{}))
        st.session_state['saved_png_exports']=row.get('png_exports',{}) or {}
        st.session_state['active_project_id']=row.get('project_id'); st.session_state['active_project_name']=row.get('project_name')
        st.session_state['loaded_upload_sig']=None; st.session_state['analysis_cache']={}; st.session_state['hidden_visual_labels']={}; st.session_state['visual_version']=st.session_state.get('visual_version',0)+1
        return True,f"Loaded project '{row.get('project_name') or row.get('project_id')}'."
    except Exception as e: return False,f'Load failed: {e}'

# Conflicts/planner

def detect_conflicts_fast(df,max_conflicts=2500,guard_mhz=0.0):
    working=active_only(df,False)
    center=find_col(working,['Center Frequency (MHz)','Center Frequency','CenterF','Frequency']); bw=find_col(working,['Bandwidth (MHz)','Bandwidth','BW'])
    stc=find_col(working,['Start Time','StartTime','Start']); enc=find_col(working,['End Time','EndTime','End'])
    eq=find_col(working,['Equipment']); unit=find_col(working,['Unit']); tech=find_col(working,['Tech']); sponsor=find_col(working,['Sponsor'])
    if center is None or bw is None or working.empty: return pd.DataFrame()
    nums=[]; rows=[]
    for pos,row in working.iterrows():
        c,b,f1,f2=row_frequency_interval(row,center,bw)
        if c is None: continue
        t1,t2=row_window(row,stc,enc); nums.append((pos,row,c,b,f1-guard_mhz,f2+guard_mhz,t1,t2))
    nums.sort(key=lambda x:x[4])
    for ai in range(len(nums)):
        pa,ra,ac,ab,af1,af2,at1,at2=nums[ai]
        for bi in range(ai+1,len(nums)):
            pb,rb,bc,bb,bf1,bf2,bt1,bt2=nums[bi]
            if bf1>=af2: break
            if intervals_overlap(af1,af2,bf1,bf2) and intervals_overlap(at1,at2,bt1,bt2):
                rows.append({'Row A':pa+1,'Row B':pb+1,'Equipment A':ra.get(eq,'') if eq else '', 'Equipment B':rb.get(eq,'') if eq else '', 'Unit A':ra.get(unit,'') if unit else '', 'Unit B':rb.get(unit,'') if unit else '', 'Tech A':ra.get(tech,'') if tech else '', 'Tech B':rb.get(tech,'') if tech else '', 'Sponsor A':ra.get(sponsor,'') if sponsor else '', 'Sponsor B':rb.get(sponsor,'') if sponsor else '', 'Center A':ac,'Center B':bc,'Bandwidth A':ab,'Bandwidth B':bb,'Time A':f'{format_time_hhmm(at1)}-{format_time_hhmm(at2)}','Time B':f'{format_time_hhmm(bt1)}-{format_time_hhmm(bt2)}','Reason':'Frequency and time overlap'})
                if len(rows)>=max_conflicts: return pd.DataFrame(rows)
    return pd.DataFrame(rows)

def time_slot_is_open(df,idx,ns,ne,center,bw,stc,enc,guard=0.0):
    _,_,mf1,mf2=row_frequency_interval(df.loc[idx],center,bw)
    if mf1 is None: return False
    for j,other in df.iterrows():
        if j==idx or not to_bool(other.get('Active'),True): continue
        _,_,of1,of2=row_frequency_interval(other,center,bw)
        if of1 is None: continue
        ot1,ot2=row_window(other,stc,enc)
        if intervals_overlap(mf1-guard,mf2+guard,of1,of2) and intervals_overlap(ns,ne,ot1,ot2): return False
    return True

def build_candidate_time_slots(day_start,day_end,window_hours,step_minutes,old_start=None):
    slots=[]; step=max(float(step_minutes)/60,1/60); x=float(day_start); last=float(day_end)-float(window_hours)
    while x<=last+1e-9:
        slots.append((round(x,6),round(x+window_hours,6))); x+=step
    return sorted(slots,key=lambda s:(abs(s[0]-old_start),s[0])) if old_start is not None else slots

def smart_time_deconflict(df,day_start=6,day_end=20,step_minutes=30,guard_mhz=0,max_passes=5):
    out=recalc_start_end_fast(df).copy(); center=find_col(out,['Center Frequency (MHz)','Center Frequency','CenterF','Frequency']); bw=find_col(out,['Bandwidth (MHz)','Bandwidth','BW']); stc=find_col(out,['Start Time','StartTime','Start']); enc=find_col(out,['End Time','EndTime','End'])
    if center is None or bw is None: return out,pd.DataFrame()
    moves=[]
    for _ in range(int(max_passes)):
        conf=detect_conflicts_fast(out,guard_mhz=guard_mhz)
        if conf.empty: break
        moved=False; candidates=[]
        for _,c in conf.iterrows():
            for lab in ['Row B','Row A']:
                idx=int(c[lab])-1
                if idx not in candidates: candidates.append(idx)
        for idx in candidates:
            if idx not in out.index: continue
            row=out.loc[idx]
            if not to_bool(row.get('Active'),True) or to_bool(row.get('Locked'),False): continue
            old_s,old_e=row_window(row,stc,enc); window=max(old_e-old_s,.25)
            for ns,ne in build_candidate_time_slots(day_start,day_end,window,step_minutes,old_s):
                if abs(ns-old_s)<1e-9 and abs(ne-old_e)<1e-9: continue
                if time_slot_is_open(out,idx,ns,ne,center,bw,stc,enc,guard_mhz):
                    out.at[idx,stc]=format_time_hhmm(ns); out.at[idx,enc]=format_time_hhmm(ne)
                    moves.append({'Row':idx+1,'Move Type':'Time','Old Start':format_time_hhmm(old_s),'Old End':format_time_hhmm(old_e),'New Start':format_time_hhmm(ns),'New End':format_time_hhmm(ne)})
                    moved=True; break
        if not moved: break
    return recalc_start_end_fast(out),pd.DataFrame(moves)

def frequency_is_open(candidate_center,candidate_bw,idx,df,center,bw,stc,enc,guard):
    cs=candidate_center-candidate_bw/2-guard; ce=candidate_center+candidate_bw/2+guard; mt1,mt2=row_window(df.loc[idx],stc,enc)
    for j,other in df.iterrows():
        if j==idx or not to_bool(other.get('Active'),True): continue
        _,_,os,oe=row_frequency_interval(other,center,bw)
        if os is None: continue
        ot1,ot2=row_window(other,stc,enc)
        if intervals_overlap(mt1,mt2,ot1,ot2) and intervals_overlap(cs,ce,os,oe): return False
    return True

def smart_frequency_deconflict(df,low_mhz=2200,high_mhz=2300,step_mhz=1,guard_mhz=0,max_passes=5):
    out=recalc_start_end_fast(df).copy(); center=find_col(out,['Center Frequency (MHz)','Center Frequency','CenterF','Frequency']); bw=find_col(out,['Bandwidth (MHz)','Bandwidth','BW']); stc=find_col(out,['Start Time','StartTime','Start']); enc=find_col(out,['End Time','EndTime','End'])
    if center is None or bw is None: return out,pd.DataFrame()
    moves=[]
    for _ in range(int(max_passes)):
        conf=detect_conflicts_fast(out,guard_mhz=guard_mhz)
        if conf.empty: break
        moved=False; candidates=[]
        for _,c in conf.iterrows():
            for lab in ['Row B','Row A']:
                idx=int(c[lab])-1
                if idx not in candidates: candidates.append(idx)
        for idx in candidates:
            row=out.loc[idx]
            if not to_bool(row.get('Active'),True) or to_bool(row.get('Locked'),False): continue
            old=to_float(row.get(center)); b=to_float(row.get(bw),1)
            if old is None or b<=0: continue
            x=low_mhz+b/2; centers=[]
            while x<=high_mhz-b/2+1e-9: centers.append(round(x,6)); x+=step_mhz
            centers=sorted(centers,key=lambda c:(abs(c-old),c))
            for cand in centers:
                if abs(cand-old)<1e-9: continue
                if frequency_is_open(cand,b,idx,out,center,bw,stc,enc,guard_mhz):
                    out.at[idx,center]=cand; moves.append({'Row':idx+1,'Move Type':'Frequency','Old Center':old,'New Center':cand}); out=recalc_start_end_fast(out); moved=True; break
        if not moved: break
    return recalc_start_end_fast(out),pd.DataFrame(moves)

def store_analysis(sheet,df): st.session_state.setdefault('analysis_cache',{})[sheet]=df
def get_stored_analysis(sheet): return st.session_state.get('analysis_cache',{}).get(sheet,pd.DataFrame())
def clear_stored_analysis(sheet): st.session_state.setdefault('analysis_cache',{}).pop(sheet,None)
def update_active_sheet_in_session(sheet,df):
    saved=recalc_start_end_fast(df).copy(); st.session_state['sheets'][sheet]=saved; st.session_state['visual_version']=st.session_state.get('visual_version',0)+1; return saved

def apply_planner_results_to_active_sheet(sheet):
    pending=st.session_state.get('pending_planner_df')
    if pending is None or len(pending)==0: return False,'No planner results are waiting to apply.'
    applied=recalc_start_end_fast(pending).copy(); st.session_state['sheets'][sheet]=applied; store_analysis(sheet,detect_conflicts_fast(applied,guard_mhz=st.session_state.get('guard_mhz',0.0))); st.session_state['planner_applied_at']=datetime.now().strftime('%Y-%m-%d %H:%M:%S'); st.session_state['visual_version']=st.session_state.get('visual_version',0)+1
    for k in ['pending_planner_df','pending_planner_moves','pending_planner_summary']: st.session_state.pop(k,None)
    return True,'Planner results applied.'

def dataframe_to_xlsx(sheets):
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine='openpyxl') as writer:
        for name,df in sheets.items(): recalc_start_end_fast(df).to_excel(writer,sheet_name=str(name)[:31] or 'Sheet',index=False)
    out.seek(0); return out.read()

def load_file(uploaded_file):
    name=getattr(uploaded_file,'name','').lower()
    if name.endswith('.csv'): return {'Imported':normalize_columns(pd.read_csv(uploaded_file),True)}
    excel=pd.ExcelFile(uploaded_file); sheets={}
    for sheet in excel.sheet_names:
        if str(sheet).strip().lower()=='dashboard': continue
        sheets[sheet]=normalize_columns(pd.read_excel(excel,sheet_name=sheet),True)
    return sheets

# visuals

def get_hidden_label_frequencies(sheet): return set(st.session_state.setdefault('hidden_visual_labels',{}).get(sheet,[]))
def set_hidden_label_frequencies(sheet,values): st.session_state.setdefault('hidden_visual_labels',{})[sheet]=sorted(set([v for v in values if v]),key=lambda x:to_float(x,0)); st.session_state['visual_version']=st.session_state.get('visual_version',0)+1

def visual_frequency_options(df):
    w=active_only(df,st.session_state.get('show_inactive_rows',False)); center=find_col(w,['Center Frequency (MHz)','Center Frequency','CenterF','Frequency'])
    labels=[]
    if center is None: return labels
    for v in w[center].tolist():
        lab=frequency_display_value(v)
        if lab and lab not in labels: labels.append(lab)
    return sorted(labels,key=lambda x:to_float(x,0))

def build_color_map(df,color_by):
    if color_by is None or color_by not in df.columns: return {}
    labels=[]
    for v in df[color_by].fillna('(blank)').astype(str).tolist():
        lab=label_value(v)
        if lab not in labels: labels.append(lab)
    return {lab:stable_color(lab) for lab in labels}

def pick_color_field(df,preferred='Equipment'):
    for c in [preferred,'Equipment','Tech','Unit','Sponsor','Tech Category','Location']:
        if c in df.columns: return c
    return df.columns[0] if len(df.columns) else None

def add_legend(ax,color_by,color_map,dark=True):
    if not color_map: return
    handles=[plt.Line2D([0],[0],marker='s',linestyle='',markerfacecolor=color,markeredgecolor=color,markersize=9,label=label) for label,color in color_map.items()]
    legend=ax.legend(handles=handles,title=color_by,loc='center left',bbox_to_anchor=(1.01,.5),frameon=True)
    legend.get_frame().set_facecolor('#111827' if dark else 'white'); legend.get_frame().set_edgecolor('#CBD5E1')
    plt.setp(legend.get_texts(),color='white' if dark else 'black',fontsize=8); plt.setp(legend.get_title(),color='white' if dark else 'black',fontsize=9,fontweight='bold')

def sorted_for_draw_order(df,power_col,draw_order):
    if power_col is None or df.empty: return df
    t=df.copy(); t['_draw_power']=t[power_col].apply(lambda x:to_float(x,0))
    if draw_order=='High power in back': return t.sort_values('_draw_power',ascending=False).drop(columns=['_draw_power'])
    if draw_order=='Low power in back': return t.sort_values('_draw_power',ascending=True).drop(columns=['_draw_power'])
    return df

def row_alpha(row,power_col,max_power,high_alpha,low_alpha):
    if power_col is None: return .8
    ratio=max(0,min(to_float(row.get(power_col),0)/max_power,1)) if max_power else 0
    return low_alpha+ratio*(high_alpha-low_alpha)

def estimate_freq_gap(plot_df,center_col):
    vals=sorted([to_float(v) for v in plot_df[center_col].tolist() if to_float(v) is not None])
    if len(vals)<2: return 999
    gaps=[vals[i+1]-vals[i] for i in range(len(vals)-1) if vals[i+1]-vals[i]>0]
    return min(gaps) if gaps else 999

def choose_label_rotation(mode,bw,idx,gap):
    if mode=='Horizontal': return 0
    if mode=='Vertical': return 90
    if mode=='Staggered': return 90 if idx%2 else 0
    return 90 if bw<8 or gap<7 else 0

def time_frequency_chart(df,color_by='Equipment',dark=True,title=None,sheet_name=None,label_preview=False,draw_order='High power in back',high_power_alpha=.95,low_power_alpha=.95,label_mode='Auto'):
    plot_df=active_only(df,st.session_state.get('show_inactive_rows',False)); hidden=set() if label_preview or not sheet_name else get_hidden_label_frequencies(sheet_name)
    color_by=color_by if color_by in plot_df.columns else pick_color_field(plot_df,color_by); cmap=build_color_map(plot_df,color_by)
    center=find_col(plot_df,['Center Frequency (MHz)','Center Frequency','CenterF','Frequency']); bwc=find_col(plot_df,['Bandwidth (MHz)','Bandwidth','BW']); stc=find_col(plot_df,['Start Time','StartTime','Start']); enc=find_col(plot_df,['End Time','EndTime','End']); powerc=find_col(plot_df,['Power (W)','PowerW','Power'])
    fig,ax=plt.subplots(figsize=(16,7)); fig.patch.set_facecolor('#111827' if dark else 'white'); ax.set_facecolor('#111827' if dark else 'white')
    rows=0; times=[]; max_power=max([to_float(v,0) for v in plot_df[powerc].tolist()]+[1]) if powerc and len(plot_df) else 1
    gap=estimate_freq_gap(plot_df,center) if center else 999; plot_df=sorted_for_draw_order(plot_df,powerc,draw_order)
    for i,(_,row) in enumerate(plot_df.iterrows()):
        c=to_float(row.get(center)) if center else None; bw=to_float(row.get(bwc),1) if bwc else 1
        if c is None: continue
        bw=1 if bw is None or bw<=0 else bw; t1,t2=row_window(row,stc,enc)
        if t2<=t1: continue
        times += [t1,t2]; lab=label_value(row.get(color_by,'(blank)')) if color_by else '(blank)'; color=cmap.get(lab,stable_color(lab)); alpha=row_alpha(row,powerc,max_power,high_power_alpha,low_power_alpha)
        ax.add_patch(Rectangle((c-bw/2,t1),bw,t2-t1,facecolor=color,edgecolor='#0F172A',linewidth=.9,alpha=alpha))
        fl=frequency_display_value(c)
        if fl not in hidden and len(plot_df)<=180:
            rot=choose_label_rotation(label_mode,bw,i,gap)
            ax.text(c,t1+(t2-t1)/2,f'{c:.3f} MHz',rotation=rot,ha='center',va='center',fontsize=7,fontweight='bold',color='white',bbox=dict(boxstyle='round,pad=0.12',facecolor='#111827',edgecolor='none',alpha=.55),clip_on=True)
        rows+=1
    ax.autoscale()
    if times:
        ymin=min(times); ymax=max(times); pad=max(.25,(ymax-ymin)*.08); ax.set_ylim(max(0,ymin-pad),min(24,ymax+pad))
    ax.set_title(title or f'Time × Frequency — by {color_by}',color='white' if dark else 'black',fontsize=15,fontweight='bold'); ax.set_xlabel('Frequency (MHz)',color='white' if dark else 'black'); ax.set_ylabel('Time (hours)',color='white' if dark else 'black'); ax.tick_params(colors='white' if dark else 'black'); ax.grid(True,alpha=.18); add_legend(ax,color_by,cmap,dark); fig.tight_layout()
    return fig,plot_df,rows

def power_chart(df,color_by='Equipment',dark=True,sheet_name=None,draw_order='High power in back',high_power_alpha=.25,low_power_alpha=.85,label_mode='Auto'):
    plot_df=active_only(df,st.session_state.get('show_inactive_rows',False)); hidden=set() if not sheet_name else get_hidden_label_frequencies(sheet_name)
    color_by=color_by if color_by in plot_df.columns else pick_color_field(plot_df,color_by); cmap=build_color_map(plot_df,color_by)
    center=find_col(plot_df,['Center Frequency (MHz)','Center Frequency','CenterF','Frequency']); bwc=find_col(plot_df,['Bandwidth (MHz)','Bandwidth','BW']); powerc=find_col(plot_df,['Power (W)','PowerW','Power'])
    fig,ax=plt.subplots(figsize=(16,7)); fig.patch.set_facecolor('#111827' if dark else 'white'); ax.set_facecolor('#111827' if dark else 'white')
    max_power=max([to_float(v,0) for v in plot_df[powerc].tolist()]+[1]) if powerc and len(plot_df) else 1; gap=estimate_freq_gap(plot_df,center) if center else 999; plot_df=sorted_for_draw_order(plot_df,powerc,draw_order)
    for i,(_,row) in enumerate(plot_df.iterrows()):
        c=to_float(row.get(center)) if center else None; bw=to_float(row.get(bwc),1) if bwc else 1; p=to_float(row.get(powerc),1) if powerc else 1
        if c is None: continue
        bw=1 if bw is None or bw<=0 else bw; p=1 if p is None or p<=0 else p; lab=label_value(row.get(color_by,'(blank)')) if color_by else '(blank)'; alpha=row_alpha(row,powerc,max_power,high_power_alpha,low_power_alpha)
        ax.add_patch(Rectangle((c-bw/2,0),bw,p,facecolor=cmap.get(lab,stable_color(lab)),edgecolor='#0F172A',linewidth=.9,alpha=alpha))
        fl=frequency_display_value(c)
        if fl not in hidden and len(plot_df)<=180:
            ax.text(c,p/2,f'{c:.3f} MHz',rotation=choose_label_rotation(label_mode,bw,i,gap),ha='center',va='center',fontsize=7,fontweight='bold',color='white',bbox=dict(boxstyle='round,pad=0.12',facecolor='#111827',edgecolor='none',alpha=.55),clip_on=True)
    ax.autoscale(); ax.set_title(f'Frequency Allocation vs Power — by {color_by}',color='white' if dark else 'black',fontsize=15,fontweight='bold'); ax.set_xlabel('Frequency (MHz)',color='white' if dark else 'black'); ax.set_ylabel('Power (W)',color='white' if dark else 'black'); ax.tick_params(colors='white' if dark else 'black'); ax.grid(True,alpha=.18); add_legend(ax,color_by,cmap,dark); fig.tight_layout(); return fig,plot_df

def fig_to_png_bytes(fig):
    buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=200,bbox_inches='tight'); buf.seek(0); return buf.read()

def time_debug_table(df):
    w=active_only(df,st.session_state.get('show_inactive_rows',False)); stc=find_col(w,['Start Time','StartTime','Start']); enc=find_col(w,['End Time','EndTime','End']); center=find_col(w,['Center Frequency (MHz)','Center Frequency','CenterF','Frequency']); eq=find_col(w,['Equipment']); unit=find_col(w,['Unit']); rows=[]
    for idx,row in w.iterrows():
        t1,t2=row_window(row,stc,enc); rows.append({'Row':idx+1,'Equipment':row.get(eq,'') if eq else '', 'Unit':row.get(unit,'') if unit else '', 'Center MHz':to_float(row.get(center)) if center else None, 'Raw Start':row.get(stc,'') if stc else '', 'Raw End':row.get(enc,'') if enc else '', 'Plotted Start Hour':t1,'Plotted End Hour':t2})
    return pd.DataFrame(rows)

# UI
st.title('Spectrum Planner — V28')
st.caption('Fixes Supabase project save by removing NaN/Inf values before JSON upload.')
with st.sidebar:
    st.header('Workbook'); uploaded=st.file_uploader('Upload allocation workbook or CSV',type=['xlsx','csv']); dark=st.checkbox('Dark visuals',value=False); st.checkbox('Show inactive rows in visuals',value=False,key='show_inactive_rows')
    st.divider(); st.header('Collaborative Projects'); st.caption('Supabase configured.' if supabase_configured() else 'Supabase not configured. Local mode is active.')
    project_id_input=st.text_input('Project ID',value=st.session_state.get('active_project_id','pcc6-working-project')); project_name_input=st.text_input('Project name',value=st.session_state.get('active_project_name','PCC6 Working Project')); updated_by_input=st.text_input('Your name/email',value='')
    pc1,pc2=st.columns(2)
    with pc1:
        if st.button('Load Project',use_container_width=True):
            ok,msg=load_project(project_id_input); (st.success if ok else st.error)(msg); 
            if ok: st.rerun()
    with pc2:
        if st.button('Save Project',type='primary',use_container_width=True):
            ok,msg=save_project(project_id_input,project_name_input,updated_by_input); (st.success if ok else st.error)(msg)
    st.divider(); st.header('Planner Mode'); planner_mode=st.radio('Planner mode',['Auto deconflict by time','Auto deconflict by frequency','Run full smart deconfliction'],index=0)
    st.subheader('Time settings'); day_start=st.number_input('Operating day start hour',value=6.0,min_value=0.0,max_value=24.0,step=.25); day_end=st.number_input('Operating day end hour',value=20.0,min_value=0.0,max_value=24.0,step=.25); time_step=st.number_input('Time step minutes',value=30,min_value=1,max_value=240,step=5)
    st.subheader('Frequency settings'); low=st.number_input('Search low MHz',value=2200.0,step=1.0); high=st.number_input('Search high MHz',value=2300.0,step=1.0); freq_step=st.number_input('Frequency step MHz',value=1.0,min_value=.001,step=.5); guard=st.number_input('Guard MHz',value=0.0,min_value=0.0,step=.1,key='guard_mhz'); max_passes=st.number_input('Max passes',value=5,min_value=1,max_value=20,step=1)
if 'sheets' not in st.session_state: st.session_state['sheets']={}
if uploaded is not None:
    data=uploaded.getvalue(); sig=hashlib.md5(data).hexdigest()
    if st.session_state.get('loaded_upload_sig')!=sig:
        buf=io.BytesIO(data); buf.name=uploaded.name; st.session_state['sheets']=load_file(buf); st.session_state['loaded_upload_sig']=sig; st.session_state['analysis_cache']={}; st.session_state['hidden_visual_labels']={}; st.session_state['visual_version']=st.session_state.get('visual_version',0)+1; st.success(f"Loaded {len(st.session_state['sheets'])} workbook tab(s). Dashboard sheets are intentionally skipped.")
if not st.session_state['sheets']:
    st.info('Upload a workbook or load a collaborative project to begin.'); st.stop()
sheet_names=list(st.session_state['sheets'].keys()); active_sheet=st.selectbox('Active sheet for plots/deconfliction',sheet_names); st.session_state['active_sheet']=active_sheet
current_df=recalc_start_end_fast(st.session_state['sheets'][active_sheet].copy())
st.subheader('Shared allocation workbook'); st.caption('Use Active to turn rows on/off. Use Locked to prevent Smart Planner from moving that row.')
edited_df=st.data_editor(current_df,use_container_width=True,hide_index=True,num_rows='dynamic',key=f"editor_{active_sheet}_{st.session_state.get('planner_applied_at','base')}_{st.session_state.get('visual_version',0)}")
edited_df=normalize_columns(edited_df,True)
c1,c2,c3=st.columns(3)
with c1:
    if st.button('💾 Save edits',type='primary',use_container_width=True): update_active_sheet_in_session(active_sheet,edited_df); clear_stored_analysis(active_sheet); st.success('Edits saved to session.')
with c2: st.download_button('Download workbook XLSX',data=dataframe_to_xlsx(st.session_state['sheets']),file_name=f"spectrum_planner_workbook_{timestamp_string()}.xlsx",mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
with c3:
    if st.button('Recalculate Start/End Frequency',use_container_width=True): update_active_sheet_in_session(active_sheet,recalc_start_end_fast(edited_df)); clear_stored_analysis(active_sheet); st.success('Start/End Frequency recalculated.'); st.rerun()
st.subheader('Performance Workflow'); w1,w2,w3,w4=st.columns(4)
with w1:
    if st.button('1. Save edits',type='primary',use_container_width=True): update_active_sheet_in_session(active_sheet,edited_df); clear_stored_analysis(active_sheet); st.success('Edits saved.')
with w2:
    if st.button('2. Recalculate frequencies',use_container_width=True): update_active_sheet_in_session(active_sheet,recalc_start_end_fast(edited_df)); clear_stored_analysis(active_sheet); st.success('Frequencies recalculated.'); st.rerun()
with w3:
    if st.button('3. Analyze conflicts',use_container_width=True):
        res=detect_conflicts_fast(st.session_state['sheets'][active_sheet],guard_mhz=guard); store_analysis(active_sheet,res); st.success(f'Conflict analysis complete: {len(res)} conflicts.')
with w4:
    if st.button('4. Generate visuals',use_container_width=True): st.session_state['visual_version']=st.session_state.get('visual_version',0)+1; st.success('Visuals updated.'); st.rerun()
metric_df=active_only(st.session_state['sheets'][active_sheet],False); conf=get_stored_analysis(active_sheet)
if conf.empty: conf=detect_conflicts_fast(metric_df,guard_mhz=guard); store_analysis(active_sheet,conf)
m1,m2,m3=st.columns(3); m1.metric('Active rows in visuals',len(metric_df)); m2.metric('Inactive rows hidden',len(st.session_state['sheets'][active_sheet])-len(metric_df)); m3.metric('Equipment conflicts',len(conf))
if st.sidebar.button('Run Smart Planner',type='primary',use_container_width=True):
    planner_input=recalc_start_end_fast(st.session_state['sheets'][active_sheet])
    if len(planner_input)>MAX_PLANNER_ROWS: st.error(f'Planner stopped to prevent freezing: {len(planner_input)} rows loaded.'); st.stop()
    start_conf=len(detect_conflicts_fast(planner_input,guard_mhz=guard))
    if planner_mode=='Auto deconflict by time': new_df,moves=smart_time_deconflict(planner_input,day_start,day_end,int(time_step),guard,int(max_passes))
    elif planner_mode=='Auto deconflict by frequency': new_df,moves=smart_frequency_deconflict(planner_input,low,high,freq_step,guard,int(max_passes))
    else:
        tdf,tm=smart_time_deconflict(planner_input,day_start,day_end,int(time_step),guard,int(max_passes)); new_df,fm=smart_frequency_deconflict(tdf,low,high,freq_step,guard,int(max_passes)); moves=pd.concat([tm,fm],ignore_index=True)
    final_conf=len(detect_conflicts_fast(new_df,guard_mhz=guard)); st.session_state['pending_planner_df']=new_df.copy(); st.session_state['pending_planner_moves']=moves.copy(); st.session_state['pending_planner_summary']=pd.DataFrame([{'Planner Mode':planner_mode,'Starting Conflicts':start_conf,'Final Conflicts':final_conf,'Move Rows':len(moves)}]); st.success('Planner complete. Review results below, preview the visual, then click Apply Planner Results.')
if 'pending_planner_summary' in st.session_state:
    st.subheader('Smart Planner Results'); st.dataframe(st.session_state['pending_planner_summary'],use_container_width=True,hide_index=True); moves=st.session_state.get('pending_planner_moves',pd.DataFrame())
    if moves is not None and not moves.empty: st.markdown('**Proposed Moves**'); st.dataframe(moves,use_container_width=True,hide_index=True)
    with st.expander('Preview Planner Visual Before Apply',expanded=True):
        pfig,_,pr=time_frequency_chart(st.session_state.get('pending_planner_df'),color_by='Equipment',dark=dark,sheet_name=None,title='Preview: Smart Planner Result',label_preview=True,label_mode='Auto'); st.pyplot(pfig,use_container_width=True); st.caption(f'Previewing {pr} planned row(s).')
    a1,a2=st.columns(2)
    with a1:
        if st.button('✅ Apply Planner Results',type='primary',use_container_width=True):
            ok,msg=apply_planner_results_to_active_sheet(active_sheet); (st.success if ok else st.error)(msg); 
            if ok: st.rerun()
    with a2:
        if st.button('Discard Planner Results',use_container_width=True):
            for k in ['pending_planner_df','pending_planner_moves','pending_planner_summary']: st.session_state.pop(k,None)
            st.info('Planner results discarded.'); st.rerun()
visual_df=recalc_start_end_fast(st.session_state['sheets'][active_sheet].copy())
st.divider(); st.subheader('Frequency Label Controls'); st.caption('Hide/show only the MHz label inside each box. Colored bars stay visible.')
opts=visual_frequency_options(visual_df); hidden=get_hidden_label_frequencies(active_sheet); visible=[f for f in opts if f not in hidden]; hidden_opts=[f for f in opts if f in hidden]
fc1,fc2=st.columns(2)
with fc1:
    st.markdown('**Frequency labels currently showing inside boxes**'); selected=[]
    with st.container(border=True):
        for lab in visible:
            if st.checkbox(lab,value=False,key=f"hide_{active_sheet}_{lab}_{st.session_state.get('visual_version',0)}"): selected.append(lab)
    if st.button('➖ Hide selected MHz labels inside boxes',use_container_width=True): set_hidden_label_frequencies(active_sheet,list(hidden.union(selected))); st.success(f'Hid {len(selected)} selected MHz label(s).'); st.rerun()
with fc2:
    st.markdown('**Frequency labels currently hidden inside boxes**'); selected_show=[]
    with st.container(border=True):
        for lab in hidden_opts:
            if st.checkbox(lab,value=False,key=f"show_{active_sheet}_{lab}_{st.session_state.get('visual_version',0)}"): selected_show.append(lab)
    s1,s2=st.columns(2)
    with s1:
        if st.button('➕ Show selected labels',use_container_width=True): set_hidden_label_frequencies(active_sheet,list(hidden.difference(selected_show))); st.success(f'Showed {len(selected_show)} selected MHz label(s).'); st.rerun()
    with s2:
        if st.button('♻️ Show all labels',use_container_width=True): set_hidden_label_frequencies(active_sheet,[]); st.success('All MHz labels are visible again.'); st.rerun()
st.info('No MHz labels are currently hidden on this sheet.' if not hidden else f"Hidden MHz labels on this sheet: {', '.join(sorted(hidden,key=lambda x:to_float(x,0)))}")
st.divider()
with st.expander('Extract / Export Visuals',expanded=True):
    st.subheader('Draw order, transparency, and label orientation'); ec1,ec2,ec3,ec4=st.columns(4)
    with ec1: draw_order=st.selectbox('Draw order',['High power in back','Low power in back','Workbook row order'],index=0)
    with ec2: high_alpha=st.slider('High-power background transparency',0.05,1.0,0.25,0.05)
    with ec3: low_alpha=st.slider('Low-power foreground transparency',0.05,1.0,0.85,0.05)
    with ec4: label_mode=st.selectbox('MHz label orientation',['Auto','Horizontal','Vertical','Staggered'],index=0)
    tab1,tab2,tab3,tab4,tab5,tab6,tab7=st.tabs(['Time × Frequency','Power View','Equipment Deconfliction','Unit Deconfliction','Sponsor Deconfliction','Conflict Tables','Time Debug'])
    with tab1:
        color_by=st.selectbox('Color boxes by',['Equipment','Tech','Unit','Sponsor','Tech Category'],index=0); fig,_,rows=time_frequency_chart(visual_df,color_by=color_by,dark=dark,sheet_name=active_sheet,draw_order=draw_order,high_power_alpha=high_alpha,low_power_alpha=low_alpha,label_mode=label_mode); st.pyplot(fig,use_container_width=True); png=fig_to_png_bytes(fig); st.download_button('Download this visual PNG',data=png,file_name=f'time_frequency_{timestamp_string()}.png',mime='image/png',use_container_width=True)
        if st.button('Save this PNG to project',use_container_width=True): st.session_state.setdefault('saved_png_exports',{})[f'time_frequency_{active_sheet}.png']=base64.b64encode(png).decode('utf-8'); st.success('PNG saved in project memory. Click Save Project to persist it.')
    with tab2:
        pfig,_=power_chart(visual_df,dark=dark,sheet_name=active_sheet,draw_order=draw_order,high_power_alpha=high_alpha,low_power_alpha=low_alpha,label_mode=label_mode); st.pyplot(pfig,use_container_width=True); st.download_button('Download this visual PNG',data=fig_to_png_bytes(pfig),file_name=f'power_view_{timestamp_string()}.png',mime='image/png',use_container_width=True)
    with tab3:
        fig,_,_=time_frequency_chart(visual_df,color_by='Equipment',dark=dark,title='Equipment Deconfliction',sheet_name=active_sheet,draw_order=draw_order,high_power_alpha=high_alpha,low_power_alpha=low_alpha,label_mode=label_mode); st.pyplot(fig,use_container_width=True); st.download_button('Download this visual PNG',data=fig_to_png_bytes(fig),file_name=f'equipment_deconfliction_{timestamp_string()}.png',mime='image/png',use_container_width=True)
    with tab4:
        fig,_,_=time_frequency_chart(visual_df,color_by='Unit',dark=dark,title='Unit Deconfliction',sheet_name=active_sheet,draw_order=draw_order,high_power_alpha=high_alpha,low_power_alpha=low_alpha,label_mode=label_mode); st.pyplot(fig,use_container_width=True); st.download_button('Download this visual PNG',data=fig_to_png_bytes(fig),file_name=f'unit_deconfliction_{timestamp_string()}.png',mime='image/png',use_container_width=True)
    with tab5:
        fig,_,_=time_frequency_chart(visual_df,color_by='Sponsor',dark=dark,title='Sponsor Deconfliction',sheet_name=active_sheet,draw_order=draw_order,high_power_alpha=high_alpha,low_power_alpha=low_alpha,label_mode=label_mode); st.pyplot(fig,use_container_width=True); st.download_button('Download this visual PNG',data=fig_to_png_bytes(fig),file_name=f'sponsor_deconfliction_{timestamp_string()}.png',mime='image/png',use_container_width=True)
    with tab6:
        latest=detect_conflicts_fast(visual_df,guard_mhz=guard); store_analysis(active_sheet,latest); st.warning(f'{len(latest)} active conflicts detected.'); st.dataframe(latest,use_container_width=True,hide_index=True); st.download_button('Download conflicts CSV',data=latest.to_csv(index=False).encode(),file_name=f'conflicts_{timestamp_string()}.csv',mime='text/csv',use_container_width=True)
    with tab7:
        dbg=time_debug_table(visual_df); st.dataframe(dbg,use_container_width=True,hide_index=True); st.download_button('Download time debug CSV',data=dbg.to_csv(index=False).encode(),file_name=f'time_debug_{timestamp_string()}.csv',mime='text/csv',use_container_width=True)
    if st.session_state.get('saved_png_exports'):
        st.subheader('Saved PNGs in project memory')
        for name,b64 in st.session_state['saved_png_exports'].items(): st.download_button(f'Download saved {name}',data=base64.b64decode(b64.encode()),file_name=name,mime='image/png',use_container_width=True)
st.caption('V27: Auto rotates crowded MHz labels vertical; Staggered alternates horizontal and vertical.')
