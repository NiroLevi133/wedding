# 💒 מערכת ניהול הוצאות חתונה

מערכת אוטומטית לניהול הוצאות חתונה דרך WhatsApp עם AI, Google Sheets ודשבורדים אינטראקטיביים.

## 🌟 תכונות עיקריות

- 📸 **ניתוח קבלות אוטומטי** - שלח תמונה, קבל ניתוח מלא
- 🤖 **AI חכם** - זיהוי ספק, סכום, קטגוריה וכל הפרטים
- 💰 **ניהול מקדמות** - זיהוי אוטומטי של מקדמות ותשלומים סופיים
- 👥 **זוגות מחוברים** - דשבורד משותף לחתן וכלה
- 📊 **דשבורד מקצועי** - גרפים, סטטיסטיקות ומעקב תקציב
- 🛠️ **פאנל מנהל** - ניהול כל הזוגות במקום אחד
- 📈 **סיכומים שבועיים** - עדכונים אוטומטיים לזוגות
- 🔄 **עדכונים חכמים** - תיקון קבלות בהודעות טבעיות

## 🚀 פריסה ב-Google Cloud

### משתני סביבה נדרשים

```bash
# Google Services
GOOGLE_CREDENTIALS_JSON={"type": "service_account", ...}
GSHEETS_SPREADSHEET_ID=your_spreadsheet_id

# WhatsApp (Green API)
GREENAPI_INSTANCE_ID=your_instance_id
GREENAPI_TOKEN=your_token

# OpenAI
OPENAI_API_KEY=your_openai_key

# Security
WEBHOOK_SHARED_SECRET=your_secret_key
ADMIN_PASSWORD=your_admin_password

# Optional
DEFAULT_CURRENCY=ILS
DEFAULT_TIMEZONE=Asia/Jerusalem
ALLOWED_PHONES=+972501234567,+972502345678
```

## 📦 פריסה ב-Cloud Run

### שלב 1: הכנת הפרויקט

```bash
# Clone/Download הפרויקט
cd wedding-expense-bot

# הגדר משתני סביבה בקובץ .env (לפיתוח בלבד)
cp .env.example .env
# ערוך את .env עם הערכים שלך
```

### שלב 2: בניה ופריסה

```bash
# התחבר ל-Google Cloud
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# בנה את הקונטיינר
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/wedding-bot

# פרוס ל-Cloud Run
gcloud run deploy wedding-bot \
  --image gcr.io/YOUR_PROJECT_ID/wedding-bot \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300s \
  --max-instances 10 \
  --set-env-vars="GOOGLE_CREDENTIALS_JSON=$GOOGLE_CREDENTIALS_JSON" \
  --set-env-vars="GSHEETS_SPREADSHEET_ID=$GSHEETS_SPREADSHEET_ID" \
  --set-env-vars="OPENAI_API_KEY=$OPENAI_API_KEY" \
  --set-env-vars="GREENAPI_INSTANCE_ID=$GREENAPI_INSTANCE_ID" \
  --set-env-vars="GREENAPI_TOKEN=$GREENAPI_TOKEN" \
  --set-env-vars="WEBHOOK_SHARED_SECRET=$WEBHOOK_SHARED_SECRET"
```

### שלב 3: הגדרת Webhook

לאחר פריסה, תקבל URL כמו:
`https://wedding-bot-xxx-uc.a.run.app`

1. היכנס ל-Green API Console
2. הגדר Webhook URL: `https://your-domain.com/webhook`
3. הוסף Authorization Header עם ה-WEBHOOK_SHARED_SECRET

## 🛠️ פיתוח מקומי

### התקנה

```bash
# Clone the repository
git clone <repository-url>
cd wedding-expense-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# או
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your credentials
```

### הרצה מקומית

```bash
# Development mode
uvicorn main:app --reload --port 8080

# Production mode
uvicorn main:app --host 0.0.0.0 --port 8080
```

### בדיקת תקינות

```bash
# בדוק שהשרת רץ
curl http://localhost:8080/health

# דשבורד מנהל
http://localhost:8080/admin/login

# API Documentation
http://localhost:8080/api-docs
```

## 📊 מבנה הפרויקט

```
wedding-expense-bot/
├── main.py                 # FastAPI application
├── config.py              # הגדרות וקונפיגורציה
├── database_manager.py    # ניהול Google Sheets
├── ai_analyzer.py         # מנוע AI לניתוח
├── bot_messages.py        # הודעות הבוט
├── webhook_handler.py     # מעבד WhatsApp
├── user_dashboard.py      # דשבורד זוגות
├── admin_panel.py         # דשבורד מנהל
├── requirements.txt       # חבילות Python
├── Dockerfile            # הגדרות קונטיינר
├── .env.example          # דוגמת משתני סביבה
└── README.md             # המדריך הזה
```

## 🎯 שימוש במערכת

### למנהל המערכת

1. **הוסף זוגות:** הכנס נתוני זוגות לגיליון `couples`
2. **צור קבוצות WhatsApp:** הוסף חתן + כלה + בוט
3. **ניטור:** `/admin/dashboard` לצפייה בכל הנתונים
4. **תמיכה:** עזור לזוגות דרך הפאנל

### לזוגות

1. **הוספה לקבוצה:** מנהל מוסיף אותכם לקבוצת WhatsApp
2. **הגדרה ראשונית:** בוט שואל תאריך חתונה ותקציב
3. **שליחת קבלות:** פשוט שלחו תמונות של קבלות לקבוצה
4. **עדכונים:** "זה 2500 לא 2000" - תיקונים טבעיים
5. **צפייה:** קישור לדשבורד האישי

## 🔧 תחזוקה

### מעקב לוגים

```bash
# Cloud Run logs
gcloud logs tail --service=wedding-bot

# Filter specific issues
gcloud logs read --service=wedding-bot --filter="severity>=ERROR"
```

### עדכון הפריסה

```bash
# לאחר שינויים בקוד:
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/wedding-bot
gcloud run deploy wedding-bot --image gcr.io/YOUR_PROJECT_ID/wedding-bot
```

### גיבוי נתונים

Google Sheets מגבה אוטומטית, אבל מומלץ:
- ייצוא חודשי לExcel
- גיבוי משתני סביבה
- העתקת Service Account keys

## 🆘 פתרון בעיות נפוצות

### בעיות חיבור לGoogle Sheets
```bash
# בדוק הרשאות Service Account
gcloud iam service-accounts get-iam-policy SERVICE_ACCOUNT_EMAIL

# בדוק שהגיליון משותף
# Google Sheets → Share → הוסף Service Account Email
```

### בעיות WhatsApp Webhook
```bash
# בדוק שה-URL נגיש
curl https://your-domain.com/health

# בדוק Green API settings
curl -X GET "https://api.green-api.com/waInstance{ID}/getSettings/{TOKEN}"
```

### בעיות OpenAI
```bash
# בדוק API key
curl -H "Authorization: Bearer $OPENAI_API_KEY" \
  "https://api.openai.com/v1/models"
```

## 📞 תמיכה

- **בעיות טכניות:** בדוק את הלוגים ב-Cloud Console
- **שגיאות במערכת:** `/health` endpoint לבדיקה
- **בעיות נתונים:** בדוק את Google Sheets ישירות

## 📈 מדדי הצלחה

המערכת פועלת נכון כאשר:
- ✅ זוגות מקבלים אישור מיידי על קבלות
- ✅ הדשבורד מציג נתונים מעודכנים
- ✅ מקדמות מתקבצות נכון
- ✅ אין שגיאות בלוגים
- ✅ סיכומים שבועיים נשלחים

---

## 🎉 המערכת מוכנה!

המערכת תומכת באלפי זוגות במקביל וכוללת כל מה שצריך לניהול מקצועי של הוצאות חתונה.


**בהצלחה! 💒**
