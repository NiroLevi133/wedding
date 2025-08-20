import os, re, base64, json, hashlib, datetime as dt
from typing import Optional, Dict, Any, Tuple

from fastapi import FastAPI, Request, HTTPException
import httpx
from pydantic import BaseModel
from dotenv import load_dotenv

# Google APIs
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

# OpenAI
from openai import OpenAI

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

GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/gcp_credentials.json")


ALLOWED_PHONES = set(p.strip() for p in (os.getenv("ALLOWED_PHONES","").split(",") if os.getenv("ALLOWED_PHONES") else []))

def chatid_to_e164(chat_id: str) -> str:
    """
    GreenAPI שולח chatId כמו '972501234567@c.us'.
    נהפוך ל-E.164 עם + בתחילת המספר: '+972501234567'
    """
    if not chat_id:
        return ""
    num = chat_id.split("@")[0]
    if not num.startswith("+"):
        num = f"+{num}"
    return num

def is_allowed(phone_e164: str) -> bool:
    # אם הרשימה ריקה – ברירת מחדל לחסום הכל (או לשנות שיתיר הכל)
    if not ALLOWED_PHONES:
        return False
    return phone_e164 in ALLOWED_PHONES


# === OpenAI client ===
oaiclient = OpenAI(api_key=OPENAI_API_KEY)

# === Google clients (service account) ===
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
creds = service_account.Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
drive = build("drive", "v3", credentials=creds)
sheets = build("sheets", "v4", credentials=creds)

# === Simple in-memory state ===
last_expense_by_phone: Dict[str, str] = {}  # chatId -> expense_id (awaiting edits window)
last_shown_field_by_phone: Dict[str, str] = {}  # which field was last displayed (for "זה לא X זה Y")
pending_until: Dict[str, dt.datetime] = {}  # chatId -> deadline time

# === Constants ===
CATEGORIES = [
    "אולם וקייטרינג", "בר/אלכוהול", "צילום", "מוזיקה/דיג'יי",
    "בגדים/טבעות", "עיצוב/פרחים", "הדפסות/הזמנות/מדיה",
    "לינה/נסיעות/הסעות", "אחר"
]

SHEET_HEADERS = [
    "expense_id", "owner_phone", "partner_group_id", "date", "amount", "currency",
    "vendor", "category", "payment_method", "invoice_number", "notes",
    "drive_file_url", "source", "status", "needs_review",
    "created_at", "updated_at", "approved_at"
]

# ========== Utilities ==========

def ez_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()

def normalize_phone_from_chatid(chat_id: str) -> str:
    # chat_id looks like "9725XXXXXXXX@c.us"
    return chat_id.split("@")[0] if chat_id else ""

def sha256_b64(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

async def greenapi_download_media(id_message: str) -> Tuple[bytes, str]:
    """
    Download binary media from GreenAPI by idMessage.
    Returns (bytes, ext)
    """
    url = f"https://api.green-api.com/waInstance{GREEN_ID}/downloadFile/{GREEN_TOKEN}"
    params = {"idMessage": id_message}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        payload = r.json()
        # payload typically has "file", "mimeType", "fileName"
        b64 = payload.get("file")
        mime = payload.get("mimeType", "image/jpeg")
        name = payload.get("fileName", "receipt.jpg")
        if not b64:
            raise HTTPException(status_code=400, detail="Failed to download file from GreenAPI")
        blob = base64.b64decode(b64)
        # ext from mime or fileName
        ext = name.split(".")[-1].lower() if "." in name else ("jpg" if "jpeg" in mime or "jpg" in mime else "png")
        return blob, ext

def ensure_folder(name: str, parent_id: str) -> str:
    # Try find folder by name under parent; else create
    q = f"mimeType='application/vnd.google-apps.folder' and name='{name}' and '{parent_id}' in parents and trashed=false"
    res = drive.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    file_metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    created = drive.files().create(body=file_metadata, fields="id").execute()
    return created["id"]

def upload_to_drive(blob: bytes, fname: str, parent_id: str) -> Tuple[str, str]:
    media = MediaInMemoryUpload(blob, mimetype="image/jpeg", resumable=False)
    file_metadata = {"name": fname, "parents": [parent_id]}
    file = drive.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
    return file["id"], file["webViewLink"]

def sheets_append_row(values: list):
    body = {"values": [values]}
    sheets.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range="A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body
    ).execute()

def sheets_find_row_by_expense(expense_id: str) -> Optional[int]:
    # Read a reasonable range; for MVP we can read all
    res = sheets.spreadsheets().values().get(spreadsheetId=SHEET_ID, range="A:Q").execute()
    rows = res.get("values", [])
    # Find header index first row
    if not rows:
        return None
    for idx, row in enumerate(rows, start=1):  # 1-based
        if row and row[0] == expense_id:
            return idx
    return None

def sheets_update_row(row_index: int, row_values: Dict[str, Any]):
    # Build full row per headers
    existing = [""] * len(SHEET_HEADERS)
    # fetch current row to preserve fields not provided
    res = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"A{row_index}:Q{row_index}"
    ).execute()
    current = res.get("values", [[]])[0] if res.get("values") else []
    for i in range(min(len(current), len(existing))):
        existing[i] = current[i]

    for k, v in row_values.items():
        if k in SHEET_HEADERS:
            idx = SHEET_HEADERS.index(k)
            existing[idx] = v if v is not None else ""

    body = {"values": [existing]}
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"A{row_index}:Q{row_index}",
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()

def to_iso_date(text: str) -> Optional[str]:
    # Accept YYYY-MM-DD or DD.MM.YYYY / DD/MM/YYYY
    text = text.strip()
    # YYYY-MM-DD
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", text)
    if m:
        return text
    # DD.MM.YYYY or DD/MM/YYYY or D.M.YYYY
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})$", text)
    if m:
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:  # yy
            y += 2000
        try:
            return dt.date(y, mth, d).isoformat()
        except:
            return None
    return None

def parse_user_edit(text: str, last_field: Optional[str]) -> Dict[str, Any]:
    # Returns dict of fields to update
    upd: Dict[str, Any] = {}

    # "קטגוריה: עיצוב"
    m = re.search(r"קטגוריה[:]\s*(.+)", text)
    if m:
        cat = m.group(1).strip()
        upd["category"] = cat

    # "סכום: 14800"
    m = re.search(r"סכום[:]\s*([\d\.,]+)", text)
    if m:
        amt = m.group(1).replace(",", "")
        try:
            upd["amount"] = float(amt)
        except:
            pass

    # "ספק: פלורל"
    m = re.search(r"ספק[:]\s*(.+)", text)
    if m:
        upd["vendor"] = m.group(1).strip()

    # "תאריך: 2025-08-20" or "תאריך: 20.08.2025"
    m = re.search(r"תאריך[:]\s*([0-9./-]+)", text)
    if m:
        iso = to_iso_date(m.group(1))
        if iso:
            upd["date"] = iso

    # "זה לא X זה Y"
    m = re.search(r"זה לא\s+(.+?)\s+זה\s+(.+)", text)
    if m and last_field:
        y = m.group(2).strip()
        # only apply to known fields
        if last_field in {"category", "vendor"}:
            upd[last_field] = y

    return upd

def build_summary_msg(data: Dict[str, Any]) -> str:
    vendor = data.get("vendor") or "-"
    date = data.get("date") or "-"
    amount = data.get("amount")
    category = data.get("category") or "-"
    payment = data.get("payment_method") or "-"
    amt_str = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if isinstance(amount, (int, float)) else "-"
    return (
        "📄 סיכום קבלה:\n"
        f"ספק: {vendor}\n"
        f"תאריך: {date}\n"
        f"סכום: {amt_str} ₪\n"
        f"קטגוריה: {category}\n"
        f"אמצעי תשלום: {payment}\n\n"
        "רוצה לתקן? כתוב: \"קטגוריה: עיצוב\" / \"סכום: 14800\" / \"ספק: פלורל\" / \"תאריך: 2025-08-20\""
    )

async def greenapi_send_text(chat_id: str, text: str):
    url = f"https://api.green-api.com/waInstance{GREEN_ID}/sendMessage/{GREEN_TOKEN}"
    payload = {"chatId": chat_id, "message": text}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()

# ========== OpenAI Vision ==========

async def analyze_receipt_with_openai(img_bytes: bytes) -> Dict[str, Any]:
    """
    Send base64 image to OpenAI and get structured JSON.
    """
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    system_prompt = (
        "אתה ממיר תמונת קבלה ל-JSON אחיד. החזר אך ורק JSON חוקי ללא טקסט נוסף, במבנה הבא:\n"
        "{\n"
        "  \"date\": \"YYYY-MM-DD\" | null,\n"
        "  \"amount\": number | null,\n"
        "  \"currency\": \"ILS\" | \"USD\" | \"EUR\" | null,\n"
        "  \"vendor\": string | null,\n"
        "  \"category\": one of [\"אולם וקייטרינג\",\"בר/אלכוהול\",\"צילום\",\"מוזיקה/דיג'יי\",\"בגדים/טבעות\",\"עיצוב/פרחים\",\"הדפסות/הזמנות/מדיה\",\"לינה/נסיעות/הסעות\",\"אחר\"],\n"
        "  \"payment_method\": \"card\" | \"cash\" | \"bank\" | null,\n"
        "  \"invoice_number\": string | null,\n"
        "  \"notes\": string | null\n"
        "}\n"
        "אם אינך בטוח בשדה מסוים, החזר null. תאריך תמיד בפורמט ISO. אם המטבע לא ברור בישראל – העדף ILS.\n"
    )
    user_prompt = "נתח את התמונה והחזר JSON בלבד לפי הסכמה. אין להוסיף הסברים."
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
    # Remove code fences if any
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
    try:
        data = json.loads(content)
    except Exception:
        # fallback minimal
        data = {"date": None, "amount": None, "currency": "ILS", "vendor": None, "category": "אחר",
                "payment_method": None, "invoice_number": None, "notes": "parse_error"}
    # defaults
    if not data.get("currency"):
        data["currency"] = DEFAULT_CURRENCY
    if data.get("category") not in CATEGORIES:
        data["category"] = "אחר"
    return data

# ========== Webhook ==========

@app.post("/webhook")
async def webhook(request: Request):
    # Optional auth
    if WEBHOOK_SHARED_SECRET:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if not auth or (not auth.endswith(WEBHOOK_SHARED_SECRET) and auth != f"Bearer {WEBHOOK_SHARED_SECRET}"):
            raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await request.json()

    # GreenAPI standard fields (simplified)
    # messageData.typeMessage: "imageMessage" | "textMessage" | ...
    type_msg = payload.get("messageData", {}).get("typeMessage")
    chat_id = payload.get("senderData", {}).get("chatId")  # "9725xxxx@c.us"
    id_message = payload.get("idMessage")
    if not chat_id:
        return {"status": "ignored"}

    # --- שימוש במספרים מורשים בלבד ---
    phone_e164 = chatid_to_e164(chat_id)  # לדוגמה +972501234567
    if not is_allowed(phone_e164):
        return {"status": "ignored_not_allowed", "phone": phone_e164}

    # מכאן והלאה תמיד עובדים עם E.164
    phone = phone_e164

    # Handle possible timeout to auto-save (ניקוי חלון העריכה)
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
                    await greenapi_send_text(chat_id, "שגיאה: לא נמצא הרשומה לעדכון.")
                    return {"status": "missing_row"}

        return {"status": "text_ignored"}

    # --- קבלה (תמונה) ---
    if type_msg == "imageMessage":
        try:
            blob, ext = await greenapi_download_media(id_message)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Download failed: {e}")

        file_hash = sha256_b64(blob)

        # ניתוח עם OpenAI
        ai = await analyze_receipt_with_openai(blob)

        # Drive path: /Receipts/{phone}/{YYYY}/{MM}/
        today = dt.datetime.now()
        y = str(today.year)
        m = f"{today.month:02d}"
        folder_phone = ensure_folder(phone, DRIVE_ROOT)
        folder_year = ensure_folder(y, folder_phone)
        folder_month = ensure_folder(m, folder_year)

        # Upload
        safe_vendor = (ai.get('vendor') or 'vendor').replace(' ', '_')
        fname = f"{today.strftime('%Y%m%d')}_{(ai.get('amount') or 'xxx')}_{safe_vendor}_{file_hash[:8]}.{ext}"
        file_id, file_url = upload_to_drive(blob, fname, folder_month)

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

        # כתיבה ל־Sheets
        row_values = [row_map.get(h, "") for h in SHEET_HEADERS]
        sheets_append_row(row_values)

        # חלון עריכה
        last_expense_by_phone[phone] = expense_id
        last_shown_field_by_phone[phone] = "category"
        pending_until[phone] = dt.datetime.now() + dt.timedelta(minutes=10)

        # סיכום למשתמש
        msg = build_summary_msg(row_map)
        await greenapi_send_text(chat_id, msg)

        return {"status": "receipt_saved", "expense_id": expense_id}

    # סוגי הודעות אחרים: מתעלמים
    return {"status": "ignored"}

