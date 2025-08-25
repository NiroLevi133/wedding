import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
from database_manager import DatabaseManager
from config import WEDDING_CATEGORIES, DASHBOARD_SETTINGS

logger = logging.getLogger(__name__)

class UserDashboard:
    """מנהל דשבורד זוגות"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def get_dashboard_html(self, group_id: str) -> str:
        """מחזיר HTML מלא לדשבורד המשתמש"""
        try:
            # טעינת נתונים
            dashboard_data = await self.get_dashboard_data(group_id)
            couple_info = self.db.get_couple_by_group_id(group_id)
            
            if not couple_info:
                return self._error_html("קבוצה לא נמצאה")
            
            # בדיקה אם יש נתונים
            if not dashboard_data.get('expenses'):
                return self._empty_dashboard_html(group_id, couple_info)
            
            return self._generate_dashboard_html(group_id, dashboard_data, couple_info)
            
        except Exception as e:
            logger.error(f"Dashboard HTML generation failed: {e}")
            return self._error_html(f"שגיאה בטעינת הדשבורד: {str(e)}")
    
    async def get_dashboard_data(self, group_id: str) -> Dict:
        """מחזיר נתוני דשבורד כJSON"""
        try:
            # קבלת הוצאות
            expenses = self.db.get_expenses_by_group(group_id, include_deleted=False)
            couple_info = self.db.get_couple_by_group_id(group_id)
            
            if not couple_info:
                raise ValueError("Group not found")
            
            # עיבוד נתונים
            processed_data = self._process_expenses_data(expenses, couple_info)
            
            return processed_data
            
        except Exception as e:
            logger.error(f"Dashboard data generation failed: {e}")
            return {"error": str(e)}
    
    def _process_expenses_data(self, expenses: List[Dict], couple_info: Dict) -> Dict:
        """מעבד נתוני הוצאות לדשבורד"""
        # סטטיסטיקות בסיסיות
        total_amount = 0
        total_count = 0
        categories_data = defaultdict(lambda: {'amount': 0, 'count': 0, 'items': []})
        monthly_data = defaultdict(lambda: {'amount': 0, 'count': 0})
        
        # עיבוד מקדמות - קיבוץ תשלומים לפי ספק
        vendor_payments = defaultdict(list)
        processed_expenses = []
        
        for expense in expenses:
            if expense.get('status') != 'active':
                continue
                
            amount = float(expense.get('amount', 0))
            if amount <= 0:
                continue
            
            vendor = expense.get('vendor', 'ספק לא ידוע')
            payment_type = expense.get('payment_type', 'full')
            
            # קיבוץ מקדמות
            vendor_payments[vendor].append({
                'expense': expense,
                'amount': amount,
                'payment_type': payment_type,
                'date': expense.get('date', ''),
                'created_at': expense.get('created_at', '')
            })
        
        # יצירת רשימה מעובדת עם מקדמות מקובצות
        for vendor, payments in vendor_payments.items():
            if len(payments) == 1:
                # תשלום יחיד
                expense = payments[0]['expense']
                processed_expenses.append({
                    **expense,
                    'display_amount': payments[0]['amount'],
                    'is_grouped': False,
                    'payment_details': None
                })
                total_amount += payments[0]['amount']
                total_count += 1
            else:
                # מספר תשלומים - קבץ אותם
                total_vendor_amount = sum(p['amount'] for p in payments)
                latest_payment = max(payments, key=lambda x: x['created_at'])
                
                payment_details = []
                for i, payment in enumerate(sorted(payments, key=lambda x: x['created_at'])):
                    if payment['payment_type'].startswith('advance'):
                        payment_details.append(f"מקדמה {i+1}: {payment['amount']:,.0f} ₪")
                    elif payment['payment_type'] == 'final':
                        payment_details.append(f"תשלום סופי: {payment['amount']:,.0f} ₪")
                    else:
                        payment_details.append(f"תשלום: {payment['amount']:,.0f} ₪")
                
                processed_expenses.append({
                    **latest_payment['expense'],
                    'display_amount': total_vendor_amount,
                    'is_grouped': True,
                    'payment_details': payment_details,
                    'payments_count': len(payments)
                })
                total_amount += total_vendor_amount
                total_count += 1
        
        # סטטיסטיקות לפי קטגוריה וחודש
        for expense in processed_expenses:
            amount = expense['display_amount']
            category = expense.get('category', 'אחר')
            
            # נתוני קטגוריה
            categories_data[category]['amount'] += amount
            categories_data[category]['count'] += 1
            categories_data[category]['items'].append(expense)
            
            # נתוני חודש
            expense_date = expense.get('date', '')
            if expense_date:
                try:
                    date_obj = datetime.strptime(expense_date, '%Y-%m-%d')
                    month_key = date_obj.strftime('%Y-%m')
                    monthly_data[month_key]['amount'] += amount
                    monthly_data[month_key]['count'] += 1
                except ValueError:
                    pass
        
        # חישוב אחוזי תקציב
        budget_info = self._calculate_budget_info(total_amount, couple_info)
        
        # חישוב ימים לחתונה
        days_to_wedding = self._calculate_days_to_wedding(couple_info.get('wedding_date'))
        
        return {
            'total_amount': total_amount,
            'total_count': total_count,
            'avg_amount': total_amount / total_count if total_count > 0 else 0,
            'categories': dict(categories_data),
            'monthly_data': dict(monthly_data),
            'expenses': processed_expenses[-20:],  # 20 אחרונות
            'budget_info': budget_info,
            'days_to_wedding': days_to_wedding,
            'couple_info': couple_info
        }
    
    def _calculate_budget_info(self, total_amount: float, couple_info: Dict) -> Dict:
        """מחשב מידע תקציב"""
        budget_str = couple_info.get('budget', '')
        
        if not budget_str or budget_str in ['אין עדיין', 'null', '']:
            return {
                'has_budget': False,
                'budget_amount': 0,
                'spent_percentage': 0,
                'remaining': 0,
                'status': 'no_budget'
            }
        
        try:
            budget_amount = float(budget_str)
            spent_percentage = (total_amount / budget_amount * 100) if budget_amount > 0 else 0
            remaining = budget_amount - total_amount
            
            # קביעת סטטוס
            if spent_percentage < 50:
                status = 'good'  # ירוק
            elif spent_percentage < 80:
                status = 'warning'  # צהוב
            elif spent_percentage < 100:
                status = 'danger'  # כתום
            else:
                status = 'over_budget'  # אדום
            
            return {
                'has_budget': True,
                'budget_amount': budget_amount,
                'spent_percentage': spent_percentage,
                'remaining': remaining,
                'status': status
            }
            
        except (ValueError, TypeError):
            return {
                'has_budget': False,
                'budget_amount': 0,
                'spent_percentage': 0,
                'remaining': 0,
                'status': 'invalid_budget'
            }
    
    def _calculate_days_to_wedding(self, wedding_date: str) -> int:
        """מחשב ימים לחתונה"""
        if not wedding_date:
            return 0
        
        try:
            wedding_dt = datetime.strptime(wedding_date, '%Y-%m-%d')
            today = datetime.now()
            delta = wedding_dt - today
            
            return max(0, delta.days)
            
        except ValueError:
            return 0
    
    def _generate_dashboard_html(self, group_id: str, data: Dict, couple_info: Dict) -> str:
        """יוצר HTML מלא לדשבורד"""
        
        # הכנת נתונים לגרפים
        categories_chart_data = self._prepare_categories_chart_data(data['categories'])
        monthly_chart_data = self._prepare_monthly_chart_data(data['monthly_data'])
        
        # צבעים לגרפים
        chart_colors = DASHBOARD_SETTINGS['chart_colors']
        
        return f"""
        <!DOCTYPE html>
        <html dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>דשבורד הוצאות חתונה</title>
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
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
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
                    margin-bottom: 40px;
                }}
                
                .section h2 {{ 
                    color: #333; 
                    margin-bottom: 20px; 
                    padding-bottom: 10px; 
                    border-bottom: 3px solid #667eea;
                    font-size: 1.5rem;
                }}
                
                .budget-card {{
                    background: white;
                    border-radius: 15px;
                    padding: 25px;
                    margin-bottom: 30px;
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                }}
                
                .budget-progress {{
                    height: 20px;
                    background: #e9ecef;
                    border-radius: 10px;
                    overflow: hidden;
                    margin: 15px 0;
                }}
                
                .budget-progress-bar {{
                    height: 100%;
                    transition: width 0.3s ease;
                }}
                
                .budget-good {{ background: #28a745; }}
                .budget-warning {{ background: #ffc107; }}
                .budget-danger {{ background: #fd7e14; }}
                .budget-over {{ background: #dc3545; }}
                
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
                
                .expenses-list {{
                    background: white;
                    border-radius: 15px;
                    overflow: hidden;
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                }}
                
                .expense-item {{
                    padding: 20px;
                    border-bottom: 1px solid #eee;
                    transition: background 0.3s ease;
                }}
                
                .expense-item:hover {{
                    background: #f8f9fa;
                }}
                
                .expense-item:last-child {{
                    border-bottom: none;
                }}
                
                .expense-header {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 10px;
                }}
                
                .expense-vendor {{
                    font-size: 1.2rem;
                    font-weight: bold;
                    color: #333;
                }}
                
                .expense-amount {{
                    font-size: 1.3rem;
                    font-weight: bold;
                    color: #667eea;
                }}
                
                .expense-details {{
                    display: flex;
                    gap: 20px;
                    font-size: 0.9rem;
                    color: #666;
                }}
                
                .expense-category {{
                    display: flex;
                    align-items: center;
                    gap: 5px;
                }}
                
                .payment-details {{
                    margin-top: 10px;
                    padding: 10px;
                    background: #f8f9fa;
                    border-radius: 8px;
                    font-size: 0.85rem;
                }}
                
                .payment-details ul {{
                    list-style: none;
                    margin: 0;
                    padding: 0;
                }}
                
                .payment-details li {{
                    margin: 5px 0;
                    color: #666;
                }}
                
                @media (max-width: 768px) {{
                    .header h1 {{ font-size: 2rem; }}
                    .stats-grid {{ grid-template-columns: repeat(2, 1fr); gap: 15px; }}
                    .charts-container {{ grid-template-columns: 1fr; }}
                    .expense-header {{ flex-direction: column; align-items: flex-start; }}
                    .expense-details {{ flex-direction: column; gap: 10px; }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>💒 דשבורד הוצאות החתונה</h1>
                    <p>מעקב מלא אחר כל ההוצאות שלכם</p>
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
                        <div class="stat-icon">⏰</div>
                        <div class="stat-value">{data['days_to_wedding']}</div>
                        <div class="stat-label">ימים לחתונה</div>
                    </div>
                </div>
                
                <div class="content">
                    {self._generate_budget_section(data['budget_info'])}
                    
                    <div class="section">
                        <h2>📊 גרפי הוצאות</h2>
                        <div class="charts-container">
                            <div class="chart-card">
                                <div class="chart-title">הוצאות לפי קטגוריה</div>
                                <div class="chart-container">
                                    <canvas id="categoriesChart"></canvas>
                                </div>
                            </div>
                            <div class="chart-card">
                                <div class="chart-title">הוצאות לפי חודש</div>
                                <div class="chart-container">
                                    <canvas id="monthlyChart"></canvas>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="section">
                        <h2>📋 הוצאות אחרונות</h2>
                        <div class="expenses-list">
                            {self._generate_expenses_list(data['expenses'])}
                        </div>
                    </div>
                </div>
            </div>
            
            <script>
                // נתוני גרפים
                const categoriesData = {json.dumps(categories_chart_data)};
                const monthlyData = {json.dumps(monthly_chart_data)};
                const chartColors = {json.dumps(chart_colors)};
                
                // גרף קטגוריות
                const categoriesCtx = document.getElementById('categoriesChart').getContext('2d');
                new Chart(categoriesCtx, {{
                    type: 'doughnut',
                    data: {{
                        labels: categoriesData.labels,
                        datasets: [{{
                            data: categoriesData.data,
                            backgroundColor: chartColors.slice(0, categoriesData.labels.length),
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
                                    font: {{ size: 11 }}
                                }}
                            }},
                            tooltip: {{
                                callbacks: {{
                                    label: function(context) {{
                                        const value = context.parsed || 0;
                                        const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                        const percentage = ((value / total) * 100).toFixed(1);
                                        return `${{context.label}}: ${{value.toLocaleString()}} ₪ (${{percentage}}%)`;
                                    }}
                                }}
                            }}
                        }}
                    }}
                }});
                
                // גרף חודשי
                const monthlyCtx = document.getElementById('monthlyChart').getContext('2d');
                new Chart(monthlyCtx, {{
                    type: 'bar',
                    data: {{
                        labels: monthlyData.labels,
                        datasets: [{{
                            label: 'הוצאות (₪)',
                            data: monthlyData.data,
                            backgroundColor: '#667eea',
                            borderColor: '#5a6fd8',
                            borderWidth: 1
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
                
                // רענון אוטומטי כל 5 דקות
                setTimeout(() => location.reload(), 300000);
                
                // אנימציות
                document.addEventListener('DOMContentLoaded', function() {{
                    const cards = document.querySelectorAll('.stat-card, .expense-item');
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
                        transform: translateY(20px);
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
    
    def _generate_budget_section(self, budget_info: Dict) -> str:
        """יוצר סקציית תקציב"""
        if not budget_info.get('has_budget'):
            return """
                <div class="budget-card">
                    <h3>💰 תקציב</h3>
                    <p>לא הוגדר תקציב עדיין</p>
                </div>
            """
        
        percentage = budget_info['spent_percentage']
        remaining = budget_info['remaining']
        status = budget_info['status']
        
        # צבע לפי סטטוס
        progress_class = f"budget-{status}"
        
        status_messages = {
            'good': '💚 הכל תחת שליטה!',
            'warning': '💛 מתקרבים לגבול',
            'danger': '🧡 זהירות - חריגה קרובה',
            'over_budget': '❤️ חריגה מהתקציב'
        }
        
        status_message = status_messages.get(status, '')
        
        return f"""
            <div class="budget-card">
                <h3>💰 מעקב תקציב</h3>
                <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
                    <span>הוצאתם: {budget_info['budget_amount'] - remaining:,.0f} ₪</span>
                    <span>תקציב: {budget_info['budget_amount']:,.0f} ₪</span>
                </div>
                <div class="budget-progress">
                    <div class="budget-progress-bar {progress_class}" style="width: {min(100, percentage):.1f}%"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 0.9rem; color: #666;">
                    <span>{percentage:.1f}% מהתקציב</span>
                    <span>נותרו: {remaining:,.0f} ₪</span>
                </div>
                <div style="margin-top: 15px; text-align: center; font-weight: bold;">
                    {status_message}
                </div>
            </div>
        """
    
    def _generate_expenses_list(self, expenses: List[Dict]) -> str:
        """יוצר רשימת הוצאות"""
        if not expenses:
            return "<div style='padding: 40px; text-align: center; color: #666;'>אין הוצאות עדיין</div>"
        
        html = ""
        for expense in reversed(expenses[-10:]):  # 10 אחרונות בסדר הפוך
            vendor = expense.get('vendor', 'ספק לא ידוע')
            amount = expense.get('display_amount', expense.get('amount', 0))
            category = expense.get('category', 'אחר')
            date = expense.get('date', '')
            is_grouped = expense.get('is_grouped', False)
            payment_details = expense.get('payment_details', [])
            
            # אמוג'י קטגוריה
            emoji = WEDDING_CATEGORIES.get(category, "📋")
            
            # עיצוב תאריך
            date_display = ""
            if date:
                try:
                    date_obj = datetime.strptime(date, '%Y-%m-%d')
                    date_display = date_obj.strftime('%d/%m/%Y')
                except ValueError:
                    date_display = date
            
            html += f"""
                <div class="expense-item">
                    <div class="expense-header">
                        <div class="expense-vendor">{vendor}</div>
                        <div class="expense-amount">{amount:,.0f} ₪</div>
                    </div>
                    <div class="expense-details">
                        <div class="expense-category">
                            <span>{emoji}</span>
                            <span>{category}</span>
                        </div>
                        {f'<div>📅 {date_display}</div>' if date_display else ''}
                        {f'<div>🔗 {len(payment_details)} תשלומים</div>' if is_grouped else ''}
                    </div>
                    {f'<div class="payment-details"><ul>{"".join(f"<li>{detail}</li>" for detail in payment_details)}</ul></div>' if payment_details else ''}
                </div>
            """
        
        return html
    
    def _prepare_categories_chart_data(self, categories: Dict) -> Dict:
        """מכין נתונים לגרף קטגוריות"""
        labels = []
        data = []
        
        # מיון לפי סכום
        sorted_categories = sorted(categories.items(), key=lambda x: x[1]['amount'], reverse=True)
        
        for category, category_data in sorted_categories:
            emoji = WEDDING_CATEGORIES.get(category, "📋")
            labels.append(f"{emoji} {category}")
            data.append(category_data['amount'])
        
        return {'labels': labels, 'data': data}
    
    def _prepare_monthly_chart_data(self, monthly_data: Dict) -> Dict:
        """מכין נתונים לגרף חודשי"""
        labels = []
        data = []
        
        # מיון לפי תאריך
        sorted_months = sorted(monthly_data.items())
        
        month_names = {
            '01': 'ינו׳', '02': 'פבר׳', '03': 'מרץ', '04': 'אפר׳',
            '05': 'מאי', '06': 'יונ׳', '07': 'יול׳', '08': 'אוג׳',
            '09': 'ספט׳', '10': 'אוק׳', '11': 'נוב׳', '12': 'דצמ׳'
        }
        
        for month_key, month_data in sorted_months:
            try:
                year, month = month_key.split('-')
                month_display = f"{month_names.get(month, month)} {year}"
                labels.append(month_display)
                data.append(month_data['amount'])
            except ValueError:
                labels.append(month_key)
                data.append(month_data['amount'])
        
        return {'labels': labels, 'data': data}
    
    def _empty_dashboard_html(self, group_id: str, couple_info: Dict) -> str:
        """HTML למקרה שאין הוצאות"""
        return """
        <!DOCTYPE html>
        <html dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>דשבורד הוצאות חתונה</title>
            <style>
                body { 
                    font-family: Arial, sans-serif; 
                    margin: 0; 
                    padding: 20px; 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    direction: rtl; 
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                .container { 
                    max-width: 600px; 
                    margin: 0 auto; 
                    background: white; 
                    padding: 50px; 
                    border-radius: 20px; 
                    box-shadow: 0 20px 60px rgba(0,0,0,0.1); 
                    text-align: center; 
                }
                .empty-state { color: #666; }
                .icon { font-size: 4rem; margin-bottom: 20px; }
                h1 { color: #333; margin-bottom: 20px; }
                p { font-size: 1.1rem; line-height: 1.6; margin-bottom: 15px; }
                .highlight { color: #667eea; font-weight: bold; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="empty-state">
                    <div class="icon">💒</div>
                    <h1>דשבורד הוצאות החתונה</h1>
                    <p>עדיין לא העליתם הוצאות 📝</p>
                    <p>התחילו לשלוח קבלות בווטסאפ והן יופיעו כאן אוטומטית!</p>
                    <p class="highlight">💡 פשוט שלחו תמונה של קבלה לקבוצה ונדאג לכל השאר</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    def _error_html(self, error_message: str) -> str:
        """HTML למקרה של שגיאה"""
        return f"""
        <!DOCTYPE html>
        <html dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>שגיאה - דשבורד הוצאות</title>
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
                    <h1>❌ שגיאה בטעינת הדשבורד</h1>
                    <p style="margin: 20px 0;">{error_message}</p>
                    <button onclick="location.reload()" class="btn">🔄 נסה שוב</button>
                </div>
            </div>
        </body>
        </html>
        """