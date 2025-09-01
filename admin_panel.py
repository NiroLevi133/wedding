import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
from database_manager import DatabaseManager
from config import WEDDING_CATEGORIES, AI_SETTINGS
from zoneinfo import ZoneInfo
import os
logger = logging.getLogger(__name__)

DEFAULT_TZ = ZoneInfo(os.getenv("DEFAULT_TIMEZONE", "UTC"))

now = datetime.now(DEFAULT_TZ)

class AdminPanel:
    """מנהל דשבורד מנהל המערכת"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def get_dashboard_html(self) -> str:
        """מחזיר HTML מלא לדשבורד המנהל"""
        try:
            stats = await self.get_system_stats()
            couples = await self.get_couples_data()
            
            return self._generate_admin_html(stats, couples)
            
        except Exception as e:
            logger.error(f"Admin dashboard generation failed: {e}")
            return self._error_html(f"שגיאה בטעינת דשבורד המנהל: {str(e)}")
    
    async def get_system_stats(self) -> Dict:
        """מחזיר סטטיסטיקות כלליות של המערכת"""
        try:
            # קבלת כל הזוגות והוצאות
            couples = self.db.get_all_active_couples()
            total_couples = len(couples)
            
            # סטטיסטיקות הוצאות
            total_expenses = 0
            total_amount = 0
            categories_stats = defaultdict(lambda: {'count': 0, 'amount': 0})
            monthly_stats = defaultdict(lambda: {'count': 0, 'amount': 0})
            needs_review_count = 0
            
            # ספירת הוצאות לפי קבוצה
            for couple in couples:
                group_id = couple.get('whatsapp_group_id')
                if not group_id:
                    continue
                
                expenses = self.db.get_expenses_by_group(group_id)
                
                for expense in expenses:
                    if expense.get('status') != 'active':
                        continue
                    
                    amount = float(expense.get('amount', 0))
                    if amount <= 0:
                        continue
                    
                    total_expenses += 1
                    total_amount += amount
                    
                    # סטטיסטיקות קטגוריות
                    category = expense.get('category', 'אחר')
                    categories_stats[category]['count'] += 1
                    categories_stats[category]['amount'] += amount
                    
                    # סטטיסטיקות חודשיות
                    date_str = expense.get('date', '')
                    if date_str:
                        try:
                            date_obj = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=DEFAULT_TZ)
                            month_key = date_obj.strftime('%Y-%m')
                            monthly_stats[month_key]['count'] += 1
                            monthly_stats[month_key]['amount'] += amount
                        except ValueError:
                            pass
                    
                    # צריך בדיקה
                    if expense.get('needs_review') == 'true' or expense.get('needs_review') is True:
                        needs_review_count += 1
            
            # חישוב ממוצעים
            avg_expenses_per_couple = total_expenses / total_couples if total_couples > 0 else 0
            avg_amount_per_expense = total_amount / total_expenses if total_expenses > 0 else 0
            
            return {
                'total_couples': total_couples,
                'total_expenses': total_expenses,
                'total_amount': total_amount,
                'avg_expenses_per_couple': avg_expenses_per_couple,
                'avg_amount_per_expense': avg_amount_per_expense,
                'needs_review_count': needs_review_count,
                'categories_stats': dict(categories_stats),
                'monthly_stats': dict(monthly_stats),
                'last_updated': datetime.now(DEFAULT_TZ).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to get system stats: {e}")
            return {'error': str(e)}
    
    async def get_couples_data(self) -> List[Dict]:
        """מחזיר נתוני כל הזוגות עם סטטיסטיקות"""
        try:
            couples = self.db.get_all_active_couples()
            couples_data = []
            
            for couple in couples:
                group_id = couple.get('whatsapp_group_id')
                
                # בסיסי
                couple_info = {
                    'group_id': group_id,
                    'phone1': couple.get('phone1', ''),
                    'phone2': couple.get('phone2', ''),
                    'wedding_date': couple.get('wedding_date', ''),
                    'budget': couple.get('budget', ''),
                    'status': couple.get('status', 'active'),
                    'created_at': couple.get('created_at', ''),
                    'total_expenses': 0,
                    'total_amount': 0,
                    'last_activity': None,
                    'needs_review_count': 0
                }
                
                if not group_id:
                    couples_data.append(couple_info)
                    continue
                
                # הוצאות הקבוצה
                expenses = self.db.get_expenses_by_group(group_id)
                
                total_amount = 0
                active_expenses = 0
                needs_review = 0
                last_activity = None
                
                for expense in expenses:
                    if expense.get('status') != 'active':
                        continue
                    
                    active_expenses += 1
                    amount = float(expense.get('amount', 0))
                    total_amount += amount
                    
                    if expense.get('needs_review') == 'true' or expense.get('needs_review') is True:
                        needs_review += 1
                    
                    # פעילות אחרונה
                    created_at = expense.get('created_at', '')
                    if created_at:
                        try:
                            expense_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            if expense_date.tzinfo is None:
                                expense_date = expense_date.replace(tzinfo=DEFAULT_TZ)
                            if not last_activity or expense_date > last_activity:
                                last_activity = expense_date
                        except ValueError:
                            pass
                
                couple_info.update({
                    'total_expenses': active_expenses,
                    'total_amount': total_amount,
                    'last_activity': last_activity.isoformat() if last_activity else None,
                    'needs_review_count': needs_review
                })
                
                couples_data.append(couple_info)
            
            # מיון לפי פעילות אחרונה
            couples_data.sort(key=lambda x: x['last_activity'] or '', reverse=True)
            
            return couples_data
            
        except Exception as e:
            logger.error(f"Failed to get couples data: {e}")
            return []
    
    async def get_group_expenses(self, group_id: str) -> Dict:
        """מחזיר הוצאות של קבוצה ספציפית"""
        try:
            expenses = self.db.get_expenses_by_group(group_id, include_deleted=True)
            couple = self.db.get_couple_by_group_id(group_id)
            
            return {
                'group_id': group_id,
                'couple_info': couple,
                'expenses': expenses,
                'total_active': len([e for e in expenses if e.get('status') == 'active']),
                'total_deleted': len([e for e in expenses if e.get('status') == 'deleted']),
                'needs_review': len([e for e in expenses if e.get('needs_review') == 'true']),
                'total_amount': sum(float(e.get('amount', 0)) for e in expenses if e.get('status') == 'active')
            }
            
        except Exception as e:
            logger.error(f"Failed to get group expenses: {e}")
            return {'error': str(e)}
    
    def _generate_admin_html(self, stats: Dict, couples: List[Dict]) -> str:
        """יוצר HTML מלא לדשבורד המנהל"""
        
        return f"""
        <!DOCTYPE html>
        <html dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>דשבורד מנהל - מערכת הוצאות חתונה</title>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                
                body {{ 
                    font-family: 'Segoe UI', Tahoma, Arial, sans-serif; 
                    background: #f8f9fa;
                    min-height: 100vh;
                    direction: rtl;
                }}
                
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 20px;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                }}
                
                .header h1 {{
                    font-size: 2rem;
                    margin-bottom: 5px;
                }}
                
                .header p {{
                    opacity: 0.9;
                    font-size: 1rem;
                }}
                
                .container {{
                    max-width: 1600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                
                .stats-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 20px;
                    margin-bottom: 30px;
                }}
                
                .stat-card {{
                    background: white;
                    padding: 25px;
                    border-radius: 12px;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                    border-left: 5px solid #667eea;
                }}
                
                .stat-icon {{
                    font-size: 2.5rem;
                    margin-bottom: 15px;
                }}
                
                .stat-value {{
                    font-size: 2.2rem;
                    font-weight: bold;
                    color: #667eea;
                    margin-bottom: 5px;
                }}
                
                .stat-label {{
                    color: #666;
                    font-size: 0.9rem;
                }}
                
                .section {{
                    background: white;
                    border-radius: 12px;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                    margin-bottom: 30px;
                    overflow: hidden;
                }}
                
                .section-header {{
                    background: #667eea;
                    color: white;
                    padding: 20px;
                    font-size: 1.3rem;
                    font-weight: bold;
                }}
                
                .section-content {{
                    padding: 25px;
                }}
                
                .couples-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 15px;
                }}
                
                .couples-table th {{
                    background: #f8f9fa;
                    padding: 15px;
                    text-align: right;
                    border-bottom: 2px solid #dee2e6;
                    font-weight: bold;
                }}
                
                .couples-table td {{
                    padding: 12px 15px;
                    border-bottom: 1px solid #dee2e6;
                    vertical-align: middle;
                }}
                
                .couples-table tr:hover {{
                    background: #f8f9fa;
                }}
                
                .status-badge {{
                    padding: 4px 8px;
                    border-radius: 20px;
                    font-size: 0.8rem;
                    font-weight: bold;
                }}
                
                .status-active {{
                    background: #d4edda;
                    color: #155724;
                }}
                
                .status-inactive {{
                    background: #f8d7da;
                    color: #721c24;
                }}
                
                .amount {{
                    font-weight: bold;
                    color: #667eea;
                }}
                
                .needs-review {{
                    background: #fff3cd;
                    color: #856404;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-size: 0.8rem;
                }}
                
                .btn {{
                    padding: 6px 12px;
                    border: none;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 0.8rem;
                    margin: 2px;
                    text-decoration: none;
                    display: inline-block;
                }}
                
                .btn-primary {{
                    background: #667eea;
                    color: white;
                }}
                
                .btn-success {{
                    background: #28a745;
                    color: white;
                }}
                
                .btn-warning {{
                    background: #ffc107;
                    color: #212529;
                }}
                
                .btn:hover {{
                    opacity: 0.8;
                }}
                
                .charts-container {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                    gap: 25px;
                    margin-bottom: 30px;
                }}
                
                .chart-card {{
                    background: white;
                    border-radius: 12px;
                    padding: 25px;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                }}
                
                .chart-title {{
                    font-size: 1.2rem;
                    font-weight: bold;
                    color: #333;
                    margin-bottom: 20px;
                    text-align: center;
                }}
                
                .chart-container {{
                    position: relative;
                    height: 300px;
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
                    box-shadow: 0 4px 15px rgba(0,0,0,0.2);
                    z-index: 1000;
                }}
                
                .refresh-btn:hover {{
                    background: #5a6fd8;
                    transform: scale(1.1);
                }}
                
                @media (max-width: 768px) {{
                    .stats-grid {{
                        grid-template-columns: repeat(2, 1fr);
                    }}
                    
                    .couples-table {{
                        font-size: 0.8rem;
                    }}
                    
                    .couples-table th,
                    .couples-table td {{
                        padding: 8px;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🛠️ דשבורד מנהל המערכת</h1>
                <p>ניהול וניטור מערכת הוצאות החתונה</p>
            </div>
            
            <div class="container">
                <!-- סטטיסטיקות כלליות -->
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-icon">👥</div>
                        <div class="stat-value">{stats.get('total_couples', 0)}</div>
                        <div class="stat-label">זוגות פעילים</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon">📄</div>
                        <div class="stat-value">{stats.get('total_expenses', 0)}</div>
                        <div class="stat-label">סה״כ קבלות</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon">💰</div>
                        <div class="stat-value">{stats.get('total_amount', 0):,.0f} ₪</div>
                        <div class="stat-label">סה״כ הוצאות</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon">📊</div>
                        <div class="stat-value">{stats.get('avg_amount_per_expense', 0):,.0f} ₪</div>
                        <div class="stat-label">ממוצע לקבלה</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon">⚠️</div>
                        <div class="stat-value">{stats.get('needs_review_count', 0)}</div>
                        <div class="stat-label">דורש בדיקה</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon">📈</div>
                        <div class="stat-value">{stats.get('avg_expenses_per_couple', 0):.1f}</div>
                        <div class="stat-label">ממוצע קבלות לזוג</div>
                    </div>
                </div>
                
                <!-- גרפים -->
                <div class="charts-container">
                    <div class="chart-card">
                        <div class="chart-title">הוצאות לפי קטגוריה</div>
                        <div class="chart-container">
                            <canvas id="categoriesChart"></canvas>
                        </div>
                    </div>
                    <div class="chart-card">
                        <div class="chart-title">מגמה חודשית</div>
                        <div class="chart-container">
                            <canvas id="monthlyChart"></canvas>
                        </div>
                    </div>
                </div>
                
                
                <!-- טבלת זוגות -->
                <div class="section">
                    <div class="section-header">
                        ➕ הוספת זוג חדש
                    </div>
                    <div class="section-content">
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px;">
                            <div>
                                <label style="display: block; margin-bottom: 5px; font-weight: bold;">📱 טלפון חתן:</label>
                                <input type="tel" id="phone1" class="form-input" placeholder="+972501234567" style="width: 100%; padding: 10px; border: 2px solid #ddd; border-radius: 8px;">
                            </div>
                            <div>
                                <label style="display: block; margin-bottom: 5px; font-weight: bold;">📱 טלפון כלה:</label>
                                <input type="tel" id="phone2" class="form-input" placeholder="+972502345678" style="width: 100%; padding: 10px; border: 2px solid #ddd; border-radius: 8px;">
                            </div>
                            <div>
                                <label style="display: block; margin-bottom: 5px; font-weight: bold;">📅 תאריך חתונה:</label>
                                <input type="date" id="weddingDate" class="form-input" style="width: 100%; padding: 10px; border: 2px solid #ddd; border-radius: 8px;">
                            </div>
                            <div>
                                <label style="display: block; margin-bottom: 5px; font-weight: bold;">💰 תקציב:</label>
                                <input type="number" id="budget" class="form-input" placeholder="80000" style="width: 100%; padding: 10px; border: 2px solid #ddd; border-radius: 8px;">
                            </div>
                        </div>
                        <button onclick="createNewCouple()" class="btn btn-success" style="padding: 12px 24px; font-size: 1rem;">
                            🚀 צור קבוצה ושלח הודעת פתיחה
                        </button>
                        <div id="createStatus" style="margin-top: 15px; padding: 10px; border-radius: 8px; display: none;"></div>
                    </div>
                </div>
                
                <!-- טבלת זוגות -->
                <div class="section">
                    <div class="section-header">
                        👥 ניהול זוגות ({len(couples)} זוגות)
                    </div>
                    <div class="section-content">
                        <table class="couples-table">
                            <thead>
                                <tr>
                                    <th>קבוצה</th>
                                    <th>טלפון 1</th>
                                    <th>טלפון 2</th>
                                    <th>תאריך חתונה</th>
                                    <th>תקציב</th>
                                    <th>קבלות</th>
                                    <th>הוצאות</th>
                                    <th>דורש בדיקה</th>
                                    <th>פעילות אחרונה</th>
                                    <th>פעולות</th>
                                </tr>
                            </thead>
                            <tbody>
                                {self._generate_couples_table_rows(couples)}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            
            <button class="refresh-btn" onclick="location.reload()" title="רענן נתונים">🔄</button>
            
            <script>
                // נתוני גרפים
                const categoriesStats = {json.dumps(stats.get('categories_stats', {}))};
                const monthlyStats = {json.dumps(stats.get('monthly_stats', {}))};
                
                // גרף קטגוריות
                const categoriesCtx = document.getElementById('categoriesChart').getContext('2d');
                const categoriesLabels = Object.keys(categoriesStats).map(cat => `{WEDDING_CATEGORIES.get('${{cat}}', '📋')} ${{cat}}`);
                const categoriesData = Object.values(categoriesStats).map(stat => stat.amount);
                
                new Chart(categoriesCtx, {{
                    type: 'doughnut',
                    data: {{
                        labels: categoriesLabels,
                        datasets: [{{
                            data: categoriesData,
                            backgroundColor: [
                                '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0',
                                '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF',
                                '#4BC0C0', '#36A2EB'
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
                                    padding: 15,
                                    usePointStyle: true,
                                    font: {{ size: 10 }}
                                }}
                            }},
                            tooltip: {{
                                callbacks: {{
                                    label: function(context) {{
                                        const value = context.parsed || 0;
                                        return `${{context.label}}: ${{value.toLocaleString()}} ₪`;
                                    }}
                                }}
                            }}
                        }}
                    }}
                }});
                
                // גרף חודשי
                const monthlyCtx = document.getElementById('monthlyChart').getContext('2d');
                const monthlyLabels = Object.keys(monthlyStats).sort();
                const monthlyData = monthlyLabels.map(month => monthlyStats[month].amount);
                
                new Chart(monthlyCtx, {{
                    type: 'line',
                    data: {{
                        labels: monthlyLabels.map(m => {{
                            const [year, month] = m.split('-');
                            const monthNames = {{
                                '01': 'ינו׳', '02': 'פבר׳', '03': 'מרץ', '04': 'אפר׳',
                                '05': 'מאי', '06': 'יונ׳', '07': 'יול׳', '08': 'אוג׳',
                                '09': 'ספט׳', '10': 'אוק׳', '11': 'נוב׳', '12': 'דצמ׳'
                            }};
                            return `${{monthNames[month] || month}} ${{year}}`;
                        }}),
                        datasets: [{{
                            label: 'הוצאות (₪)',
                            data: monthlyData,
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            borderWidth: 3,
                            fill: true,
                            tension: 0.4
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{ display: false }},
                            tooltip: {{
                                callbacks: {{
                                    label: function(context) {{
                                        return `${{context.parsed.y.toLocaleString()}} ₪`;
                                    }}
                                }}
                            }}
                        }},
                        scales: {{
                            y: {{
                                beginAtZero: true,
                                ticks: {{
                                    callback: function(value) {{
                                        return value.toLocaleString() + ' ₪';
                                    }}
                                }}
                            }}
                        }}
                    }}
                }});
                
                // פונקציות אדמין
                async function createNewCouple() {{
                    const phone1 = document.getElementById('phone1').value.trim();
                    const phone2 = document.getElementById('phone2').value.trim();
                    const weddingDate = document.getElementById('weddingDate').value;
                    const budget = document.getElementById('budget').value;
                    const statusDiv = document.getElementById('createStatus');
                    
                    // ולידציה בסיסית
                    if (!phone1 || !phone2) {{
                        statusDiv.innerHTML = '❌ יש למלא את שני מספרי הטלפון';
                        statusDiv.className = 'alert alert-error';
                        statusDiv.style.display = 'block';
                        return;
                    }}
                    
                    if (phone1 === phone2) {{
                        statusDiv.innerHTML = '❌ מספרי הטלפון לא יכולים להיות זהים';
                        statusDiv.className = 'alert alert-error';
                        statusDiv.style.display = 'block';
                        return;
                    }}
                    
                    // הצגת loading
                    statusDiv.innerHTML = '⏳ יוצר קבוצה ושולח הודעת פתיחה...';
                    statusDiv.className = 'alert alert-info';
                    statusDiv.style.display = 'block';
                    
                    try {{
                        const response = await fetch('/admin/api/create-couple', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json',
                                'X-Admin-Token': document.cookie.split('admin_token=')[1]?.split(';')[0]
                            }},
                            body: JSON.stringify({{
                                phone1: phone1,
                                phone2: phone2,
                                wedding_date: weddingDate || null,
                                budget: budget || 'אין עדיין'
                            }})
                        }});
                        
                        const result = await response.json();
                        
                        if (result.success) {{
                            statusDiv.innerHTML = `✅ קבוצה נוצרה בהצלחה!<br>
                                                  📱 קבוצה: ${{result.group_id}}<br>
                                                  💬 הודעת פתיחה נשלחה`;
                            statusDiv.className = 'alert alert-success';
                            
                            // נקה את הטופס
                            document.getElementById('phone1').value = '';
                            document.getElementById('phone2').value = '';
                            document.getElementById('weddingDate').value = '';
                            document.getElementById('budget').value = '';
                            
                            // רענן את הדף אחרי 3 שניות
                            setTimeout(() => {{
                                location.reload();
                            }}, 3000);
                            
                        }} else {{
                            statusDiv.innerHTML = `❌ שגיאה: ${{result.error}}`;
                            statusDiv.className = 'alert alert-error';
                        }}
                        
                    }} catch (error) {{
                        statusDiv.innerHTML = `❌ שגיאה בחיבור: ${{error.message}}`;
                        statusDiv.className = 'alert alert-error';
                    }}
                }}
                
                async function sendSummary(groupId) {{
                    if (!confirm('שלח סיכום שבועי לקבוצה זו?')) return;
                    
                    try {{
                        const response = await fetch(`/admin/api/send-summary/${{groupId}}`, {{
                            method: 'POST',
                            credentials: 'same-origin'
                        }});
                        
                        const result = await response.json();
                        
                        if (result.success) {{
                            alert('סיכום נשלח בהצלחה!');
                        }} else {{
                            alert('שגיאה בשליחת הסיכום');
                        }}
                    }} catch (error) {{
                        alert('שגיאה בחיבור לשרת');
                    }}
                }}
                
                function viewExpenses(groupId) {{
                    window.open(`/dashboard/${{groupId}}`, '_blank');
                }}
                
                // רענון אוטומטי כל 2 דקות
                setTimeout(() => location.reload(), 120000);
            </script>
        </body>
        </html>
        """
    
    def _generate_couples_table_rows(self, couples: List[Dict]) -> str:
        """יוצר שורות טבלת הזוגות"""
        if not couples:
            return "<tr><td colspan='10' style='text-align: center; padding: 40px; color: #666;'>אין זוגות רשומים</td></tr>"
        
        html = ""
        for couple in couples:
            group_id = couple.get('group_id', '')
            phone1 = couple.get('phone1', '')[-4:] if couple.get('phone1') else '----'
            phone2 = couple.get('phone2', '')[-4:] if couple.get('phone2') else '----'
            
            # תאריך חתונה
            wedding_date = couple.get('wedding_date', '')
            if wedding_date:
                try:
                    # ✅ FIX: wedding_date aware
                    date_obj = datetime.strptime(wedding_date, '%Y-%m-%d').replace(tzinfo=DEFAULT_TZ)
                    now = datetime.now(DEFAULT_TZ)
                    wedding_display = date_obj.strftime('%d/%m/%Y')
                    days_left = (date_obj - now).days
                    if days_left > 0:
                        wedding_display += f" ({days_left} ימים)"
                    elif days_left == 0:
                        wedding_display += " (היום!)"
                    else:
                        wedding_display += " (עבר)"
                except ValueError:
                    wedding_display = wedding_date
            else:
                wedding_display = "לא הוגדר"
            
            budget = couple.get('budget', '')
            if budget and budget != 'אין עדיין':
                try:
                    budget_display = f"{float(budget):,.0f} ₪"
                except ValueError:
                    budget_display = budget
            else:
                budget_display = "לא הוגדר"
            
            last_activity = couple.get('last_activity')
            if last_activity:
                try:
                    activity_date = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                    # ✅ FIX: לוודא tzinfo
                    if activity_date.tzinfo is None:
                        activity_date = activity_date.replace(tzinfo=DEFAULT_TZ)
                    now = datetime.now(DEFAULT_TZ)
                    days_ago = (now - activity_date).days
                    
                    if days_ago == 0:
                        activity_display = "היום"
                    elif days_ago == 1:
                        activity_display = "אתמול"
                    elif days_ago < 7:
                        activity_display = f"לפני {days_ago} ימים"
                    else:
                        activity_display = activity_date.strftime('%d/%m')
                except ValueError:
                    activity_display = "לא ידוע"
            else:
                activity_display = "אף פעם"
            
            # סטטוס
            status = couple.get('status', 'active')
            status_class = 'status-active' if status == 'active' else 'status-inactive'
            status_text = 'פעיל' if status == 'active' else 'לא פעיל'
            
            # צריך בדיקה
            needs_review = couple.get('needs_review_count', 0)
            needs_review_display = f"<span class='needs-review'>{needs_review}</span>" if needs_review > 0 else "0"
            
            html += f"""
                <tr>
                    <td><code>{group_id[:12]}...</code></td>
                    <td>****{phone1}</td>
                    <td>****{phone2}</td>
                    <td>{wedding_display}</td>
                    <td>{budget_display}</td>
                    <td>{couple.get('total_expenses', 0)}</td>
                    <td class="amount">{couple.get('total_amount', 0):,.0f} ₪</td>
                    <td>{needs_review_display}</td>
                    <td>{activity_display}</td>
                    <td>
                        <button class="btn btn-primary" onclick="viewExpenses('{group_id}')" title="צפה בדשבורד">👁️</button>
                        <button class="btn btn-success" onclick="sendSummary('{group_id}')" title="שלח סיכום">📊</button>
                    </td>
                </tr>
            """
        
        return html
    
    def _error_html(self, error_message: str) -> str:
        """HTML למקרה של שגיאה"""
        return f"""
        <!DOCTYPE html>
        <html dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>שגיאה - דשבורד מנהל</title>
            <style>
                body {{ 
                    font-family: Arial, sans-serif; 
                    margin: 0; 
                    padding: 20px; 
                    background: #f5f5f5; 
                    direction: rtl; 
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }}
                .container {{ 
                    max-width: 600px; 
                    background: white; 
                    padding: 50px; 
                    border-radius: 15px; 
                    box-shadow: 0 4px 20px rgba(0,0,0,0.1); 
                    text-align: center; 
                }}
                .error {{ color: #d32f2f; }}
                .btn {{ 
                    padding: 12px 24px; 
                    margin: 10px; 
                    background: #667eea; 
                    color: white; 
                    border: none; 
                    border-radius: 8px; 
                    cursor: pointer; 
                    text-decoration: none; 
                    display: inline-block;
                }}
                .btn:hover {{ background: #5a6fd8; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="error">
                    <h1>❌ שגיאה בדשבורד המנהל</h1>
                    <p style="margin: 20px 0;">{error_message}</p>
                    <button onclick="location.reload()" class="btn">🔄 נסה שוב</button>
                    <a href="/admin/login" class="btn">🔐 חזור לכניסה</a>
                </div>
            </div>
        </body>
        </html>
        """