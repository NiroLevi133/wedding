import os, re, base64, json, hashlib, datetime as dt, random
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

# Google credentials - עכשיו הקובץ קיים!
GOOGLE_CREDENTIALS_PATH = "./gcp_credentials.json"

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

# לזוגות מחוברים: cache זיכרון + התמדה ב-GSheets(Tab "links")
LINKS_TAB = "links!A:D"  # A: phone_a, B: phone_b, C: group_id, D: created_at
links_cache: List[Tuple[str, str, str]] = []  # (phone_a, phone_b, group_id)
pending_link_codes: Dict[str, Dict[str, str]] = {}  
# key: code, value: {"initiator": "+972...", "target": "+972...", "created_at": iso}

SHEET_HEADERS = [
    "expense_id", "owner_phone", "partner_group_id", "date", "amount", "currency",
    "vendor", "category", "payment_method", "invoice_number", "notes",
    "drive_file_url", "source", "status", "needs_review",
    "created_at", "updated_at", "approved_at"
]

# ===== Utilities =====
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

def chatid_to_e164(chat_id: str) -> str:
    if not chat_id:
        return ""
    num = chat_id.split("@")[0]
    return f"+{num}" if not num.startswith("+") else num

def e164_to_chatid(phone_e164: str) -> str:
    # +972501234567 -> 972501234567@c.us
    digits = phone_e164.replace("+", "").strip()
    return f"{digits}@c.us"

def normalize_phone(text: str) -> Optional[str]:
    # משמר + בתחילת המספר; מתיר רק ספרות אחרי
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

async def greenapi_send_text(chat_id: str, text: str):
    url = f"https://api.green-api.com/waInstance{GREEN_ID}/sendMessage/{GREEN_TOKEN}"
    payload = {"chatId": chat_id, "message": text}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()

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
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(download_url)
        r.raise_for_status()
        blob = r.content
        ext = file_name.split(".")[-1].lower() if "." in file_name else ("jpg" if "jpeg" in mime_type else "png")
        return blob, ext

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
    file_metadata = {'name': filename, 'parents': [folder_id]}
    file = drive.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = file.get('id')
    permission = {'type': 'anyone', 'role': 'reader'}
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
    """Load all pairs from links tab into memory."""
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
    except Exception:
        # if tab missing, keep empty; user should create tab 'links' with headers
        pass

def sorted_pair_gid(a: str, b: str) -> str:
    aa, bb = sorted([a, b])
    raw = f"{aa}|{bb}"
    return "grp_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

def find_group_for_phone(phone: str) -> Optional[str]:
    # search cache first
    for a, b, gid in links_cache:
        if phone == a or phone == b:
            return gid
    # lazy reload once if empty
    load_links_cache()
    for a, b, gid in links_cache:
        if phone == a or phone == b:
            return gid
    return None

def add_link_pair(p1: str, p2: str) -> str:
    gid = sorted_pair_gid(p1, p2)
    # avoid duplicates in cache
    for a, b, g in links_cache:
        if {a, b} == {p1, p2}:
            return g
    sheets_append_links_row(p1, p2, gid)
    # update cache
    links_cache.append((p1, p2, gid))
    return gid

def build_summary_msg(data: dict) -> str:
    vendor = data.get('vendor', 'לא זוהה')
    amount = data.get('amount', 'לא זוהה')
    currency = data.get('currency', 'ILS')
    category = data.get('category', 'אחר')
    date = data.get('date', 'לא זוהה')
    payment_method = data.get('payment_method', '')
    invoice_number = data.get('invoice_number', '')
    msg = f"""✅ קבלה נשמרה!

🏪 ספק: {vendor}
💰 סכום: {amount} {currency}
📅 תאריך: {date}
🏷️ קטגוריה: {category}"""
    if payment_method:
        payment_emoji = "💳" if payment_method == "card" else "💵" if payment_method == "cash" else "🏦"
        msg += f"\n{payment_emoji} תשלום: {payment_method}"
    if invoice_number:
        msg += f"\n📋 מספר חשבונית: {invoice_number}"
    return msg

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
        "\"invoice_number\": string | null, \"notes\": string | null }\n\n"
        "חוקי זיהוי קטגוריות:\n"
        "- אולמות, גנים, קייטרינג, מקומות אירועים = 'אולם וקייטרינג'\n"
        "- דיג'יי, DJ, BPM, תקליטן, מוזיקה, להקה, זמר = 'מוזיקה/דיג'יי'\n"
        "- צלם, וידאו, קליפ, עריכה = 'צילום'\n"
        "- פרחים, עיצוב, דקורציה = 'עיצוב/פרחים'"
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

# ===== FastAPI endpoints =====
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

@app.post("/webhook")
async def webhook(request: Request):
    try:
        if WEBHOOK_SHARED_SECRET:
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if not auth or (not auth.endswith(WEBHOOK_SHARED_SECRET) and auth != f"Bearer {WEBHOOK_SHARED_SECRET}"):
                raise HTTPException(status_code=401, detail="Unauthorized")

        payload = await request.json()
        print(f"📦 Full payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")

        ensure_google()
        # ודא שהמטמון של הלינקים נטען
        if not links_cache:
            load_links_cache()

        type_msg = payload.get("messageData", {}).get("typeMessage")
        chat_id = payload.get("senderData", {}).get("chatId")
        id_message = payload.get("idMessage")

        print(f"📋 Message type: {type_msg}")
        print(f"👤 Chat ID: {chat_id}")
        print(f"🆔 Message ID: {id_message}")

        if not chat_id:
            return {"status": "ignored", "reason": "no_chat_id"}

        phone_e164 = chatid_to_e164(chat_id)
        if not is_allowed(phone_e164):
            return {"status": "ignored_not_allowed", "phone": phone_e164}

        phone = phone_e164

        # === TEXT HANDLING (commands + confirmation) ===
        if type_msg == "textMessage":
            text = payload.get("messageData", {}).get("textMessageData", {}).get("textMessage", "")
            text = text.strip()
            if not text:
                return {"status": "ok"}

            # 1) Help
            if text.lower() in ["עזרה", "help"]:
                help_msg = (
                    "🔹 שליחת קבלה: שלחו תמונה/קובץ – נוציא נתונים ונשמור\n"
                    "🔹 חיבור יוזרים: כתבו\n"
                    "   חבר +972501234567\n"
                    "   ואז בן/בת הזוג צריכים לענות מהמספר שלהם: מאשר 123456\n"
                )
                await greenapi_send_text(chat_id, help_msg)
                return {"status": "help_sent"}

            # 2) Start link flow: 'חבר <phone>'
            m = re.match(r"^(?:חבר|חיבור)\s+(\+?\d{9,15})$", text)
            if m:
                target = normalize_phone(m.group(1))
                if not target:
                    await greenapi_send_text(chat_id, "❌ מספר לא תקין. דוגמה: חבר +972501234567")
                    return {"status": "invalid_phone"}

                if target == phone:
                    await greenapi_send_text(chat_id, "🤷‍♂️ אי אפשר לחבר את עצמך לעצמך 😉")
                    return {"status": "same_phone"}

                # אם כבר מחוברים – החזר group_id
                existing_gid = find_group_for_phone(phone)
                if existing_gid and find_group_for_phone(target) == existing_gid:
                    await greenapi_send_text(chat_id, f"✅ כבר מחוברים! group_id: {existing_gid}")
                    return {"status": "already_linked", "group_id": existing_gid}

                # צור קוד, שלח ליעד
                code = f"{random.randint(100000, 999999)}"
                pending_link_codes[code] = {"initiator": phone, "target": target, "created_at": ez_now_iso()}
                # שלח הודעה ליעד
                target_chat = e164_to_chatid(target)
                try:
                    await greenapi_send_text(
                        target_chat,
                        f"🔗 בקשה לחיבור חשבונות מאת {phone}\n"
                        f"אם זה בסדר מבחינתך, ענו כאן: 'מאשר {code}'"
                    )
                except Exception as e:
                    await greenapi_send_text(chat_id, f"❌ לא הצלחתי לשלוח הודעה ליעד. ודא שהמספר {target} זמין בווטסאפ. ({e})")
                    return {"status": "target_send_failed"}

                await greenapi_send_text(
                    chat_id,
                    f"📨 שלחתי אימות ל{target}.\n"
                    f"כשהוא/היא יענו: 'מאשר {code}' – נחבר אתכם."
                )
                return {"status": "link_code_sent", "code": code, "target": target}

            # 3) Confirm link: 'מאשר 123456' (must come from target phone)
            m2 = re.match(r"^(?:מאשר|מאשרת)\s+(\d{6})$", text)
            if m2:
                code = m2.group(1)
                rec = pending_link_codes.get(code)
                if not rec:
                    await greenapi_send_text(chat_id, "❌ קוד לא נמצא או שפג תוקפו.")
                    return {"status": "code_not_found"}
                initiator = rec["initiator"]
                target = rec["target"]
                # המאשר חייב להיות היעד בפועל
                if phone != target:
                    await greenapi_send_text(chat_id, "❌ הקוד הזה לא משויך למספר שלך.")
                    return {"status": "wrong_phone_for_code"}

                gid = add_link_pair(initiator, target)
                # ניקוי הקוד מהזכרון
                pending_link_codes.pop(code, None)

                # אישורים דו-צדדיים
                await greenapi_send_text(e164_to_chatid(initiator), f"✅ מעולה! חיברנו אותך עם {target}\nGroup: {gid}")
                await greenapi_send_text(e164_to_chatid(target), f"✅ חיבור הושלם עם {initiator}\nGroup: {gid}")
                return {"status": "linked", "group_id": gid, "a": initiator, "b": target}

            # טקסט רגיל
            await greenapi_send_text(chat_id, f"קיבלתי את ההודעה: '{text}' 📝\nשלח תמונת קבלה לניתוח!\nאו: חבר +9725XXXXXXXX לחיבור יוזרים.")
            return {"status": "text_received"}

        # === IMAGE handling ===
        elif type_msg == "imageMessage":
            try:
                blob, ext = await greenapi_download_media(payload)
                ai = await analyze_receipt_with_openai(blob)
                file_hash = sha256_b64(blob)
                expense_id = hashlib.md5((file_hash + phone).encode()).hexdigest()
                now_iso = ez_now_iso()

                # partner group id (אם קיים)
                gid = find_group_for_phone(phone) or ""

                # Drive upload
                try:
                    today = dt.datetime.now()
                    phone_folder = ensure_folder(phone, DRIVE_ROOT)
                    safe_vendor = re.sub(r'[^\w\u0590-\u05FF]+', '_', str(ai.get('vendor') or 'vendor'))
                    filename = f"{today.strftime('%Y%m%d')}_{(ai.get('amount') or 'unknown')}_{safe_vendor}_{file_hash[:8]}.{ext}"
                    file_id, drive_url = upload_to_drive(blob, filename, phone_folder)
                except Exception as drive_error:
                    print(f"❌ Drive upload failed: {drive_error}")
                    drive_url = ""
                    try:
                        message_data = payload.get("messageData", {})
                        if "fileMessageData" in message_data:
                            drive_url = message_data["fileMessageData"].get("downloadUrl", "")
                        elif "imageMessage" in message_data:
                            drive_url = message_data["imageMessage"].get("downloadUrl", "")
                    except:
                        drive_url = "URL לא זמין"

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

                try:
                    row_values = [row_map.get(h, "") for h in SHEET_HEADERS]
                    sheets_append_row(row_values)
                except Exception as e:
                    print(f"❌ Error saving to sheets: {e}")

                msg = build_summary_msg(ai)
                # הוסף שורת קבוצה למי שזה רלוונטי
                if gid:
                    msg += f"\n👥 קבוצה: {gid}"
                await greenapi_send_text(chat_id, msg)

                return {"status": "receipt_saved", "expense_id": expense_id, "analysis": ai, "group_id": gid}
            except Exception as e:
                print(f"❌ Error processing image: {str(e)}")
                await greenapi_send_text(chat_id, f"❌ שגיאה: {str(e)}")
                raise
        else:
            print(f"❓ Unknown message type: {type_msg}")
            return {"status": "ignored", "message_type": type_msg, "reason": "unsupported_type"}

    except Exception as e:
        print(f"💥 Error in webhook: {str(e)}")
        try:
            if 'chat_id' in locals():
                await greenapi_send_text(chat_id, "❌ אירעה שגיאה במערכת.")
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
