import streamlit as st
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# We now use Bokeh for a massive, customizable location button!
from bokeh.models.widgets import Button
from bokeh.models import CustomJS
from streamlit_bokeh_events import streamlit_bokeh_events

# --- 1. GOOGLE DRIVE FOLDER ID ---
DRIVE_FOLDER_ID = "1bYXCpK0aqrE86-Q5tkrWfw5M72x_6SAp"

# --- 2. GOOGLE AUTHENTICATION (Cached for speed) ---
@st.cache_resource
def get_google_clients():
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    sheets_client = gspread.authorize(creds)
    drive_client = build('drive', 'v3', credentials=creds)
    return sheets_client, drive_client

# --- 3. REAL EMPLOYEE DIRECTORY ---
EMPLOYEE_MAP = {
    "Hardua": ["Select Name", "_SHRI_RAFEEK_KHAN_Outsource", "SHRI_AVDHESH_GARG_Outsource", "SHRI_MANOJ_KUMAR_PAL_Outsource", "SHRI_NANDKISHOR_KUSHWAHA_Outsource", "SHRI_NAVEEN_KUMAR_NIGAM_JE", "SHRI_PREM_LAL_KUSHWAHA_Outsource", "SHRI_RAKESH_KUSHWAHA_Outsource", "SHRI_RAMDHANI_VERMA_Outsource", "SHRI_RAVI_DAHIYA_Outsource", "SHRI_SATYA_NARAYAN_KORI_LM"],
    "Jasso": ["Select Name", "Shri Bardani Prasad Loniya_Outsource", "Shri Chandra Dev Singh_Outsource", "Shri Deepak Kumar Loniya_Outsource", "Shri Devkumar Kushwaha_Outsource", "Shri Heeralal Kushwaha_Outsource", "Shri Pradeep Prajapati_Outsource", "Shri Rajneesh Paal_Outsource", "Shri Salman Khan_Outsource", "Shri Santosh Prajapati_Outsource", "Shri Shudhansu Rawat_LA", "Shri Shyambihari Kushwaha_Outsource", "Shri Vikash Kushwaha_Outsource", "Shri Virendra Kumaar Pal_Outsource", "Shri Virendra Kushwaha_Outsource", "Shri Vishnu Saket_LA", "Shri Yogendra kushwaha_Outsource"],
    "Nagod T": ["Select Name", "DHIRENDRA KUSHWAHA_Outsource", "HARSH GAUTAM_Outsource", "K.K. KUSHWAHA_Outsource", "MANISH KUMAR ARYA_Outsource", "MO. RASHID_Outsource", "ROHIT KUSHWAHA_Outsource", "SHIVAM KUSHWAHA_Outsource", "SUHEL AHMAD_Outsource", "SUNEEL KUMAR MISHRA_Outsource", "SURENDRA SINGH PARIHAR_Outsource"],
    "Nagod RES": ["Select Name", "AJAY SHUKLA _Outsource", "Akash Dwivedi _Outsource", "Akash kushwaha _Outsource", "Anil kushwaha _Meter Reader", "Anil kushwaha _Outsource", "Moolchand kushwaha _Outsource", "Munnilal LM", "Panjabi kushwaha _Outsource", "pradeep singh parihar _Outsource", "PUSHPENDRA KUSHWAHA _Outsource", "RAJBHAN KUSHWAHA _Outsource", "Ravikant Chaturvedi _Outsource", "Sourabh Singh_Peon", "sundar rajak _Outsource"],
    "Singhpur": ["Select Name", "ANIL KUMAR GARG_METER READER", "ASHOK KUMAR URMALIYA _OS ALM", "BABU LAL KUSHWAHA_OS ALM", "BHUPENDRA KUSHWAHA_MEETAR READER", "DHEERAJ KOTWAR_MEETAR READER", "MO. NASEEMUDEEN_TA GR. II", "MR. KAMTA PRASAD SHUKLA_ALM", "MR. PRADEEP KUMAR SINGH_ALM", "MR. VISHRAM KUMAR KUSHWAHA_ALM", "MUKESH SARKAR_MEETAR READER", "NARENDRA KUMAR PANDEY_MEETAR READER", "PARSAS MANI SINGH_MEETAR READER", "PUNIT DWIVEDI_MEETAR READER", "RISHI NARAYAN PRAJAPATI_MEETAR READER", "ROHIT KUMAR ARAYA_MEETAR READER", "SHIV SHANKAR GAUTAM_OS ALM", "SUNEEL KUMAR PANDEY_OS ALM", "VEERENDRA PRATAP KUSHWAHA_OS ALM", "YOGENDRA PRATAP KUSHWAHA_OS ALM"],
    "Division Office": ["Select Name", "Admin", "Manager"]
}

st.set_page_config(page_title="Nagod Field App", page_icon="⚡")

# --- 4. SESSION STATE INITIALIZATION ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['dc_name'] = ""
    st.session_state['employee_name'] = ""

if 'input_ivrs' not in st.session_state:
    st.session_state['input_ivrs'] = ""
if 'input_mobile' not in st.session_state:
    st.session_state['input_mobile'] = ""
if 'success_msg' not in st.session_state:
    st.session_state['success_msg'] = ""

# --- AUTO-CLEANER FUNCTION ---
def enforce_numeric():
    if 'input_ivrs' in st.session_state:
        st.session_state['input_ivrs'] = ''.join(filter(str.isdigit, st.session_state['input_ivrs']))
    if 'input_mobile' in st.session_state:
        st.session_state['input_mobile'] = ''.join(filter(str.isdigit, st.session_state['input_mobile']))


# --- 5. ADMIN SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Admin Dashboard")
    st.success("🟢 Connected to Google Cloud")
    st.markdown("[📊 Open Google Sheets](https://sheets.google.com)")
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
    
    temp_dc = st.selectbox("Name of DC *", ["Choose", "Hardua", "Jasso", "Nagod T", "Nagod RES", "Singhpur", "Division Office"])
    if temp_dc != "Choose":
        temp_name = st.selectbox("Select your Name *", EMPLOYEE_MAP[temp_dc])
        
        if temp_name != "Select Name":
            if st.button("Lock Details & Start", type="primary"):
                st.session_state['dc_name'] = temp_dc
                st.session_state['employee_name'] = temp_name
                st.session_state['logged_in'] = True
                st.rerun()

# ==========================================
# SCREEN 2: THE REPEATABLE FIELD APP 
# ==========================================
else:
    st.markdown("### 🔒 Logged In As")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("DC", value=st.session_state['dc_name'], disabled=True)
    with col2:
        st.text_input("Employee", value=st.session_state['employee_name'], disabled=True)
    
    if st.button("Log Out / Change Name"):
        st.session_state['logged_in'] = False
        st.rerun()
        
    st.divider()

    # --- 1. BIG Location Button ---
    st.subheader("📍 1. Capture Consumer Location")
    
    # Create the large green button
    loc_button = Button(label="Fetch Location First", button_type="success", sizing_mode="stretch_width")
    loc_button.js_on_event("button_click", CustomJS(code="""
        navigator.geolocation.getCurrentPosition(
            (loc) => {
                document.dispatchEvent(new CustomEvent("GET_LOCATION", {detail: {lat: loc.coords.latitude, lon: loc.coords.longitude}}))
            }
        )
    """))
    
    # Render it securely into the Streamlit app
    result = streamlit_bokeh_events(
        loc_button,
        events="GET_LOCATION",
        key="get_location",
        refresh_on_update=False,
        override_height=50,
        debounce_time=0
    )

    # Extract coordinates if the button was pressed
    lat, lng = None, None
    if result and "GET_LOCATION" in result:
        lat = result.get("GET_LOCATION")["lat"]
        lng = result.get("GET_LOCATION")["lon"]

    if lat and lng:
        st.success(f"✅ Location locked: {lat}, {lng}")
    else:
        st.warning("⚠️ Please tap the green button above.")

    # --- 2. Consumer Details Form ---
    st.subheader("📝 2. Consumer Details")
    
    ivrs = st.text_input("IVRS of Consumer (10 Digits) *", max_chars=10, key="input_ivrs", on_change=enforce_numeric)
    mobile = st.text_input("Correct Mobile Number (10 Digits) *", max_chars=10, key="input_mobile", on_change=enforce_numeric)
    
    valid_ivrs = ivrs.isdigit() and len(ivrs) == 10
    valid_mobile = mobile.isdigit() and len(mobile) == 10

    if ivrs and not valid_ivrs:
        st.caption("❌ *IVRS must be exactly 10 numeric digits.*")
    if mobile and not valid_mobile:
        st.caption("❌ *Mobile number must be exactly 10 numeric digits.*")
    
    response = st.selectbox("Consumer Response *", [
        "Select Response", 
        "1. Consumer Contacted", 
        "2. Line TD", 
        "3. Bill Paid", 
        "4. Bill Correction Required"
    ])

    f1a = f1b = f2a = f3a = f4a = f4b = ""

    if response == "1. Consumer Contacted":
        st.info("Follow-up: Contacted")
        f1a = "Yes" if st.checkbox("a. Mobile number corrected") else "No"
        f1b = st.number_input("b. Bill will be paid within ___ days", min_value=0, step=1)
    elif response == "2. Line TD":
        st.info("Follow-up: Line TD")
        f2a = st.text_input("a. Meter Reading at disconnection")
    elif response == "3. Bill Paid":
        st.info("Follow-up: Bill Paid")
        f3a = st.number_input("a. Amount Paid (₹)", min_value=0.0, step=10.0)
    elif response == "4. Bill Correction Required":
        st.info("Follow-up: Correction")
        f4a = st.radio("a. Application given to DC office?", ["Yes", "No"], index=1)
        f4b = st.radio("b. Complaint Registered?", ["Yes", "No"], index=1)

    st.divider()

    # --- 3. Optional: Theft & Media Upload ---
    st.subheader("🚨 3. Additional Reports & Evidence")
    
    theft_reported = "No"
    theft_type = ""
    theft_details = ""
    
    if st.checkbox("Report Theft or Irregularity", key="theft_checkbox"):
        theft_reported = "Yes"
        st.error("⚠️ Theft Reporting Activated")
        theft_type = st.selectbox("Type of Theft *", [
            "Select Type", "Tariff Change", "Meter Defective Big House", "Meter Bypass", "Direct Theft"
        ], key="theft_type_dropdown")
        theft_details = st.text_area("Provide additional details (Optional):", key="theft_details_input")

    st.write("📸/🎥 **Evidence Upload (Optional)**")
    
    # The New Radio Button Choice for Media!
    media_source = st.radio("Choose source:", ["No Media", "Take a Picture", "Upload Image/Video"], horizontal=True)
    
    media_file = None
    if media_source == "Take a Picture":
        media_file = st.camera_input("Take a picture", key="photo_input")
    elif media_source == "Upload Image/Video":
        media_file = st.file_uploader("Upload an image or video from your device", type=['jpg', 'jpeg', 'png', 'mp4', 'mov', 'avi'], key="media_upload")

    st.write("") 
    
    # --- 4. Validation & Google Sync ---
    disable_button = not (valid_ivrs and valid_mobile)

    if st.button("💾 Sync to Google & Next", type="primary", disabled=disable_button):
        
        if not lat or not lng:
            st.error("⚠️ Please capture the GPS location first.")
        elif response == "Select Response":
            st.error("⚠️ Please select a Consumer Response.")
        elif theft_reported == "Yes" and theft_type == "Select Type":
            st.error("⚠️ You checked 'Report Theft'. Please select the Type of Theft.")
        else:
            with st.spinner("Syncing to Google Cloud..."):
                try:
                    sheets_client, drive_client = get_google_clients()
                    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 1. Dynamically Upload Image OR Video to Google Drive
                    media_filename = "No Media"
                    if media_file is not None:
                        # Find the correct file extension based on what they uploaded
                        original_name = getattr(media_file, "name", "photo.jpg")
                        ext = original_name.split('.')[-1].lower() if '.' in original_name else 'jpg'
                        
                        # Set the correct formatting for Google Drive
                        if ext in ['mp4', 'mov', 'avi']:
                            mimetype = f'video/{ext}'
                        elif ext in ['jpg', 'jpeg']:
                            mimetype = 'image/jpeg'
                        elif ext == 'png':
                            mimetype = 'image/png'
                        else:
                            mimetype = 'application/octet-stream'

                        media_filename = f"{ivrs}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
                        
                        file_metadata = {
                            'name': media_filename,
                            'parents': [DRIVE_FOLDER_ID]
                        }
                        
                        media_upload = MediaIoBaseUpload(io.BytesIO(media_file.getvalue()), mimetype=mimetype, resumable=False)
                        drive_client.files().create(body=file_metadata, media_body=media_upload, fields='id').execute()

                    # 2. Append Data to Google Sheets
                    sheet = sheets_client.open("Nagod_Field_Data").sheet1
                    
                    row_data = [
                        timestamp_str, st.session_state['dc_name'], st.session_state['employee_name'], 
                        lat, lng, ivrs, mobile, response, 
                        str(f1a), str(f1b), str(f2a), str(f3a), str(f4a), str(f4b), 
                        theft_reported, theft_type, theft_details, media_filename
                    ]
                    
                    sheet.append_row(row_data)

                    # Wipe all inputs clean for the next house
                    st.session_state['input_ivrs'] = ""
                    st.session_state['input_mobile'] = ""
                    if 'theft_checkbox' in st.session_state: st.session_state['theft_checkbox'] = False
                    if 'theft_type_dropdown' in st.session_state: st.session_state['theft_type_dropdown'] = "Select Type"
                    if 'theft_details_input' in st.session_state: st.session_state['theft_details_input'] = ""
                    if 'photo_input' in st.session_state: st.session_state['photo_input'] = None
                    if 'media_upload' in st.session_state: st.session_state['media_upload'] = None
                    
                    # Force the Location Button to reset!
                    if 'get_location' in st.session_state: del st.session_state['get_location']

                    st.session_state['success_msg'] = f"✅ IVRS {ivrs} synced to Google! Ready for next consumer."
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Failed to sync to Google: {e}")
