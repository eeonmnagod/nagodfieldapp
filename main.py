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

# File Names (Must match GitHub EXACTLY)
DO_FILE = "DO.xlsx"
MGR_FILE = "Mangers.xlsx"
OFFICE_FILE = "Office_Staff.xlsx"
SUBSTATION_FILE = "Substation_Staff.xlsx"

st.set_page_config(page_title="Nagod Command Center", page_icon="⚡", layout="wide")

# --- 2. DATA ENGINE (BULLETPROOF PANDAS CACHE) ---
@st.cache_data
def load_databases():
    try:
        # Read all data as text to prevent phone numbers/IVRS from losing zeros
        df_do = pd.read_excel(DO_FILE, dtype=str)
        df_mgr = pd.read_excel(MGR_FILE, dtype=str)
        df_off = pd.read_excel(OFFICE_FILE, dtype=str)
        df_sub = pd.read_excel(SUBSTATION_FILE, dtype=str)

        # THE FIX: Strip hidden spaces from all Excel column headers automatically
        df_do.columns = df_do.columns.str.strip()
        df_mgr.columns = df_mgr.columns.str.strip()
        df_off.columns = df_off.columns.str.strip()
        df_sub.columns = df_sub.columns.str.strip()

        # Standardize the Substation sheet's Location Code column
        if 'Location_code' in df_sub.columns:
            df_sub.rename(columns={'Location_code': 'Location Code'}, inplace=True)

        return df_do, df_mgr, df_off, df_sub
    except Exception as e:
        st.error(f"⚠️ Database Load Error: {e}")
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
        # Check if 'Location Code' actually exists after stripping spaces
        if 'Location Code' not in df_do.columns:
            st.error("❌ CRITICAL: The column 'Location Code' is missing from the DO.xlsx file. Please check your Excel sheet headers.")
            st.stop()

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
                    names = ["Select Name"] + df_off[df_off['Location Code'] == loc_code]['NAME OF OFFICE STAFF'].dropna().tolist()
                else:
                    names = ["Select Name"] + df_sub[df_sub['Location Code'] == loc_code]['NAME OF SUB STSTION OPERATOR'].dropna().tolist()
                
                emp_name = st.selectbox("Select Your Name *", names)
                
                if emp_name != "Select Name" and st.button("Access Calling Dashboard", type="primary"):
                    st.session_state.update({'logged_in': True, 'role': role, 'location_code': loc_code, 'emp_name': emp_name})
                    st.rerun()

        # --- ROUTE 3: DC INCHARGE ---
        elif role == "3. DC Incharge (Manager)":
            loc_code = st.selectbox("Select Assigned DC (Location Code) *", loc_codes)
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
                            st.error("❌ Incorrect Password. Please enter your valid DC Location Code.")

        # --- ROUTE 4: DIVISION ADMIN ---
        elif role == "4. Division Admin":
            admin_pass = st.text_input("Master Password", type="password")
            if st.button("Unlock Division Analytics", type="primary"):
                if admin_pass == MASTER_PASSWORD:
                    st.session_state.update({'logged_in': True, 'role': role, 'emp_name': "Division Admin"})
                    st.rerun()
                else:
                    st.error("❌ Incorrect Master Password")

# ==========================================
# SCREEN 2: THE OPERATIONAL DASHBOARDS
# ==========================================
else:
    role = st.session_state['role']
    st.sidebar.success(f"🟢 Active Shift: {st.session_state['emp_name']}")
    if st.sidebar.button("Log Out"):
        st.session_state.clear()
        st.rerun()

    # ---------------------------------------------------------
    # ROUTE 1: FIELD STAFF
    # ---------------------------------------------------------
    if role == "1. Field Staff (Line Worker)":
        st.header(f"📍 Field Operations: Group-RD {st.session_state['group_rd']}")
        my_consumers = df_do[df_do['Group-RD'] == st.session_state['group_rd']]
        
        st.info(f"Target: 30 Visits Today. Pending DOs in your Group-RD: {len(my_consumers)}")
        
        loc = get_geolocation()
        lat, lng = (loc['coords']['latitude'], loc['coords']['longitude']) if loc and 'coords' in loc else (None, None)
        if not lat:
            st.warning("Awaiting GPS Signal...")

        st.divider()
        search_ivrs = st.text_input("Enter 10-Digit IVRS *", max_chars=10, key=f"search_{st.session_state.form_key}")
        
        if search_ivrs and len(search_ivrs) == 10:
            consumer_data = my_consumers[my_consumers['Consumer No'] == search_ivrs]
            
            if not consumer_data.empty:
                c_name = consumer_data.iloc[0]['Consumer Name']
                c_arrear = consumer_data.iloc[0]['Arrear']
                c_mob = str(consumer_data.iloc[0]['Mobile No']).split('.')[0] if pd.notna(consumer_data.iloc[0]['Mobile No']) else ""
                c_village = str(consumer_data.iloc[0]['Address1']) if pd.notna(consumer_data.iloc[0]['Address1']) else ""
                
                st.success(f"✅ Found: **{c_name}** | Arrears: **₹{c_arrear}**")
                
                st.markdown("### Data Verification")
                col1, col2 = st.columns(2)
                with col1:
                    mob_correct = st.radio(f"Is Mobile ({c_mob}) correct?", ["Yes", "No - Update"], key=f"m_{st.session_state.form_key}")
                    final_mob = st.text_input("Enter Correct Mobile", key=f"m_new_{st.session_state.form_key}") if mob_correct == "No - Update" else c_mob
                with col2:
                    vill_correct = st.radio(f"Is Village ({c_village}) correct?", ["Yes", "No - Update"], key=f"v_{st.session_state.form_key}")
                    final_vill = st.text_input("Enter Correct Village", key=f"v_new_{st.session_state.form_key}") if vill_correct == "No - Update" else c_village
                
                st.markdown("### Action Taken")
                action = st.selectbox("Consumer Response", ["Select", "Bill Paid", "Line TD", "Promise to Pay", "Not Traceable"], key=f"act_{st.session_state.form_key}")
                photo = st.camera_input("Capture Evidence Photo (Required)", key=f"photo_{st.session_state.form_key}")
                
                if action != "Select" and photo and st.button("💾 Sync Data to Cloud", type="primary"):
                    if not lat:
                        st.error("Wait for GPS to lock before submitting.")
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
                            
                            st.session_state.form_key += 1
                            st.rerun()
            else:
                st.error("⚠️ IVRS not found in your assigned Group-RD. Please verify the number.")

    # ---------------------------------------------------------
    # ROUTE 2: CALLING DESK
    # ---------------------------------------------------------
    elif role == "2. Calling Desk (Substation & Office)":
        st.header(f"📞 Calling Desk: Location Code {st.session_state['location_code']}")
        
        my_consumers = df_do[df_do['Location Code'] == st.session_state['location_code']].copy()
        
        # Ensure Arrear is numeric before sorting
        my_consumers['Arrear'] = pd.to_numeric(my_consumers['Arrear'], errors='coerce').fillna(0)
        my_consumers = my_consumers.sort_values(by="Arrear", ascending=False)
        
        st.warning("🎯 Target: 50 Calls Today. Displaying Top Defaulters:")
        st.dataframe(my_consumers[['Consumer No', 'Consumer Name', 'Arrear', 'Mobile No']].head(100), use_container_width=True)
        
        target_ivrs = st.selectbox("Select Consumer IVRS to Call:", ["Select"] + my_consumers['Consumer No'].tolist())
        
        if target_ivrs != "Select":
            c_data = my_consumers[my_consumers['Consumer No'] == target_ivrs].iloc[0]
            st.markdown(f"### Consumer: {c_data['Consumer Name']} | Arrears: ₹{c_data['Arrear']}")
            mob = str(c_data['Mobile No']).split('.')[0] if pd.notna(c_data['Mobile No']) else "No Number"
            st.markdown(f"## [📞 CLICK TO CALL {mob}](tel:+91{mob})")
            
            call_status = st.selectbox("Call Status", ["Select", "Promise to Pay", "Already Paid", "Switch Off", "Wrong Number"])
            notes = st.text_input("Additional Notes")
            
            if call_status != "Select" and st.button("Log Call", type="primary"):
                sheets_client = get_sheets_client()
                ws = sheets_client.open("Nagod_Calling_Data").sheet1
                ws.append_row([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state['location_code'], 
                    st.session_state['emp_name'], target_ivrs, call_status, notes
                ])
                st.success("Call logged successfully!")

    # ---------------------------------------------------------
    # ROUTE 3: DC INCHARGE
    # ---------------------------------------------------------
    elif role == "3. DC Incharge (Manager)":
        st.header(f"📊 Manager Dashboard: {st.session_state['location_code']}")
        st.markdown("*Live integration with Google Sheets data will visualize progress here.*")
        col1, col2 = st.columns(2)
        col1.metric(label="Total Houses Visited Today", value="18 / 30 Target", delta="-12")
        col2.metric(label="Total Calls Made Today", value="45 / 50 Target", delta="-5")

    # ---------------------------------------------------------
    # ROUTE 4: DIVISION ADMIN
    # ---------------------------------------------------------
    elif role == "4. Division Admin":
        st.header("🏢 Division Command Center")
        st.error("🔴 ACTION REQUIRED: Staff Failing Targets")
        st.write("- **Jasso DC (Line Staff):** 4 visits logged today. Activity critically low.")
        
        if st.button("Generate Show-Cause Letter"):
            st.text_area("Hindi Draft for Dispatch:", value="सूचना:\n\nयह देखा गया है कि आज आपके द्वारा निर्धारित 30 उपभोक्ताओं के लक्ष्य के विरुद्ध मात्र अत्यंत कम कार्यवाही की गई है। राजस्व वसूली के कार्य में लापरवाही प्रतीत होती है। कृपया तत्काल स्पष्टीकरण प्रस्तुत करें।", height=150)
            st.success("Draft Generated. Click inside the box to copy, paste, and dispatch.")
