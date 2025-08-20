import os, re, base64, json, hashlib, datetime as dt
from typing import Optional, Dict, Any, Tuple

from fastapi import FastAPI, Request, HTTPException
import httpx
from dotenv import load_dotenv
from flask import Flask
    
# Google APIs
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

# OpenAI
from openai import OpenAI

# Load env vars (useful locally, Cloud Run uses real ENV instead)
load_dotenv()

app = FastAPI()

@app.route("/")
def home():
    return {"status": "ok", "message": "האפליקציה שלך עובדת על Cloud Run!"}

# קריטי: להאזין על ה־PORT ש־Cloud Run נותן
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
    
    
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

# Service account path (Cloud Run injects this when mounting secret)
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/secrets/gcp_credentials.json")

ALLOWED_PHONES = set(p.strip() for p in (os.getenv("ALLOWED_PHONES","").split(",") if os.getenv("ALLOWED_PHONES") else []))

# === Globals for Google clients ===
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
creds = None
drive = None
sheets = None

# === OpenAI client ===
oaiclient = OpenAI(api_key=OPENAI_API_KEY)

@app.get("/health")
def health():
    """Health check endpoint for Cloud Run"""
    return {"ok": True}

# === Init Google APIs (lazy) ===
def ensure_google():
    """Initialize Google Drive/Sheets once, when first needed."""
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

# ========== Utilities ==========
def chatid_to_e164(chat_id: str) -> str:
    if not chat_id:
        return ""
    num = chat_id.split("@")[0]
    return f"+{num}" if not num.startswith("+") else num

def is_allowed(phone_e164: str) -> bool:
    return phone_e164 in ALLOWED_PHONES if ALLOWED_PHONES else False

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

# ========== OpenAI Vision ==========
async def analyze_receipt_with_openai(img_bytes: bytes) -> Dict[str, Any]:
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
    try:
        data = json.loads(content)
    except Exception:
        data = {"date": None, "amount": None, "currency": "ILS", "vendor": None, "category": "אחר",
                "payment_method": None, "invoice_number": None, "notes": "parse_error"}
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
        return {"status": "ignored"}

    phone_e164 = chatid_to_e164(chat_id)
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

