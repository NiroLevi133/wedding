import os
import sys
from typing import Dict, List
from dotenv import load_dotenv

# טען משתני סביבה
load_dotenv()

# === API Keys & Tokens ===
GREENAPI_INSTANCE_ID = os.getenv("GREENAPI_INSTANCE_ID", "")
GREENAPI_TOKEN = os.getenv("GREENAPI_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
WEBHOOK_SHARED_SECRET = os.getenv("WEBHOOK_SHARED_SECRET", "")

# === Google Services ===
GSHEETS_SPREADSHEET_ID = os.getenv("GSHEETS_SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

# === הגדרות בסיסיות ===
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "ILS")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Jerusalem")

# טלפונים מורשים
ALLOWED_PHONES_STR = os.getenv("ALLOWED_PHONES", "")
ALLOWED_PHONES = set(phone.strip() for phone in ALLOWED_PHONES_STR.split(",") if phone.strip()) if ALLOWED_PHONES_STR else set()

# === הגדרות מערכת ===
PORT = int(os.getenv("PORT", "8080"))
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# === Google Sheets - טווחי עמודות ===
EXPENSES_SHEET = "expenses!A:L"  # טבלת הוצאות
COUPLES_SHEET = "couples!A:G"   # טבלת זוגות
VENDORS_SHEET = "vendors!A:F"   # טבלת ספקים

# === כותרות עמודות - הוצאות ===
EXPENSE_HEADERS = [
    "expense_id",
    "amount", 
    "vendor",
    "date",
    "category",
    "group_id",
    "payment_type",
    "related_expense_id", 
    "created_at",
    "needs_review",
    "status",
    "deleted_at"
    "last_updated"
]

# === כותרות עמודות - זוגות ===
COUPLES_HEADERS = [
    "phone1",
    "phone2", 
    "whatsapp_group_id",
    "budget",
    "wedding_date",
    "created_at",
    "status"
]

# === כותרות עמודות - ספקים ===
VENDORS_HEADERS = [
    "vendor_name",
    "category",
    "confidence", 
    "last_seen",
    "group_id_source",
    "created_at"
]

# === 10 קטגוריות קבועות ===
WEDDING_CATEGORIES = {
    "אולם": "🏛️",
    "מזון": "🍽️", 
    "צילום": "📸",
    "לבוש": "👗",
    "עיצוב": "🌸",
    "הדפסות": "📄",
    "אקססוריז": "💍",
    "מוזיקה": "🎵",
    "הסעות": "🚗",
    "אחר": "📋"
}

# רשימת קטגוריות בלבד
CATEGORY_LIST = list(WEDDING_CATEGORIES.keys())

# === מצבי תשלום ===
PAYMENT_TYPES = {
    "full": "תשלום מלא",
    "advance": "מקדמה", 
    "advance_1": "מקדמה ראשונה",
    "advance_2": "מקדמה שנייה",
    "advance_3": "מקדמה שלישית",
    "final": "תשלום סופי"
}

# === סטטוסים ===
EXPENSE_STATUSES = {
    "active": "פעיל",
    "deleted": "נמחק",
    "pending_review": "ממתין לבדיקה"
}

COUPLE_STATUSES = {
    "active": "פעיל",
    "inactive": "לא פעיל", 
    "completed": "חתונה הושלמה"
}

# === הגדרות AI ===
AI_SETTINGS = {
    "max_tokens": 500,
    "temperature": 0.1,
    "model": "gpt-4o-mini",
    "fallback_vendor_names": {
        "restaurant": "מסעדה לא מזוהה",
        "store": "חנות לא מזוהה", 
        "service": "ספק שירותים",
        "unknown": "ספק לא ידוע"
    }
}

# === הגדרות בוט ===
BOT_PHONE_NUMBER = os.getenv("BOT_PHONE_NUMBER", "+972507676706")

# === הגדרות WhatsApp ===
WHATSAPP_SETTINGS = {
    "api_timeout": 30,
    "max_retries": 3,
    "edit_window_minutes": 10  # זמן לעריכת הודעות
}

# === הגדרות דשבורד ===
DASHBOARD_SETTINGS = {
    "items_per_page": 20,
    "chart_colors": [
        "#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0",
        "#9966FF", "#FF9F40", "#FF6384", "#C9CBCF",
        "#4BC0C0", "#36A2EB"
    ]
}

# === הגדרות סיכום שבועי ===
WEEKLY_SUMMARY_SETTINGS = {
    "send_day": 0,  # יום ראשון
    "send_hour": 9,  # 9 בבוקר
    "enabled": True
}

# === בדיקת תקינות הגדרות ===
def validate_config() -> Dict[str, bool]:
    """בודק שכל ההגדרות הדרושות קיימות"""
    checks = {
        "green_api": bool(GREENAPI_INSTANCE_ID and GREENAPI_TOKEN),
        "openai": bool(OPENAI_API_KEY),
        "google_sheets": bool(GSHEETS_SPREADSHEET_ID and GOOGLE_CREDENTIALS_JSON),
        "webhook_secret": bool(WEBHOOK_SHARED_SECRET)
    }
    return checks

# === לוגים ===
LOGGING_CONFIG = {
    "level": "INFO" if not DEBUG else "DEBUG",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "handlers": ["console"]
}

# === הגדרות בטיחות ===
SAFETY_SETTINGS = {
    "max_file_size_mb": 10,
    "allowed_image_types": [".jpg", ".jpeg", ".png", ".webp"],
    "rate_limit_per_group": 50,  # מקסימום 50 קבלות ביום לקבוצה
    "max_edit_attempts": 5  # מקסימום 5 ניסיונות עריכה לקבלה
}

ADVANCE_PAYMENT_VENDORS = {
    'אולם': ['אולם', 'גן אירועים', 'מתחם', 'אולמי'],
    'צילום': ['צלם', 'צילום', 'וידאו', 'סטודיו'],
    'מוזיקה': ['דיג׳יי', 'להקה', 'זמר', 'DJ'],
    'מזון': ['קייטרינג', 'קייטרנר', 'שף']
}

# === בדיקת תקינות בטעינה ===
def validate_required_env_vars() -> bool:
    """בודק שמשתני הסביבה הקריטיים קיימים"""
    required = {
        "GREENAPI_INSTANCE_ID": GREENAPI_INSTANCE_ID,
        "GREENAPI_TOKEN": GREENAPI_TOKEN,
        "GSHEETS_SPREADSHEET_ID": GSHEETS_SPREADSHEET_ID,
        "GOOGLE_CREDENTIALS_JSON": GOOGLE_CREDENTIALS_JSON
    }
    
    missing = [name for name, value in required.items() if not value]
    
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        print("Please set these environment variables before starting the application.")
        return False
    
    print("✅ All required environment variables are set")
    return True

# הרצה בטעינה - בדיקה בסיסית בלבד, לא יוצא מהתוכנית
if __name__ == "__main__":
    # רק אם הקובץ נטען ישירות
    validate_required_env_vars()