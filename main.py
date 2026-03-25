import streamlit as st
import pandas as pd
from datetime import datetime, date
import gspread
from google.oauth2.service_account import Credentials
from streamlit_js_eval import get_geolocation
import base64
import requests
import time
import pytz
from datetime import datetime, date

# Add this helper to get strict Indian time:
IST = pytz.timezone('Asia/Kolkata')

# Then, anywhere in your code where you see datetime.now(), change it to:
# datetime.now(IST)

# --- 1. CONFIGURATION & SECRETS ---
GAS_URL = "https://script.google.com/macros/s/AKfycbxrYfFv7rhhvG9RtkEGurrLUcRQAxpJkfDA0r7S32_tvHE_dcSkELzmKxQ_QDQXyfO_/exec"
MASTER_PASSWORD = "ngb.test"

# File Names
DO_FILE = "DO.xlsx"
MGR_FILE = "Mangers.xlsx"
OFFICE_FILE = "Office_Staff.xlsx"
SUBSTATION_FILE = "Substation_Staff.xlsx"
FIELD_FILE = "Field_Staff.xlsx"

st.set_page_config(page_title="Nagod Command Center", page_icon="⚡", layout="wide")

# --- 2. GOOGLE SHEETS AUTHENTICATION ---
@st.cache_resource
def get_sheets_client():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    return gspread.authorize(creds)

# --- 3. DATA ENGINE & HISTORY TRACKER ---
@st.cache_data(ttl=300)
def load_call_history():
    try:
        client = get_sheets_client()
        ws = client.open("Nagod_Calling_Data").sheet1
        records = ws.get_all_values()
        if len(records) > 1:
            df = pd.DataFrame(records[1:], columns=records[0])
            return df
    except Exception as e:
        pass 
    return pd.DataFrame(columns=['Timestamp', 'Location Code', 'Emp Name', 'IVRS', 'Status', 'Notes', 'FollowUpDate'])

@st.cache_data
def load_databases():
    try:
        df_do = pd.read_excel(DO_FILE, sheet_name="DO", dtype=str)
        df_mgr = pd.read_excel(MGR_FILE, dtype=str)
        df_off = pd.read_excel(OFFICE_FILE, dtype=str)
        df_sub = pd.read_excel(SUBSTATION_FILE, dtype=str)
        
        try:
            df_field = pd.read_excel(FIELD_FILE, dtype=str)
            df_field.columns = df_field.columns.str.strip()
        except Exception:
            df_field = pd.DataFrame(columns=['Location Code', 'Name of Staff'])

        df_do.columns = df_do.columns.str.strip()
        df_mgr.columns = df_mgr.columns.str.strip()
        df_off.columns = df_off.columns.str.strip()
        df_sub.columns = df_sub.columns.str.strip()

        if 'Location_code' in df_sub.columns:
            df_sub.rename(columns={'Location_code': 'Location Code'}, inplace=True)

        return df_do, df_mgr, df_off, df_sub, df_field
    except Exception as e:
        st.error(f"⚠️ Database Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_do, df_mgr, df_off, df_sub, df_field = load_databases()
df_calls = load_call_history()

# Process PTP Logic
ptp_counts = {}
todays_followups = []
escalated_field_ivrs = []

if not df_calls.empty and not df_do.empty:
    ptp_history = df_calls[(df_calls['Status'] == 'Promise to Pay') & (df_calls['IVRS'].isin(df_do['Consumer No']))]
    ptp_counts = ptp_history['IVRS'].value_counts().to_dict()
    escalated_field_ivrs = [ivrs for ivrs, count in ptp_counts.items() if count >= 2]
    
    today_str = date.today().strftime('%Y-%m-%d')
    todays_followups = ptp_history[ptp_history['FollowUpDate'] <= today_str]['IVRS'].unique().tolist()

# --- DC MAPPING & DIVISION INJECTION ---
dc_mapping = {}
if not df_mgr.empty and 'NAME OF DC' in df_mgr.columns:
    dc_mapping = dict(zip(df_mgr['Location Code'], df_mgr['NAME OF DC']))

dc_mapping['1535000'] = "Division Office"

def format_dc_dropdown(code):
    if code == "Select": return "Select"
    return f"{code} - {dc_mapping.get(code, 'Unknown DC')}"

# --- 4. SESSION STATE ---
if 'logged_in' not in st.session_state:
    st.session_state.update({
        'logged_in': False, 'role': None, 'location_code': None, 
        'group': None, 'rd': None, 'emp_name': "", 'form_key': 0,
        'login_step': 1, 'last_activity_time': None,
        'called_ivrs': [], 'lat': None, 'lng': None
    })

# ==========================================
# SCREEN 1: THE SECURE LOGIN
# ==========================================
if not st.session_state['logged_in']:
    st.title("⚡ Nagod Division Command Center")
    st.markdown("### Select Your Operating Role")
    
    role = st.radio("Login As:", [
        "1. Field Staff (Line Worker)", 
        "2. Calling Desk (Substation & Office)", 
        "3. DC Incharge (Manager)", 
        "4. Division Admin",
        "5. Vigilance (Theft Detection)"
    ])
    st.divider()

    if not df_do.empty:
        if 'Location Code' not in df_do.columns:
            st.error("❌ CRITICAL: 'Location Code' missing from DO.xlsx.")
            st.stop()

        raw_loc_codes = df_do['Location Code'].dropna().unique().tolist()
        if '1535000' not in raw_loc_codes:
            raw_loc_codes.append('1535000')
        loc_codes = ["Select"] + sorted(raw_loc_codes)
        
        # --- ROUTE 1: FIELD STAFF ---
        if role == "1. Field Staff (Line Worker)":
            if st.session_state['login_step'] == 1:
                st.subheader("Step 1: Activate Shift")
                loc_code = st.selectbox("Select Your DC *", loc_codes, format_func=format_dc_dropdown)
                
                emp_name = "Select Name"
                if loc_code != "Select":
                    if not df_field.empty and 'Location Code' in df_field.columns:
                        staff_list = ["Select Name"] + df_field[df_field['Location Code'] == loc_code]['Name of Staff'].dropna().tolist()
                        emp_name = st.selectbox("Select Your Name *", staff_list)
                    else:
                        st.warning("⚠️ Field_Staff.xlsx is missing or empty. Please use text input.")
                        emp_name = st.text_input("Enter Your Name *")
                
                if st.button("⏱️ Activate Shift", type="primary"):
                    if loc_code != "Select" and emp_name != "Select Name" and emp_name != "":
                        st.session_state.update({'location_code': loc_code, 'emp_name': emp_name, 'login_step': 2, 'last_activity_time': datetime.now()})
                        st.rerun()
                    else:
                        st.error("Please select both a DC and your Name.")

            elif st.session_state['login_step'] == 2:
                active_dc_name = dc_mapping.get(st.session_state['location_code'], st.session_state['location_code'])
                st.success(f"🟢 Shift Activated: **{st.session_state['emp_name']}** | **{active_dc_name} DC**")
                
                loc = get_geolocation()
                if loc and 'coords' in loc:
                    st.session_state['lat'] = loc['coords']['latitude']
                    st.session_state['lng'] = loc['coords']['longitude']
                    st.success(f"📍 GPS Locked: {st.session_state['lat']:.4f}, {st.session_state['lng']:.4f}")
                else:
                    st.info("🛰️ Acquiring GPS Satellite Lock... Please allow location permissions.")
                
                dc_data = df_do[df_do['Location Code'] == st.session_state['location_code']]
                
                filtered_groups = ["Select"] + sorted(dc_data['Group'].dropna().unique().tolist())
                selected_group = st.selectbox("Select Your Assigned Group *", filtered_groups)
                
                filtered_rds = ["Select"]
                if selected_group != "Select":
                    filtered_rds += sorted(dc_data[dc_data['Group'] == selected_group]['RD'].dropna().unique().tolist())
                
                selected_rd = st.selectbox("Select Your Assigned RD *", filtered_rds)
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🚀 Enter Dashboard", type="primary") and selected_group != "Select" and selected_rd != "Select":
                        st.session_state.update({
                            'logged_in': True, 'role': role, 
                            'group': selected_group, 'rd': selected_rd, 
                            'last_activity_time': datetime.now()
                        })
                        st.rerun()
                with col2:
                    if st.button("Cancel Shift"):
                        st.session_state['login_step'] = 1
                        st.rerun()

        # --- ROUTE 5: VIGILANCE (THEFT DETECTION) LOGIN (REVERTED TO TEXT INPUT) ---
        elif role == "5. Vigilance (Theft Detection)":
            if st.session_state['login_step'] == 1:
                st.subheader("Step 1: Activate Vigilance Patrol")
                loc_code = st.selectbox("Select Operating DC *", loc_codes, format_func=format_dc_dropdown)
                
                # --- REVERTED: Simple text input for the squad/officer name ---
                emp_name = st.text_input("Enter Officer/Squad Name *")
                
                if st.button("⏱️ Activate Patrol", type="primary"):
                    if loc_code != "Select" and emp_name:
                        st.session_state.update({'location_code': loc_code, 'emp_name': emp_name, 'login_step': 2, 'last_activity_time': datetime.now()})
                        st.rerun()
                    else:
                        st.error("Please select a DC and enter your Name.")

            elif st.session_state['login_step'] == 2:
                active_dc_name = dc_mapping.get(st.session_state['location_code'], st.session_state['location_code'])
                st.success(f"🚨 Vigilance Active: **{st.session_state['emp_name']}** | **{active_dc_name} DC**")
                
                loc = get_geolocation()
                if loc and 'coords' in loc:
                    st.session_state['lat'] = loc['coords']['latitude']
                    st.session_state['lng'] = loc['coords']['longitude']
                    st.success(f"📍 GPS Locked: {st.session_state['lat']:.4f}, {st.session_state['lng']:.4f}")
                else:
                    st.info("🛰️ Acquiring Fast GPS Lock... Please allow location permissions.")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🚀 Enter Theft Dashboard", type="primary"):
                        st.session_state.update({'logged_in': True, 'role': role, 'last_activity_time': datetime.now()})
                        st.rerun()
                with col2:
                    if st.button("Cancel Patrol"):
                        st.session_state['login_step'] = 1
                        st.rerun()

        # --- ROUTE 2: CALLING DESK LOGIN ---
        elif role == "2. Calling Desk (Substation & Office)":
            desk_type = st.radio("Select Desk Type:", ["Office Staff", "Substation Operator"])
            loc_code = st.selectbox("Select DC *", loc_codes, format_func=format_dc_dropdown)
            if loc_code != "Select":
                if desk_type == "Office Staff":
                    names = ["Select Name"] + df_off[df_off['Location Code'] == loc_code]['NAME OF OFFICE STAFF'].dropna().tolist()
                else:
                    names = ["Select Name"] + df_sub[df_sub['Location Code'] == loc_code]['NAME OF SUB STSTION OPERATOR'].dropna().tolist()
                
                emp_name = st.selectbox("Select Your Name *", names)
                
                if emp_name != "Select Name" and st.button("Access Calling Dashboard", type="primary"):
                    st.session_state.update({'logged_in': True, 'role': role, 'location_code': loc_code, 'emp_name': emp_name})
                    st.rerun()

        # --- ROUTE 3: DC INCHARGE ---
        elif role == "3. DC Incharge (Manager)":
            loc_code = st.selectbox("Select Assigned DC *", loc_codes, format_func=format_dc_dropdown)
            if loc_code != "Select":
                names = ["Select Name"] + df_mgr[df_mgr['Location Code'] == loc_code]['Name of Managers'].dropna().tolist()
                emp_name = st.selectbox("Select Manager Name *", names)
                if emp_name != "Select Name":
                    mgr_pass = st.text_input("Enter Password (DC Location Code) *", type="password")
                    if st.button("Open DC Dashboard", type="primary"):
                        if mgr_pass == loc_code:
                            st.session_state.update({'logged_in': True, 'role': role, 'location_code': loc_code, 'emp_name': emp_name})
                            st.rerun()
                        else:
                            st.error("❌ Incorrect Password.")

        # --- ROUTE 4: DIVISION ADMIN ---
        elif role == "4. Division Admin":
            admin_pass = st.text_input("Master Password", type="password")
            if st.button("Unlock Division Analytics", type="primary"):
                if admin_pass == MASTER_PASSWORD:
                    st.session_state.update({'logged_in': True, 'role': role, 'emp_name': "Division Admin"})
                    st.rerun()

# ==========================================
# SCREEN 2: THE OPERATIONAL DASHBOARDS
# ==========================================
else:
    role = st.session_state['role']
    active_dc_name = dc_mapping.get(st.session_state['location_code'], st.session_state['location_code'])
    
    st.sidebar.success(f"🟢 Active Shift: {st.session_state['emp_name']}")
    if st.sidebar.button("Log Out"):
        st.session_state.clear()
        st.rerun()

    # ---------------------------------------------------------
    # ROUTE 1: FIELD STAFF 
    # ---------------------------------------------------------
    if role == "1. Field Staff (Line Worker)":
        
        idle_time_seconds = (datetime.now() - st.session_state['last_activity_time']).total_seconds()
        if int(idle_time_seconds / 60) >= 15:
            st.error(f"⚠️ INACTIVITY ALERT: You have been idle for {int(idle_time_seconds / 60)} minutes.")
        
        st.header(f"📍 {active_dc_name} DC | Group: {st.session_state['group']} | RD: {st.session_state['rd']}")
        
        my_consumers = df_do[(df_do['Group'] == st.session_state['group']) & (df_do['RD'] == st.session_state['rd'])]
        
        my_escalated = my_consumers[my_consumers['Consumer No'].isin(escalated_field_ivrs)]
        if not my_escalated.empty:
            st.error("🚨 HIGH PRIORITY: The following consumers have broken 2+ promises to pay via phone. Physical site visit required immediately.")
            st.dataframe(my_escalated[['Consumer No', 'Consumer Name', 'Arrear', 'Address1']], use_container_width=True)
            escalation_target = st.selectbox("Select Broken Promise Target:", ["Select"] + my_escalated['Consumer No'].tolist())
            search_ivrs = escalation_target if escalation_target != "Select" else st.text_input("Or Enter Regular 10-Digit IVRS *", max_chars=10, key=f"search_{st.session_state.form_key}")
        else:
            st.info(f"Target: 30 Visits Today. Pending DOs in your Group & RD: {len(my_consumers)}")
            search_ivrs = st.text_input("Enter 10-Digit IVRS *", max_chars=10, key=f"search_{st.session_state.form_key}")
        
        lat = st.session_state.get('lat')
        lng = st.session_state.get('lng')
        
        if search_ivrs and len(search_ivrs) == 10:
            consumer_data = my_consumers[my_consumers['Consumer No'] == search_ivrs]
            
            if not consumer_data.empty:
                c_name = consumer_data.iloc[0]['Consumer Name']
                c_arrear = consumer_data.iloc[0]['Arrear']
                c_mob = str(consumer_data.iloc[0]['Mobile No']).split('.')[0] if pd.notna(consumer_data.iloc[0]['Mobile No']) else ""
                c_village = str(consumer_data.iloc[0]['Address1']) if pd.notna(consumer_data.iloc[0]['Address1']) else ""
                
                st.success(f"✅ Found: **{c_name}** | Arrears: **₹{c_arrear}**")
                
                col1, col2 = st.columns(2)
                with col1:
                    mob_correct = st.radio(f"Is Mobile ({c_mob}) correct?", ["Yes", "No - Update"], key=f"m_{st.session_state.form_key}")
                    final_mob = st.text_input("Enter Correct Mobile", max_char=10, key=f"m_new_{st.session_state.form_key}") if mob_correct == "No - Update" else c_mob
                with col2:
                    vill_correct = st.radio(f"Is Village ({c_village}) correct?", ["Yes", "No - Update"], key=f"v_{st.session_state.form_key}")
                    final_vill = st.text_input("Enter Correct Village", key=f"v_new_{st.session_state.form_key}") if vill_correct == "No - Update" else c_village
                
                action = st.selectbox("Consumer Response", ["Select", "Bill Paid", "Line TD", "Promise to Pay", "Not Traceable"], key=f"act_{st.session_state.form_key}")
                photo = st.camera_input("Capture Evidence Photo (Required)", key=f"photo_{st.session_state.form_key}")
                
                if action != "Select" and photo and st.button("💾 Sync Data to Cloud", type="primary"):
                    if not lat:
                        st.error("Wait for GPS to lock before submitting. Refresh the page if needed.")
                    else:
                        with st.spinner("Syncing to Google Sheets..."):
                            photo_filename = f"{search_ivrs}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                            payload = {"base64": base64.b64encode(photo.getvalue()).decode('utf-8'), "filename": photo_filename, "mimetype": "image/jpeg"}
                            requests.post(GAS_URL, json=payload)
                            
                            sheets_client = get_sheets_client()
                            ws = sheets_client.open("Nagod_Field_Data").sheet1
                            ws.append_row([
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state['location_code'], 
                                st.session_state['emp_name'], lat, lng, search_ivrs, c_name, c_arrear, 
                                final_mob, final_vill, action, photo_filename
                            ])
                            st.session_state['last_activity_time'] = datetime.now()
                            st.session_state.form_key += 1
                            st.rerun()
            else:
                st.error("⚠️ IVRS not found in your assigned Group & RD.")

    # ---------------------------------------------------------
    # ROUTE 5: VIGILANCE (THEFT DETECTION) DASHBOARD
    # ---------------------------------------------------------
    elif role == "5. Vigilance (Theft Detection)":
        st.header(f"🚨 Vigilance Dashboard | {active_dc_name} DC")
        st.warning("All theft reports require photographic evidence and immediate GPS coordinate locks.")
        
        lat = st.session_state.get('lat')
        lng = st.session_state.get('lng')

        st.markdown("### Log New Incident")
        theft_type = st.selectbox("Type of Case *", ["Select", "Direct Hooking (Katiya)", "Tariff Change", "Meter Bypass", "Load Enhancement", "Meter Tampering", "Premisses Change"], key=f"t_type_{st.session_state.form_key}")
        
        col1, col2 = st.columns(2)
        with col1:
            is_consumer = st.radio("Is Suspect an existing consumer? *", ["Unknown", "Yes"], key=f"t_is_c_{st.session_state.form_key}")
        with col2:
            ivrs_no = st.text_input("Enter IVRS (If Yes)", key=f"t_ivrs_{st.session_state.form_key}") if is_consumer == "Yes" else "N/A"
            
        suspect_name = st.text_input("Name of Suspect, Location Details and other details *", key=f"t_name_{st.session_state.form_key}")
        je_informed = st.selectbox("Has the JE been informed? *", ["Select", "Yes", "No"], key=f"t_je_{st.session_state.form_key}")
        
        photo = st.camera_input("Capture Evidence Photo (Required) *", key=f"t_photo_{st.session_state.form_key}")

        if st.button("🚨 Submit Report", type="primary"):
            if theft_type == "Select" or je_informed == "Select" or not suspect_name or not photo:
                st.error("⚠️ Please fill all required fields, confirm JE status, and capture the evidence photo.")
            elif not lat:
                st.error("⚠️ GPS Lock missing. Please refresh the page or check your permissions.")
            else:
                with st.spinner("Uploading evidence and logging record..."):
                    photo_filename = f"VIGILANCE_{st.session_state['location_code']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                    payload = {"base64": base64.b64encode(photo.getvalue()).decode('utf-8'), "filename": photo_filename, "mimetype": "image/jpeg"}
                    requests.post(GAS_URL, json=payload)
                    
                    sheets_client = get_sheets_client()
                    try:
                        ws = sheets_client.open("Nagod_Theft_Data").sheet1
                        ws.append_row([
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state['location_code'], 
                            st.session_state['emp_name'], lat, lng, theft_type, is_consumer, ivrs_no, 
                            suspect_name, je_informed, photo_filename
                        ])
                        st.session_state['last_activity_time'] = datetime.now()
                        st.session_state.form_key += 1
                        st.success("✅ Record Logged Successfully!")
                        time.sleep(1.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving to Google Sheets: Please ensure you created a sheet named 'Nagod_Theft_Data'. Error details: {e}")

    # ---------------------------------------------------------
    # ROUTE 2: CALLING DESK
    # ---------------------------------------------------------
    elif role == "2. Calling Desk (Substation & Office)":
        
        if st.session_state['location_code'] == '1535000':
            st.header("📞 Division HQ Calling Desk (Global Access)")
            all_dcs = ["All DCs"] + sorted(df_do['Location Code'].dropna().unique().tolist())
            target_dc = st.selectbox("Target Specific DC (Optional):", all_dcs, format_func=lambda x: format_dc_dropdown(x) if x != "All DCs" else "All DCs")
            
            if target_dc != "All DCs":
                dc_consumers = df_do[df_do['Location Code'] == target_dc].copy()
            else:
                dc_consumers = df_do.copy()
        else:
            st.header(f"📞 Calling Desk: {active_dc_name} DC")
            dc_consumers = df_do[df_do['Location Code'] == st.session_state['location_code']].copy()
        
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            all_groups = ["All Groups"] + sorted(dc_consumers['Group'].dropna().unique().tolist())
            selected_group = st.selectbox("Target Specific Group:", all_groups)
        
        if selected_group != "All Groups":
            dc_consumers = dc_consumers[dc_consumers['Group'] == selected_group]
            
        with col_f2:
            if selected_group != "All Groups":
                all_rds = ["All RDs"] + sorted(dc_consumers['RD'].dropna().unique().tolist())
                selected_rd = st.selectbox("Target Specific RD:", all_rds)
                if selected_rd != "All RDs":
                    dc_consumers = dc_consumers[dc_consumers['RD'] == selected_rd]
            else:
                st.selectbox("Target Specific RD:", ["Select Group First"], disabled=True)

        dc_consumers = dc_consumers[~dc_consumers['Consumer No'].isin(st.session_state['called_ivrs'])]
        
        my_followups = dc_consumers[dc_consumers['Consumer No'].isin(todays_followups)]
        if not my_followups.empty:
            st.warning("📅 SCHEDULED FOLLOW-UPS: These consumers promised to pay by today.")
            st.dataframe(my_followups[['Consumer No', 'Consumer Name', 'Arrear', 'Mobile No']], use_container_width=True)
            target_ivrs = st.selectbox("Select Follow-up IVRS:", ["Select"] + my_followups['Consumer No'].tolist())
        else:
            dc_consumers['Arrear'] = pd.to_numeric(dc_consumers['Arrear'], errors='coerce').fillna(0)
            top_defaulters = dc_consumers.sort_values(by="Arrear", ascending=False).head(50)
            st.info(f"🎯 Displaying Top {len(top_defaulters)} Pending Defaulters:")
            
            st.dataframe(top_defaulters[['Consumer No', 'Consumer Name', 'Arrear', 'Mobile No', 'Group', 'RD']], use_container_width=True)
            target_ivrs = st.selectbox("Select Consumer IVRS to Call:", ["Select"] + top_defaulters['Consumer No'].tolist())
        
        if target_ivrs != "Select":
            c_data = dc_consumers[dc_consumers['Consumer No'] == target_ivrs].iloc[0]
            st.markdown(f"### Consumer: {c_data['Consumer Name']} | Arrears: ₹{c_data['Arrear']}")
            mob = str(c_data['Mobile No']).split('.')[0] if pd.notna(c_data['Mobile No']) else "No Number"
            st.markdown(f"## [📞 CLICK TO CALL {mob}](tel:+91{mob})")
            
            call_status = st.selectbox("Call Status", ["Select", "Promise to Pay", "Already Paid", "Switch Off", "Wrong Number"])
            
            ptp_date_str = ""
            if call_status == "Promise to Pay":
                ptp_date = st.date_input("Expected Payment Date", min_value=date.today())
                ptp_date_str = ptp_date.strftime('%Y-%m-%d')
                
            notes = st.text_input("Additional Notes")
            
            if st.button("💾 Log Call", type="primary"):
                if call_status == "Select":
                    st.error("⚠️ Please select a Call Status from the dropdown before submitting!")
                else:
                    with st.spinner("Logging call to database..."):
                        sheets_client = get_sheets_client()
                        ws = sheets_client.open("Nagod_Calling_Data").sheet1
                        ws.append_row([
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state['location_code'], 
                            st.session_state['emp_name'], target_ivrs, call_status, notes, ptp_date_str
                        ])
                    
                    st.session_state['called_ivrs'].append(target_ivrs)
                    st.success("Call logged successfully!")
                    time.sleep(1.5)
                    st.rerun()

    # ---------------------------------------------------------
    # ROUTE 3 & 4 (Unchanged)
    # ---------------------------------------------------------
    elif role == "3. DC Incharge (Manager)":
        st.header(f"📊 Manager Dashboard: {active_dc_name} DC")
        col1, col2 = st.columns(2)
        col1.metric("Houses Visited Today", "18 / 30 Target", "-12")
        col2.metric("Calls Made Today", "45 / 50 Target", "-5")

    elif role == "4. Division Admin":
        st.header("🏢 Division Command Center")
        st.error("🔴 ACTION REQUIRED: Staff Failing Targets")
        st.write("- **Jasso DC (Line Staff):** 4 visits logged today. Activity critically low.")
