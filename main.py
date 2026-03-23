import streamlit as st
import pandas as pd
from datetime import datetime, date
import gspread
from google.oauth2.service_account import Credentials
from streamlit_js_eval import get_geolocation
import base64
import requests
import time

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

        # --- ROUTE 5: VIGILANCE (THEFT
