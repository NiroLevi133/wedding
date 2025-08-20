import os, re, base64, json, hashlib, datetime as dt, random, logging
from typing import Optional, Dict, Any, Tuple, List

from fastapi import FastAPI, Request, HTTPException
import httpx
from dotenv import load_dotenv

# Google APIs
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

# OpenAI
from openai import OpenAI

load_dotenv()

# ✅ הגדר לוגים פשוטים
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

# === ENV ===
PORT = int(os.getenv("PORT", "8080"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GREEN_ID = os.getenv("GREENAPI_INSTANCE_ID", "")
GREEN_TOKEN = os.getenv("GREENAPI_TOKEN", "")
WEBHOOK_SHARED_SECRET = os.getenv("WEBHOOK_SHARED_SECRET", "")

SHEET_ID = os.getenv("GSHEETS_SPREADSHEET_ID")
DRIVE_ROOT = os.getenv("GDRIVE_ROOT_FOLDER_ID")
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "ILS")

# ✅ Google credentials - עכשיו ממשתני סביבה!
# Google Service Account credentials environment variables
GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
GOOGLE_PRIVATE_KEY_ID = os.getenv("GOOGLE_PRIVATE_KEY_ID")
GOOGLE_PRIVATE_KEY = os.getenv("GOOGLE_PRIVATE_KEY")
GOOGLE_CLIENT_EMAIL = os.getenv("GOOGLE_CLIENT_EMAIL")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

ALLOWED_PHONES = set(p.strip() for p in (os.getenv("ALLOWED_PHONES","").split(",") if os.getenv("ALLOWED_PHONES") else []))

# === Globals ===
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
creds = None
drive = None
sheets = None

oaiclient = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

pending_until: Dict[str, dt.datetime] = {}
last_expense_by_phone: Dict[str, dict] = {}
last_shown_field_by_phone: Dict[str, str] = {}

# לזוגות מחוברים
LINKS_TAB = "links!A:D"
links_cache: List[Tuple[str, str, str]] = []
pending_link_codes: Dict[str, Dict[str, str]] = {}

SHEET_HEADERS = [
    "expense_id", "owner_phone", "partner_group_id", "date", "amount", "currency",
    "vendor", "category", "payment_method", "invoice_number", "notes",
    "drive_file_url", "source", "status", "needs_review",
    "created_at", "updated_at", "approved_at"
]

# ✅ הודעת עזרה משופרת
HELP_MSG = """🤖 **מערכת ניהול הוצאות חתונה**

📋 **פקודות זמינות:**
• שלח תמונת קבלה → ניתוח אוטומטי ושמירה
• `חבר +972XXXXXXXXX` → חיבור לבן/בת זוג  
• `מאשר XXXXXX` → אישור חיבור
• `עזרה` → הודעה זו

💡 **טיפים:**
• תמונות ברורות נותנות תוצאות טובות יותר
• בדוק שהסכום והספק נכונים בגיליון
• שני בני הזוג יכולים לשלוח קבלות לאותה קבוצה

🔗 לגישה לגיליון - פנו למנהל המערכת"""

# ===== ✅ Utilities with improved error handling =====
def ensure_google():
    global creds, drive, sheets
    if drive is not None and sheets is not None:
        return
    
    try:
        # ✅ בניית credentials ממשתני סביבה
        if not all([GOOGLE_PROJECT_ID, GOOGLE_PRIVATE_KEY, GOOGLE_CLIENT_EMAIL]):
            raise RuntimeError("Missing required Google credentials environment variables")
        
        # ✅ תיקון הפרטי קי - החלפת \\n ב-\n אמיתיים
        private_key = GOOGLE_PRIVATE_KEY.replace('\\n', '\n')
        
        creds_info = {
            "type": "service_account",
            "project_id": GOOGLE_PROJECT_ID,
            "private_key_id": GOOGLE_PRIVATE_KEY_ID,
            "private_key": private_key,
            "client_email": GOOGLE_CLIENT_EMAIL,
            "client_id": GOOGLE_CLIENT_ID,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{GOOGLE_CLIENT_EMAIL.replace('@', '%40')}",
            "universe_domain": "googleapis.com"
        }
        
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=SCOPES
        )
        drive = build("drive", "v3", credentials=creds)
        sheets = build("sheets", "v4", credentials=creds)
        logger.info("Google services initialized successfully from environment variables")
    except Exception as e:
        logger.error(f"Failed to initialize Google services: {e}")
        raise

def chatid_to_e164(chat_id: str) -> str:
    if not chat_id:
        return ""
    num = chat_id.split("@")[0]
    return f"+{num}" if not num.startswith("+") else num

def e164_to_chatid(phone_e164: str) -> str:
    digits = phone_e164.replace("+", "").strip()
    return f"{digits}@c.us"

def normalize_phone(text: str) -> Optional[str]:
    text = text.strip()
    m = re.match(r"^\+?\d{9,15}$", text.replace(" ", ""))
    if not m:
        return None
    if not text.startswith("+"):
        text = "+" + text
    return text

def is_allowed(phone_e164: str) -> bool:
    return phone_e164 in ALLOWED_PHONES if ALLOWED_PHONES else True

def ez_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sha256_b64(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

# ✅ ולידציה של נתוני הוצאה
def validate_expense_data(data: dict) -> tuple[bool, str]:
    """בדיקה פשוטה של נתוני הוצאה"""
    if not data.get('amount') or not isinstance(data['amount'], (int, float)) or data['amount'] <= 0:
        return False, "❌ סכום לא תקין"
    
    if not data.get('vendor') or len(str(data['vendor']).strip()) < 2:
        return False, "❌ שם ספק לא תקין"
    
    valid_categories = [
        "אולם וקייטרינג","בר/אלכוהול","צילום","מוזיקה/דיג'יי",
        "בגדים/טבעות","עיצוב/פרחים","הדפסות/הזמנות/מדיה",
        "לינה/נסיעות/הסעות","אחר"
    ]
    if data.get('category') not in valid_categories:
        return False, f"❌ קטגוריה לא תקינה: {data.get('category')}"
    
    return True, "✅ תקין"

# ✅ שליחת הודעה עם טיפול בשגיאות
async def safe_greenapi_send_text(chat_id: str, text: str):
    """שליחת הודעה עם טיפול בשגיאות"""
    try:
        url = f"https://api.green-api.com/waInstance{GREEN_ID}/sendMessage/{GREEN_TOKEN}"
        payload = {"chatId": chat_id, "message": text}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            logger.info(f"Message sent successfully to {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")
        # אל תזרוק exception - רק תתעד
        pass

async def greenapi_download_media(payload: dict) -> Tuple[bytes, str]:
    message_data = payload.get("messageData", {})
    if "fileMessageData" in message_data:
        file_data = message_data["fileMessageData"]
        download_url = file_data.get("downloadUrl")
        file_name = file_data.get("fileName", "image.jpg")
        mime_type = file_data.get("mimeType", "image/jpeg")
    elif "imageMessage" in message_data:
        file_data = message_data["imageMessage"]
        download_url = file_data.get("downloadUrl")
        file_name = file_data.get("fileName", "image.jpg")
        mime_type = file_data.get("mimeType", "image/jpeg")
    else:
        raise HTTPException(status_code=400, detail="לא נמצא קישור להורדת הקובץ")
    
    if not download_url:
        raise HTTPException(status_code=400, detail="לא נמצא קישור להורדת הקובץ")
    
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(download_url)
            r.raise_for_status()
            blob = r.content
            ext = file_name.split(".")[-1].lower() if "." in file_name else ("jpg" if "jpeg" in mime_type else "png")
            logger.info(f"Media downloaded successfully: {len(blob)} bytes")
            return blob, ext
    except Exception as e:
        logger.error(f"Failed to download media: {e}")
        raise

def ensure_folder(folder_name: str, parent_folder_id: str) -> str:
    ensure_google()
    query = f"name='{folder_name}' and parents in '{parent_folder_id}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    file_metadata = {
        'name': folder_name,
        'parents': [parent_folder_id],
        'mimeType': 'application/vnd.google-apps.folder'
    }
    folder = drive.files().create(body=file_metadata, fields='id').execute()
    return folder.get('id')

# ✅ העלאה ל-Drive עם טיפול בשגיאות
def safe_upload_to_drive(blob: bytes, filename: str, folder_id: str) -> Tuple[str, str]:
    """העלאה ל-Drive עם טיפול בשגיאות"""
    try:
        ensure_google()
        if filename.lower().endswith(('.jpg', '.jpeg')):
            mimetype = 'image/jpeg'
        elif filename.lower().endswith('.png'):
            mimetype = 'image/png'
        elif filename.lower().endswith('.pdf'):
            mimetype = 'application/pdf'
        else:
            mimetype = 'application/octet-stream'
        
        media = MediaInMemoryUpload(blob, mimetype=mimetype)
        file_metadata = {'name': filename, 'parents': [folder_id]}
        file = drive.files().create(body=file_metadata, media_body=media, fields='id').execute()
        file_id = file.get('id')
        
        permission = {'type': 'anyone', 'role': 'reader'}
        drive.permissions().create(fileId=file_id, body=permission).execute()
        
        file_url = f"https://drive.google.com/file/d/{file_id}/view"
        logger.info(f"File uploaded successfully: {file_url}")
        return file_id, file_url
        
    except Exception as e:
        logger.error(f"Drive upload failed: {e}")
        # החזר ערכים ברירת מחדל במקום לזרוק exception
        return "", "העלאה נכשלה - הקבלה נשמרה בלי קובץ"

# ✅ שמירה בגיליון עם טיפול בשגיאות
def safe_sheets_append_row(row_values: list):
    """הוספת שורה לגיליון עם טיפול בשגיאות"""
    try:
        ensure_google()
        body = {'values': [row_values]}
        sheets.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range='A:A',
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        logger.info("Row added to spreadsheet successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to add row to spreadsheet: {e}")
        return False

def sheets_get_range(a1_range: str) -> List[List[str]]:
    ensure_google()
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=a1_range
    ).execute()
    return resp.get("values", [])

def sheets_append_links_row(phone_a: str, phone_b: str, group_id: str):
    ensure_google()
    body = {'values': [[phone_a, phone_b, group_id, ez_now_iso()]]}
    sheets.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=LINKS_TAB,
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body=body
    ).execute()

def load_links_cache():
    global links_cache
    try:
        rows = sheets_get_range(LINKS_TAB)
        new_cache = []
        for r in rows:
            if len(r) >= 3:
                a = normalize_phone(r[0]) or ""
                b = normalize_phone(r[1]) or ""
                gid = r[2]
                if a and b and gid:
                    new_cache.append((a, b, gid))
        links_cache = new_cache
        logger.info(f"Links cache loaded: {len(links_cache)} pairs")
    except Exception as e:
        logger.warning(f"Failed to load links cache: {e}")

def sorted_pair_gid(a: str, b: str) -> str:
    aa, bb = sorted([a, b])
    raw = f"{aa}|{bb}"
    return "grp_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

def find_group_for_phone(phone: str) -> Optional[str]:
    for a, b, gid in links_cache:
        if phone == a or phone == b:
            return gid
    load_links_cache()
    for a, b, gid in links_cache:
        if phone == a or phone == b:
            return gid
    return None

def add_link_pair(p1: str, p2: str) -> str:
    gid = sorted_pair_gid(p1, p2)
    for a, b, g in links_cache:
        if {a, b} == {p1, p2}:
            return g
    sheets_append_links_row(p1, p2, gid)
    links_cache.append((p1, p2, gid))
    return gid

# ✅ הודעת סיכום משופרת
def build_enhanced_summary_msg(data: dict, validation_status: str = "✅") -> str:
    vendor = data.get('vendor', 'לא זוהה')
    amount = data.get('amount', 'לא זוהה') 
    currency = data.get('currency', 'ILS')
    category = data.get('category', 'אחר')
    date = data.get('date', 'לא זוהה')
    
    # אמוג'י לפי קטגוריה
    category_emojis = {
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
    emoji = category_emojis.get(category, "📋")
    
    msg = f"""{validation_status} קבלה נשמרה!

🏪 ספק: {vendor}
💰 סכום: {amount} {currency}  
📅 תאריך: {date}
{emoji} קטגוריה: {category}"""

    payment_method = data.get('payment_method')
    if payment_method:
        payment_emoji = "💳" if payment_method == "card" else "💵" if payment_method == "cash" else "🏦"
        msg += f"\n{payment_emoji} תשלום: {payment_method}"
    
    invoice_number = data.get('invoice_number')
    if invoice_number:
        msg += f"\n📋 מספר חשבונית: {invoice_number}"

    # התראה אם יש בעיות
    issues = []
    if not data.get('amount'):
        issues.append("💰 סכום")
    if not data.get('vendor') or data.get('vendor') == 'לא זוהה':
        issues.append("🏪 ספק")
    if not data.get('date'):
        issues.append("📅 תאריך")
        
    if issues:
        msg += f"\n\n⚠️ יש לבדוק: {', '.join(issues)}"
        msg += "\n💡 כדאי לעדכן ידנית בגיליון"
    
    return msg

def preprocess_image_for_ocr(img_bytes: bytes) -> bytes:
    """
    שיפור איכות תמונה לOCR (דורש: pip install Pillow)
    """
    try:
        from PIL import Image, ImageEnhance
        import io
        
        img = Image.open(io.BytesIO(img_bytes))
        
        # המר ל-RGB
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # שיפור ניגודיות
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.3)
        
        # שיפור חדות
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(1.2)
        
        # שיפור בהירות
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.05)
        
        # צמצום גודל אם צריך
        max_size = 1500
        if max(img.width, img.height) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # שמירה כ-JPEG איכותי
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=90, optimize=True)
        return output.getvalue()
        
    except ImportError:
        logger.warning("PIL not installed, skipping image preprocessing")
        return img_bytes
    except Exception as e:
        logger.warning(f"Image preprocessing failed: {e}")
        return img_bytes

def fix_broken_json(content: str) -> str:
    """תיקון JSON פגום"""
    try:
        # תיקונים בסיסיים
        content = content.replace("'", '"')
        content = re.sub(r',\s*([}\]])', r'\1', content)  # הסר פסיקים לפני סגירה
        content = re.sub(r'([{,]\s*)(\w+):', r'\1"\2":', content)  # הוסף מרכאות למפתחות
        
        # ודא JSON object תקין
        content = content.strip()
        if not content.startswith('{'):
            content = '{' + content
        if not content.endswith('}'):
            content = content + '}'
            
        return content
    except Exception:
        return content

def normalize_date(date_str: str) -> Optional[str]:
    """המרת תאריך לפורמט ISO"""
    if not date_str or str(date_str).lower() in ['null', 'לא זוהה', 'unknown']:
        return None
        
    try:
        # נקה את המחרוזת
        date_str = str(date_str).strip()
        
        # פטרנים של תאריכים בישראל
        patterns = [
            (r'(\d{1,2})[/./-](\d{1,2})[/./-](\d{4})', 'DMY'),  # DD/MM/YYYY
            (r'(\d{4})[/./-](\d{1,2})[/./-](\d{1,2})', 'YMD'),  # YYYY/MM/DD  
            (r'(\d{1,2})[/./-](\d{1,2})[/./-](\d{2})', 'DMY2'), # DD/MM/YY
        ]
        
        for pattern, format_type in patterns:
            match = re.search(pattern, date_str)
            if match:
                groups = [int(g) for g in match.groups()]
                
                if format_type == 'DMY':
                    day, month, year = groups
                elif format_type == 'YMD':
                    year, month, day = groups
                elif format_type == 'DMY2':
                    day, month, year = groups
                    # המר שנה דו-ספרתית
                    year = 2000 + year if year < 50 else 1900 + year
                
                # ודא שהערכים הגיוניים
                if 1 <= day <= 31 and 1 <= month <= 12 and 2020 <= year <= 2030:
                    return f"{year:04d}-{month:02d}-{day:02d}"
        
        return None
    except Exception:
        return None

def clean_and_validate_data(data: dict) -> dict:
    """ניקוי ואימות נתונים חזרים מ-OpenAI"""
    
    # תיקון תאריך
    if data.get('date'):
        data['date'] = normalize_date(str(data['date']))
    
    # תיקון סכום
    if data.get('amount'):
        try:
            amount = data['amount']
            if isinstance(amount, str):
                # נקה מטקסט ופסיקים
                amount = re.sub(r'[^\d.,]', '', amount.replace(',', ''))
                amount = float(amount) if amount else None
            data['amount'] = float(amount) if amount and amount > 0 else None
        except (ValueError, TypeError):
            data['amount'] = None
    
    # תיקון מטבע
    if not data.get("currency") or data["currency"] not in ["ILS", "USD", "EUR"]:
        data["currency"] = DEFAULT_CURRENCY
    
    # תיקון קטגוריה
    valid_categories = [
        "אולם וקייטרינג","בר/אלכוהול","צילום","מוזיקה/דיג'יי",
        "בגדים/טבעות","עיצוב/פרחים","הדפסות/הזמנות/מדיה",
        "לינה/נסיעות/הסעות","אחר"
    ]
    if data.get("category") not in valid_categories:
        data["category"] = "אחר"
    
    # תיקון דרך תשלום
    payment = data.get('payment_method')
    if payment:
        payment = str(payment).lower().strip()
        if any(word in payment for word in ['אשראי', 'כרטיס', 'card', 'credit', 'ויזה', 'מאסטר']):
            data['payment_method'] = 'card'
        elif any(word in payment for word in ['מזומן', 'cash', 'כסף']):
            data['payment_method'] = 'cash'
        elif any(word in payment for word in ['העברה', 'בנק', 'bank', 'transfer', 'ביט']):
            data['payment_method'] = 'bank'
        else:
            data['payment_method'] = None
    
    # ניקוי ספק
    if data.get('vendor'):
        vendor = str(data['vendor']).strip()
        # הסר ביטויים לא רלוונטיים
        if len(vendor) < 2 or vendor.lower() in ['לא זוהה', 'unknown', 'n/a', 'null']:
            data['vendor'] = None
        else:
            # נקה ביטויים נפוצים מיותרים
            vendor = re.sub(r'(בע"מ|בעמ|ltd|inc).*$', '', vendor, flags=re.IGNORECASE).strip()
            data['vendor'] = vendor if len(vendor) >= 2 else None
    
    # ניקוי מספר חשבונית
    if data.get('invoice_number'):
        invoice = str(data['invoice_number']).strip()
        if len(invoice) < 2 or invoice.lower() in ['לא זוהה', 'unknown', 'n/a', 'null']:
            data['invoice_number'] = None
        else:
            data['invoice_number'] = invoice
    
    return data

# ✅ ניתוח קבלה עם טיפול בשגיאות
async def safe_analyze_receipt_with_openai(img_bytes: bytes) -> Dict[str, Any]:
    """
    גרסה משופרת לניתוח קבלות עם פרומפט מתקדם
    """
    if not oaiclient:
        return {
            "date": None, "amount": None, "currency": "ILS", "vendor": "OpenAI לא זמין",
            "category": "אחר", "payment_method": None, "invoice_number": None,
            "notes": "OpenAI API key not configured"
        }
    
    try:
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        
        # ✅ הפרומפט המשופר - הרבה יותר מדויק!
        system_prompt = """אתה מומחה בניתוח קבלות ותמונות חשבוניות לחתונות בישראל.

חוקי ניתוח קריטיים:
1. תאריך - בישראל התאריך הוא יום/חודש/שנה (DD/MM/YYYY)
2. סכום - חפש את הסכום הסופי בלבד! מילים כמו "סה״כ", "סך הכל", "לתשלום"
3. ספק - שם העסק הראשי בראש הקבלה
4. מטבע - ₪, שקל, NIS = ILS; $ = USD; € = EUR
5. תשלום - "אשראי", "ויזה" = card; "מזומן" = cash; "העברה", "ביט" = bank

קטגוריות לחתונה (בחר בדיוק אחת):
- "אולם וקייטרינג": אולמות, גנים, אירועים, קייטרינג, מזון
- "בר/אלכוהול": יין, בירה, אלכוהול, משקאות חריפים
- "צילום": צלמים, וידאו, קליפ, עריכה, אלבום
- "מוזיקה/דיג'יי": דיג'יי, DJ, מוזיקה, להקה, זמר/ת
- "בגדים/טבעות": שמלת כלה, חליפת חתן, טבעות, תכשיטים
- "עיצוב/פרחים": פרחים, זרים, עיצוב, דקורציה, קישוטים
- "הדפסות/הזמנות/מדיה": הזמנות, הדפסות, תפריטים, שלטים
- "לינה/נסיעות/הסעות": מלונות, צימרים, נסיעות, הסעות
- "אחר": כל דבר אחר

דוגמאות:
- "אולמי דיאמונד" → "אולם וקייטרינג"
- "יקב ברקן" → "בר/אלכוהול"
- "צלם רון" → "צילום"
- "סופר פארם" → "אחר"

JSON נדרש:
{
  "date": "YYYY-MM-DD" או null,
  "amount": מספר או null,
  "currency": "ILS" או "USD" או "EUR",
  "vendor": "שם ספק" או null,
  "category": קטגוריה מהרשימה,
  "payment_method": "card" או "cash" או "bank" או null,
  "invoice_number": "מספר" או null,
  "notes": "הערות" או null
}

חשוב: אם לא בטוח - תן null. אל תמציא מידע. החזר רק JSON!"""

        user_prompt = """נתח את תמונת הקבלה בעיון:
1. איפה התאריך?
2. איפה הסכום הסופי? (חפש "סה״כ", "לתשלום")
3. מה שם העסק?
4. איזה סוג עסק?
5. איך שילמו?

החזר רק JSON, בלי טקסט נוסף!"""

        # ✅ קריאה משופרת ל-OpenAI
        resp = oaiclient.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
            temperature=0.05,  # ✅ מאוד נמוך = יותר מדויק
            max_tokens=400,
        )
        
        content = resp.choices[0].message.content.strip()
        
        # ✅ ניקוי התשובה
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
        content = content.strip()
        
        # ✅ ניסיון לפענח JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed, trying to fix: {e}")
            # תיקון בסיסי
            content = content.replace("'", '"')
            content = re.sub(r',\s*}', '}', content)
            try:
                data = json.loads(content)
            except:
                logger.error(f"Could not parse: {content[:200]}")
                raise ValueError("JSON parsing failed")
        
        # ✅ ניקוי ואימות נתונים
        data = clean_receipt_data(data)
        # ✅ צור expense_id פשוט לצרכי המעקב
        expense_id = f"EXP_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
        data = await smart_bilingual_categorization(data, expense_id)

        logger.info(f"Receipt analyzed: vendor={data.get('vendor')}, amount={data.get('amount')}")
        return data
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return {
            "date": None, "amount": None, "currency": "ILS", 
            "vendor": "ניתוח נכשל", "category": "אחר",
            "payment_method": None, "invoice_number": None,
            "notes": f"error: {str(e)}"
        }

def clean_receipt_data(data: dict) -> dict:
    """ניקוי ואימות הנתונים"""
    
    # תיקון תאריך ישראלי
    if data.get('date'):
        date_str = str(data['date']).strip()
        # DD/MM/YYYY -> YYYY-MM-DD
        match = re.search(r'(\d{1,2})[/./-](\d{1,2})[/./-](\d{4})', date_str)
        if match:
            day, month, year = map(int, match.groups())
            if 1 <= day <= 31 and 1 <= month <= 12 and 2020 <= year <= 2030:
                data['date'] = f"{year:04d}-{month:02d}-{day:02d}"
            else:
                data['date'] = None
        else:
            data['date'] = None
    
    # תיקון סכום
    if data.get('amount'):
        try:
            amount = str(data['amount']).replace(',', '').replace('₪', '').strip()
            amount = re.sub(r'[^\d.]', '', amount)
            data['amount'] = float(amount) if amount and float(amount) > 0 else None
        except:
            data['amount'] = None
    
    # תיקון מטבע
    if not data.get("currency") or data["currency"] not in ["ILS", "USD", "EUR"]:
        data["currency"] = "ILS"
    
    # תיקון קטגוריה
    valid_categories = [
        "אולם וקייטרינג","בר/אלכוהול","צילום","מוזיקה/דיג'יי",
        "בגדים/טבעות","עיצוב/פרחים","הדפסות/הזמנות/מדיה",
        "לינה/נסיעות/הסעות","אחר"
    ]
    if data.get("category") not in valid_categories:
        data["category"] = "אחר"
    
    # תיקון דרך תשלום
    payment = data.get('payment_method')
    if payment:
        payment = str(payment).lower()
        if any(word in payment for word in ['אשראי', 'card', 'ויזה', 'מאסטר']):
            data['payment_method'] = 'card'
        elif any(word in payment for word in ['מזומן', 'cash']):
            data['payment_method'] = 'cash'
        elif any(word in payment for word in ['העברה', 'bank', 'ביט']):
            data['payment_method'] = 'bank'
        else:
            data['payment_method'] = None
    
    # ניקוי ספק
    if data.get('vendor'):
        vendor = str(data['vendor']).strip()
        if len(vendor) < 2 or vendor.lower() in ['לא זוהה', 'unknown']:
            data['vendor'] = None
        else:
            data['vendor'] = vendor
    
    return data

# ===== FastAPI endpoints =====
@app.get("/")
def home():
    return {"status": "ok", "message": "מערכת ניהול הוצאות חתונה פעילה! 💒✨"}

@app.get("/health")
async def enhanced_health_check():
    """בדיקת תקינות משופרת"""
    checks = {
        "status": "healthy",
        "timestamp": dt.datetime.now().isoformat(),
        "services": {}
    }
    
    # בדוק Google Services
    try:
        ensure_google()
        # בדיקה פשוטה - קריאה לגיליון
        sheets.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
        checks["services"]["google_sheets"] = "healthy"
    except Exception as e:
        checks["services"]["google_sheets"] = f"unhealthy: {str(e)[:100]}"
        checks["status"] = "degraded"
    
    # בדוק OpenAI
    try:
        if oaiclient:
            checks["services"]["openai"] = "configured"
        else:
            checks["services"]["openai"] = "not_configured"
    except Exception as e:
        checks["services"]["openai"] = f"error: {str(e)[:50]}"
    
    # בדוק Green API
    try:
        if GREEN_ID and GREEN_TOKEN:
            checks["services"]["green_api"] = "configured"
        else:
            checks["services"]["green_api"] = "not_configured"
    except Exception as e:
        checks["services"]["green_api"] = f"error: {str(e)[:50]}"
    
    return checks

@app.get("/debug")
def debug():
    return {
        "google_credentials_env": bool(GOOGLE_PROJECT_ID and GOOGLE_PRIVATE_KEY and GOOGLE_CLIENT_EMAIL),
        "openai_configured": bool(OPENAI_API_KEY),
        "greenapi_configured": bool(GREEN_ID and GREEN_TOKEN),
        "sheets_id": SHEET_ID[:10] + "..." if SHEET_ID else "NOT_SET",
        "drive_root": DRIVE_ROOT[:10] + "..." if DRIVE_ROOT else "NOT_SET",
        "allowed_phones_count": len(ALLOWED_PHONES),
        "links_cache_size": len(links_cache)
    }

@app.post("/webhook")
async def webhook(request: Request):
    logger.info("Webhook received")
    
    try:
        if WEBHOOK_SHARED_SECRET:
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if not auth or (not auth.endswith(WEBHOOK_SHARED_SECRET) and auth != f"Bearer {WEBHOOK_SHARED_SECRET}"):
                logger.warning("Unauthorized webhook attempt")
                raise HTTPException(status_code=401, detail="Unauthorized")

        payload = await request.json()
        logger.info(f"Processing webhook payload for message type: {payload.get('messageData', {}).get('typeMessage')}")

        ensure_google()
        if not links_cache:
            load_links_cache()

        type_msg = payload.get("messageData", {}).get("typeMessage")
        chat_id = payload.get("senderData", {}).get("chatId")
        id_message = payload.get("idMessage")

        if not chat_id:
            logger.warning("No chat_id in webhook")
            return {"status": "ignored", "reason": "no_chat_id"}

        phone_e164 = chatid_to_e164(chat_id)
        if not is_allowed(phone_e164):
            logger.warning(f"Phone not allowed: {phone_e164}")
            return {"status": "ignored_not_allowed", "phone": phone_e164}

        phone = phone_e164
        logger.info(f"Processing message from {phone}")

        # === TEXT HANDLING ===
        if type_msg == "textMessage":
            text = payload.get("messageData", {}).get("textMessageData", {}).get("textMessage", "").strip()
            if not text:
                return {"status": "ok"}

            # 1) Help
            if text.lower() in ["עזרה", "help"]:
                await safe_greenapi_send_text(chat_id, HELP_MSG)
                return {"status": "help_sent"}

            # 2) Start link flow
            m = re.match(r"^(?:חבר|חיבור)\s+(\+?\d{9,15})$", text)
            if m:
                target = normalize_phone(m.group(1))
                if not target:
                    await safe_greenapi_send_text(chat_id, "❌ מספר לא תקין. דוגמה: חבר +972501234567")
                    return {"status": "invalid_phone"}

                if target == phone:
                    await safe_greenapi_send_text(chat_id, "🤷‍♂️ אי אפשר לחבר את עצמך לעצמך 😉")
                    return {"status": "same_phone"}

                existing_gid = find_group_for_phone(phone)
                if existing_gid and find_group_for_phone(target) == existing_gid:
                    await safe_greenapi_send_text(chat_id, f"✅ כבר מחוברים! group_id: {existing_gid}")
                    return {"status": "already_linked", "group_id": existing_gid}

                code = f"{random.randint(100000, 999999)}"
                pending_link_codes[code] = {"initiator": phone, "target": target, "created_at": ez_now_iso()}
                
                target_chat = e164_to_chatid(target)
                try:
                    await safe_greenapi_send_text(
                        target_chat,
                        f"🔗 בקשה לחיבור חשבונות מאת {phone}\n"
                        f"אם זה בסדר מבחינתך, ענו כאן: 'מאשר {code}'"
                    )
                    await safe_greenapi_send_text(
                        chat_id,
                        f"📨 שלחתי אימות ל{target}.\n"
                        f"כשהוא/היא יענו: 'מאשר {code}' – נחבר אתכם."
                    )
                    return {"status": "link_code_sent", "code": code, "target": target}
                except Exception as e:
                    logger.error(f"Failed to send message to target {target}: {e}")
                    await safe_greenapi_send_text(chat_id, f"❌ לא הצלחתי לשלוח הודעה ליעד. ודא שהמספר {target} זמין בווטסאפ.")
                    return {"status": "target_send_failed"}

            # 3) Confirm link
            m2 = re.match(r"^(?:מאשר|מאשרת)\s+(\d{6})$", text)
            if m2:
                code = m2.group(1)
                rec = pending_link_codes.get(code)
                if not rec:
                    await safe_greenapi_send_text(chat_id, "❌ קוד לא נמצא או שפג תוקפו.")
                    return {"status": "code_not_found"}
                
                initiator = rec["initiator"]
                target = rec["target"]
                if phone != target:
                    await safe_greenapi_send_text(chat_id, "❌ הקוד הזה לא משויך למספר שלך.")
                    return {"status": "wrong_phone_for_code"}

                gid = add_link_pair(initiator, target)
                pending_link_codes.pop(code, None)

                await safe_greenapi_send_text(e164_to_chatid(initiator), f"✅ מעולה! חיברנו אותך עם {target}\nGroup: {gid}")
                await safe_greenapi_send_text(e164_to_chatid(target), f"✅ חיבור הושלם עם {initiator}\nGroup: {gid}")
                return {"status": "linked", "group_id": gid, "a": initiator, "b": target}

            # טקסט רגיל
            await safe_greenapi_send_text(chat_id, 
                f"קיבלתי את ההודעה: '{text}' 📝\n"
                f"שלח תמונת קבלה לניתוח!\n"
                f"או: חבר +9725XXXXXXXX לחיבור יוזרים.\n"
                f"כתוב 'עזרה' לפרטים נוספים."
            )
            return {"status": "text_received"}

        # === IMAGE HANDLING ===
        elif type_msg == "imageMessage":
            try:
                logger.info("Processing image message")
                blob, ext = await greenapi_download_media(payload)
                
                # ✅ ניתוח עם טיפול בשגיאות
                ai = await safe_analyze_receipt_with_openai(blob)
                
                # ✅ ולידציה
                is_valid, validation_msg = validate_expense_data(ai)
                if not is_valid:
                    await safe_greenapi_send_text(chat_id, validation_msg + "\n🔄 נסה לשלוח קבלה אחרת או בדוק שהתמונה ברורה")
                    return {"status": "validation_failed", "message": validation_msg}
                
                file_hash = sha256_b64(blob)
                expense_id = hashlib.md5((file_hash + phone).encode()).hexdigest()
                now_iso = ez_now_iso()

                gid = find_group_for_phone(phone) or ""

                # ✅ העלאה ל-Drive עם טיפול בשגיאות
                drive_url = ""
                try:
                    today = dt.datetime.now()
                    phone_folder = ensure_folder(phone, DRIVE_ROOT)
                    safe_vendor = re.sub(r'[^\w\u0590-\u05FF]+', '_', str(ai.get('vendor') or 'vendor'))
                    filename = f"{today.strftime('%Y%m%d')}_{(ai.get('amount') or 'unknown')}_{safe_vendor}_{file_hash[:8]}.{ext}"
                    file_id, drive_url = safe_upload_to_drive(blob, filename, phone_folder)
                    logger.info(f"File uploaded successfully to Drive: {drive_url}")
                except Exception as drive_error:
                    logger.error(f"Drive upload failed: {drive_error}")
                    drive_url = "העלאה נכשלה"
                    # נסה לקבל URL מה-payload כגיבוי
                    try:
                        message_data = payload.get("messageData", {})
                        if "fileMessageData" in message_data:
                            backup_url = message_data["fileMessageData"].get("downloadUrl", "")
                            if backup_url:
                                drive_url = backup_url
                        elif "imageMessage" in message_data:
                            backup_url = message_data["imageMessage"].get("downloadUrl", "")
                            if backup_url:
                                drive_url = backup_url
                    except:
                        pass

                row_map = {
                    "expense_id": expense_id,
                    "owner_phone": phone,
                    "partner_group_id": gid,
                    "date": ai.get("date") or "",
                    "amount": ai.get("amount") or "",
                    "currency": ai.get("currency") or DEFAULT_CURRENCY,
                    "vendor": ai.get("vendor") or "",
                    "category": ai.get("category") or "אחר",
                    "payment_method": ai.get("payment_method") or "",
                    "invoice_number": ai.get("invoice_number") or "",
                    "notes": ai.get("notes") or "",
                    "drive_file_url": drive_url,
                    "source": "whatsapp",
                    "status": "received",
                    "needs_review": "לא" if ai.get("amount") and ai.get("vendor") else "כן",
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "approved_at": "",
                }

                # ✅ שמירה בגיליון עם טיפול בשגיאות
                row_values = [row_map.get(h, "") for h in SHEET_HEADERS]
                sheet_saved = safe_sheets_append_row(row_values)
                
                if not sheet_saved:
                    # אם השמירה נכשלה, עדיין שלח הודעה למשתמש עם התראה
                    await safe_greenapi_send_text(chat_id, 
                        "⚠️ הקבלה נותחה אך יש בעיה בשמירה לגיליון.\n"
                        "נתונים שזוהו:\n"
                        f"🏪 ספק: {ai.get('vendor', 'לא זוהה')}\n"
                        f"💰 סכום: {ai.get('amount', 'לא זוהה')} {ai.get('currency', 'ILS')}\n"
                        "💡 נסה שוב מאוחר יותר או צור קשר עם התמיכה."
                    )
                    return {"status": "analysis_success_sheet_failed", "analysis": ai}

                # ✅ הודעת סיכום משופרת
                msg = build_enhanced_summary_msg(ai, "✅")
                if gid:
                    msg += f"\n👥 קבוצה: {gid}"
                
                # הוסף מידע על הצלחת/כישלון העלאה
                if "העלאה נכשלה" in drive_url:
                    msg += f"\n⚠️ הקובץ לא הועלה ל-Drive (הנתונים נשמרו)"
                
                await safe_greenapi_send_text(chat_id, msg)
                logger.info(f"Receipt processed successfully: {expense_id}")

                return {
                    "status": "receipt_saved", 
                    "expense_id": expense_id, 
                    "analysis": ai, 
                    "group_id": gid,
                    "drive_uploaded": "העלאה נכשלה" not in drive_url,
                    "sheet_saved": sheet_saved
                }
                
            except Exception as e:
                logger.error(f"Error processing image: {str(e)}", exc_info=True)
                await safe_greenapi_send_text(chat_id, 
                    f"❌ שגיאה בעיבוד התמונה.\n"
                    f"💡 נסה שוב עם תמונה ברורה יותר או צור קשר עם התמיכה."
                )
                return {"status": "image_processing_failed", "error": str(e)}
        
        else:
            logger.info(f"Unsupported message type: {type_msg}")
            return {"status": "ignored", "message_type": type_msg, "reason": "unsupported_type"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}", exc_info=True)
        try:
            if 'chat_id' in locals():
                await safe_greenapi_send_text(chat_id, 
                    "❌ אירעה שגיאה במערכת.\n"
                    "💡 נסה שוב מאוחר יותר או צור קשר עם התמיכה."
                )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

VENDORS_BILINGUAL_TAB = "vendors_bilingual!A:F"  # A: hebrew_name, B: english_name, C: category, D: source_receipt_id, E: created_at, F: confidence

# cache פשוט
bilingual_vendors = {}  # key: normalized_name, value: vendor_info

def normalize_vendor_simple(name: str) -> str:
    """נרמול פשוט של שם ספק"""
    if not name:
        return ""
    # הורד אותיות, הסר רווחים מיותרים, הסר תווים מיוחדים
    normalized = name.strip().lower()
    normalized = normalized.replace('"', '').replace("'", '').replace('.', '').replace(',', '')
    normalized = normalized.replace('בע"מ', '').replace('בעמ', '').replace('ltd', '').replace('inc', '')
    return ' '.join(normalized.split())  # הסר רווחים כפולים

def load_bilingual_vendors():
    """טוען ספקים דו-לשוניים מהגיליון"""
    global bilingual_vendors
    
    try:
        ensure_google()
        rows = sheets_get_range(VENDORS_BILINGUAL_TAB)
        
        bilingual_vendors = {}
        for i, row in enumerate(rows):
            if i == 0:  # דלג על כותרת
                continue
            if len(row) >= 3:
                hebrew_name = row[0].strip() if len(row) > 0 else ""
                english_name = row[1].strip() if len(row) > 1 else ""
                category = row[2].strip() if len(row) > 2 else "אחר"
                source_receipt_id = row[3] if len(row) > 3 else ""
                created_at = row[4] if len(row) > 4 else ""
                confidence = int(row[5]) if len(row) > 5 and str(row[5]).isdigit() else 85
                
                # צור מפתח מנורמל
                main_name = hebrew_name or english_name
                if main_name:
                    normalized_key = normalize_vendor_simple(main_name)
                    bilingual_vendors[normalized_key] = {
                        'hebrew_name': hebrew_name,
                        'english_name': english_name,
                        'category': category,
                        'source_receipt_id': source_receipt_id,
                        'created_at': created_at,
                        'confidence': confidence
                    }
        
        logger.info(f"Loaded {len(bilingual_vendors)} bilingual vendors")
        
    except Exception as e:
        logger.warning(f"Could not load bilingual vendors: {e}")
        # אם הטאב לא קיים, צור אותו
        create_bilingual_vendors_tab()

def create_bilingual_vendors_tab():
    """יוצר טאב חדש לספקים דו-לשוניים"""
    try:
        ensure_google()
        headers = ["hebrew_name", "english_name", "category", "source_receipt_id", "created_at", "confidence"]
        body = {'values': [headers]}
        sheets.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range="vendors_bilingual!A1:F1",
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        logger.info("Created bilingual vendors tab")
    except Exception as e:
        logger.error(f"Failed to create bilingual vendors tab: {e}")

def lookup_bilingual_vendor_simple(vendor_name: str) -> dict:
    """חיפוש פשוט של ספק בבסיס הנתונים הדו-לשוני"""
    if not vendor_name:
        return None
    
    # טען אם עדיין לא נטען
    if not bilingual_vendors:
        load_bilingual_vendors()
    
    # נרמל את השם לחיפוש
    normalized_input = normalize_vendor_simple(vendor_name)
    
    # חיפוש מדויק
    if normalized_input in bilingual_vendors:
        return bilingual_vendors[normalized_input]
    
    # חיפוש חלקי
    for normalized_key, vendor_data in bilingual_vendors.items():
        if (normalized_input in normalized_key or 
            normalized_key in normalized_input):
            return vendor_data
    
    return None

async def analyze_new_vendor_bilingual(vendor_name: str, expense_id: str) -> dict:
    """ניתוח ספק חדש עם AI דו-לשוני"""
    if not oaiclient:
        return None
    
    try:
        prompt = f"""אתה מומחה בזיהוי עסקים ישראליים וגלובליים.

שם העסק: "{vendor_name}"

תן לי:
1. השם בעברית
2. השם באנגלית  
3. הקטגוריה לחתונה

קטגוריות: אולם וקייטרינג, בר/אלכוהול, צילום, מוזיקה/דיג'יי, בגדים/טבעות, עיצוב/פרחים, הדפסות/הזמנות/מדיה, לינה/נסיעות/הסעות, אחר

דוגמאות:
- "קרולינה למקה" → Hebrew: "קרולינה למקה", English: "Carolina Lemke", Category: "בגדים/טבעות"
- "יקב ברקן" → Hebrew: "יקב ברקן", English: "Barkan Winery", Category: "בר/אלכוהול"

החזר JSON בלבד:
{{
  "hebrew_name": "השם בעברית",
  "english_name": "השם באנגלית", 
  "category": "קטגוריה",
  "confidence": מספר בין 70-95
}}"""

        resp = oaiclient.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200
        )
        
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
        
        try:
            result = json.loads(content)
            result['source_receipt_id'] = expense_id
            return result
        except:
            logger.error(f"Failed to parse AI response: {content}")
            return None
            
    except Exception as e:
        logger.error(f"AI analysis failed: {e}")
        return None

def save_new_bilingual_vendor(vendor_data: dict) -> bool:
    """שומר ספק דו-לשוני חדש"""
    try:
        ensure_google()
        
        now_iso = ez_now_iso()
        row_data = [
            vendor_data.get('hebrew_name', ''),
            vendor_data.get('english_name', ''),
            vendor_data.get('category', 'אחר'),
            vendor_data.get('source_receipt_id', ''),
            now_iso,
            vendor_data.get('confidence', 85)
        ]
        
        body = {'values': [row_data]}
        sheets.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=VENDORS_BILINGUAL_TAB,
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        # עדכן cache
        main_name = vendor_data.get('hebrew_name') or vendor_data.get('english_name')
        if main_name:
            normalized_key = normalize_vendor_simple(main_name)
            bilingual_vendors[normalized_key] = vendor_data
        
        logger.info(f"Saved new bilingual vendor: {vendor_data.get('hebrew_name')} / {vendor_data.get('english_name')}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save bilingual vendor: {e}")
        return False

async def smart_bilingual_categorization(receipt_data: dict, expense_id: str) -> dict:
    """הפונקציה הראשית לקטגוריזציה דו-לשונית"""
    vendor = receipt_data.get('vendor')
    original_category = receipt_data.get('category', 'אחר')
    
    if not vendor or len(vendor) < 3:
        return receipt_data
    
    # שלב 1: חפש בבסיס הנתונים
    existing_vendor = lookup_bilingual_vendor_simple(vendor)
    
    if existing_vendor:
        # נמצא!
        receipt_data['category'] = existing_vendor['category']
        
        hebrew_name = existing_vendor.get('hebrew_name', '')
        english_name = existing_vendor.get('english_name', '')
        
        notes = receipt_data.get('notes', '') or ''
        match_note = f"זוהה: {hebrew_name}"
        if english_name and english_name != hebrew_name:
            match_note += f" / {english_name}"
        
        receipt_data['notes'] = f"{notes}\n{match_note}".strip()
        
        logger.info(f"Found existing vendor: {vendor} → {existing_vendor['category']}")
        return receipt_data
    
    # שלב 2: לא נמצא - נתח עם AI
    if original_category == 'אחר':
        logger.info(f"Analyzing new vendor: {vendor}")
        
        ai_result = await analyze_new_vendor_bilingual(vendor, expense_id)
        
        if ai_result and ai_result.get('confidence', 0) > 70:
            # שמור בבסיס הנתונים
            save_success = save_new_bilingual_vendor(ai_result)
            
            # עדכן קבלה
            receipt_data['category'] = ai_result['category']
            
            hebrew_name = ai_result.get('hebrew_name', '')
            english_name = ai_result.get('english_name', '')
            
            notes = receipt_data.get('notes', '') or ''
            new_note = f"ספק חדש: {hebrew_name}"
            if english_name and english_name != hebrew_name:
                new_note += f" / {english_name}"
            
            receipt_data['notes'] = f"{notes}\n{new_note}".strip()
            
            logger.info(f"Added new vendor: {vendor} → {ai_result['category']}")
    
    return receipt_data


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)