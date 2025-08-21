import streamlit as st
import pandas as pd
import time
import secrets
import re
import os
import requests
from datetime import datetime, timedelta
from typing import Optional
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Google Sheets
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ===============================
# קונפיגורציה ואתחול
# ===============================
st.set_page_config(
    page_title="💒 ניהול הוצאות חתונה",
    page_icon="💒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# קבועים
PHONE_PATTERN = re.compile(r"^0\d{9}$")
CODE_TTL_SECONDS = 300
MAX_AUTH_ATTEMPTS = 5

# Google Sheets Configuration
SHEET_ID = os.getenv("GSHEETS_SPREADSHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

# WhatsApp Configuration  
GREEN_ID = os.getenv("GREENAPI_INSTANCE_ID")
GREEN_TOKEN = os.getenv("GREENAPI_TOKEN")

# Headers for expense sheet
EXPENSE_HEADERS = [
    "expense_id", "owner_phone", "partner_group_id", "date", "amount", "currency",
    "vendor", "category", "payment_method", "invoice_number", "notes",
    "drive_file_url", "source", "status", "needs_review",
    "created_at", "updated_at", "approved_at"
]

# קטגוריות
CATEGORIES = [
    "אולם וקייטרינג", "בר/אלכוהול", "צילום", "מוזיקה/דיג'יי",
    "בגדים/טבעות", "עיצוב/פרחים", "הדפסות/הזמנות/מדיה",
    "לינה/נסיעות/הסעות", "אחר"
]

CATEGORY_EMOJIS = {
    "אולם וקייטרינג": "🏛️",
    "בר/אלכוהול": "🍺", 
    "צילום": "📸",
    "מוזיקה/דיג'יי": "🎵",
    "בגדים/טבעות": "👗",
    "עיצוב/פרחים": "🌸",
    "הדפסות/הזמנות/מדיה": "📄",
    "לינה/נסיעות/הסעות": "✈️",
    "אחר": "📋"
}

# ===============================
# CSS עיצוב
# ===============================
def load_dashboard_css():
    st.markdown("""
    <style>
    /* עיצוב כללי */
    .stApp {
        direction: rtl;
        font-family: 'Segoe UI', 'Heebo', sans-serif;
    }
    
    /* כותרת ראשית */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        text-align: center;
        margin-bottom: 2rem;
        color: white;
        box-shadow: 0 8px 32px rgba(0,0,0,0.1);
    }
    
    .main-header h1 {
        font-size: 2.5rem;
        margin: 0;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
    }
    
    .main-header p {
        font-size: 1.1rem;
        margin: 0.5rem 0 0 0;
        opacity: 0.9;
    }
    
    /* כרטיסי סטטיסטיקות */
    .stat-card {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        border-right: 4px solid #667eea;
        margin-bottom: 1rem;
        transition: transform 0.2s ease;
    }
    
    .stat-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.12);
    }
    
    .stat-value {
        font-size: 2rem;
        font-weight: bold;
        color: #667eea;
        margin: 0;
    }
    
    .stat-label {
        font-size: 0.9rem;
        color: #666;
        margin: 0;
    }
    
    /* טבלה מותאמת אישית */
    .custom-table {
        background: white;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        margin: 1rem 0;
    }
    
    .table-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1rem;
        font-weight: bold;
        text-align: center;
    }
    
    /* כפתורי סינון */
    .filter-button {
        background: #f8f9fa;
        border: 2px solid #e9ecef;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        margin: 0.25rem;
        cursor: pointer;
        transition: all 0.2s ease;
        display: inline-block;
    }
    
    .filter-button:hover {
        background: #667eea;
        color: white;
        border-color: #667eea;
    }
    
    .filter-button.active {
        background: #667eea;
        color: white;
        border-color: #667eea;
    }
    
    /* אימות */
    .auth-container {
        max-width: 400px;
        margin: 5rem auto;
        background: white;
        padding: 3rem;
        border-radius: 20px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        text-align: center;
    }
    
    .auth-header {
        margin-bottom: 2rem;
    }
    
    .auth-icon {
        font-size: 4rem;
        margin-bottom: 1rem;
    }
    
    .auth-title {
        font-size: 1.8rem;
        color: #333;
        margin: 0;
    }
    
    .auth-subtitle {
        color: #666;
        margin: 0.5rem 0 0 0;
    }
    
    /* Responsive */
    @media (max-width: 768px) {
        .main-header h1 {
            font-size: 2rem;
        }
        
        .auth-container {
            margin: 2rem auto;
            padding: 2rem;
        }
    }
    </style>
    """, unsafe_allow_html=True)

# ===============================
# פונקציות Google Sheets
# ===============================
@st.cache_resource
def get_sheets_service():
    """יצירת חיבור ל-Google Sheets"""
    try:
        if GOOGLE_CREDENTIALS_JSON:
            import json
            creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
            credentials = service_account.Credentials.from_service_account_info(
                creds_dict, 
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
            )
            service = build("sheets", "v4", credentials=credentials)
            return service
        else:
            st.error("❌ לא נמצאו אישורי Google Sheets")
            return None
    except Exception as e:
        st.error(f"❌ שגיאה בחיבור ל-Google Sheets: {e}")
        return None

def load_expenses_data():
    """טעינת נתוני הוצאות מ-Google Sheets"""
    service = get_sheets_service()
    if not service or not SHEET_ID:
        return pd.DataFrame()
    
    try:
        # קריאת נתונים מהגיליון
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='A:R'  # כל העמודות
        ).execute()
        
        values = result.get('values', [])
        if not values:
            return pd.DataFrame()
        
        # יצירת DataFrame
        headers = values[0] if values else EXPENSE_HEADERS
        data = values[1:] if len(values) > 1 else []
        
        df = pd.DataFrame(data, columns=headers)
        
        # נקה ותקן נתונים
        if 'amount' in df.columns:
            df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
        
        return df
        
    except Exception as e:
        st.error(f"❌ שגיאה בטעינת נתונים: {e}")
        return pd.DataFrame()

def load_links_data():
    """טעינת נתוני קישורים בין בני זוג"""
    service = get_sheets_service()
    if not service or not SHEET_ID:
        return pd.DataFrame()
    
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='links!A:D'
        ).execute()
        
        values = result.get('values', [])
        if len(values) < 2:
            return pd.DataFrame()
        
        df = pd.DataFrame(values[1:], columns=['phone_a', 'phone_b', 'group_id', 'created_at'])
        return df
        
    except Exception as e:
        return pd.DataFrame()

# ===============================
# פונקציות עזר
# ===============================
def normalize_phone_basic(phone: str) -> Optional[str]:
    """נרמול בסיסי של מספר טלפון"""
    if not phone:
        return None
    
    digits = re.sub(r"\D", "", phone)
    if PHONE_PATTERN.match(digits):
        return digits
    return None

def send_verification_code(phone: str, code: str) -> bool:
    """שליחת קוד אימות ב-WhatsApp"""
    if not GREEN_ID or not GREEN_TOKEN:
        return False
    
    try:
        clean_phone = "".join(filter(str.isdigit, phone))
        
        if clean_phone.startswith("0"):
            chat_id = "972" + clean_phone[1:] + "@c.us"
        elif clean_phone.startswith("972"):
            chat_id = clean_phone + "@c.us"
        else:
            chat_id = "972" + clean_phone + "@c.us"
        
        url = f"https://api.green-api.com/waInstance{GREEN_ID}/sendMessage/{GREEN_TOKEN}"
        
        payload = {
            "chatId": chat_id,
            "message": f"🔐 קוד האימות שלך למערכת ניהול הוצאות החתונה: {code}\n\nהקוד תקף ל-5 דקות."
        }
        
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
        
    except Exception as e:
        st.error(f"❌ שגיאה בשליחת הודעה: {e}")
        return False

def get_user_phones(user_phone: str, links_df: pd.DataFrame) -> list:
    """מחזיר רשימת טלפונים של המשתמש וביו זוגו"""
    phones = [user_phone]
    
    if links_df.empty:
        return phones
    
    # חפש קישורים
    for _, row in links_df.iterrows():
        if user_phone == row['phone_a']:
            phones.append(row['phone_b'])
        elif user_phone == row['phone_b']:
            phones.append(row['phone_a'])
    
    return list(set(phones))

def format_currency(amount, currency='ILS'):
    """עיצוב מטבע"""
    if pd.isna(amount) or amount == 0:
        return "0"
    
    symbol = {"ILS": "₪", "USD": "$", "EUR": "€"}.get(currency, "₪")
    return f"{amount:,.0f} {symbol}"

# ===============================
# רכיב אימות
# ===============================
def auth_flow():
    """זרימת אימות המשתמש"""
    if st.session_state.get("authenticated"):
        return True
    
    load_dashboard_css()
    
    # מיכל אימות מרכזי
    st.markdown("""
    <div class="auth-container">
        <div class="auth-header">
            <div class="auth-icon">💒</div>
            <h1 class="auth-title">מערכת ניהול הוצאות חתונה</h1>
            <p class="auth-subtitle">התחבר עם מספר הטלפון שלך</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    auth_state = st.session_state.get("auth_state", "phone")
    
    if auth_state == "phone":
        with st.container():
            phone = st.text_input(
                "מספר טלפון", 
                placeholder="05X-XXXXXXX",
                max_chars=10,
                key="phone_input"
            )
            
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                if st.button("📱 שלח קוד אימות", type="primary", use_container_width=True):
                    normalized_phone = normalize_phone_basic(phone)
                    if not normalized_phone:
                        st.error("❌ מספר טלפון לא תקין")
                    else:
                        code = "".join(secrets.choice("0123456789") for _ in range(4))
                        
                        st.session_state.update({
                            "auth_code": code,
                            "user_phone": normalized_phone,
                            "code_timestamp": time.time(),
                            "auth_state": "verify",
                            "auth_attempts": 0
                        })
                        
                        if send_verification_code(normalized_phone, code):
                            st.success("✅ קוד נשלח לווטסאפ!")
                            st.rerun()
                        else:
                            st.error("❌ שגיאה בשליחת הקוד - נסה שוב")
    
    elif auth_state == "verify":
        st.markdown("""
        <div class="auth-container">
            <div class="auth-header">
                <div class="auth-icon">🔐</div>
                <h1 class="auth-title">אימות קוד</h1>
                <p class="auth-subtitle">הזן את הקוד שנשלח אליך בווטסאפ</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        code_input = st.text_input(
            "קוד אימות", 
            placeholder="הכנס 4 ספרות",
            max_chars=4,
            key="code_input"
        )
        
        # בדיקת תפוגה
        elapsed = time.time() - st.session_state.get("code_timestamp", 0)
        if elapsed > CODE_TTL_SECONDS:
            st.warning("⏰ הקוד פג תוקף")
            if st.button("🔄 חזור להתחלה"):
                st.session_state.auth_state = "phone"
                st.rerun()
            return False
        
        remaining = CODE_TTL_SECONDS - elapsed
        st.info(f"⏱️ הקוד תקף עוד {int(remaining)} שניות")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("✅ אמת קוד", type="primary", use_container_width=True):
                if code_input == st.session_state.get("auth_code"):
                    st.session_state.authenticated = True
                    st.success("🎉 התחברת בהצלחה!")
                    time.sleep(1)
                    st.rerun()
                else:
                    attempts = st.session_state.get("auth_attempts", 0) + 1
                    st.session_state.auth_attempts = attempts
                    
                    if attempts >= MAX_AUTH_ATTEMPTS:
                        st.error("❌ חרגת ממספר הניסיונות המותר")
                        st.session_state.auth_state = "phone"
                        st.rerun()
                    else:
                        remaining_attempts = MAX_AUTH_ATTEMPTS - attempts
                        st.error(f"❌ קוד שגוי ({remaining_attempts} ניסיונות נותרו)")
        
        with col2:
            if st.button("↩️ חזור", use_container_width=True):
                st.session_state.auth_state = "phone"
                st.rerun()
    
    return False

# ===============================
# דשבורד ראשי
# ===============================
def main_dashboard():
    """הדשבורד הראשי"""
    load_dashboard_css()
    
    # כותרת ראשית
    st.markdown("""
    <div class="main-header">
        <h1>💒 ניהול הוצאות החתונה שלך</h1>
        <p>כל ההוצאות שלך במקום אחד - מאורגן וברור</p>
    </div>
    """, unsafe_allow_html=True)
    
    # טעינת נתונים
    with st.spinner("📊 טוען נתונים..."):
        expenses_df = load_expenses_data()
        links_df = load_links_data()
    
    if expenses_df.empty:
        st.info("📝 עדיין לא הועלו הוצאות. התחל לשלוח קבלות בווטסאפ!")
        return
    
    # סינון לפי משתמש וביו זוגו
    user_phone = st.session_state.get("user_phone")
    user_phones = get_user_phones(user_phone, links_df)
    
    # סינון הוצאות של המשתמש
    user_expenses = expenses_df[expenses_df['owner_phone'].isin(user_phones)].copy()
    
    if user_expenses.empty:
        st.info("📝 עדיין לא נמצאו הוצאות עבור המספר שלך. התחל לשלוח קבלות בווטסאפ!")
        return
    
    # סטטיסטיקות עליונות
    display_statistics(user_expenses)
    
    # גרפים
    display_charts(user_expenses)
    
    # טבלת הוצאות עם סינונים
    display_expenses_table(user_expenses)

def display_statistics(df):
    """הצגת סטטיסטיקות עליונות"""
    col1, col2, col3, col4 = st.columns(4)
    
    total_amount = df['amount'].sum()
    total_count = len(df)
    avg_amount = df['amount'].mean() if total_count > 0 else 0
    categories_count = df['category'].nunique()
    
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <p class="stat-value">{format_currency(total_amount)}</p>
            <p class="stat-label">💰 סך ההוצאות</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <p class="stat-value">{total_count}</p>
            <p class="stat-label">📄 מספר קבלות</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="stat-card">
            <p class="stat-value">{format_currency(avg_amount)}</p>
            <p class="stat-label">📊 ממוצע קבלה</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="stat-card">
            <p class="stat-value">{categories_count}</p>
            <p class="stat-label">🏷️ קטגוריות</p>
        </div>
        """, unsafe_allow_html=True)

def display_charts(df):
    """הצגת גרפים"""
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 הוצאות לפי קטגוריה")
        
        category_sum = df.groupby('category')['amount'].sum().reset_index()
        category_sum = category_sum.sort_values('amount', ascending=False)
        
        fig = px.pie(
            category_sum, 
            values='amount', 
            names='category',
            title="התפלגות הוצאות"
        )
        fig.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("📈 מגמת הוצאות לאורך זמן")
        
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            daily_expenses = df.groupby(df['date'].dt.date)['amount'].sum().reset_index()
            
            fig = px.line(
                daily_expenses, 
                x='date', 
                y='amount',
                title="הוצאות יומיות"
            )
            fig.update_xaxes(title="תאריך")
            fig.update_yaxes(title="סכום (₪)")
            st.plotly_chart(fig, use_container_width=True)

def display_expenses_table(df):
    """הצגת טבלת הוצאות עם סינונים"""
    st.subheader("📋 רשימת ההוצאות")
    
    # סינונים
    col1, col2, col3 = st.columns(3)
    
    with col1:
        selected_categories = st.multiselect(
            "סנן לפי קטגוריה",
            options=df['category'].unique(),
            default=df['category'].unique()
        )
    
    with col2:
        date_range = st.date_input(
            "טווח תאריכים",
            value=(df['date'].min(), df['date'].max()) if 'date' in df.columns else None,
            key="date_filter"
        )
    
    with col3:
        min_amount = st.number_input(
            "סכום מינימלי",
            min_value=0,
            value=0,
            step=50
        )
    
    # החלת סינונים
    filtered_df = df[df['category'].isin(selected_categories)]
    
    if 'date' in filtered_df.columns and date_range:
        if len(date_range) == 2:
            start_date, end_date = date_range
            filtered_df = filtered_df[
                (filtered_df['date'].dt.date >= start_date) & 
                (filtered_df['date'].dt.date <= end_date)
            ]
    
    filtered_df = filtered_df[filtered_df['amount'] >= min_amount]
    
    # הכנת טבלה לתצוגה
    display_columns = ['date', 'vendor', 'amount', 'currency', 'category', 'payment_method', 'drive_file_url']
    table_df = filtered_df[display_columns].copy()
    
    # עיצוב עמודות
    table_df['date'] = pd.to_datetime(table_df['date']).dt.strftime('%d/%m/%Y')
    table_df['amount'] = table_df.apply(lambda x: format_currency(x['amount'], x['currency']), axis=1)
    table_df['category'] = table_df['category'].apply(lambda x: f"{CATEGORY_EMOJIS.get(x, '📋')} {x}")
    table_df['drive_file_url'] = table_df['drive_file_url'].apply(
        lambda x: f'<a href="{x}" target="_blank">📄 צפה בקבלה</a>' if x else "לא זמין"
    )
    
    # שמות עמודות בעברית
    table_df.columns = ['תאריך', 'ספק', 'סכום', 'מטבע', 'קטגוריה', 'אמצעי תשלום', 'קישור לקבלה']
    
    # הצגת הטבלה
    st.markdown(
        table_df.to_html(escape=False, index=False), 
        unsafe_allow_html=True
    )
    
    # סיכום
    if not filtered_df.empty:
        total_filtered = filtered_df['amount'].sum()
        st.markdown(f"""
        <div class="stat-card">
            <p class="stat-value">{format_currency(total_filtered)}</p>
            <p class="stat-label">💰 סך ההוצאות המסוננות ({len(filtered_df)} פריטים)</p>
        </div>
        """, unsafe_allow_html=True)

# ===============================
# הפעלה ראשית
# ===============================
def main():
    """פונקציה ראשית"""
    # אתחול session state
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    # בדיקת אימות
    if not auth_flow():
        return
    
    # הצגת דשבורד
    main_dashboard()
    
    # כפתור יציאה
    with st.sidebar:
        st.markdown("---")
        if st.button("🚪 התנתק", use_container_width=True):
            st.session_state.clear()
            st.rerun()

if __name__ == "__main__":
    main()