import streamlit as st
from streamlit_js_eval import get_geolocation
from datetime import datetime
import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials
import base64
import requests

# --- 1. GOOGLE APPS SCRIPT WEB APP URL ---
# ⚠️ PASTE THE URL YOU COPIED FROM GOOGLE APPS SCRIPT HERE
GAS_URL = "https://script.google.com/macros/s/AKfycbxsOA-9QBFSRg9lKxPT0tmhtvotAprAXpT81EdH1554hIr7io7DuX1G4yZkPewoAoNP/exec"

# --- 2. GOOGLE SHEETS AUTHENTICATION ---
@st.cache_resource
def get_sheets_client():
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    return gspread.authorize(creds)

# --- 3. REAL EMPLOYEE DIRECTORY ---
EMPLOYEE_MAP = {
    "Hardua": ["Select Name", "_SHRI_RAFEEK_KHAN_Outsource", "SHRI_AVDHESH_GARG_Outsource", "SHRI_MANOJ_KUMAR_PAL_Outsource", "SHRI_NANDKISHOR_KUSHWAHA_Outsource", "SHRI_NAVEEN_KUMAR_NIGAM_JE", "SHRI_PREM_LAL_KUSHWAHA_Outsource", "SHRI_RAKESH_KUSHWAHA_Outsource", "SHRI_RAMDHANI_VERMA_Outsource", "SHRI_RAVI_DAHIYA_Outsource", "SHRI_SATYA_NARAYAN_KORI_LM"],
    "Jasso": ["Select Name", "Shri Bardani Prasad Loniya_Outsource", "Shri Chandra Dev Singh_Outsource", "Shri Deepak Kumar Loniya_Outsource", "Shri Devkumar Kushwaha_Outsource", "Shri Heeralal Kushwaha_Outsource", "Shri Pradeep Prajapati_Outsource", "Shri Rajneesh Paal_Outsource", "Shri Salman Khan_Outsource", "Shri Santosh Prajapati_Outsource", "Shri Shudhansu Rawat_LA", "Shri Shyambihari Kushwaha_Outsource", "Shri Vikash Kushwaha_Outsource", "Shri Virendra Kumaar Pal_Outsource", "Shri Virendra Kushwaha_Outsource", "Shri Vishnu Saket_LA", "Shri Yogendra kushwaha_Outsource"],
    "Nagod T": ["Select Name", "DHIRENDRA KUSHWAHA_Outsource", "HARSH GAUTAM_Outsource", "K.K. KUSHWAHA_Outsource", "MANISH KUMAR ARYA_Outsource", "MO. RASHID_Outsource", "ROHIT KUSHWAHA_Outsource", "SHIVAM KUSHWAHA_Outsource", "SUHEL AHMAD_Outsource", "SUNEEL KUMAR MISHRA_Outsource", "SURENDRA SINGH PARIHAR_Outsource"],
    "Nagod RES": ["Select Name", "AJAY SHUKLA _Outsource", "Akash Dwivedi _Outsource", "Akash kushwaha _Outsource", "Anil kushwaha _Meter Reader", "Anil kushwaha _Outsource", "Moolchand kushwaha _Outsource", "Munnilal LM", "Panjabi kushwaha _Outsource", "pradeep singh parihar _Outsource", "PUSHPENDRA KUSHWAHA _Outsource", "RAJBHAN KUSHWAHA _Outsource", "Ravikant Chaturvedi _Outsource", "Sourabh Singh_Peon", "sundar rajak _Outsource"],
    "Singhpur": ["Select Name", "ANIL KUMAR GARG_METER READER", "ASHOK KUMAR URMALIYA _OS ALM", "BABU LAL KUSHWAHA_OS ALM", "BHUPENDRA KUSHWAHA_MEETAR READER", "DHEERAJ KOTWAR_MEETAR READER", "MO. NASEEMUDEEN_TA GR. II", "MR. KAMTA PRASAD SHUKLA_ALM", "MR. PRADEEP KUMAR SINGH_ALM", "MR. VISHRAM KUMAR KUSHWAHA_ALM", "MUKESH SARKAR_MEETAR READER", "NARENDRA KUMAR PANDEY_MEETAR READER", "PARSAS MANI SINGH_MEETAR READER", "PUNIT DWIVEDI_MEETAR READER", "RISHI NARAYAN PRAJAPATI_MEETAR READER", "ROHIT KUMAR ARAYA_MEETAR READER", "SHIV SHANKAR GAUTAM_OS ALM", "SUNEEL KUMAR PANDEY_OS ALM", "VEERENDRA PRATAP KUSHWAHA_OS ALM", "YOGENDRA PRATAP KUSHWAHA_OS ALM"],
    "Division Office": ["Select Name", "Admin", "Manager"],
    # NEW: Dedicated group for Substation Operators
    "Substation (Calling Desk)": ["Select Name", "Operator 1", "Operator 2", "Operator 3"] 
}

st.set_page_config(page_title="Nagod Field App", page_icon="⚡")

# --- 4. SESSION STATE INITIALIZATION ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['dc_name'] = ""
    st.session_state['employee_name'] = ""

if 'success_msg' not in st.session_state:
    st.session_state['success_msg'] = ""

if 'form_key' not in st.session_state:
    st.session_state.form_key = 0

# --- AUTO-CLEANER FUNCTION ---
def enforce_numeric():
    ivrs_key = f"ivrs_{st.session_state.form_key}"
    mob_key = f"mobile_{st.session_state.form_key}"
    
    if ivrs_key in st.session_state:
        st.session_state[ivrs_key] = ''.join(filter(str.isdigit, st.session_state[ivrs_key]))
    if mob_key in st.session_state:
        st.session_state[mob_key] = ''.join(filter(str.isdigit, st.session_state[mob_key]))


# --- 5. ADMIN SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Admin Dashboard")
    st.success("🟢 Connected to Google Cloud")
    st.markdown("[📊 Open Field Data](https://sheets.google.com)")
    st.markdown("[📞 Open Calling Data](https://sheets.google.com)")
    st.markdown("[📁 Open Google Drive](https://drive.google.com)")

st.title("Nagod Division Field App")

if st.session_state['success_msg']:
    st.success(st.session_state['success_msg'])
    st.session_state['success_msg'] = ""

# ==========================================
# SCREEN 1: THE LOGIN GATE
# ==========================================
if not st.session_state['logged_in']:
    st.subheader("Login to Lock ID")
    
    temp_dc = st.selectbox("Name of DC / Role *", ["Choose", "Hardua", "Jasso", "Nagod T", "Nagod RES", "Singhpur", "Division Office", "Substation (Calling Desk)"])
    if temp_dc != "Choose":
        temp_name = st.selectbox("Select your Name *", EMPLOYEE_MAP[temp_dc])
        
        if temp_name != "Select Name":
            if st.button("Lock Details & Start", type="primary"):
                st.session_state['dc_name'] = temp_dc
                st.session_state['employee_name'] = temp_name
                st.session_state['logged_in'] = True
                st.rerun()

# ==========================================
# SCREEN 2: THE REPEATABLE APP 
# ==========================================
else:
    # --- UI: Header ---
    st.markdown("### 🔒 Logged In As")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("DC/Role", value=st.session_state['dc_name'], disabled=True)
    with col2:
        st.text_input("Employee", value=st.session_state['employee_name'], disabled=True)
    
    if st.button("Log Out / Change Name"):
        st.session_state['logged_in'] = False
        st.rerun()
        
    st.divider()

    # Define a flag to easily check if the user is a caller
    is_caller = (st.session_state['dc_name'] == "Substation (Calling Desk)")

    # --- UI: GPS (Field Workers Only) ---
    lat, lng = None, None
    if not is_caller:
        st.subheader("📍 1. Capturing Location...")
        loc = get_geolocation()
        
        if loc and 'coords' in loc:
            lat = loc['coords']['latitude']
            lng = loc['coords']['longitude']
            st.success(f"Location locked automatically: {lat}, {lng}")
        else:
            st.warning("Awaiting GPS coordinates... (Please ensure location is allowed in browser settings)")
    else:
        st.info("📞 Operating in Substation Calling Mode. GPS Disabled.")

    # --- UI: Common Inputs ---
    st.subheader("📝 Consumer Details")
    
    ivrs = st.text_input("IVRS of Consumer (10 Digits) *", max_chars=10, key=f"ivrs_{st.session_state.form_key}", on_change=enforce_numeric)
    mobile = st.text_input("Correct Mobile Number (10 Digits) *", max_chars=10, key=f"mobile_{st.session_state.form_key}", on_change=enforce_numeric)
    
    valid_ivrs = ivrs.isdigit() and len(ivrs) == 10
    valid_mobile = mobile.isdigit() and len(mobile) == 10

    if ivrs and not valid_ivrs:
        st.caption("❌ *IVRS must be exactly 10 numeric digits.*")
    if mobile and not valid_mobile:
        st.caption("❌ *Mobile number must be exactly 10 numeric digits.*")
    
    # --- UI: Dynamic Response Options ---
    f1a = f1b = f2a = f3a = f4a = f4b = call_days = call_note = ""
    theft_reported = "No"
    theft_type = theft_details = ""
    photo = None

    if is_caller:
        # CALLING DESK QUESTIONS
        response = st.selectbox("Call Status *", [
            "Select Status", "1. Contacted - Promise to Pay", "2. Contacted - Already Paid", 
            "3. Switch Off / Not Reachable", "4. Wrong Number", "5. Other"
        ], key=f"resp_call_{st.session_state.form_key}")

        if response == "1. Contacted - Promise to Pay":
            call_days = st.number_input("Will pay within ___ days", min_value=0, step=1, key=f"c_days_{st.session_state.form_key}")
        elif response == "5. Other":
            call_note = st.text_input("Enter Details:", key=f"c_note_{st.session_state.form_key}")

    else:
        # FIELD WORKER QUESTIONS
        response = st.selectbox("Consumer Response *", [
            "Select Response", "1. Consumer Contacted", "2. Line TD", "3. Bill Paid", "4. Bill Correction Required"
        ], key=f"resp_{st.session_state.form_key}")

        if response == "1. Consumer Contacted":
            st.info("Follow-up: Contacted")
            f1a = "Yes" if st.checkbox("a. Mobile number corrected", key=f"f1a_{st.session_state.form_key}") else "No"
            f1b = st.number_input("b. Bill will be paid within ___ days", min_value=0, step=1, key=f"f1b_{st.session_state.form_key}")
        elif response == "2. Line TD":
            st.info("Follow-up: Line TD")
            f2a = st.text_input("a. Meter Reading at disconnection", key=f"f2a_{st.session_state.form_key}")
        elif response == "3. Bill Paid":
            st.info("Follow-up: Bill Paid")
            f3a = st.number_input("a. Amount Paid (₹)", min_value=0.0, step=10.0, key=f"f3a_{st.session_state.form_key}")
        elif response == "4. Bill Correction Required":
            st.info("Follow-up: Correction")
            f4a = st.radio("a. Application given to DC office?", ["Yes", "No"], index=1, key=f"f4a_{st.session_state.form_key}")
            f4b = st.radio("b. Complaint Registered?", ["Yes", "No"], index=1, key=f"f4b_{st.session_state.form_key}")

        st.divider()

        # Optional Theft & Photo for Field Workers ONLY
        st.subheader("🚨 Additional Reports (Optional)")
        if st.checkbox("Report Theft or Irregularity", key=f"theft_chk_{st.session_state.form_key}"):
            theft_reported = "Yes"
            st.error("⚠️ Theft Reporting Activated")
            theft_type = st.selectbox("Type of Theft *", ["Select Type", "Tariff Change", "Meter Defective Big House", "Meter Bypass", "Direct Theft"], key=f"theft_typ_{st.session_state.form_key}")
            theft_details = st.text_area("Provide additional details (Optional):", key=f"theft_det_{st.session_state.form_key}")

        st.write("📸 **Capture Photo Evidence**")
        photo = st.camera_input("Take a picture", key=f"photo_{st.session_state.form_key}")

    st.write("") 
    
    # --- 4. Validation & Google Sync ---
    disable_button = not (valid_ivrs and valid_mobile)

    if st.button("💾 Sync to Google & Next", type="primary", disabled=disable_button):
        
        # Validations
        if not is_caller and (not lat or not lng):
            st.error("⚠️ GPS location has not been captured yet. Please wait or check permissions.")
        elif response in ["Select Response", "Select Status"]:
            st.error("⚠️ Please select a Response/Status.")
        elif not is_caller and theft_reported == "Yes" and theft_type == "Select Type":
            st.error("⚠️ You checked 'Report Theft'. Please select the Type of Theft.")
        else:
            with st.spinner("Syncing to Google Cloud..."):
                try:
                    sheets_client = get_sheets_client()
                    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # Helper function to push data to ANY spreadsheet dynamically
                    def push_to_sheet(spreadsheet_name, sheet_title, base_hdrs, base_dat, specific_headers, specific_data):
                        ss = sheets_client.open(spreadsheet_name)
                        try:
                            ws = ss.worksheet(sheet_title)
                        except WorksheetNotFound:
                            ws = ss.add_worksheet(title=sheet_title, rows=1000, cols=20)
                            ws.append_row(base_hdrs + specific_headers)
                        ws.append_row(base_dat + specific_data)

                    # ==========================================
                    # ROUTE 1: CALLING DESK DATA
                    # ==========================================
                    if is_caller:
                        base_data = [timestamp_str, st.session_state['employee_name'], ivrs, mobile, response]
                        base_headers = ["Timestamp", "Operator Name", "IVRS", "Mobile", "Call Status"]
                        
                        if response == "1. Contacted - Promise to Pay":
                            push_to_sheet("Nagod_Calling_Data", "Promise to Pay", base_headers, base_data, ["Days to Pay"], [str(call_days)])
                        elif response == "5. Other":
                            push_to_sheet("Nagod_Calling_Data", "Other Details", base_headers, base_data, ["Notes"], [call_note])
                        else:
                            push_to_sheet("Nagod_Calling_Data", "General Call Logs", base_headers, base_data, [], [])

                    # ==========================================
                    # ROUTE 2: FIELD WORKER DATA
                    # ==========================================
                    else:
                        # 1. Upload Photo
                        photo_filename = "No Photo"
                        if photo is not None:
                            photo_filename = f"{ivrs}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                            base64_image = base64.b64encode(photo.getvalue()).decode('utf-8')
                            payload = {"base64": base64_image, "filename": photo_filename, "mimetype": "image/jpeg"}
                            requests.post(GAS_URL, json=payload)

                        # 2. Append Data
                        base_data = [timestamp_str, st.session_state['dc_name'], st.session_state['employee_name'], lat, lng, ivrs, mobile]
                        base_headers = ["Timestamp", "DC Name", "Employee", "Lat", "Lng", "IVRS", "Mobile"]

                        if response == "1. Consumer Contacted":
                            push_to_sheet("Nagod_Field_Data", "Contacted", base_headers, base_data, ["Mobile Corrected?", "Pay within Days", "Photo File"], [str(f1a), str(f1b), photo_filename])
                        elif response == "2. Line TD":
                            push_to_sheet("Nagod_Field_Data", "Line TD", base_headers, base_data, ["Meter Reading at TD", "Photo File"], [str(f2a), photo_filename])
                        elif response == "3. Bill Paid":
                            push_to_sheet("Nagod_Field_Data", "Bill Paid", base_headers, base_data, ["Amount Paid (Rs)", "Photo File"], [str(f3a), photo_filename])
                        elif response == "4. Bill Correction Required":
                            push_to_sheet("Nagod_Field_Data", "Correction Req", base_headers, base_data, ["App given to DC?", "Complaint Registered?", "Photo File"], [str(f4a), str(f4b), photo_filename])

                        if theft_reported == "Yes":
                            push_to_sheet("Nagod_Field_Data", "Theft Reports", base_headers, base_data, ["Theft Type", "Details", "Photo File"], [theft_type, theft_details, photo_filename])

                    # Wipes the form clean!
                    st.session_state.form_key += 1
                    
                    st.session_state['success_msg'] = f"✅ IVRS {ivrs} synced to Google! Ready for next consumer."
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Failed to sync to Google: {e}")
