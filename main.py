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

# Load env vars
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

# Google credentials path - עכשיו הקובץ קיים!
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./gcp_credentials.json")

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
    return {"status": "ok", "message": "מערכת ניהול הוצאות חתונה פעילה! 💒✨"}

@app.get("/health")
def health():
    return {"ok": True, "service": "wedding-expenses", "timestamp": dt.datetime.now().isoformat()}

@app.get("/debug")
def debug():
    return {
        "credentials_file_exists": os.path.exists(GOOGLE_CREDENTIALS_PATH),
        "credentials_path": GOOGLE_CREDENTIALS_PATH,
        "openai_configured": bool(OPENAI_API_KEY),
        "greenapi_configured": bool(GREEN_ID and GREEN_TOKEN),
        "sheets_id": SHEET_ID[:10] + "..." if SHEET_ID else "NOT_SET",
        "drive_root": DRIVE_ROOT[:10] + "..." if DRIVE_ROOT else "NOT_SET"
    }

# === Init Google APIs ===
def ensure_google():
    global creds, drive, sheets
    if drive is not None and sheets is not None:
        return
    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        raise RuntimeError(f"Google credentials file not found at {GOOGLE_CREDENTIALS_PATH}")
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_PATH, scopes=SCOPES
    )
    drive = build("drive", "v3", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)

# === Utilities ===
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

# === Google Drive/Sheets helpers ===
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

def upload_to_drive(blob: bytes, filename: str, folder_id: str) -> Tuple[str, str]:
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
    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }
    
    file = drive.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = file.get('id')
    
    permission = {
        'type': 'anyone',
        'role': 'reader'
    }
    drive.permissions().create(fileId=file_id, body=permission).execute()
    
    file_url = f"https://drive.google.com/file/d/{file_id}/view"
    return file_id, file_url

def sheets_append_row(row_values: list):
    ensure_google()
    body = {'values': [row_values]}
    sheets.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range='A:A',
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body=body
    ).execute()

def build_summary_msg(data: dict) -> str:
    vendor = data.get('vendor', 'לא זוהה')
    amount = data.get('amount', 'לא זוהה')
    currency = data.get('currency', 'ILS')
    category = data.get('category', 'אחר')
    date = data.get('date', 'לא זוהה')
    
    msg = f"""✅ קבלה נשמרה!

🏪 ספק: {vendor}
💰 סכום: {amount} {currency}
📅 תאריך: {date}
🏷️ קטגוריה: {category}

📝 לעריכה: שלח הודעה עם הערך החדש"""
    
    return msg

# === OpenAI Vision ===
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

# === Webhook ===
@app.post("/webhook")
async def webhook(request: Request):
    try:
        if WEBHOOK_SHARED_SECRET:
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if not auth or (not auth.endswith(WEBHOOK_SHARED_SECRET) and auth != f"Bearer {WEBHOOK_SHARED_SECRET}"):
                raise HTTPException(status_code=401, detail="Unauthorized")

        payload = await request.json()
        ensure_google()

        type_msg = payload.get("messageData", {}).get("typeMessage")
        chat_id = payload.get("senderData", {}).get("chatId")
        id_message = payload.get("idMessage")

        if not chat_id:
            return {"status": "ignored", "reason": "no_chat_id"}

        phone_e164 = chatid_to_e164(chat_id)
        if not is_allowed(phone_e164):
            return {"status": "ignored_not_allowed", "phone": phone_e164}

        phone = phone_e164

        # --- עריכות (טקסט) ---
        if type_msg == "textMessage":
            text = payload.get("messageData", {}).get("textMessageData", {}).get("textMessage", "")
            text = text.strip()
            if not text:
                return {"status": "ok"}

            if text.lower() in ["עזרה", "help"]:
                help_msg = """🔹 איך להשתמש במערכת:
📸 שלח תמונת קבלה - המערכת תנתח אותה אוטומטית

🔹 קטגוריות זמינות:
אולם וקייטרינג, בר/אלכוהול, צילום, מוזיקה/דיג'יי, בגדים/טבעות, עיצוב/פרחים, הדפסות/הזמנות/מדיה, לינה/נסיעות/הסעות, אחר"""
                
                await greenapi_send_text(chat_id, help_msg)
                return {"status": "help_sent"}

            return {"status": "text_ignored"}

        # --- קבלה (תמונה) ---
        if type_msg == "imageMessage":
            try:
                await greenapi_send_text(chat_id, "📷 מעבד את התמונה... אנא המתן")
                
                blob, ext = await greenapi_download_media(id_message)
                file_hash = sha256_b64(blob)

                # ניתוח עם OpenAI
                ai = await analyze_receipt_with_openai(blob)

                # יצירת מבנה תיקיות ב-Drive
                today = dt.datetime.now()
                y = str(today.year)
                m = f"{today.month:02d}"
                
                folder_phone = ensure_folder(phone, DRIVE_ROOT)
                folder_year = ensure_folder(y, folder_phone)
                folder_month = ensure_folder(m, folder_year)

                # העלאה ל-Drive
                safe_vendor = re.sub(r'[^\w\u0590-\u05FF]+', '_', str(ai.get('vendor') or 'vendor'))
                fname = f"{today.strftime('%Y%m%d')}_{(ai.get('amount') or 'xxx')}_{safe_vendor}_{file_hash[:8]}.{ext}"
                
                file_id, file_url = upload_to_drive(blob, fname, folder_month)

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
                row_values = [row_map.get(h, "") for h in SHEET_HEADERS]
                sheets_append_row(row_values)

                # סיכום למשתמש
                msg = build_summary_msg(row_map)
                await greenapi_send_text(chat_id, msg)

                return {"status": "receipt_saved", "expense_id": expense_id, "file_url": file_url}

        return {"status": "ignored", "message_type": type_msg}
        
    except Exception as e:
        print(f"Error in webhook: {str(e)}")
        import traceback
        traceback.print_exc()
        
        try:
            if 'chat_id' in locals():
                await greenapi_send_text(chat_id, "❌ אירעה שגיאה במערכת. נסה שוב.")
        except:
            pass
            
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)