import os
import json
import datetime as dt
from google.oauth2 import service_account
from googleapiclient.discovery import build
from collections import defaultdict
import hashlib
import random
from fastapi.responses import HTMLResponse

# משתני סביבה
SHEET_ID = os.getenv("GSHEETS_SPREADSHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# משתנים גלובליים
creds = None
sheets = None

def ensure_google():
    """פונקציה לחיבור Google Sheets"""
    global creds, sheets
    if sheets is not None:
        return
    
    try:
        google_creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if google_creds_json:
            creds_dict = json.loads(google_creds_json)
            creds = service_account.Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
        else:
            # fallback למשתני סביבה נפרדים
            GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
            GOOGLE_PRIVATE_KEY_ID = os.getenv("GOOGLE_PRIVATE_KEY_ID")
            GOOGLE_PRIVATE_KEY = os.getenv("GOOGLE_PRIVATE_KEY")
            GOOGLE_CLIENT_EMAIL = os.getenv("GOOGLE_CLIENT_EMAIL")
            GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
            
            if not all([GOOGLE_PROJECT_ID, GOOGLE_PRIVATE_KEY, GOOGLE_CLIENT_EMAIL]):
                raise RuntimeError("Missing Google credentials")
            
            creds_dict = {
                "type": "service_account",
                "project_id": GOOGLE_PROJECT_ID,
                "private_key_id": GOOGLE_PRIVATE_KEY_ID or "",
                "private_key": GOOGLE_PRIVATE_KEY,
                "client_email": GOOGLE_CLIENT_EMAIL,
                "client_id": GOOGLE_CLIENT_ID or "",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "universe_domain": "googleapis.com"
            }
            creds = service_account.Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
        
        sheets = build("sheets", "v4", credentials=creds)
    except Exception as e:
        raise RuntimeError(f"Failed to initialize Google Sheets: {e}")

def get_partner_phones(user_phone: str, partner_group: str) -> list:
    """מחזיר רשימת טלפונים לחיפוש (המשתמש + בן/בת זוג אם יש)"""
    phones = [user_phone]
    
    if partner_group:
        # טען את טבלת החיבורים
        try:
            ensure_google()
            result = sheets.spreadsheets().values().get(
                spreadsheetId=SHEET_ID,
                range='links!A:C'
            ).execute()
            
            links = result.get('values', [])
            for row in links:
                if len(row) >= 3 and row[2] == partner_group:
                    # מצא את שני המספרים בקבוצה
                    phone1 = row[0]
                    phone2 = row[1]
                    
                    if phone1 == user_phone and phone2 not in phones:
                        phones.append(phone2)
                    elif phone2 == user_phone and phone1 not in phones:
                        phones.append(phone1)
        except:
            pass
    
    return phones

async def dashboard(user_phone: str, partner_group: str = None):
    """דשבורד ראשי מקצועי עם נתונים אישיים בלבד"""
    try:
        # קבל רשימת טלפונים לסינון
        allowed_phones = get_partner_phones(user_phone, partner_group)
        
        # טעינת נתונים מהגיליון
        ensure_google()
        result = sheets.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='A:R'
        ).execute()
        
        values = result.get('values', [])
        if not values or len(values) < 2:
            return generate_empty_dashboard(user_phone)
        
        # עיבוד הנתונים - רק של המשתמש והבן/בת זוג
        headers = values[0]
        data_rows = values[1:]
        
        expenses = []
        for row in data_rows:
            if len(row) >= 6:
                try:
                    owner_phone = row[1] if len(row) > 1 else ''
                    
                    # סנן רק הוצאות של המשתמש או בן/בת הזוג
                    if owner_phone in allowed_phones:
                        expense = {
                            'owner_phone': owner_phone,
                            'date': row[3] if len(row) > 3 else '',
                            'amount': float(row[4]) if len(row) > 4 and row[4] else 0,
                            'currency': row[5] if len(row) > 5 else 'ILS',
                            'vendor': row[6] if len(row) > 6 else '',
                            'category': row[7] if len(row) > 7 else 'אחר',
                            'payment_method': row[8] if len(row) > 8 else '',
                            'drive_file_url': row[11] if len(row) > 11 else ''
                        }
                        if expense['amount'] > 0:
                            expenses.append(expense)
                except (ValueError, IndexError):
                    continue
        
        if not expenses:
            return generate_empty_dashboard(user_phone)
        
        # חישוב סטטיסטיקות
        total_amount = sum(exp['amount'] for exp in expenses)
        total_count = len(expenses)
        avg_amount = total_amount / total_count if total_count > 0 else 0
        
        # קבלות לפי קטגוריה
        categories = {}
        for exp in expenses:
            cat = exp['category']
            if cat not in categories:
                categories[cat] = {'count': 0, 'amount': 0}
            categories[cat]['count'] += 1
            categories[cat]['amount'] += exp['amount']
        
        # אמוג'י לקטגוריות
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
        
        # שם משתמש לתצוגה
        display_name = user_phone[-4:]
        partner_info = ""
        if partner_group and len(allowed_phones) > 1:
            partner_phone = [p for p in allowed_phones if p != user_phone][0]
            partner_info = f" ו-{partner_phone[-4:]}"
        
        # יצירת HTML דינמי
        dashboard_html = f"""
        <!DOCTYPE html>
        <html dir="rtl">
        <head>
            <meta charset="UTF-8">
            <title>דשבורד הוצאות חתונה - אישי</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                
                body {{ 
                    font-family: 'Segoe UI', Tahoma, Arial, sans-serif; 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    direction: rtl;
                    padding: 20px;
                }}
                
                .container {{ 
                    max-width: 1400px; 
                    margin: 0 auto; 
                    background: white; 
                    border-radius: 20px; 
                    box-shadow: 0 20px 60px rgba(0,0,0,0.1);
                    overflow: hidden;
                }}
                
                .header {{ 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white; 
                    padding: 30px;
                    text-align: center;
                    position: relative;
                }}
                
                .logout-btn {{
                    position: absolute;
                    top: 20px;
                    left: 20px;
                    background: rgba(255,255,255,0.2);
                    color: white;
                    border: 1px solid rgba(255,255,255,0.3);
                    padding: 8px 16px;
                    border-radius: 20px;
                    text-decoration: none;
                    font-size: 0.9rem;
                    transition: all 0.3s ease;
                }}
                
                .logout-btn:hover {{
                    background: rgba(255,255,255,0.3);
                    transform: scale(1.05);
                }}
                
                .user-info {{
                    position: absolute;
                    top: 20px;
                    right: 20px;
                    background: rgba(255,255,255,0.2);
                    padding: 8px 16px;
                    border-radius: 20px;
                    font-size: 0.9rem;
                }}
                
                .header h1 {{ 
                    font-size: 2.5rem; 
                    margin-bottom: 10px;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                }}
                
                .header p {{ 
                    font-size: 1.1rem; 
                    opacity: 0.9;
                }}
                
                .nav-buttons {{
                    text-align: center;
                    padding: 20px;
                    background: #f8f9fa;
                    border-bottom: 1px solid #e9ecef;
                }}
                
                .nav-btn {{
                    background: #667eea;
                    color: white;
                    padding: 12px 24px;
                    margin: 0 10px;
                    border: none;
                    border-radius: 25px;
                    text-decoration: none;
                    display: inline-block;
                    font-weight: bold;
                    transition: all 0.3s ease;
                }}
                
                .nav-btn:hover {{
                    background: #5a6fd8;
                    transform: translateY(-2px);
                    box-shadow: 0 8px 15px rgba(0,0,0,0.2);
                }}
                
                .stats-grid {{ 
                    display: grid; 
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
                    gap: 20px; 
                    padding: 30px;
                    background: #f8f9fa;
                }}
                
                .stat-card {{ 
                    background: white; 
                    padding: 25px; 
                    border-radius: 15px; 
                    text-align: center;
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                    border-right: 5px solid #667eea;
                    transition: transform 0.3s ease, box-shadow 0.3s ease;
                }}
                
                .stat-card:hover {{ 
                    transform: translateY(-5px);
                    box-shadow: 0 15px 35px rgba(0,0,0,0.15);
                }}
                
                .stat-icon {{ 
                    font-size: 2.5rem; 
                    margin-bottom: 10px;
                }}
                
                .stat-value {{ 
                    font-size: 2rem; 
                    font-weight: bold; 
                    color: #667eea; 
                    margin-bottom: 5px;
                }}
                
                .stat-label {{ 
                    color: #666; 
                    font-size: 0.9rem;
                }}
                
                .content {{ 
                    padding: 30px;
                }}
                
                .section {{ 
                    margin-bottom: 40px;
                }}
                
                .section h2 {{ 
                    color: #333; 
                    margin-bottom: 20px; 
                    padding-bottom: 10px; 
                    border-bottom: 3px solid #667eea;
                    font-size: 1.5rem;
                }}
                
                .categories-grid {{ 
                    display: grid; 
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
                    gap: 15px; 
                    margin-bottom: 30px;
                }}
                
                .category-card {{ 
                    background: white; 
                    border: 2px solid #e9ecef; 
                    border-radius: 12px; 
                    padding: 20px; 
                    text-align: center;
                    transition: all 0.3s ease;
                }}
                
                .category-card:hover {{ 
                    border-color: #667eea; 
                    transform: translateY(-2px);
                    box-shadow: 0 8px 20px rgba(0,0,0,0.1);
                }}
                
                .category-emoji {{ 
                    font-size: 2rem; 
                    margin-bottom: 10px;
                }}
                
                .category-name {{ 
                    font-weight: bold; 
                    color: #333; 
                    margin-bottom: 8px;
                }}
                
                .category-amount {{ 
                    color: #667eea; 
                    font-size: 1.2rem; 
                    font-weight: bold;
                }}
                
                .category-count {{ 
                    color: #666; 
                    font-size: 0.9rem; 
                    margin-top: 5px;
                }}
                
                .table-container {{ 
                    background: white; 
                    border-radius: 12px; 
                    overflow: hidden; 
                    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                }}
                
                .table {{ 
                    width: 100%; 
                    border-collapse: collapse;
                }}
                
                .table th {{ 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    color: white; 
                    padding: 15px; 
                    text-align: center; 
                    font-weight: bold;
                }}
                
                .table td {{ 
                    padding: 12px; 
                    text-align: center; 
                    border-bottom: 1px solid #eee;
                }}
                
                .table tr:hover {{ 
                    background: #f8f9fa;
                }}
                
                .table tr:nth-child(even) {{ 
                    background: #fafafa;
                }}
                
                .amount-cell {{ 
                    font-weight: bold; 
                    color: #667eea;
                }}
                
                .link-button {{ 
                    background: #667eea; 
                    color: white; 
                    padding: 5px 10px; 
                    border-radius: 5px; 
                    text-decoration: none; 
                    font-size: 0.8rem;
                    transition: background 0.3s ease;
                }}
                
                .link-button:hover {{ 
                    background: #5a6fd8; 
                    text-decoration: none;
                }}
                
                .refresh-btn {{ 
                    position: fixed; 
                    bottom: 30px; 
                    left: 30px; 
                    background: #667eea; 
                    color: white; 
                    border: none; 
                    width: 60px; 
                    height: 60px; 
                    border-radius: 50%; 
                    font-size: 1.5rem; 
                    cursor: pointer; 
                    box-shadow: 0 8px 20px rgba(0,0,0,0.2);
                    transition: all 0.3s ease;
                }}
                
                .refresh-btn:hover {{ 
                    background: #5a6fd8; 
                    transform: scale(1.1);
                }}
                
                @media (max-width: 768px) {{
                    .header h1 {{ font-size: 2rem; }}
                    .stats-grid {{ grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }}
                    .categories-grid {{ grid-template-columns: 1fr; }}
                    .table-container {{ overflow-x: auto; }}
                    .user-info, .logout-btn {{ position: static; margin: 10px; }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <a href="#" class="logout-btn" onclick="logout()">🚪 יציאה</a>
                    <div class="user-info">👤 {display_name}{partner_info}</div>
                    <h1>💒 דשבורד הוצאות החתונה</h1>
                    <p>הנתונים האישיים שלכם</p>
                </div>
                
                <div class="nav-buttons">
                    <a href="/dashboard" class="nav-btn">📋 דשבורד ראשי</a>
                    <a href="/dashboard-summary" class="nav-btn">📊 דשבורד סיכום</a>
                </div>
                
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-icon">💰</div>
                        <div class="stat-value">{total_amount:,.0f} ₪</div>
                        <div class="stat-label">סך ההוצאות שלכם</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon">📄</div>
                        <div class="stat-value">{total_count}</div>
                        <div class="stat-label">מספר קבלות</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon">📊</div>
                        <div class="stat-value">{avg_amount:,.0f} ₪</div>
                        <div class="stat-label">ממוצע לקבלה</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon">🏷️</div>
                        <div class="stat-value">{len(categories)}</div>
                        <div class="stat-label">קטגוריות</div>
                    </div>
                </div>
                
                <div class="content">
                    <div class="section">
                        <h2>📊 הוצאות לפי קטגוריה</h2>
                        <div class="categories-grid">
        """
        
        # הוספת קטגוריות
        for category, data in sorted(categories.items(), key=lambda x: x[1]['amount'], reverse=True):
            emoji = category_emojis.get(category, "📋")
            dashboard_html += f"""
                            <div class="category-card">
                                <div class="category-emoji">{emoji}</div>
                                <div class="category-name">{category}</div>
                                <div class="category-amount">{data['amount']:,.0f} ₪</div>
                                <div class="category-count">{data['count']} קבלות</div>
                            </div>
            """
        
        # טבלת הוצאות אחרונות
        dashboard_html += f"""
                        </div>
                    </div>
                    
                    <div class="section">
                        <h2>📋 הוצאות אחרונות</h2>
                        <div class="table-container">
                            <table class="table">
                                <thead>
                                    <tr>
                                        <th>תאריך</th>
                                        <th>ספק</th>
                                        <th>סכום</th>
                                        <th>קטגוריה</th>
                                        <th>תשלום</th>
                                        <th>קבלה</th>
                                    </tr>
                                </thead>
                                <tbody>
        """
        
        # הוספת שורות הוצאות (10 אחרונות)
        recent_expenses = sorted(expenses, key=lambda x: x.get('date', ''), reverse=True)[:10]
        
        for expense in recent_expenses:
            date_display = expense['date'][:10] if expense['date'] else 'לא ידוע'
            vendor = expense['vendor'] or 'לא ידוע'
            amount = f"{expense['amount']:,.0f} ₪"
            category = expense['category']
            emoji = category_emojis.get(category, "📋")
            payment_display = {
                'card': 'כרטיס אשראי',
                'cash': 'מזומן',
                'bank': 'העברה בנקאית'
            }.get(expense['payment_method'], expense['payment_method'] or 'לא ידוע')
            
            receipt_link = ""
            if expense['drive_file_url']:
                receipt_link = f'<a href="{expense["drive_file_url"]}" target="_blank" class="link-button">📄 צפה</a>'
            else:
                receipt_link = '<span style="color: #999;">לא זמין</span>'
            
            dashboard_html += f"""
                                    <tr>
                                        <td>{date_display}</td>
                                        <td>{vendor}</td>
                                        <td class="amount-cell">{amount}</td>
                                        <td>{emoji} {category}</td>
                                        <td>{payment_display}</td>
                                        <td>{receipt_link}</td>
                                    </tr>
            """
        
        # סיום ה-HTML
        dashboard_html += f"""
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
            
            <button class="refresh-btn" onclick="location.reload()" title="רענן נתונים">🔄</button>
            
            <script>
                // פונקציית יציאה
                async function logout() {{
                    if (confirm('האם אתה בטוח שברצונך לצאת?')) {{
                        try {{
                            const response = await fetch('/auth/logout', {{
                                method: 'POST',
                                credentials: 'same-origin'
                            }});
                            if (response.ok) {{
                                window.location.href = '/login';
                            }}
                        }} catch (error) {{
                            console.error('Logout error:', error);
                            window.location.href = '/login';
                        }}
                    }}
                }}
                
                // רענון אוטומטי כל 5 דקות
                setTimeout(function() {{
                    location.reload();
                }}, 300000);
                
                // הוספת אפקטים
                document.addEventListener('DOMContentLoaded', function() {{
                    const cards = document.querySelectorAll('.stat-card, .category-card');
                    cards.forEach((card, index) => {{
                        card.style.animationDelay = (index * 0.1) + 's';
                        card.style.animation = 'fadeInUp 0.6s ease forwards';
                    }});
                }});
            </script>
            
            <style>
                @keyframes fadeInUp {{
                    from {{
                        opacity: 0;
                        transform: translateY(30px);
                    }}
                    to {{
                        opacity: 1;
                        transform: translateY(0);
                    }}
                }}
            </style>
        </body>
        </html>
        """
        
        return dashboard_html
        
    except Exception as e:
        return error_dashboard(str(e), user_phone)

def generate_empty_dashboard(user_phone: str):
    """HTML למקרה שאין נתונים"""
    display_name = user_phone[-4:]
    
    return f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>דשבורד הוצאות חתונה</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); direction: rtl; }}
            .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 50px; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.1); text-align: center; }}
            .no-data {{ color: #666; }}
            .logout-btn {{ background: #dc3545; color: white; padding: 10px 20px; border: none; border-radius: 5px; text-decoration: none; display: inline-block; margin: 20px; }}
            .user-badge {{ background: #667eea; color: white; padding: 5px 15px; border-radius: 20px; display: inline-block; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="user-badge">👤 {display_name}</div>
            <div class="no-data">
                <h1>💒 דשבורד הוצאות החתונה</h1>
                <p style="font-size: 1.2rem; margin: 30px 0;">📝 עדיין לא העלית הוצאות</p>
                <p>התחל לשלוח קבלות בווטסאפ כדי לראות נתונים!</p>
                <a href="#" onclick="logout()" class="logout-btn">🚪 יציאה</a>
            </div>
        </div>
        <script>
            async function logout() {{
                if (confirm('האם אתה בטוח שברצונך לצאת?')) {{
                    try {{
                        await fetch('/auth/logout', {{ method: 'POST', credentials: 'same-origin' }});
                        window.location.href = '/login';
                    }} catch (error) {{
                        window.location.href = '/login';
                    }}
                }}
            }}
        </script>
    </body>
    </html>
    """

def error_dashboard(error_msg: str, user_phone: str):
    """HTML למקרה של שגיאה"""
    display_name = user_phone[-4:]
    
    return f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>דשבורד הוצאות חתונה - שגיאה</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; direction: rtl; }}
            .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 50px; border-radius: 15px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; }}
            .error {{ color: #d32f2f; }}
            .btn {{ padding: 10px 20px; margin: 10px; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; }}
            .retry-btn {{ background: #4caf50; color: white; }}
            .logout-btn {{ background: #dc3545; color: white; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="error">
                <h1>❌ שגיאה בטעינת הנתונים</h1>
                <p>משתמש: {display_name}</p>
                <p style="margin: 20px 0;">שגיאה: {error_msg}</p>
                <button onclick="location.reload()" class="btn retry-btn">🔄 נסה שוב</button>
                <a href="#" onclick="logout()" class="btn logout-btn">🚪 יציאה</a>
            </div>
        </div>
        <script>
            async function logout() {{
                await fetch('/auth/logout', {{ method: 'POST', credentials: 'same-origin' }});
                window.location.href = '/login';
            }}
        </script>
    </body>
    </html>
    """
async def dashboard_summary():
    """דשבורד סיכום מקצועי עם גרפים וניתוחים"""
    try:
        # טעינת נתונים מהגיליון
        ensure_google()
        result = sheets.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='A:R'
        ).execute()
        
        values = result.get('values', [])
        if not values or len(values) < 2:
            return no_data_html()
        
        # עיבוד הנתונים
        headers = values[0]
        data_rows = values[1:]
        
        # יצירת מבנה נתונים
        expenses = []
        for row in data_rows:
            if len(row) >= 6:
                try:
                    expense = {
                        'owner_phone': row[1] if len(row) > 1 else '',
                        'date': row[3] if len(row) > 3 else '',
                        'amount': float(row[4]) if len(row) > 4 and row[4] else 0,
                        'currency': row[5] if len(row) > 5 else 'ILS',
                        'vendor': row[6] if len(row) > 6 else '',
                        'category': row[7] if len(row) > 7 else 'אחר',
                        'payment_method': row[8] if len(row) > 8 else '',
                        'drive_file_url': row[11] if len(row) > 11 else ''
                    }
                    if expense['amount'] > 0:
                        expenses.append(expense)
                except (ValueError, IndexError):
                    continue
        
        if not expenses:
            return no_data_html()
        
        # חישובי סיכום
        summary_data = calculate_summary_data(expenses)
        
        # יצירת HTML דינמי
        return generate_summary_html(summary_data, expenses)
        
    except Exception as e:
        return error_html(str(e))

def calculate_summary_data(expenses):
    """חישוב כל הנתונים לסיכום"""
    
    # סטטיסטיקות כלליות
    total_amount = sum(exp['amount'] for exp in expenses)
    total_count = len(expenses)
    avg_amount = total_amount / total_count if total_count > 0 else 0
    
    # קבלות לפי חודש
    monthly_data = defaultdict(lambda: {'count': 0, 'amount': 0, 'categories': defaultdict(float)})
    
    for exp in expenses:
        try:
            # המרת תאריך
            if exp['date']:
                date_parts = exp['date'][:10].split('-')
                if len(date_parts) == 3:
                    year, month, day = date_parts
                    month_key = f"{year}-{month.zfill(2)}"
                else:
                    month_key = "לא ידוע"
            else:
                month_key = "לא ידוע"
            
            monthly_data[month_key]['count'] += 1
            monthly_data[month_key]['amount'] += exp['amount']
            monthly_data[month_key]['categories'][exp['category']] += exp['amount']
            
        except:
            monthly_data["לא ידוע"]['count'] += 1
            monthly_data["לא ידוע"]['amount'] += exp['amount']
            monthly_data["לא ידוע"]['categories'][exp['category']] += exp['amount']
    
    # קבלות לפי קטגוריה
    categories = defaultdict(lambda: {'count': 0, 'amount': 0})
    for exp in expenses:
        cat = exp['category']
        categories[cat]['count'] += 1
        categories[cat]['amount'] += exp['amount']
    
    # ספקים מובילים
    vendors = defaultdict(lambda: {'count': 0, 'amount': 0})
    for exp in expenses:
        vendor = exp['vendor'] or 'לא ידוע'
        vendors[vendor]['count'] += 1
        vendors[vendor]['amount'] += exp['amount']
    
    # הוצאות אחרונות
    recent_expenses = sorted(expenses, key=lambda x: x.get('date', ''), reverse=True)[:15]
    
    return {
        'total_amount': total_amount,
        'total_count': total_count,
        'avg_amount': avg_amount,
        'monthly_data': dict(monthly_data),
        'categories': dict(categories),
        'vendors': dict(vendors),
        'recent_expenses': recent_expenses
    }

def generate_summary_html(data, expenses):
    """יצירת HTML מלא לדשבורד"""
    
    # אמוג'י לקטגוריות
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
    
    # נתוני גרף עוגה לקטגוריות
    categories_chart_data = []
    categories_chart_labels = []
    categories_chart_colors = [
        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', 
        '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF', '#4BC0C0'
    ]
    
    for i, (category, cat_data) in enumerate(sorted(data['categories'].items(), key=lambda x: x[1]['amount'], reverse=True)):
        categories_chart_data.append(cat_data['amount'])
        categories_chart_labels.append(category)
    
    # נתוני גרף עוגה לחודשים
    monthly_chart_data = []
    monthly_chart_labels = []
    
    for month_key in sorted(data['monthly_data'].keys()):
        if month_key != "לא ידוע":
            try:
                # המרת המפתח לתצוגה יפה
                year, month = month_key.split('-')
                month_names = {
                    '01': 'ינואר', '02': 'פברואר', '03': 'מרץ', '04': 'אפריל',
                    '05': 'מאי', '06': 'יוני', '07': 'יולי', '08': 'אוגוסט',
                    '09': 'ספטמבר', '10': 'אוקטובר', '11': 'נובמבר', '12': 'דצמבר'
                }
                month_display = f"{month_names.get(month, month)} {year}"
                monthly_chart_labels.append(month_display)
                monthly_chart_data.append(data['monthly_data'][month_key]['amount'])
            except:
                monthly_chart_labels.append(month_key)
                monthly_chart_data.append(data['monthly_data'][month_key]['amount'])
    
    # אם יש "לא ידוע", הוסף בסוף
    if "לא ידוע" in data['monthly_data']:
        monthly_chart_labels.append("לא ידוע")
        monthly_chart_data.append(data['monthly_data']["לא ידוע"]['amount'])
    
    html = f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>דשבורד סיכום - הוצאות חתונה</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            
            body {{ 
                font-family: 'Segoe UI', Tahoma, Arial, sans-serif; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                direction: rtl;
                padding: 20px;
            }}
            
            .container {{ 
                max-width: 1600px; 
                margin: 0 auto; 
                background: white; 
                border-radius: 20px; 
                box-shadow: 0 20px 60px rgba(0,0,0,0.1);
                overflow: hidden;
            }}
            
            .header {{ 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; 
                padding: 30px;
                text-align: center;
            }}
            
            .header h1 {{ 
                font-size: 2.8rem; 
                margin-bottom: 10px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            }}
            
            .header p {{ 
                font-size: 1.2rem; 
                opacity: 0.9;
            }}
            
            .nav-buttons {{
                text-align: center;
                padding: 20px;
                background: #f8f9fa;
                border-bottom: 1px solid #e9ecef;
            }}
            
            .nav-btn {{
                background: #667eea;
                color: white;
                padding: 12px 24px;
                margin: 0 10px;
                border: none;
                border-radius: 25px;
                text-decoration: none;
                display: inline-block;
                font-weight: bold;
                transition: all 0.3s ease;
            }}
            
            .nav-btn:hover {{
                background: #5a6fd8;
                transform: translateY(-2px);
                box-shadow: 0 8px 15px rgba(0,0,0,0.2);
            }}
            
            .stats-grid {{ 
                display: grid; 
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
                gap: 20px; 
                padding: 30px;
                background: #f8f9fa;
            }}
            
            .stat-card {{ 
                background: white; 
                padding: 25px; 
                border-radius: 15px; 
                text-align: center;
                box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                border-right: 5px solid #667eea;
                transition: transform 0.3s ease;
            }}
            
            .stat-card:hover {{ 
                transform: translateY(-5px);
            }}
            
            .stat-icon {{ 
                font-size: 2.5rem; 
                margin-bottom: 10px;
            }}
            
            .stat-value {{ 
                font-size: 2rem; 
                font-weight: bold; 
                color: #667eea; 
                margin-bottom: 5px;
            }}
            
            .stat-label {{ 
                color: #666; 
                font-size: 0.9rem;
            }}
            
            .content {{ 
                padding: 30px;
            }}
            
            .section {{ 
                margin-bottom: 50px;
            }}
            
            .section h2 {{ 
                color: #333; 
                margin-bottom: 25px; 
                padding-bottom: 15px; 
                border-bottom: 3px solid #667eea;
                font-size: 1.8rem;
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            
            .charts-container {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                gap: 30px;
                margin-bottom: 40px;
            }}
            
            .chart-card {{
                background: white;
                border-radius: 15px;
                padding: 25px;
                box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                border: 1px solid #e9ecef;
            }}
            
            .chart-title {{
                font-size: 1.3rem;
                font-weight: bold;
                color: #333;
                margin-bottom: 20px;
                text-align: center;
            }}
            
            .chart-container {{
                position: relative;
                height: 300px;
            }}
            
            .monthly-summary {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }}
            
            .month-card {{
                background: white;
                border: 2px solid #e9ecef;
                border-radius: 12px;
                padding: 20px;
                transition: all 0.3s ease;
            }}
            
            .month-card:hover {{
                border-color: #667eea;
                transform: translateY(-2px);
                box-shadow: 0 8px 20px rgba(0,0,0,0.1);
            }}
            
            .month-title {{
                font-size: 1.2rem;
                font-weight: bold;
                color: #333;
                margin-bottom: 10px;
                text-align: center;
            }}
            
            .month-amount {{
                font-size: 1.5rem;
                font-weight: bold;
                color: #667eea;
                text-align: center;
                margin-bottom: 10px;
            }}
            
            .month-count {{
                color: #666;
                text-align: center;
                margin-bottom: 15px;
            }}
            
            .month-categories {{
                border-top: 1px solid #eee;
                padding-top: 15px;
            }}
            
            .month-category {{
                display: flex;
                justify-content: space-between;
                padding: 5px 0;
                font-size: 0.9rem;
            }}
            
            .table-container {{ 
                background: white; 
                border-radius: 12px; 
                overflow: hidden; 
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                margin-bottom: 30px;
            }}
            
            .table {{ 
                width: 100%; 
                border-collapse: collapse;
            }}
            
            .table th {{ 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                color: white; 
                padding: 15px; 
                text-align: center; 
                font-weight: bold;
                position: sticky;
                top: 0;
                z-index: 10;
            }}
            
            .table td {{ 
                padding: 12px; 
                text-align: center; 
                border-bottom: 1px solid #eee;
            }}
            
            .table tr:hover {{ 
                background: #f8f9fa;
            }}
            
            .table tr:nth-child(even) {{ 
                background: #fafafa;
            }}
            
            .amount-cell {{ 
                font-weight: bold; 
                color: #667eea;
            }}
            
            .link-button {{ 
                background: #667eea; 
                color: white; 
                padding: 6px 12px; 
                border-radius: 6px; 
                text-decoration: none; 
                font-size: 0.8rem;
                transition: all 0.3s ease;
            }}
            
            .link-button:hover {{ 
                background: #5a6fd8; 
                text-decoration: none;
                transform: scale(1.05);
            }}
            
            .vendors-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 30px;
            }}
            
            .vendor-card {{
                background: white;
                border: 1px solid #e9ecef;
                border-radius: 10px;
                padding: 15px;
                text-align: center;
                transition: all 0.3s ease;
            }}
            
            .vendor-card:hover {{
                border-color: #667eea;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            }}
            
            .vendor-name {{
                font-weight: bold;
                color: #333;
                margin-bottom: 8px;
            }}
            
            .vendor-amount {{
                color: #667eea;
                font-size: 1.1rem;
                font-weight: bold;
                margin-bottom: 5px;
            }}
            
            .vendor-count {{
                color: #666;
                font-size: 0.9rem;
            }}
            
            .refresh-btn {{ 
                position: fixed; 
                bottom: 30px; 
                left: 30px; 
                background: #667eea; 
                color: white; 
                border: none; 
                width: 60px; 
                height: 60px; 
                border-radius: 50%; 
                font-size: 1.5rem; 
                cursor: pointer; 
                box-shadow: 0 8px 20px rgba(0,0,0,0.2);
                transition: all 0.3s ease;
                z-index: 1000;
            }}
            
            .refresh-btn:hover {{ 
                background: #5a6fd8; 
                transform: scale(1.1);
            }}
            
            @media (max-width: 768px) {{
                .header h1 {{ font-size: 2rem; }}
                .charts-container {{ grid-template-columns: 1fr; }}
                .monthly-summary {{ grid-template-columns: 1fr; }}
                .vendors-grid {{ grid-template-columns: 1fr; }}
                .stats-grid {{ grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }}
                .table-container {{ overflow-x: auto; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 דשבורד סיכום - הוצאות החתונה</h1>
                <p>ניתוח מקיף ומפורט של כל ההוצאות שלכם</p>
            </div>
            
            <div class="nav-buttons">
                <a href="/dashboard" class="nav-btn">📋 דשבורד ראשי</a>
                <a href="/dashboard-summary" class="nav-btn">📊 דשבורד סיכום</a>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-icon">💰</div>
                    <div class="stat-value">{data['total_amount']:,.0f} ₪</div>
                    <div class="stat-label">סך ההוצאות</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">📄</div>
                    <div class="stat-value">{data['total_count']}</div>
                    <div class="stat-label">מספר קבלות</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">📊</div>
                    <div class="stat-value">{data['avg_amount']:,.0f} ₪</div>
                    <div class="stat-label">ממוצע לקבלה</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">🏷️</div>
                    <div class="stat-value">{len(data['categories'])}</div>
                    <div class="stat-label">קטגוריות</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">📅</div>
                    <div class="stat-value">{len(data['monthly_data'])}</div>
                    <div class="stat-label">חודשים פעילים</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">🏪</div>
                    <div class="stat-value">{len(data['vendors'])}</div>
                    <div class="stat-label">ספקים</div>
                </div>
            </div>
            
            <div class="content">
                <!-- גרפי עוגה -->
                <div class="section">
                    <h2>🥧 ניתוח גרפי</h2>
                    <div class="charts-container">
                        <div class="chart-card">
                            <div class="chart-title">🏷️ הוצאות לפי קטגוריה</div>
                            <div class="chart-container">
                                <canvas id="categoriesChart"></canvas>
                            </div>
                        </div>
                        <div class="chart-card">
                            <div class="chart-title">📅 הוצאות לפי חודש</div>
                            <div class="chart-container">
                                <canvas id="monthlyChart"></canvas>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- סיכום חודשי -->
                <div class="section">
                    <h2>📅 סיכום חודשי מפורט</h2>
                    <div class="monthly-summary">
    """
    
    # הוספת כרטיסי חודשים
    for month_key in sorted(data['monthly_data'].keys()):
        month_data = data['monthly_data'][month_key]
        
        # המרת שם החודש
        if month_key != "לא ידוע":
            try:
                year, month = month_key.split('-')
                month_names = {
                    '01': 'ינואר', '02': 'פברואר', '03': 'מרץ', '04': 'אפריל',
                    '05': 'מאי', '06': 'יוני', '07': 'יולי', '08': 'אוגוסט',
                    '09': 'ספטמבר', '10': 'אוקטובר', '11': 'נובמבר', '12': 'דצמבר'
                }
                month_display = f"{month_names.get(month, month)} {year}"
            except:
                month_display = month_key
        else:
            month_display = "לא ידוע"
        
        html += f"""
                        <div class="month-card">
                            <div class="month-title">📅 {month_display}</div>
                            <div class="month-amount">{month_data['amount']:,.0f} ₪</div>
                            <div class="month-count">{month_data['count']} קבלות</div>
                            <div class="month-categories">
        """
        
        # הוספת קטגוריות בחודש
        for category, amount in sorted(month_data['categories'].items(), key=lambda x: x[1], reverse=True):
            emoji = category_emojis.get(category, "📋")
            html += f"""
                                <div class="month-category">
                                    <span>{emoji} {category}</span>
                                    <span>{amount:,.0f} ₪</span>
                                </div>
            """
        
        html += """
                            </div>
                        </div>
        """
    
    html += """
                    </div>
                </div>
                
                <!-- ספקים מובילים -->
                <div class="section">
                    <h2>🏪 הספקים המובילים</h2>
                    <div class="vendors-grid">
    """
    
    # הוספת כרטיסי ספקים (10 הראשונים)
    top_vendors = sorted(data['vendors'].items(), key=lambda x: x[1]['amount'], reverse=True)[:10]
    
    for vendor, vendor_data in top_vendors:
        html += f"""
                        <div class="vendor-card">
                            <div class="vendor-name">🏪 {vendor}</div>
                            <div class="vendor-amount">{vendor_data['amount']:,.0f} ₪</div>
                            <div class="vendor-count">{vendor_data['count']} קניות</div>
                        </div>
        """
    
    html += """
                    </div>
                </div>
                
                <!-- טבלת הוצאות מפורטת -->
                <div class="section">
                    <h2>📋 כל ההוצאות המפורטות</h2>
                    <div class="table-container">
                        <table class="table">
                            <thead>
                                <tr>
                                    <th>תאריך</th>
                                    <th>ספק</th>
                                    <th>סכום</th>
                                    <th>קטגוריה</th>
                                    <th>אמצעי תשלום</th>
                                    <th>טלפון</th>
                                    <th>קבלה</th>
                                </tr>
                            </thead>
                            <tbody>
    """
    
    # הוספת שורות הוצאות (כל ההוצאות)
    for expense in data['recent_expenses']:
        date_display = expense['date'][:10] if expense['date'] else 'לא ידוע'
        vendor = expense['vendor'] or 'לא ידוע'
        amount = f"{expense['amount']:,.0f} ₪"
        category = expense['category']
        emoji = category_emojis.get(category, "📋")
        
        payment_display = {
            'card': 'כרטיס אשראי',
            'cash': 'מזומן',
            'bank': 'העברה בנקאית'
        }.get(expense['payment_method'], expense['payment_method'] or 'לא ידוע')
        
        phone = expense['owner_phone'][-4:] if expense['owner_phone'] else 'לא ידוע'
        
        receipt_link = ""
        if expense['drive_file_url']:
            receipt_link = f'<a href="{expense["drive_file_url"]}" target="_blank" class="link-button">📄 צפה</a>'
        else:
            receipt_link = '<span style="color: #999;">לא זמין</span>'
        
        html += f"""
                                <tr>
                                    <td>{date_display}</td>
                                    <td>{vendor}</td>
                                    <td class="amount-cell">{amount}</td>
                                    <td>{emoji} {category}</td>
                                    <td>{payment_display}</td>
                                    <td>****{phone}</td>
                                    <td>{receipt_link}</td>
                                </tr>
        """
    
    # סיום ה-HTML עם הסקריפטים לגרפים
    html += f"""
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        
        <button class="refresh-btn" onclick="location.reload()" title="רענן נתונים">🔄</button>
        
        <script>
            // הגדרת Chart.js בעברית
            Chart.defaults.font.family = "Segoe UI, Tahoma, Arial, sans-serif";
            Chart.defaults.font.size = 12;
            
            // גרף עוגה לקטגוריות
            const categoriesCtx = document.getElementById('categoriesChart').getContext('2d');
            new Chart(categoriesCtx, {{
                type: 'pie',
                data: {{
                    labels: {categories_chart_labels},
                    datasets: [{{
                        data: {categories_chart_data},
                        backgroundColor: {categories_chart_colors[:len(categories_chart_data)]},
                        borderWidth: 2,
                        borderColor: '#fff'
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{
                                padding: 20,
                                usePointStyle: true,
                                font: {{
                                    size: 11
                                }}
                            }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const label = context.label || '';
                                    const value = context.parsed || 0;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = ((value / total) * 100).toFixed(1);
                                    return `${{label}}: ${{value.toLocaleString()}} ₪ (${{percentage}}%)`;
                                }}
                            }}
                        }}
                    }}
                }}
            }});
            
            // גרף עוגה לחודשים
            const monthlyCtx = document.getElementById('monthlyChart').getContext('2d');
            new Chart(monthlyCtx, {{
                type: 'doughnut',
                data: {{
                    labels: {monthly_chart_labels},
                    datasets: [{{
                        data: {monthly_chart_data},
                        backgroundColor: [
                            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', 
                            '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF',
                            '#4BC0C0', '#36A2EB', '#FFCE56', '#FF6384'
                        ],
                        borderWidth: 2,
                        borderColor: '#fff'
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{
                                padding: 20,
                                usePointStyle: true,
                                font: {{
                                    size: 11
                                }}
                            }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const label = context.label || '';
                                    const value = context.parsed || 0;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = ((value / total) * 100).toFixed(1);
                                    return `${{label}}: ${{value.toLocaleString()}} ₪ (${{percentage}}%)`;
                                }}
                            }}
                        }}
                    }}
                }}
            }});
            
            // רענון אוטומטי כל 5 דקות
            setTimeout(function() {{
                location.reload();
            }}, 300000);
            
            // אנימציות טעינה
            document.addEventListener('DOMContentLoaded', function() {{
                const cards = document.querySelectorAll('.stat-card, .month-card, .vendor-card, .chart-card');
                cards.forEach((card, index) => {{
                    card.style.animationDelay = (index * 0.05) + 's';
                    card.style.animation = 'fadeInUp 0.6s ease forwards';
                }});
                
                // אנימציה לטבלה
                const tableRows = document.querySelectorAll('.table tbody tr');
                tableRows.forEach((row, index) => {{
                    row.style.animationDelay = (index * 0.02) + 's';
                    row.style.animation = 'fadeIn 0.4s ease forwards';
                }});
            }});
            
            // פונקציה להדפסה
            function printDashboard() {{
                window.print();
            }}
            
            // הוספת כפתור הדפסה
            const printBtn = document.createElement('button');
            printBtn.innerHTML = '🖨️';
            printBtn.className = 'refresh-btn';
            printBtn.style.bottom = '100px';
            printBtn.title = 'הדפס דוח';
            printBtn.onclick = printDashboard;
            document.body.appendChild(printBtn);
        </script>
        
        <style>
            @keyframes fadeInUp {{
                from {{
                    opacity: 0;
                    transform: translateY(30px);
                }}
                to {{
                    opacity: 1;
                    transform: translateY(0);
                }}
            }}
            
            @keyframes fadeIn {{
                from {{
                    opacity: 0;
                }}
                to {{
                    opacity: 1;
                }}
            }}
            
            /* עיצוב להדפסה */
            @media print {{
                body {{
                    background: white !important;
                    padding: 0 !important;
                }}
                
                .container {{
                    box-shadow: none !important;
                    border-radius: 0 !important;
                }}
                
                .refresh-btn {{
                    display: none !important;
                }}
                
                .nav-buttons {{
                    display: none !important;
                }}
                
                .chart-container {{
                    height: 200px !important;
                }}
            }}
        </style>
    </body>
    </html>
    """
    
    return html

def no_data_html():
    """HTML למקרה שאין נתונים"""
    return """
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>דשבורד סיכום - אין נתונים</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; direction: rtl; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 50px; border-radius: 15px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; }
            .no-data { color: #666; }
            .nav-btn { background: #667eea; color: white; padding: 12px 24px; margin: 10px; border: none; border-radius: 25px; text-decoration: none; display: inline-block; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="no-data">
                <h1>📊 דשבורד סיכום - הוצאות החתונה</h1>
                <p style="font-size: 1.2rem; margin: 30px 0;">📝 עדיין לא הועלו הוצאות</p>
                <p>התחילו לשלוח קבלות בווטסאפ כדי לראות ניתוחים מפורטים!</p>
                <a href="/dashboard" class="nav-btn">📋 חזור לדשבורד הראשי</a>
            </div>
        </div>
    </body>
    </html>
    """

def error_html(error_msg):
    """HTML למקרה של שגיאה"""
    return f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>דשבורד סיכום - שגיאה</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; direction: rtl; }}
            .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 50px; border-radius: 15px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; }}
            .error {{ color: #d32f2f; }}
            .nav-btn {{ background: #667eea; color: white; padding: 12px 24px; margin: 10px; border: none; border-radius: 25px; text-decoration: none; display: inline-block; }}
            .retry-btn {{ background: #4caf50; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; margin: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="error">
                <h1>❌ שגיאה בטעינת הנתונים</h1>
                <p style="font-size: 1.1rem; margin: 20px 0;">אירעה שגיאה בגישה לגיליון:</p>
                <code style="background: #f5f5f5; padding: 10px; border-radius: 5px; display: block; margin: 20px 0;">{error_msg}</code>
                <p>נסו לרענן את הדף או צרו קשר עם התמיכה</p>
                <button onclick="location.reload()" class="retry-btn">🔄 נסה שוב</button>
                <a href="/dashboard" class="nav-btn">📋 חזור לדשבורד הראשי</a>
            </div>
        </div>
    </body>
    </html>
    """