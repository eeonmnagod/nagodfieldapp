import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from streamlit_js_eval import get_geolocation
import base64
import requests

# --- 1. CONFIGURATION & SECRETS ---
GAS_URL = "https://script.google.com/macros/s/AKfycbxrYfFv7rhhvG9RtkEGurrLUcRQAxpJkfDA0r7S32_tvHE_dcSkELzmKxQ_QDQXyfO_/exec"
MASTER_PASSWORD = "ngb.test" # Division Admin Password

# File Names (Ensuring these match your GitHub Repo EXACTLY)
DO_FILE = "DO.xlsx"
MGR_FILE = "Mangers.xlsx"
OFFICE_FILE = "Office_Staff.xlsx"
SUBSTATION_FILE = "Substation_Staff.xlsx"

st.set_page_config(page_title="Nagod Command Center", page_icon="⚡", layout="wide")

# --- 2. DATA ENGINE (PANDAS CACHE) ---
@st.cache_data
def load_databases():
    try:
        df_do = pd.read_excel(DO_FILE, dtype={'Consumer No': str, 'Mobile No': str, 'Location Code': str})
        df_mgr = pd.read_excel(MGR_FILE, dtype={'Location Code': str})
        df_off = pd.read_excel(OFFICE_FILE, dtype={'Location Code': str})
        df_sub = pd.read_excel(SUBSTATION_FILE, dtype={'Location_code': str})
        return df_do, df_mgr, df_off, df_sub
    except Exception as e:
        st.error(f"⚠️ Database Load Error. Please ensure all Excel files are uploaded to the repository. Details: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_do, df_mgr, df_off, df_sub = load_databases()

# --- 3. GOOGLE SHEETS AUTHENTICATION ---
@st.cache_resource
def get_sheets_client():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    return gspread.authorize(creds)

# --- 4. SESSION STATE ---
if 'logged_in' not in st.session_state:
    st.session_state.update({
        'logged_in': False, 'role': None, 'location_code': None, 
        'group_rd': None, 'emp_name': "", 'form_key': 0
    })

# ==========================================
# SCREEN 1: THE 4-TIER SECURE LOGIN
# ==========================================
if not st.session_state['logged_in']:
    st.title("⚡ Nagod Division Command Center")
    st.markdown("### Select Your Operating Role")
    
    role = st.radio("Login As:", [
        "1. Field Staff (Line Worker)", 
        "2. Calling Desk (Substation & Office)", 
        "3. DC Incharge (Manager)", 
        "4. Division Admin"
    ])
    st.divider()

    if not df_do.empty:
        loc_codes = ["Select"] + sorted(df_do['Location Code'].dropna().unique().tolist())
        
        # --- ROUTE 1: FIELD STAFF ---
        if role == "1. Field Staff (Line Worker)":
            emp_name = st.text_input("Enter Your Name *")
            loc_code = st.selectbox("Select Your DC (Location Code) *", loc_codes)
            
            if loc_code != "Select":
                filtered_group_rds = ["Select"] + sorted(df_do[df_do['Location Code'] == loc_code]['Group-RD'].dropna().unique().tolist())
                group_rd = st.selectbox("Select Your Group-RD *", filtered_group_rds)
                
                if group_rd != "Select" and emp_name and st.button("Access Field App", type="primary"):
                    st.session_state.update({'logged_in': True, 'role': role, 'location_code': loc_code, 'group_rd': group_rd, 'emp_name': emp_name})
                    st.rerun()

        # --- ROUTE 2: CALLING DESK ---
        elif role == "2. Calling Desk (Substation & Office)":
            desk_type = st.radio("Select Desk Type:", ["Office Staff", "Substation Operator"])
            loc_code = st.selectbox("Select DC (Location Code) *", loc_codes)
            
            if loc_code != "Select":
                if desk_type == "Office Staff":
                    names = ["Select Name"] + df_off[df_off['Location Code'] == loc_code]['NAME OF OFFICE STAFF '].dropna().tolist()
                else:
                    names = ["Select Name"] + df_sub[df_sub['Location_code'] == loc_code]['NAME OF SUB STSTION OPERATOR '].dropna().tolist()
                
                emp_name = st.selectbox("Select Your Name *", names)
                
                if emp_name != "Select Name" and st.button("Access Calling Dashboard", type="primary"):
                    st.session_state.update({'logged_in': True, 'role': role, 'location_code': loc_code, 'emp_name': emp_name})
                    st.rerun()

        # --- ROUTE 3: DC INCHARGE (PASSWORD PROTECTED) ---
        elif role == "3. DC Incharge (Manager)":
            loc_code = st.selectbox("Select Assigned DC (Location Code) *", loc_codes)
            if loc_code != "Select":
                names = ["Select Name"] + df_mgr[df_mgr['Location Code'] == loc_code]['Name of Managers'].dropna().tolist()
                emp_name = st.selectbox("Select Manager Name *", names)
                
                if emp_name != "Select Name":
                    mgr_pass = st.text_input("Enter Password (DC Location Code) *", type="password")
