@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """דשבורד מקצועי עם נתונים אמיתיים"""
    try:
        # טעינת נתונים מהגיליון
        ensure_google()
        result = sheets.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='A:R'  # כל העמודות
        ).execute()
        
        values = result.get('values', [])
        if not values or len(values) < 2:
            # אם אין נתונים
            return """
            <!DOCTYPE html>
            <html dir="rtl">
            <head>
                <meta charset="UTF-8">
                <title>דשבורד הוצאות חתונה</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; direction: rtl; }
                    .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
                    .no-data { text-align: center; padding: 50px; color: #666; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="no-data">
                        <h1>💒 דשבורד הוצאות החתונה</h1>
                        <p>📝 עדיין לא הועלו הוצאות</p>
                        <p>התחילו לשלוח קבלות בווטסאפ כדי לראות נתונים!</p>
                    </div>
                </div>
            </body>
            </html>
            """
        
        # עיבוד הנתונים
        headers = values[0]
        data_rows = values[1:]
        
        # יצירת מבנה נתונים
        expenses = []
        for row in data_rows:
            if len(row) >= 6:  # ודא שיש מספיק עמודות
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
                    if expense['amount'] > 0:  # רק הוצאות עם סכום
                        expenses.append(expense)
                except (ValueError, IndexError):
                    continue
        
        if not expenses:
            return """
            <!DOCTYPE html>
            <html dir="rtl">
            <head>
                <meta charset="UTF-8">
                <title>דשבורד הוצאות חתונה</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; direction: rtl; }
                    .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
                    .no-data { text-align: center; padding: 50px; color: #666; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="no-data">
                        <h1>💒 דשבורד הוצאות החתונה</h1>
                        <p>📊 נמצאו נתונים אך אין הוצאות תקינות</p>
                        <p>בדקו שהנתונים בגיליון תקינים</p>
                    </div>
                </div>
            </body>
            </html>
            """
        
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
        
        # יצירת HTML דינמי
        dashboard_html = f"""
        <!DOCTYPE html>
        <html dir="rtl">
        <head>
            <meta charset="UTF-8">
            <title>דשבורד הוצאות חתונה</title>
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
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>💒 דשבורד הוצאות החתונה</h1>
                    <p>סיכום מלא של ההוצאות שלכם</p>
                </div>
                
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-icon">💰</div>
                        <div class="stat-value">{total_amount:,.0f} ₪</div>
                        <div class="stat-label">סך ההוצאות</div>
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
                                        <td>{category_emojis.get(category, "📋")} {category}</td>
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
        # במקרה של שגיאה
        return f"""
        <!DOCTYPE html>
        <html dir="rtl">
        <head>
            <meta charset="UTF-8">
            <title>דשבורד הוצאות חתונה - שגיאה</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; direction: rtl; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }}
                .error {{ text-align: center; padding: 50px; color: #d32f2f; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="error">
                    <h1>❌ שגיאה בטעינת הנתונים</h1>
                    <p>אירעה שגיאה בגישה לגיליון: {str(e)}</p>
                    <p>נסו לרענן את הדף או צרו קשר עם התמיכה</p>
                    <button onclick="location.reload()" style="padding: 10px 20px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer;">🔄 נסה שוב</button>
                </div>
            </div>
        </body>
        </html>
        """