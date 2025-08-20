import os, re, base64, json, hashlib, datetime as dt
from typing import Optional, Dict, Any, Tuple

from fastapi import FastAPI, Request, HTTPException
import httpx
from dotenv import load_dotenv
    
# Google APIs
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

# OpenAI
from openai import OpenAI

# Load env vars (useful locally, Cloud Run uses real ENV instead)
load_dotenv()

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
DEFAULT_TZ = os.getenv("DEFAULT_TIMEZONE", "Asia/Jerusalem")

# Service account path with fallback options
def get_google_credentials():
    """Get Google credentials from various possible sources"""
    print("🔍 Looking for Google credentials...")
    
    # בדיקה מהירה לEnvironment Variable (הכי פשוט)
    print("🔑 Checking environment variable 'secret'...")
    creds_content = os.getenv("secret")
    if creds_content:
        print(f"✅ Found credentials in environment variable (length: {len(creds_content)})")
        
        import tempfile
        try:
            # כתוב לקובץ זמני
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                # ניסיון חכם לזהות את הפורמט
                content = creds_content.strip()
                if content.startswith('{') and content.endswith('}'):
                    # זה כבר JSON
                    f.write(content)
                else:
                    # אולי זה base64
                    try:
                        import base64
                        decoded = base64.b64decode(content).decode('utf-8')
                        f.write(decoded)
                    except:
                        # אם לא, פשוט נכתוב כמו שזה
                        f.write(content)
                
                temp_path = f.name
                print(f"✅ Created temp credentials file at {temp_path}")
                
                # וודא שהקובץ תקין
                with open(temp_path, 'r') as check_f:
                    test_content = check_f.read(100)
                    print(f"📄 File content preview: {test_content[:50]}...")
                
                return temp_path
                
        except Exception as e:
            print(f"❌ Error creating temp file: {e}")
    else:
        print("   ❌ Environment variable 'secret' not set")
    
    # רק אם Environment Variable לא עובד, תחפש קבצים
    print("📁 Fallback: Checking file paths...")
    
    possible_paths = [
        "/secrets/gcp-credentials",
        "/secrets/gcp_credentials.json", 
        "./gcp_credentials.json",
        "/app/gcp_credentials.json"
    ]
    
    for path in possible_paths:
        if os.path.exists(path) and os.path.isfile(path):
            print(f"✅ Found credentials file at {path}")
            return path
    
    print("❌ No credentials found anywhere!")
    return Noned locations:")
    print("  - /secrets/gcp_credentials.json")
    print("  - Environment variable 'secret'")
    print("  - ./gcp_credentials.json")
    print("  - /app/gcp_credentials.json")
    print(f"  - GOOGLE_APPLICATION_CREDENTIALS: {os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'NOT_SET')}")
    
    return None

# אל תקרא לפונקציה בזמן הטעינה - זה יגרום לקריסה אם אין credentials
# GOOGLE_CREDENTIALS_PATH = get_google_credentials()

# במקום זה, פשוט הגדר None ותן לפונקציה ensure_google לטפל בזה
GOOGLE_CREDENTIALS_PATH = None

ALLOWED_PHONES = set(p.strip() for p in (os.getenv("ALLOWED_PHONES","").split(",") if os.getenv("ALLOWED_PHONES") else []))

# === Globals for Google clients ===
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
creds = None
drive = None
sheets = None

# === OpenAI client ===
oaiclient = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# === Session management ===
pending_until = {}
last_expense_by_phone = {}
last_shown_field_by_phone = {}

# Define sheet headers
SHEET_HEADERS = [
    "expense_id", "owner_phone", "partner_group_id", "date", "amount", "currency",
    "vendor", "category", "payment_method", "invoice_number", "notes",
    "drive_file_url", "source", "status", "needs_review", 
    "created_at", "updated_at", "approved_at"
]

@app.get("/")
def home():
    return {"status": "ok", "message": "מערכת ניהול הוצאות חתונה פעילה! 💒✨", "startup": "success"}

@app.get("/health")
def health():
    """Health check endpoint for Cloud Run"""
    return {"ok": True, "service": "wedding-expenses", "timestamp": ez_now_iso()}

# === Init Google APIs (lazy) ===
def ensure_google():
    """Initialize Google Drive/Sheets once, when first needed."""
    global creds, drive, sheets
    if drive is not None and sheets is not None:
        return
        
    print("🔍 Getting Google credentials...")
    try:
        credentials_path = get_google_credentials()
        if not credentials_path:
            raise RuntimeError("Google credentials not found in any location!")
            
        if not os.path.exists(credentials_path):
            raise RuntimeError(f"Google credentials file not found at {credentials_path}")
            
        print(f"🔑 Using credentials from: {credentials_path}")
        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        drive = build("drive", "v3", credentials=creds)
        sheets = build("sheets", "v4", credentials=creds)
        print("✅ Google APIs initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize Google APIs: {e}")
        raise

# ========== Utilities ==========
def chatid_to_e164(chat_id: str) -> str:
    if not chat_id:
        return ""
    num = chat_id.split("@")[0]
    return f"+{num}" if not num.startswith("+") else num

def is_allowed(phone_e164: str) -> bool:
    return phone_e164 in ALLOWED_PHONES if ALLOWED_PHONES else True

def ez_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sha256_b64(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

async def greenapi_download_media(id_message: str) -> Tuple[bytes, str]:
    url = f"https://api.green-api.com/waInstance{GREEN_ID}/downloadFile/{GREEN_TOKEN}"
    params = {"idMessage": id_message}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        payload = r.json()
        b64 = payload.get("file")
        mime = payload.get("mimeType", "image/jpeg")
        name = payload.get("fileName", "receipt.jpg")
        if not b64:
            raise HTTPException(status_code=400, detail="Failed to download file from GreenAPI")
        blob = base64.b64decode(b64)
        ext = name.split(".")[-1].lower() if "." in name else ("jpg" if "jpeg" in mime else "png")
        return blob, ext

async def greenapi_send_text(chat_id: str, text: str):
    url = f"https://api.green-api.com/waInstance{GREEN_ID}/sendMessage/{GREEN_TOKEN}"
    payload = {"chatId": chat_id, "message": text}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()

# ========== Google Drive/Sheets helpers ==========
def ensure_folder(folder_name: str, parent_folder_id: str) -> str:
    """Create folder in Google Drive if it doesn't exist, return folder ID"""
    ensure_google()
    
    # חפש תיקיה קיימת
    query = f"name='{folder_name}' and parents in '{parent_folder_id}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    
    if files:
        return files[0]['id']
    
    # צור תיקיה חדשה
    file_metadata = {
        'name': folder_name,
        'parents': [parent_folder_id],
        'mimeType': 'application/vnd.google-apps.folder'
    }
    folder = drive.files().create(body=file_metadata, fields='id').execute()
    return folder.get('id')

def upload_to_drive(blob: bytes, filename: str, folder_id: str) -> Tuple[str, str]:
    """Upload file to Google Drive, return (file_id, file_url)"""
    ensure_google()
    
    # זהה את סוג הקובץ
    if filename.lower().endswith(('.jpg', '.jpeg')):
        mimetype = 'image/jpeg'
    elif filename.lower().endswith('.png'):
        mimetype = 'image/png'
    elif filename.lower().endswith('.pdf'):
        mimetype = 'application/pdf'
    else:
        mimetype = 'application/octet-stream'
    
    media = MediaInMemoryUpload(blob, mimetype=mimetype)
    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }
    
    file = drive.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = file.get('id')
    
    # הפוך הקובץ לציבורי לקריאה
    permission = {
        'type': 'anyone',
        'role': 'reader'
    }
    drive.permissions().create(fileId=file_id, body=permission).execute()
    
    file_url = f"https://drive.google.com/file/d/{file_id}/view"
    return file_id, file_url

def sheets_append_row(row_values: list):
    """Append row to Google Sheets"""
    ensure_google()
    
    body = {
        'values': [row_values]
    }
    
    result = sheets.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range='A:A',
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body=body
    ).execute()
    
    return result

def sheets_find_row_by_expense(expense_id: str) -> Optional[int]:
    """Find row number by expense ID"""
    ensure_google()
    
    # קרא את כל הנתונים מהגיליון
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range='A:A'
    ).execute()
    
    values = result.get('values', [])
    
    # חפש את השורה עם expense_id
    for i, row in enumerate(values):
        if row and len(row) > 0 and row[0] == expense_id:
            return i + 1  # גוגל שיטס מתחיל מ-1
    
    return None

def sheets_update_row(row_num: int, updates: dict):
    """Update specific row in sheets"""
    ensure_google()
    
    # קרא את השורה הנוכחית
    current_result = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f'A{row_num}:{chr(65 + len(SHEET_HEADERS) - 1)}{row_num}'
    ).execute()
    
    current_values = current_result.get('values', [[]])[0]
    
    # הרחב את הרשימה אם היא קצרה מדי
    while len(current_values) < len(SHEET_HEADERS):
        current_values.append('')
    
    # עדכן את הערכים
    for field, value in updates.items():
        if field in SHEET_HEADERS:
            index = SHEET_HEADERS.index(field)
            current_values[index] = str(value)
    
    # כתוב חזרה לגיליון
    body = {
        'values': [current_values]
    }
    
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f'A{row_num}:{chr(65 + len(SHEET_HEADERS) - 1)}{row_num}',
        valueInputOption='USER_ENTERED',
        body=body
    ).execute()

def create_initial_sheet_headers():
    """Create initial headers in the Google Sheet if needed"""
    ensure_google()
    
    try:
        # בדוק אם כבר יש headers
        result = sheets.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='A1:Z1'
        ).execute()
        
        values = result.get('values', [])
        if values and len(values[0]) >= len(SHEET_HEADERS):
            return  # Headers כבר קיימים
        
        # צור headers
        hebrew_headers = [
            "מזהה הוצאה", "טלפון", "קבוצת שותפים", "תאריך", "סכום", "מטבע",
            "ספק", "קטגוריה", "אמצעי תשלום", "מספר חשבונית", "הערות",
            "קישור לקובץ", "מקור", "סטטוס", "דרוש בדיקה",
            "נוצר בתאריך", "עודכן בתאריך", "אושר בתאריך"
        ]
        
        body = {
            'values': [hebrew_headers]
        }
        
        sheets.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range='A1:R1',
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
    except Exception as e:
        print(f"Error creating headers: {e}")

# ========== User interaction helpers ==========
def parse_user_edit(text: str, field: str) -> Optional[dict]:
    """Parse user edit text and return updates dict"""
    text = text.strip()
    if not text:
        return None
    
    # אם המשתמש שלח מספר בלבד, זה כנראה סכום
    if re.match(r'^\d+(\.\d{1,2})?$', text):
        return {"amount": float(text)}
    
    # אם המשתמש שלח אחת מהקטגוריות
    categories = [
        "אולם וקייטרינג", "בר/אלכוהול", "צילום", "מוזיקה/דיג'יי",
        "בגדים/טבעות", "עיצוב/פרחים", "הדפסות/הזמנות/מדיה", 
        "לינה/נסיעות/הסעות", "אחר"
    ]
    
    for cat in categories:
        if cat in text:
            return {"category": cat}
    
    # אם המשתמש שלח תאריך (פורמט פשוט)
    date_match = re.search(r'(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})', text)
    if date_match:
        day, month, year = date_match.groups()
        if len(year) == 2:
            year = "20" + year
        try:
            dt.datetime(int(year), int(month), int(day))
            return {"date": f"{year}-{month.zfill(2)}-{day.zfill(2)}"}
        except:
            pass
    
    # אחרת, נתייחס לזה כשם ספק
    if len(text) > 1 and not text.isdigit():
        return {"vendor": text}
    
    return None

def build_summary_msg(data: dict) -> str:
    """Build summary message for user"""
    vendor = data.get('vendor', 'לא זוהה')
    amount = data.get('amount', 'לא זוהה')
    currency = data.get('currency', 'ILS')
    category = data.get('category', 'אחר')
    date = data.get('date', 'לא זוהה')
    payment_method = data.get('payment_method', '')
    
    msg = f"""✅ קבלה נשמרה!

🏪 ספק: {vendor}
💰 סכום: {amount} {currency}
📅 תאריך: {date}
🏷️ קטגוריה: {category}"""
    
    if payment_method:
        payment_emoji = "💳" if payment_method == "card" else "💵" if payment_method == "cash" else "🏦"
        msg += f"\n{payment_emoji} תשלום: {payment_method}"
    
    msg += "\n\n📝 לעריכה: שלח הודעה עם הערך החדש"
    msg += "\n⏰ חלון עריכה: 10 דקות"
    
    return msg

# ========== OpenAI Vision ==========
async def analyze_receipt_with_openai(img_bytes: bytes) -> Dict[str, Any]:
    if not oaiclient:
        return {
            "date": None, "amount": None, "currency": "ILS", "vendor": "OpenAI לא זמין", 
            "category": "אחר", "payment_method": None, "invoice_number": None, 
            "notes": "OpenAI API key not configured"
        }
    
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    system_prompt = (
        "אתה ממיר תמונת קבלה ל-JSON אחיד. החזר אך ורק JSON חוקי ללא טקסט נוסף, במבנה הבא:\n"
        "{ \"date\": \"YYYY-MM-DD\" | null, \"amount\": number | null, "
        "\"currency\": \"ILS\" | \"USD\" | \"EUR\" | null, "
        "\"vendor\": string | null, "
        "\"category\": one of [\"אולם וקייטרינג\",\"בר/אלכוהול\",\"צילום\",\"מוזיקה/דיג'יי\","
        "\"בגדים/טבעות\",\"עיצוב/פרחים\",\"הדפסות/הזמנות/מדיה\",\"לינה/נסיעות/הסעות\",\"אחר\"], "
        "\"payment_method\": \"card\" | \"cash\" | \"bank\" | null, "
        "\"invoice_number\": string | null, \"notes\": string | null }"
    )
    user_prompt = "נתח את התמונה והחזר JSON בלבד לפי הסכמה. אין להוסיף הסברים."
    
    try:
        resp = oaiclient.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
            temperature=0
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
        data = json.loads(content)
    except Exception as e:
        data = {
            "date": None, "amount": None, "currency": "ILS", "vendor": "שגיאת ניתוח", 
            "category": "אחר", "payment_method": None, "invoice_number": None, 
            "notes": f"parse_error: {str(e)}"
        }
    
    if not data.get("currency"):
        data["currency"] = DEFAULT_CURRENCY
    if data.get("category") not in [
        "אולם וקייטרינג","בר/אלכוהול","צילום","מוזיקה/דיג'יי",
        "בגדים/טבעות","עיצוב/פרחים","הדפסות/הזמנות/מדיה","לינה/נסיעות/הסעות","אחר"
    ]:
        data["category"] = "אחר"
    return data

# ========== Webhook ==========
@app.post("/webhook")
async def webhook(request: Request):
    print("🔥 WEBHOOK CALLED!")
    print(f"⏰ Time: {dt.datetime.now()}")
    
    try:
        # בדיקת אימות
        if WEBHOOK_SHARED_SECRET:
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if not auth or (not auth.endswith(WEBHOOK_SHARED_SECRET) and auth != f"Bearer {WEBHOOK_SHARED_SECRET}"):
                raise HTTPException(status_code=401, detail="Unauthorized")

        payload = await request.json()
        print(f"📦 Payload received: {json.dumps(payload, indent=2, ensure_ascii=False)}")
        
        ensure_google()
        print("✅ Google APIs initialized successfully")

        # וודא שיש headers בגיליון
        create_initial_sheet_headers()

        type_msg = payload.get("messageData", {}).get("typeMessage")
        chat_id = payload.get("senderData", {}).get("chatId")
        id_message = payload.get("idMessage")

        if not chat_id:
            return {"status": "ignored", "reason": "no_chat_id"}

        phone_e164 = chatid_to_e164(chat_id)
        if not is_allowed(phone_e164):
            return {"status": "ignored_not_allowed", "phone": phone_e164}

        phone = phone_e164

        # ניקוי session שפג תוקפו
        now = dt.datetime.now()
        if phone in pending_until and now > pending_until[phone]:
            pending_until.pop(phone, None)
            last_expense_by_phone.pop(phone, None)
            last_shown_field_by_phone.pop(phone, None)

        # --- עריכות (טקסט) ---
        if type_msg == "textMessage":
            text = payload.get("messageData", {}).get("textMessageData", {}).get("textMessage", "")
            text = text.strip()
            if not text:
                return {"status": "ok"}

            # בדוק אם זה פקודת מערכת
            if text.lower() in ["סטטוס", "status", "עזרה", "help"]:
                help_msg = """🔹 איך להשתמש במערכת:
📸 שלח תמונת קבלה - המערכת תנתח אותה אוטומטית
✏️ לעריכה - שלח טקסט חדש תוך 10 דקות

🔹 דוגמאות לעריכה:
• "500" - לשינוי סכום
• "סופר פארם" - לשינוי ספק
• "צילום" - לשינוי קטגוריה
• "15/12/2024" - לשינוי תאריך

🔹 קטגוריות זמינות:
אולם וקייטרינג, בר/אלכוהול, צילום, מוזיקה/דיג'יי, בגדים/טבעות, עיצוב/פרחים, הדפסות/הזמנות/מדיה, לינה/נסיעות/הסעות, אחר"""
                
                await greenapi_send_text(chat_id, help_msg)
                return {"status": "help_sent"}

            exp_id = last_expense_by_phone.get(phone)
            if exp_id:
                upd = parse_user_edit(text, last_shown_field_by_phone.get(phone))
                if upd:
                    row = sheets_find_row_by_expense(exp_id)
                    if row:
                        upd["updated_at"] = ez_now_iso()
                        sheets_update_row(row, upd)

                        msg = "עודכן ✅\n" + build_summary_msg({
                            "vendor": upd.get("vendor"),
                            "date": upd.get("date"),
                            "amount": upd.get("amount"),
                            "category": upd.get("category"),
                            "payment_method": upd.get("payment_method"),
                        })
                        await greenapi_send_text(chat_id, msg)

                        pending_until[phone] = now + dt.timedelta(minutes=10)
                        for k in ["category", "vendor"]:
                            if k in upd:
                                last_shown_field_by_phone[phone] = k
                                break
                        return {"status": "updated"}
                    else:
                        await greenapi_send_text(chat_id, "❌ שגיאה: לא נמצא הרשומה לעדכון.")
                        return {"status": "missing_row"}
                else:
                    await greenapi_send_text(chat_id, "❓ לא הבנתי את העריכה. נסה שוב או שלח 'עזרה' להוראות.")
                    return {"status": "edit_not_understood"}

            return {"status": "text_ignored"}

        # --- קבלה (תמונה) ---
        if type_msg == "imageMessage":
            try:
                await greenapi_send_text(chat_id, "📷 מעבד את התמונה... אנא המתן")
                
                blob, ext = await greenapi_download_media(id_message)
            except Exception as e:
                await greenapi_send_text(chat_id, f"❌ שגיאה בהורדת התמונה: {str(e)}")
                raise HTTPException(status_code=400, detail=f"Download failed: {e}")

            file_hash = sha256_b64(blob)

            # ניתוח עם OpenAI
            ai = await analyze_receipt_with_openai(blob)

            # יצירת מבנה תיקיות ב-Drive
            today = dt.datetime.now()
            y = str(today.year)
            m = f"{today.month:02d}"
            
            try:
                folder_phone = ensure_folder(phone, DRIVE_ROOT)
                folder_year = ensure_folder(y, folder_phone)
                folder_month = ensure_folder(m, folder_year)
            except Exception as e:
                await greenapi_send_text(chat_id, f"❌ שגיאה ביצירת תיקיות: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Folder creation failed: {e}")

            # העלאה ל-Drive
            safe_vendor = re.sub(r'[^\w\u0590-\u05FF]+', '_', str(ai.get('vendor') or 'vendor'))
            fname = f"{today.strftime('%Y%m%d')}_{(ai.get('amount') or 'xxx')}_{safe_vendor}_{file_hash[:8]}.{ext}"
            
            try:
                file_id, file_url = upload_to_drive(blob, fname, folder_month)
            except Exception as e:
                await greenapi_send_text(chat_id, f"❌ שגיאה בהעלאת הקובץ: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

            # יצירת רשומה חדשה
            expense_id = hashlib.md5((file_hash + phone).encode()).hexdigest()
            now_iso = ez_now_iso()
            row_map = {
                "expense_id": expense_id,
                "owner_phone": phone,
                "partner_group_id": "",
                "date": ai.get("date") or "",
                "amount": ai.get("amount") or "",
                "currency": ai.get("currency") or DEFAULT_CURRENCY,
                "vendor": ai.get("vendor") or "",
                "category": ai.get("category") or "אחר",
                "payment_method": ai.get("payment_method") or "",
                "invoice_number": ai.get("invoice_number") or "",
                "notes": ai.get("notes") or "",
                "drive_file_url": file_url,
                "source": "whatsapp",
                "status": "received",
                "needs_review": "",
                "created_at": now_iso,
                "updated_at": now_iso,
                "approved_at": "",
            }

            # שמירה בגיליון
            try:
                row_values = [row_map.get(h, "") for h in SHEET_HEADERS]
                sheets_append_row(row_values)
            except Exception as e:
                await greenapi_send_text(chat_id, f"❌ שגיאה בשמירה בגיליון: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Sheets save failed: {e}")

            # הגדרת חלון עריכה
            last_expense_by_phone[phone] = expense_id
            last_shown_field_by_phone[phone] = "category"
            pending_until[phone] = dt.datetime.now() + dt.timedelta(minutes=10)

            # שליחת סיכום למשתמש
            msg = build_summary_msg(row_map)
            await greenapi_send_text(chat_id, msg)

            return {"status": "receipt_saved", "expense_id": expense_id, "file_url": file_url}

        # סוגי הודעות אחרים
        return {"status": "ignored", "message_type": type_msg}
        
    except Exception as e:
        # לוג את השגיאה
        print(f"💥 ERROR in webhook: {str(e)}")
        print(f"📄 Error type: {type(e).__name__}")
        import traceback
        print(f"🔍 Full traceback:")
        traceback.print_exc()
        
        # נסה לשלוח הודעת שגיאה למשתמש
        try:
            if 'chat_id' in locals():
                await greenapi_send_text(chat_id, "❌ אירעה שגיאה במערכת. צוות הטכני יטפל בבעיה.")
        except:
            pass  # אל תתקע על שגיאה בשליחת הודעת השגיאה
            
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# ========== Additional endpoints ==========
@app.get("/stats/{phone}")
async def get_phone_stats(phone: str):
    """Get expense statistics for a phone number"""
    try:
        ensure_google()
        
        # נקה את מספר הטלפון
        phone = phone if phone.startswith('+') else f'+{phone}'
        
        # קרא את כל הנתונים
        result = sheets.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='A:R'
        ).execute()
        
        values = result.get('values', [])
        if len(values) < 2:
            return {"total_expenses": 0, "total_amount": 0, "categories": {}}
        
        # פילטר לפי טלפון
        phone_expenses = []
        for row in values[1:]:  # דלג על headers
            if len(row) > 1 and row[1] == phone:
                phone_expenses.append(row)
        
        # חשב סטטיסטיקות
        total_expenses = len(phone_expenses)
        total_amount = 0
        categories = {}
        
        for row in phone_expenses:
            if len(row) > 4:
                try:
                    amount = float(row[4]) if row[4] else 0
                    total_amount += amount
                except:
                    pass
            
            if len(row) > 7:
                category = row[7] or 'אחר'
                categories[category] = categories.get(category, 0) + 1
        
        return {
            "phone": phone,
            "total_expenses": total_expenses,
            "total_amount": total_amount,
            "categories": categories,
            "currency": DEFAULT_CURRENCY
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stats error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)