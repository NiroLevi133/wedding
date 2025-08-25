import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from google.oauth2 import service_account
from googleapiclient.discovery import build
from config import *

logger = logging.getLogger(__name__)

class DatabaseManager:
    """מנהל את כל הפעולות עם Google Sheets"""
    
    def __init__(self):
        self.sheets = None
        self.credentials = None
        self._init_google_sheets()
    
    def _init_google_sheets(self):
        """מאתחל חיבור לGoogle Sheets"""
        try:
            if GOOGLE_CREDENTIALS_JSON:
                creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
                self.credentials = service_account.Credentials.from_service_account_info(
                    creds_dict, 
                    scopes=["https://www.googleapis.com/auth/spreadsheets"]
                )
            else:
                raise ValueError("Missing Google credentials")
            
            self.sheets = build("sheets", "v4", credentials=self.credentials)
            logger.info("Google Sheets initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets: {e}")
            raise
    
    def _get_current_timestamp(self) -> str:
        """מחזיר timestamp נוכחי"""
        return datetime.now(timezone.utc).isoformat()
    
    def _read_sheet_range(self, range_name: str) -> List[List[str]]:
        """קורא טווח מהגיליון"""
        try:
            result = self.sheets.spreadsheets().values().get(
                spreadsheetId=GSHEETS_SPREADSHEET_ID,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            logger.debug(f"Read {len(values)} rows from {range_name}")
            return values
            
        except Exception as e:
            logger.error(f"Failed to read {range_name}: {e}")
            return []
    
    def _append_sheet_row(self, range_name: str, values: List) -> bool:
        """מוסיף שורה לגיליון"""
        try:
            body = {'values': [values]}
            
            result = self.sheets.spreadsheets().values().append(
                spreadsheetId=GSHEETS_SPREADSHEET_ID,
                range=range_name,
                valueInputOption='USER_ENTERED',
                insertDataOption='INSERT_ROWS',
                body=body
            ).execute()
            
            logger.info(f"Added row to {range_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to append to {range_name}: {e}")
            return False
    
    def _update_sheet_row(self, range_name: str, values: List) -> bool:
        """מעדכן שורה בגיליון"""
        try:
            body = {'values': [values]}
            
            result = self.sheets.spreadsheets().values().update(
                spreadsheetId=GSHEETS_SPREADSHEET_ID,
                range=range_name,
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            logger.info(f"Updated row in {range_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update {range_name}: {e}")
            return False
    
    # === הוצאות ===
    
    def save_expense(self, expense_data: Dict) -> bool:
        """שומר הוצאה חדשה"""
        try:
            # יצירת expense_id ייחודי
            if not expense_data.get('expense_id'):
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                import random
                expense_data['expense_id'] = f"EXP_{timestamp}_{random.randint(1000, 9999)}"
            
            # מילוי ערכי ברירת מחדל
            current_time = self._get_current_timestamp()
            expense_data.setdefault('created_at', current_time)
            expense_data.setdefault('status', 'active')
            expense_data.setdefault('needs_review', False)
            
            # יצירת שורה לפי סדר הכותרות
            row_values = []
            for header in EXPENSE_HEADERS:
                value = expense_data.get(header, '')
                row_values.append(str(value) if value is not None else '')
            
            success = self._append_sheet_row(EXPENSES_SHEET, row_values)
            
            if success:
                logger.info(f"Saved expense: {expense_data.get('expense_id')}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to save expense: {e}")
            return False
    
    def get_expenses_by_group(self, group_id: str, include_deleted: bool = False) -> List[Dict]:
        """מחזיר כל ההוצאות של קבוצה"""
        try:
            rows = self._read_sheet_range(EXPENSES_SHEET)
            
            if not rows:
                return []
            
            # הסר כותרת
            data_rows = rows[1:] if len(rows) > 1 else []
            expenses = []
            
            for row in data_rows:
                if len(row) < len(EXPENSE_HEADERS):
                    # השלם שורות חסרות
                    row.extend([''] * (len(EXPENSE_HEADERS) - len(row)))
                
                expense = dict(zip(EXPENSE_HEADERS, row))
                
                # סנן לפי קבוצה
                if expense.get('group_id') == group_id:
                    # סנן מחוקים אם צריך
                    if not include_deleted and expense.get('status') == 'deleted':
                        continue
                    
                    expenses.append(expense)
            
            logger.debug(f"Found {len(expenses)} expenses for group {group_id}")
            return expenses
            
        except Exception as e:
            logger.error(f"Failed to get expenses for group {group_id}: {e}")
            return []
    
    def update_expense_status(self, expense_id: str, status: str, deleted_at: Optional[str] = None) -> bool:
        """מעדכן סטטוס הוצאה"""
        try:
            rows = self._read_sheet_range(EXPENSES_SHEET)
            
            if not rows or len(rows) < 2:
                return False
            
            # מחפש את השורה
            headers = rows[0]
            data_rows = rows[1:]
            
            for i, row in enumerate(data_rows):
                if len(row) > 0 and row[0] == expense_id:  # expense_id בעמודה הראשונה
                    # עדכן סטטוס
                    if len(row) < len(EXPENSE_HEADERS):
                        row.extend([''] * (len(EXPENSE_HEADERS) - len(row)))
                    
                    # מעדכן לפי אינדקס העמודות
                    status_index = EXPENSE_HEADERS.index('status')
                    row[status_index] = status
                    
                    if deleted_at and 'deleted_at' in EXPENSE_HEADERS:
                        deleted_index = EXPENSE_HEADERS.index('deleted_at')
                        row[deleted_index] = deleted_at
                    
                    # מעדכן בגיליון
                    row_number = i + 2  # +1 לכותרת +1 לאינדקס מ-1
                    range_name = f"expenses!A{row_number}:L{row_number}"
                    
                    return self._update_sheet_row(range_name, row)
            
            logger.warning(f"Expense {expense_id} not found for status update")
            return False
            
        except Exception as e:
            logger.error(f"Failed to update expense status: {e}")
            return False
    
    # === זוגות ===
    
    def get_couple_by_group_id(self, group_id: str) -> Optional[Dict]:
        """מחזיר פרטי זוג לפי group_id"""
        try:
            rows = self._read_sheet_range(COUPLES_SHEET)
            
            if not rows or len(rows) < 2:
                return None
            
            data_rows = rows[1:]
            
            for row in data_rows:
                if len(row) < len(COUPLES_HEADERS):
                    row.extend([''] * (len(COUPLES_HEADERS) - len(row)))
                
                couple = dict(zip(COUPLES_HEADERS, row))
                
                if couple.get('whatsapp_group_id') == group_id:
                    logger.debug(f"Found couple for group {group_id}")
                    return couple
            
            logger.warning(f"No couple found for group {group_id}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to get couple by group {group_id}: {e}")
            return None
    
    def get_all_active_couples(self) -> List[Dict]:
        """מחזיר כל הזוגות הפעילים"""
        try:
            rows = self._read_sheet_range(COUPLES_SHEET)
            
            if not rows or len(rows) < 2:
                return []
            
            data_rows = rows[1:]
            couples = []
            
            for row in data_rows:
                if len(row) < len(COUPLES_HEADERS):
                    row.extend([''] * (len(COUPLES_HEADERS) - len(row)))
                
                couple = dict(zip(COUPLES_HEADERS, row))
                
                # רק זוגות פעילים
                if couple.get('status', 'active') == 'active':
                    couples.append(couple)
            
            logger.debug(f"Found {len(couples)} active couples")
            return couples
            
        except Exception as e:
            logger.error(f"Failed to get active couples: {e}")
            return []
    
    # === ספקים ===
    
    def get_vendor_category(self, vendor_name: str) -> Optional[str]:
        """מחזיר קטגוריה של ספק קיים"""
        try:
            rows = self._read_sheet_range(VENDORS_SHEET)
            
            if not rows or len(rows) < 2:
                return None
            
            data_rows = rows[1:]
            vendor_lower = vendor_name.lower().strip()
            
            for row in data_rows:
                if len(row) < len(VENDORS_HEADERS):
                    continue
                
                vendor = dict(zip(VENDORS_HEADERS, row))
                stored_vendor = vendor.get('vendor_name', '').lower().strip()
                
                # חיפוש מדויק או חלקי
                if (stored_vendor == vendor_lower or 
                    vendor_lower in stored_vendor or 
                    stored_vendor in vendor_lower):
                    
                    logger.debug(f"Found category for vendor {vendor_name}: {vendor.get('category')}")
                    return vendor.get('category')
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get vendor category: {e}")
            return None
    
    def save_vendor_category(self, vendor_name: str, category: str, confidence: int = 85, group_id: str = "") -> bool:
        """שומר ספק וקטגוריה חדשים"""
        try:
            current_time = self._get_current_timestamp()
            
            row_values = [
                vendor_name,
                category,
                str(confidence),
                current_time,
                group_id,
                current_time
            ]
            
            success = self._append_sheet_row(VENDORS_SHEET, row_values)
            
            if success:
                logger.info(f"Saved vendor: {vendor_name} -> {category}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to save vendor: {e}")
            return False
    
    # === מקדמות ===
    
    def find_related_expenses(self, vendor_name: str, group_id: str) -> List[Dict]:
        """מחפש הוצאות קשורות לאותו ספק"""
        try:
            expenses = self.get_expenses_by_group(group_id)
            related = []
            
            vendor_lower = vendor_name.lower().strip()
            
            for expense in expenses:
                expense_vendor = expense.get('vendor', '').lower().strip()
                
                if (expense_vendor == vendor_lower or 
                    vendor_lower in expense_vendor or
                    expense_vendor in vendor_lower):
                    related.append(expense)
            
            # מיון לפי תאריך יצירה
            related.sort(key=lambda x: x.get('created_at', ''))
            
            logger.debug(f"Found {len(related)} related expenses for {vendor_name}")
            return related
            
        except Exception as e:
            logger.error(f"Failed to find related expenses: {e}")
            return []
    
    def update_payment_types(self, expenses: List[Dict]) -> bool:
        """מעדכן סוגי תשלום למקדמות"""
        try:
            if len(expenses) <= 1:
                return True
            
            # עדכן כל התשלומים חוץ מהאחרון למקדמות
            for i, expense in enumerate(expenses[:-1]):
                payment_type = f"advance_{i+1}" if len(expenses) > 2 else "advance"
                self._update_expense_payment_type(expense['expense_id'], payment_type)
            
            # האחרון תמיד סופי
            self._update_expense_payment_type(expenses[-1]['expense_id'], "final")
            
            logger.info(f"Updated payment types for {len(expenses)} expenses")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update payment types: {e}")
            return False
    
    def _update_expense_payment_type(self, expense_id: str, payment_type: str) -> bool:
        """מעדכן סוג תשלום של הוצאה ספציפית"""
        try:
            rows = self._read_sheet_range(EXPENSES_SHEET)
            
            if not rows or len(rows) < 2:
                return False
            
            data_rows = rows[1:]
            
            for i, row in enumerate(data_rows):
                if len(row) > 0 and row[0] == expense_id:
                    if len(row) < len(EXPENSE_HEADERS):
                        row.extend([''] * (len(EXPENSE_HEADERS) - len(row)))
                    
                    # עדכן payment_type
                    payment_type_index = EXPENSE_HEADERS.index('payment_type')
                    row[payment_type_index] = payment_type
                    
                    # עדכן בגיליון
                    row_number = i + 2
                    range_name = f"expenses!A{row_number}:L{row_number}"
                    
                    return self._update_sheet_row(range_name, row)
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to update payment type: {e}")
            return False
    
    # === בדיקות תקינות ===
    
    def health_check(self) -> Dict[str, bool]:
        """בודק שהמערכת עובדת"""
        checks = {
            "sheets_connection": False,
            "can_read_expenses": False,
            "can_read_couples": False,
            "can_read_vendors": False
        }
        
        try:
            # בדיקת חיבור
            if self.sheets:
                checks["sheets_connection"] = True
            
            # בדיקת קריאה
            expenses = self._read_sheet_range(EXPENSES_SHEET)
            if expenses is not None:
                checks["can_read_expenses"] = True
            
            couples = self._read_sheet_range(COUPLES_SHEET)
            if couples is not None:
                checks["can_read_couples"] = True
                
            vendors = self._read_sheet_range(VENDORS_SHEET)
            if vendors is not None:
                checks["can_read_vendors"] = True
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
        
        return checks