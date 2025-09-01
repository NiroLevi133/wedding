# קובץ חדש: budget_manager.py
import logging
from typing import Dict, List, Optional
from datetime import datetime
from database_manager import DatabaseManager
from config import CATEGORY_LIST

logger = logging.getLogger(__name__)

class BudgetManager:
    """מנהל תקציבים לזוגות ולספקים"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def set_vendor_budget(self, group_id: str, vendor_name: str, budget: float) -> bool:
        """מגדיר תקציב לספק מסוים"""
        try:
            budget_data = {
                'group_id': group_id,
                'vendor_name': vendor_name,
                'budget_amount': budget,
                'created_at': datetime.now().isoformat(),
                'status': 'active'
            }
            
            # שמירה בגיליון vendor_budgets חדש
            return self.db._append_sheet_row('vendor_budgets!A:F', [
                group_id,
                vendor_name,
                str(budget),
                budget_data['created_at'],
                'active',
                ''  # reserved for notes
            ])
            
        except Exception as e:
            logger.error(f"Failed to set vendor budget: {e}")
            return False
    
    def set_category_budget(self, group_id: str, category: str, budget: float) -> bool:
        """מגדיר תקציב לקטגוריה"""
        try:
            if category not in CATEGORY_LIST:
                return False
            
            budget_data = {
                'group_id': group_id,
                'category': category,
                'budget_amount': budget,
                'created_at': datetime.now().isoformat(),
                'status': 'active'
            }
            
            # שמירה בגיליון category_budgets חדש
            return self.db._append_sheet_row('category_budgets!A:F', [
                group_id,
                category,
                str(budget),
                budget_data['created_at'],
                'active',
                ''  # reserved for notes
            ])
            
        except Exception as e:
            logger.error(f"Failed to set category budget: {e}")
            return False
    
    def get_budget_status(self, group_id: str) -> Dict:
        """מחזיר סטטוס תקציב מפורט"""
        try:
            # קבלת כל ההוצאות
            expenses = self.db.get_expenses_by_group(group_id)
            
            # קבלת תקציבי ספקים
            vendor_budgets = self._get_vendor_budgets(group_id)
            
            # קבלת תקציבי קטגוריות
            category_budgets = self._get_category_budgets(group_id)
            
            # חישוב סטטוס לכל ספק
            vendor_status = {}
            for vendor, budget in vendor_budgets.items():
                vendor_expenses = [e for e in expenses if e['vendor'] == vendor and e['status'] == 'active']
                spent = sum(float(e['amount']) for e in vendor_expenses)
                vendor_status[vendor] = {
                    'budget': budget,
                    'spent': spent,
                    'remaining': budget - spent,
                    'percentage': (spent / budget * 100) if budget > 0 else 0,
                    'status': self._get_budget_alert_level(spent, budget)
                }
            
            # חישוב סטטוס לכל קטגוריה
            category_status = {}
            for category, budget in category_budgets.items():
                cat_expenses = [e for e in expenses if e['category'] == category and e['status'] == 'active']
                spent = sum(float(e['amount']) for e in cat_expenses)
                category_status[category] = {
                    'budget': budget,
                    'spent': spent,
                    'remaining': budget - spent,
                    'percentage': (spent / budget * 100) if budget > 0 else 0,
                    'status': self._get_budget_alert_level(spent, budget)
                }
            
            # סטטוס כללי
            couple = self.db.get_couple_by_group_id(group_id)
            total_budget = float(couple.get('budget', 0)) if couple.get('budget') not in ['אין עדיין', None] else 0
            total_spent = sum(float(e['amount']) for e in expenses if e['status'] == 'active')
            
            return {
                'total': {
                    'budget': total_budget,
                    'spent': total_spent,
                    'remaining': total_budget - total_spent if total_budget > 0 else None,
                    'percentage': (total_spent / total_budget * 100) if total_budget > 0 else 0
                },
                'vendors': vendor_status,
                'categories': category_status,
                'alerts': self._generate_budget_alerts(vendor_status, category_status)
            }
            
        except Exception as e:
            logger.error(f"Failed to get budget status: {e}")
            return {}
    
    def _get_vendor_budgets(self, group_id: str) -> Dict[str, float]:
        """מחזיר תקציבי ספקים"""
        try:
            rows = self.db._read_sheet_range('vendor_budgets!A:F')
            if not rows or len(rows) < 2:
                return {}
            
            budgets = {}
            for row in rows[1:]:
                if len(row) >= 3 and row[0] == group_id and row[4] == 'active':
                    budgets[row[1]] = float(row[2])
            
            return budgets
            
        except Exception as e:
            logger.error(f"Failed to get vendor budgets: {e}")
            return {}
    
    def _get_category_budgets(self, group_id: str) -> Dict[str, float]:
        """מחזיר תקציבי קטגוריות"""
        try:
            rows = self.db._read_sheet_range('category_budgets!A:F')
            if not rows or len(rows) < 2:
                return {}
            
            budgets = {}
            for row in rows[1:]:
                if len(row) >= 3 and row[0] == group_id and row[4] == 'active':
                    budgets[row[1]] = float(row[2])
            
            return budgets
            
        except Exception as e:
            logger.error(f"Failed to get category budgets: {e}")
            return {}
    
    def _get_budget_alert_level(self, spent: float, budget: float) -> str:
        """קובע רמת התראה לתקציב"""
        if budget <= 0:
            return 'no_budget'
        
        percentage = (spent / budget) * 100
        
        if percentage >= 100:
            return 'over_budget'
        elif percentage >= 90:
            return 'critical'
        elif percentage >= 75:
            return 'warning'
        elif percentage >= 50:
            return 'moderate'
        else:
            return 'good'
    
    def _generate_budget_alerts(self, vendor_status: Dict, category_status: Dict) -> List[str]:
        """יוצר רשימת התראות תקציב"""
        alerts = []
        
        # התראות ספקים
        for vendor, status in vendor_status.items():
            if status['status'] == 'over_budget':
                alerts.append(f"⚠️ חריגה בתקציב ל{vendor}: {status['spent']:,.0f} מתוך {status['budget']:,.0f}")
            elif status['status'] == 'critical':
                alerts.append(f"🔴 קרוב לחריגה ב{vendor}: {status['percentage']:.0f}% מהתקציב")
        
        # התראות קטגוריות
        for category, status in category_status.items():
            if status['status'] == 'over_budget':
                alerts.append(f"⚠️ חריגה בקטגוריית {category}: {status['spent']:,.0f} מתוך {status['budget']:,.0f}")
        
        return alerts