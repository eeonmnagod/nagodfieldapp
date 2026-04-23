# streamlit_app.py
import streamlit as st
import pandas as pd
import pytz
import base64
import requests
import time
import re
from datetime import datetime, date
import gspread
from google.oauth2.service_account import Credentials
from streamlit_js_eval import get_geolocation

# -------------------------
# Config
# -------------------------
st.set_page_config(page_title="Nagod Command Center", page_icon="⚡", layout="wide")

# Put sensitive values into st.secrets in production
GAS_URL = st.secrets.get("gas_url", "https://script.google.com/macros/s/AKfycbxrYfFv7rhhvG9RtkEGurrLUcRQAxpJkfDA0r7S32_tvHE_dcSkELzmKxQ_QDQXyfO_/exec")
MASTER_PASSWORD = st.secrets.get("master_password", "ngb.test")

# Google Sheets spreadsheet ID (from your link)
SPREADSHEET_ID = "1Hsq777fDZj-vxnyqGyDLqH8FYtP-XxiZwqclXaSqDu4"

# Timezone helper
IST = pytz.timezone("Asia/Kolkata")

# -------------------------
# Small helpers
# -------------------------
def now_ist():
    return datetime.now(IST)

def to_iso_str(dt):
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = IST.localize(dt)
    return dt.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S %z")

def normalize_columns(df):
    df = df.copy()
    df.columns = df.columns.str.strip().str.replace("\n", " ").str.replace("\r", " ")
    return df

def clean_mobile(m):
    if pd.isna(m):
        return ""
    s = re.sub(r"\D", "", str(m))
    return s[-10:] if len(s) >= 10 else s

def is_valid_ivrs(ivrs):
    return isinstance(ivrs, str) and ivrs.isdigit() and len(ivrs) == 10

def safe_post_gas(payload, url=GAS_URL, retries=3, timeout=10):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            return True, r.text
        except Exception as e:
            last_err = e
            time.sleep(0.5 * attempt)
    return False, str(last_err)

@st.cache_resource
def get_sheets_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    sa_info = st.secrets.get("gcp_service_account")
    if not sa_info:
        raise RuntimeError("Missing service account credentials in st.secrets['gcp_service_account']")
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)

def safe_append_row(sheet_name, row, retries=3):
    last_err = None
    try:
        client = get_sheets_client()
    except Exception as e:
        return False, f"Sheets auth failed: {e}"
    for attempt in range(1, retries + 1):
        try:
            ws = client.open(sheet_name).sheet1
            ws.append_row(row)
            return True, "OK"
        except Exception as e:
            last_err = e
            time.sleep(0.5 * attempt)
    return False, str(last_err)

# -------------------------
# Load DO data from Google Sheets (one DC per tab)
# -------------------------
@st.cache_data(ttl=300)
def load_do_from_gsheet(spreadsheet_id: str):
    dc_tabs = {}
    load_errors = []
    try:
        client = get_sheets_client()
        sh = client.open_by_key(spreadsheet_id)
        worksheets = sh.worksheets()
        for ws in worksheets:
            title = ws.title.strip()
            try:
                records = ws.get_all_records()
                if not records:
                    df = pd.DataFrame()
                else:
                    df = pd.DataFrame.from_records(records)
                    df = normalize_columns(df)
                    # Map common variants to canonical names if present
                    col_map = {}
                    for c in df.columns:
                        lc = c.lower().replace(" ", "").replace("_", "")
                        if lc in ("locationcode", "location_code", "location"):
                            col_map[c] = "Location Code"
                        if lc in ("consumerno", "consumer_no", "consumer"):
                            col_map[c] = "Consumer No"
                        if lc in ("consumername", "consumer_name"):
                            col_map[c] = "Consumer Name"
                        if lc in ("mobileno", "mobile", "mobile_no"):
                            col_map[c] = "Mobile No"
                        if lc in ("arrear", "arrears"):
                            col_map[c] = "Arrear"
                        if lc in ("address1", "address"):
                            col_map[c] = "Address1"
                        if lc in ("group",):
                            col_map[c] = "Group"
                        if lc in ("rd", "r_d"):
                            col_map[c] = "RD"
                    if col_map:
                        df = df.rename(columns=col_map)
                dc_tabs[title] = df
            except Exception as e_tab:
                load_errors.append((title, str(e_tab)))
                dc_tabs[title] = pd.DataFrame()
        loc_codes = ["Select"] + sorted(dc_tabs.keys())
        return dc_tabs, loc_codes, load_errors
    except Exception as e:
        return {}, ["Select"], [("spreadsheet", str(e))]

dc_tabs, loc_codes, load_errors = load_do_from_gsheet(SPREADSHEET_ID)

# -------------------------
# Load call history from Google Sheets (same as earlier)
# -------------------------
@st.cache_data(ttl=300)
def load_call_history():
    try:
        client = get_sheets_client()
        ws = client.open("Nagod_Calling_Data").sheet1
        records = ws.get_all_values()
        if len(records) <= 1:
            return pd.DataFrame(columns=["Timestamp", "Location Code", "Emp Name", "IVRS", "Status", "Notes", "FollowUpDate"])
        df = pd.DataFrame(records[1:], columns=records[0])
        df = normalize_columns(df)
        if "FollowUpDate" in df.columns:
            df["FollowUpDate_parsed"] = pd.to_datetime(df["FollowUpDate"], errors="coerce").dt.date
        else:
            df["FollowUpDate_parsed"] = pd.NaT
        return df
    except Exception as e:
        st.error(f"⚠️ Could not load call history: {e}")
        return pd.DataFrame(columns=["Timestamp", "Location Code", "Emp Name", "IVRS", "Status", "Notes", "FollowUpDate"])

df_calls = load_call_history()

# Compute PTP history and escalations
ptp_counts = {}
todays_followups = []
escalated_field_ivrs = []
if not df_calls.empty and "Status" in df_calls.columns:
    ptp_history = df_calls[(df_calls["Status"] == "Promise to Pay") & df_calls["IVRS"].notna()]
    if not ptp_history.empty:
        ptp_counts = ptp_history["IVRS"].value_counts().to_dict()
        escalated_field_ivrs = [ivrs for ivrs, cnt in ptp_counts.items() if cnt >= 2]
    if "FollowUpDate_parsed" in df_calls.columns:
        today_dt = date.today()
        todays_followups = ptp_history[ptp_history["FollowUpDate_parsed"].notna() & (ptp_history["FollowUpDate_parsed"] <= today_dt)]["IVRS"].dropna().unique().tolist()

# DC mapping from manager sheet if available (try to find a 'Mangers' tab)
dc_mapping = {}
if "Mangers" in dc_tabs and not dc_tabs["Mangers"].empty and "NAME OF DC" in dc_tabs["Mangers"].columns and "Location Code" in dc_tabs["Mangers"].columns:
    dc_mapping = dict(zip(dc_tabs["Mangers"]["Location Code"], dc_tabs["Mangers"]["NAME OF DC"]))
dc_mapping["1535000"] = "Division Office"

def format_dc_dropdown(code):
    if code == "Select":
        return "Select"
    return f"{code} - {dc_mapping.get(code, 'Unknown DC')}"

# -------------------------
# Session state defaults
# -------------------------
if "logged_in" not in st.session_state:
    st.session_state.update({
        "logged_in": False,
        "role": None,
        "location_code": None,
        "group": None,
        "rd": None,
        "emp_name": "",
        "form_key": 0,
        "login_step": 1,
        "last_activity_time": None,
        "called_ivrs": [],
        "lat": None,
        "lng": None,
    })

# -------------------------
# UI: Login (with DC dropdown from sheet tabs)
# -------------------------
if not st.session_state["logged_in"]:
    st.title("⚡ Nagod Division Command Center")
    st.markdown("### Select Your Operating Role")
    role = st.radio("Login As:", [
        "1. Field Staff (Line Worker)",
        "2. Calling Desk (Substation & Office)",
        "3. DC Incharge (Manager)",
        "4. Division Admin",
        "5. Vigilance (Theft Detection)",
    ])
    st.divider()

    # Show any load errors
    if load_errors:
        for tab, err in load_errors:
            if err:
                st.warning(f"Tab '{tab}': {err}")

    selected_dc_tab = st.selectbox("Select DC (sheet tab):", loc_codes)
    if selected_dc_tab != "Select":
        df_selected = dc_tabs.get(selected_dc_tab, pd.DataFrame())
    else:
        df_selected = pd.DataFrame()

    # Validate df_selected presence for flows that need it
    # --- Field Staff ---
    if role == "1. Field Staff (Line Worker)":
        if st.session_state["login_step"] == 1:
            st.subheader("Step 1: Activate Shift")
            # Use sheet tabs as DC choices; also allow Location Code if present in sheet
            loc_code = st.selectbox("Select Your DC *", loc_codes, format_func=lambda x: x if x == "Select" else x)
            emp_name = "Select Name"
            if loc_code != "Select":
                # If df_selected has staff list, use it
                df_for_staff = dc_tabs.get(loc_code, pd.DataFrame())
                if not df_for_staff.empty and "Name of Staff" in df_for_staff.columns:
                    staff_list = ["Select Name"] + df_for_staff["Name of Staff"].dropna().tolist()
                    emp_name = st.selectbox("Select Your Name *", staff_list)
                else:
                    st.warning("⚠️ Field staff list not found in this tab. Please enter your name.")
                    emp_name = st.text_input("Enter Your Name *")
            if st.button("⏱️ Activate Shift", type="primary"):
                if loc_code != "Select" and emp_name and emp_name != "Select Name":
                    st.session_state.update({
                        "location_code": loc_code,
                        "emp_name": emp_name,
                        "login_step": 2,
                        "last_activity_time": now_ist(),
                    })
                    st.experimental_rerun()
                else:
                    st.error("Please select both a DC and your Name.")

        elif st.session_state["login_step"] == 2:
            active_dc_name = st.session_state.get("location_code")
            st.success(f"🟢 Shift Activated: **{st.session_state['emp_name']}** | **{active_dc_name}**")
            loc = get_geolocation()
            if loc and "coords" in loc:
                st.session_state["lat"] = loc["coords"]["latitude"]
                st.session_state["lng"] = loc["coords"]["longitude"]
                st.success(f"📍 GPS Locked: {st.session_state['lat']:.4f}, {st.session_state['lng']:.4f}")
            else:
                st.info("🛰️ Acquiring GPS Satellite Lock... Please allow location permissions.")

            # Use the selected DC tab's data for group/RD selection
            df_dc = dc_tabs.get(st.session_state["location_code"], pd.DataFrame())
            if df_dc.empty:
                st.warning("This DC tab is empty. You can still proceed but consumer lookups will not work.")
                filtered_groups = ["Select"]
            else:
                filtered_groups = ["Select"] + sorted(df_dc["Group"].dropna().unique().tolist())
            selected_group = st.selectbox("Select Your Assigned Group *", filtered_groups)

            filtered_rds = ["Select"]
            if selected_group != "Select" and not df_dc.empty:
                filtered_rds += sorted(df_dc[df_dc["Group"] == selected_group]["RD"].dropna().unique().tolist())
            selected_rd = st.selectbox("Select Your Assigned RD *", filtered_rds)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("🚀 Enter Dashboard", type="primary") and selected_group != "Select" and selected_rd != "Select":
                    st.session_state.update({
                        "logged_in": True,
                        "role": role,
                        "group": selected_group,
                        "rd": selected_rd,
                        "last_activity_time": now_ist(),
                    })
                    st.experimental_rerun()
            with col2:
                if st.button("Cancel Shift"):
                    st.session_state["login_step"] = 1
                    st.experimental_rerun()

    # --- Vigilance ---
    elif role == "5. Vigilance (Theft Detection)":
        if st.session_state["login_step"] == 1:
            st.subheader("Step 1: Activate Vigilance Patrol")
            loc_code = st.selectbox("Select Operating DC *", loc_codes)
            emp_name = st.text_input("Enter Officer/Squad Name *")
            if st.button("⏱️ Activate Patrol", type="primary"):
                if loc_code != "Select" and emp_name:
                    st.session_state.update({"location_code": loc_code, "emp_name": emp_name, "login_step": 2, "last_activity_time": now_ist()})
                    st.experimental_rerun()
                else:
                    st.error("Please select a DC and enter your Name.")
        elif st.session_state["login_step"] == 2:
            active_dc_name = st.session_state.get("location_code")
            st.success(f"🚨 Vigilance Active: **{st.session_state['emp_name']}** | **{active_dc_name}**")
            loc = get_geolocation()
            if loc and "coords" in loc:
                st.session_state["lat"] = loc["coords"]["latitude"]
                st.session_state["lng"] = loc["coords"]["longitude"]
                st.success(f"📍 GPS Locked: {st.session_state['lat']:.4f}, {st.session_state['lng']:.4f}")
            else:
                st.info("🛰️ Acquiring Fast GPS Lock... Please allow location permissions.")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🚀 Enter Theft Dashboard", type="primary"):
                    st.session_state.update({"logged_in": True, "role": role, "last_activity_time": now_ist()})
                    st.experimental_rerun()
            with col2:
                if st.button("Cancel Patrol"):
                    st.session_state["login_step"] = 1
                    st.experimental_rerun()

    # --- Calling Desk ---
    elif role == "2. Calling Desk (Substation & Office)":
        desk_type = st.radio("Select Desk Type:", ["Office Staff", "Substation Operator"])
        loc_code = st.selectbox("Select DC *", loc_codes)
        if loc_code != "Select":
            df_for_desk = dc_tabs.get(loc_code, pd.DataFrame())
            if desk_type == "Office Staff":
                names = ["Select Name"] + (df_for_desk["NAME OF OFFICE STAFF"].dropna().tolist() if "NAME OF OFFICE STAFF" in df_for_desk.columns else [])
            else:
                names = ["Select Name"] + (df_for_desk["NAME OF SUB STSTION OPERATOR"].dropna().tolist() if "NAME OF SUB STSTION OPERATOR" in df_for_desk.columns else [])
            emp_name = st.selectbox("Select Your Name *", names)
            if emp_name != "Select Name" and st.button("Access Calling Dashboard", type="primary"):
                st.session_state.update({"logged_in": True, "role": role, "location_code": loc_code, "emp_name": emp_name})
                st.experimental_rerun()

    # --- DC Incharge ---
    elif role == "3. DC Incharge (Manager)":
        loc_code = st.selectbox("Select Assigned DC *", loc_codes)
        if loc_code != "Select":
            df_mgr_tab = dc_tabs.get(loc_code, pd.DataFrame())
            names = ["Select Name"] + (df_mgr_tab["Name of Managers"].dropna().tolist() if "Name of Managers" in df_mgr_tab.columns else [])
            emp_name = st.selectbox("Select Manager Name *", names)
            if emp_name != "Select Name":
                mgr_pass = st.text_input("Enter Password (DC Location Code) *", type="password")
                if st.button("Open DC Dashboard", type="primary"):
                    if mgr_pass == loc_code:
                        st.session_state.update({"logged_in": True, "role": role, "location_code": loc_code, "emp_name": emp_name})
                        st.experimental_rerun()
                    else:
                        st.error("❌ Incorrect Password.")

    # --- Division Admin ---
    elif role == "4. Division Admin":
        admin_pass = st.text_input("Master Password", type="password")
        if st.button("Unlock Division Analytics", type="primary"):
            if admin_pass == MASTER_PASSWORD:
                st.session_state.update({"logged_in": True, "role": role, "emp_name": "Division Admin"})
                st.experimental_rerun()
            else:
                st.error("❌ Incorrect Master Password.")

# -------------------------
# Operational dashboards (use selected DC tab data where needed)
# -------------------------
else:
    role = st.session_state["role"]
    active_dc_name = st.session_state.get("location_code")
    st.sidebar.success(f"🟢 Active Shift: {st.session_state['emp_name']}")
    if st.sidebar.button("Log Out"):
        st.session_state.clear()
        st.experimental_rerun()

    # Idle time check
    if st.session_state.get("last_activity_time"):
        idle_time_seconds = (now_ist() - st.session_state["last_activity_time"]).total_seconds()
        if int(idle_time_seconds / 60) >= 15:
            st.error(f"⚠️ INACTIVITY ALERT: You have been idle for {int(idle_time_seconds / 60)} minutes.")

    # Use the DC tab selected at login
    df_dc = dc_tabs.get(active_dc_name, pd.DataFrame())

    # -------------------------
    # Field Staff Dashboard
    # -------------------------
    if role == "1. Field Staff (Line Worker)":
        st.header(f"📍 {active_dc_name} | Group: {st.session_state.get('group')} | RD: {st.session_state.get('rd')}")
        my_consumers = df_dc[(df_dc.get("Group") == st.session_state.get("group")) & (df_dc.get("RD") == st.session_state.get("rd"))] if not df_dc.empty else pd.DataFrame()

        my_escalated = my_consumers[my_consumers.get("Consumer No", pd.Series()).isin(escalated_field_ivrs)] if not my_consumers.empty else pd.DataFrame()
        if not my_escalated.empty:
            st.error("🚨 HIGH PRIORITY: The following consumers have broken 2+ promises to pay via phone. Physical site visit required immediately.")
            st.dataframe(my_escalated[["Consumer No", "Consumer Name", "Arrear", "Address1"]], use_container_width=True)
            escalation_target = st.selectbox("Select Broken Promise Target:", ["Select"] + my_escalated["Consumer No"].tolist())
            search_ivrs = escalation_target if escalation_target != "Select" else st.text_input("Or Enter Regular 10-Digit IVRS *", max_chars=10, key=f"search_{st.session_state['form_key']}")
        else:
            st.info(f"Target: 30 Visits Today. Pending DOs in your Group & RD: {len(my_consumers)}")
            search_ivrs = st.text_input("Enter 10-Digit IVRS *", max_chars=10, key=f"search_{st.session_state['form_key']}")

        lat = st.session_state.get("lat")
        lng = st.session_state.get("lng")

        if search_ivrs and is_valid_ivrs(str(search_ivrs)):
            consumer_data = my_consumers[my_consumers.get("Consumer No") == search_ivrs] if not my_consumers.empty else pd.DataFrame()
            if not consumer_data.empty:
                c = consumer_data.iloc[0]
                c_name = c.get("Consumer Name", "")
                c_arrear = c.get("Arrear", "")
                c_mob = clean_mobile(c.get("Mobile No", ""))
                c_village = c.get("Address1", "")

                st.success(f"✅ Found: **{c_name}** | Arrears: **₹{c_arrear}**")
                col1, col2 = st.columns(2)
                with col1:
                    mob_correct = st.radio(f"Is Mobile ({c_mob}) correct?", ["Yes", "No - Update"], key=f"m_{st.session_state['form_key']}")
                    final_mob = st.text_input("Enter Correct Mobile", max_chars=10, key=f"m_new_{st.session_state['form_key']}") if mob_correct == "No - Update" else c_mob
                with col2:
                    vill_correct = st.radio(f"Is Village ({c_village}) correct?", ["Yes", "No - Update"], key=f"v_{st.session_state['form_key']}")
                    final_vill = st.text_input("Enter Correct Village", key=f"v_new_{st.session_state['form_key']}") if vill_correct == "No - Update" else c_village

                action = st.selectbox("Consumer Response", ["Select", "Bill Paid", "Line TD", "Promise to Pay", "Not Traceable"], key=f"act_{st.session_state['form_key']}")
                photo = st.camera_input("Capture Evidence Photo (Required)", key=f"photo_{st.session_state['form_key']}")

                if action != "Select" and photo and st.button("💾 Sync Data to Cloud", type="primary"):
                    if not lat:
                        st.error("Wait for GPS to lock before submitting. Refresh the page if needed.")
                    else:
                        with st.spinner("Syncing to Google Sheets..."):
                            photo_filename = f"{search_ivrs}_{now_ist().strftime('%Y%m%d_%H%M%S')}.jpg"
                            payload = {"base64": base64.b64encode(photo.getvalue()).decode("utf-8"), "filename": photo_filename, "mimetype": "image/jpeg"}
                            ok, resp = safe_post_gas(payload)
                            if not ok:
                                st.error(f"Failed to upload photo: {resp}")
                            else:
                                row = [
                                    to_iso_str(now_ist()),
                                    st.session_state.get("location_code", ""),
                                    st.session_state.get("emp_name", ""),
                                    lat,
                                    lng,
                                    search_ivrs,
                                    c_name,
                                    c_arrear,
                                    final_mob,
                                    final_vill,
                                    action,
                                    photo_filename,
                                ]
                                ok2, msg = safe_append_row("Nagod_Field_Data", row)
                                if ok2:
                                    st.session_state["last_activity_time"] = now_ist()
                                    st.session_state["form_key"] += 1
                                    st.success("✅ Synced successfully.")
                                    st.experimental_rerun()
                                else:
                                    st.error(f"Failed to log to sheet: {msg}")
            else:
                st.error("⚠️ IVRS not found in your assigned Group & RD.")

    # -------------------------
    # Vigilance Dashboard
    # -------------------------
    elif role == "5. Vigilance (Theft Detection)":
        st.header(f"🚨 Vigilance Dashboard | {active_dc_name}")
        st.warning("All theft reports require photographic evidence and immediate GPS coordinate locks.")
        lat = st.session_state.get("lat")
        lng = st.session_state.get("lng")

        st.markdown("### Log New Incident")
        theft_type = st.selectbox("Type of Case *", ["Select", "Direct Hooking (Katiya)", "Tariff Change", "Meter Bypass", "Load Enhancement", "Meter Tampering", "Premisses Change"], key=f"t_type_{st.session_state['form_key']}")
        col1, col2 = st.columns(2)
        with col1:
            is_consumer = st.radio("Is Suspect an existing consumer? *", ["Unknown", "Yes"], key=f"t_is_c_{st.session_state['form_key']}")
        with col2:
            ivrs_no = st.text_input("Enter IVRS (If Yes)", key=f"t_ivrs_{st.session_state['form_key']}") if is_consumer == "Yes" else "N/A"

        suspect_name = st.text_input("Name of Suspect, Location Details and other details *", key=f"t_name_{st.session_state['form_key']}")
        je_informed = st.selectbox("Has the JE been informed? *", ["Select", "Yes", "No"], key=f"t_je_{st.session_state['form_key']}")
        photo = st.camera_input("Capture Evidence Photo (Required) *", key=f"t_photo_{st.session_state['form_key']}")

        if st.button("🚨 Submit Report", type="primary"):
            if theft_type == "Select" or je_informed == "Select" or not suspect_name or not photo:
                st.error("⚠️ Please fill all required fields, confirm JE status, and capture the evidence photo.")
            elif not lat:
                st.error("⚠️ GPS Lock missing. Please refresh the page or check your permissions.")
            else:
                with st.spinner("Uploading evidence and logging record..."):
                    photo_filename = f"VIGILANCE_{st.session_state['location_code']}_{now_ist().strftime('%Y%m%d_%H%M%S')}.jpg"
                    payload = {"base64": base64.b64encode(photo.getvalue()).decode("utf-8"), "filename": photo_filename, "mimetype": "image/jpeg"}
                    ok, resp = safe_post_gas(payload)
                    if not ok:
                        st.error(f"Failed to upload photo: {resp}")
                    else:
                        row = [
                            to_iso_str(now_ist()),
                            st.session_state.get("location_code", ""),
                            st.session_state.get("emp_name", ""),
                            lat,
                            lng,
                            theft_type,
                            is_consumer,
                            ivrs_no,
                            suspect_name,
                            je_informed,
                            photo_filename,
                        ]
                        ok2, msg = safe_append_row("Nagod_Theft_Data", row)
                        if ok2:
                            st.session_state["last_activity_time"] = now_ist()
                            st.session_state["form_key"] += 1
                            st.success("✅ Record Logged Successfully!")
                            st.experimental_rerun()
                        else:
                            st.error(f"Error saving to Google Sheets: {msg}")

    # -------------------------
    # Calling Desk
    # -------------------------
    elif role == "2. Calling Desk (Substation & Office)":
        if st.session_state.get("location_code") == "1535000":
            st.header("📞 Division HQ Calling Desk (Global Access)")
            all_dcs = ["All DCs"] + sorted([k for k in dc_tabs.keys() if k != "Mangers"])
            target_dc = st.selectbox("Target Specific DC (Optional):", all_dcs)
            if target_dc != "All DCs":
                dc_consumers = dc_tabs.get(target_dc, pd.DataFrame()).copy()
            else:
                # Merge all DC tabs (excluding manager tab) for global view
                frames = []
                for k, v in dc_tabs.items():
                    if k == "Mangers":
                        continue
                    if not v.empty:
                        v2 = v.copy()
                        v2["DC_Tab"] = k
                        frames.append(v2)
                dc_consumers = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        else:
            st.header(f"📞 Calling Desk: {active_dc_name}")
            dc_consumers = df_dc.copy() if not df_dc.empty else pd.DataFrame()

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            all_groups = ["All Groups"] + sorted(dc_consumers["Group"].dropna().unique().tolist()) if not dc_consumers.empty and "Group" in dc_consumers.columns else ["All Groups"]
            selected_group = st.selectbox("Target Specific Group:", all_groups)

        if selected_group != "All Groups" and not dc_consumers.empty:
            dc_consumers = dc_consumers[dc_consumers["Group"] == selected_group]

        with col_f2:
            if selected_group != "All Groups" and not dc_consumers.empty:
                all_rds = ["All RDs"] + sorted(dc_consumers["RD"].dropna().unique().tolist())
                selected_rd = st.selectbox("Target Specific RD:", all_rds)
                if selected_rd != "All RDs":
                    dc_consumers = dc_consumers[dc_consumers["RD"] == selected_rd]
            else:
                st.selectbox("Target Specific RD:", ["Select Group First"], disabled=True)

        dc_consumers = dc_consumers[~dc_consumers.get("Consumer No", pd.Series()).isin(st.session_state.get("called_ivrs", []))] if not dc_consumers.empty else pd.DataFrame()

        my_followups = dc_consumers[dc_consumers.get("Consumer No", pd.Series()).isin(todays_followups)] if not dc_consumers.empty else pd.DataFrame()
        if not my_followups.empty:
            st.warning("📅 SCHEDULED FOLLOW-UPS: These consumers promised to pay by today.")
            st.dataframe(my_followups[["Consumer No", "Consumer Name", "Arrear", "Mobile No"]], use_container_width=True)
            target_ivrs = st.selectbox("Select Follow-up IVRS:", ["Select"] + my_followups["Consumer No"].tolist())
        else:
            if not dc_consumers.empty and "Arrear" in dc_consumers.columns:
                dc_consumers["Arrear"] = pd.to_numeric(dc_consumers["Arrear"], errors="coerce").fillna(0)
                top_defaulters = dc_consumers.sort_values(by="Arrear", ascending=False).head(50)
            else:
                top_defaulters = dc_consumers.head(50) if not dc_consumers.empty else pd.DataFrame()
            st.info(f"🎯 Displaying Top {len(top_defaulters)} Pending Defaulters:")
            if not top_defaulters.empty:
                st.dataframe(top_defaulters[["Consumer No", "Consumer Name", "Arrear", "Mobile No", "Group", "RD"]], use_container_width=True)
                target_ivrs = st.selectbox("Select Consumer IVRS to Call:", ["Select"] + top_defaulters["Consumer No"].tolist())
            else:
                st.info("No consumers available for calling.")
                target_ivrs = "Select"

        if target_ivrs != "Select":
            c_data = dc_consumers[dc_consumers["Consumer No"] == target_ivrs].iloc[0]
            st.markdown(f"### Consumer: {c_data.get('Consumer Name','')} | Arrears: ₹{c_data.get('Arrear','')}")
            mob = clean_mobile(c_data.get("Mobile No", ""))
            if mob:
                st.markdown(f"## [📞 CLICK TO CALL {mob}](tel:+91{mob})")
            else:
                st.markdown("## No valid mobile number available")

            call_status = st.selectbox("Call Status", ["Select", "Promise to Pay", "Already Paid", "Switch Off", "Wrong Number"])
            ptp_date_str = ""
            if call_status == "Promise to Pay":
                ptp_date = st.date_input("Expected Payment Date", min_value=date.today())
                ptp_date_str = ptp_date.strftime("%Y-%m-%d")
            notes = st.text_input("Additional Notes")

            if st.button("💾 Log Call", type="primary"):
                if call_status == "Select":
                    st.error("⚠️ Please select a Call Status from the dropdown before submitting!")
                else:
                    with st.spinner("Logging call to database..."):
                        row = [
                            to_iso_str(now_ist()),
                            st.session_state.get("location_code", ""),
                            st.session_state.get("emp_name", ""),
                            target_ivrs,
                            call_status,
                            notes,
                            ptp_date_str,
                        ]
                        ok, msg = safe_append_row("Nagod_Calling_Data", row)
                        if ok:
                            st.session_state["called_ivrs"].append(target_ivrs)
                            st.success("Call logged successfully!")
                            st.experimental_rerun()
                        else:
                            st.error(f"Failed to log call: {msg}")

    # -------------------------
    # Manager & Admin placeholders
    # -------------------------
    elif role == "3. DC Incharge (Manager)":
        st.header(f"📊 Manager Dashboard: {active_dc_name}")
        col1, col2 = st.columns(2)
        col1.metric("Houses Visited Today", "18 / 30 Target", "-12")
        col2.metric("Calls Made Today", "45 / 50 Target", "-5")

    elif role == "4. Division Admin":
        st.header("🏢 Division Command Center")
        st.error("🔴 ACTION REQUIRED: Staff Failing Targets")
        st.write("- **Jasso DC (Line Staff):** 4 visits logged today. Activity critically low.")
