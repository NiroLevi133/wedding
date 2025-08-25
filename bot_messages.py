import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from config import WEDDING_CATEGORIES, PAYMENT_TYPES

logger = logging.getLogger(__name__)

class BotMessages:
    """מנהל את כל הודעות הבוט והתגובות"""
    
    @staticmethod
    def welcome_message_step1() -> str:
        """הודעת פתיחה - שלב 1"""
        return """🎉 מזל טוב! ברוכים הבאים למערכת הכי פשוטה לניהול הוצאות חתונה!

✨ מה אני עושה בשבילכם?
📸 אתם שולחים תמונות קבלות
🤖 אני מזהה הכל אוטומטית - ספק, סכום, קטגוריה  
📊 מכין לכם דשבורד מסודר
📈 מעדכן אתכם איפה אתם עומדים
💪 עושה לכם את החיים קלים!

📅 בואו נתחיל - מתי התאריך הגדול שלכם?"""

    @staticmethod
    def welcome_message_step2() -> str:
        """הודעת פתיחה - שלב 2"""
        return """מעולה! 🎊

💰 מה התקציב שהגדרתם לחתונה?
(אם עדיין לא הגדרתם - פשוט כתבו "אין עדיין")"""

    @staticmethod
    def welcome_message_step3() -> str:
        """הודעת פתיחה - שלב 3"""
        return """✨ הכל מוכן! מעכשיו פשוט שלחו קבלות ואני אדאג לכל השאר! 📸"""

    @staticmethod
    def receipt_saved_success(expense_data: Dict) -> str:
        """הודעת אישור על קבלה שנשמרה"""
        vendor = expense_data.get('vendor', 'ספק לא ידוע')
        amount = expense_data.get('amount', 0)
        category = expense_data.get('category', 'אחר')
        
        # אמוג'י לקטגוריה
        emoji = WEDDING_CATEGORIES.get(category, "📋")
        
        return f"""✅ נשמר!

🏪 {vendor}
💰 {amount:,.0f} ₪
{emoji} {category}"""

    @staticmethod
    def receipt_updated_success(expense_data: Dict, changed_field: str = "") -> str:
        """הודעת אישור על עדכון קבלה"""
        vendor = expense_data.get('vendor', 'ספק לא ידוע')
        amount = expense_data.get('amount', 0)
        category = expense_data.get('category', 'אחר')
        
        emoji = WEDDING_CATEGORIES.get(category, "📋")
        
        base_msg = f"""🔄 עודכן!

🏪 {vendor}
💰 {amount:,.0f} ₪
{emoji} {category}"""
        
        if changed_field:
            base_msg += f" ← שונה"
        
        return base_msg

    @staticmethod
    def receipt_deleted_success(expense_data: Dict) -> str:
        """הודעת אישור על מחיקת קבלה"""
        vendor = expense_data.get('vendor', 'ספק לא ידוע')
        amount = expense_data.get('amount', 0)
        
        return f"""🗑️ נמחק!
{vendor} - {amount:,.0f} ₪"""

    @staticmethod
    def image_unclear_request() -> str:
        """בקשה לפרטים כשתמונה לא ברורה"""
        return """😅 התמונה קצת לא ברורה...

רק תכתבו לי:
💰 כמה שילמתם?
🏪 לאיזה ספק?

ואני אדאג לשמור!"""

    @staticmethod
    def manual_entry_saved(vendor: str, amount: float) -> str:
        """אישור שמירה של הכנסה ידנית"""
        return f"""✅ נשמר!

🏪 {vendor}
💰 {amount:,.0f} ₪
📋 אחר

💡 אפשר לשנות פרטים בדשבורד אם צריך"""

    @staticmethod
    def help_message() -> str:
        """הודעת עזרה"""
        return """🤖 איך אני עוזר לכם?

📸 **שליחת קבלות:**
פשוט שלחו תמונה של קבלה ואני אזהה הכל

🔧 **עריכת קבלות:**
כתבו הודעה טבעית כמו:
• "זה בגדים לא צילום"
• "2500 לא 2000" 
• "זה רמי לוי לא מקס"
• "מחק את זה"

📊 **דשבורד:**
כל ההוצאות שלכם מסודרות ומחושבות

💡 **טיפ:** אם תמונה לא ברורה, פשוט כתבו לי את הפרטים ואני אשמור"""

    @staticmethod
    def error_general() -> str:
        """הודעת שגיאה כללית"""
        return """😅 משהו השתבש... אבל אל תדאגו!

נסו שוב או כתבו לי את הפרטים ידנית:
💰 סכום
🏪 שם הספק

ואני אדאג לשמור בשבילכם!"""

    @staticmethod
    def group_not_found() -> str:
        """הודעה כשקבוצה לא נמצאת במערכת"""
        return """👋 שלום! אני רואה שאתם לא רשומים במערכת עדיין.

צרו קשר עם המנהל כדי להוסיף אתכם למערכת ✨"""

    @staticmethod
    def weekly_summary(summary_data: Dict) -> str:
        """סיכום שבועי"""
        total_week = summary_data.get('week_total', 0)
        total_overall = summary_data.get('overall_total', 0)
        categories = summary_data.get('categories', {})
        days_left = summary_data.get('days_to_wedding', 0)
        budget_percent = summary_data.get('budget_percentage', 0)
        
        if total_week == 0:
            # שבוע ללא הוצאות
            return f"""📊 שבוע רגוע ללא הוצאות חדשות

💰 סה"כ עד כה: {total_overall:,.0f} ₪
⏰ נותרו {days_left} יום לחתונה

שבוע טוב! 😊"""
        
        # יצירת רשימת קטגוריות
        categories_text = ""
        for category, amount in sorted(categories.items(), key=lambda x: x[1], reverse=True):
            emoji = WEDDING_CATEGORIES.get(category, "📋")
            categories_text += f"{emoji} {category}: {amount:,.0f} ₪\n"
        
        # הודעת סטטוס תקציב
        budget_status = ""
        if budget_percent > 0:
            if budget_percent < 50:
                budget_status = "💚 הכל תחת שליטה!"
            elif budget_percent < 80:
                budget_status = "💛 אתם במסלול טוב"
            elif budget_percent < 100:
                budget_status = "🧡 מתקרבים לתקציב"
            else:
                budget_status = "❤️ חריגה מהתקציב - כדאי לבדוק"
            
            budget_status += f" ({budget_percent:.0f}%)"
        
        return f"""📊 סיכום השבוע שעבר

💰 הוצאות השבוע: {total_week:,.0f} ₪
📈 סה"כ עד כה: {total_overall:,.0f} ₪

{categories_text.strip()}

⏰ נותרו {days_left} יום לחתונה
{budget_status}

שבוע טוב! 😊"""

    @staticmethod  
    def advance_payment_detected(vendor: str, total_payments: int) -> str:
        """הודעה כשמזהה מקדמה"""
        if total_payments == 2:
            return f"""💡 זיהיתי שזה התשלום השני ל{vendor}

התשלום הראשון עבר להיות מקדמה, וזה התשלום הסופי.
הסכומים מחושבים נכון בדשבورד! ✅"""
        else:
            return f"""💡 זיהיתי מספר תשלומים ל{vendor}

כל התשלומים חוץ מהאחרון הם מקדמות.
הסכום הכולל מחושב נכון! ✅"""

    @staticmethod
    def budget_alert_warning(current_amount: float, budget: float) -> str:
        """התראת תקציב"""
        percentage = (current_amount / budget) * 100
        
        if percentage >= 90:
            return f"""🚨 התראת תקציב!

הוצאתם כבר {current_amount:,.0f} ₪ מתוך {budget:,.0f} ₪
({percentage:.0f}% מהתקציב)

כדאי לבדוק את הדשבורד ולראות איפה אפשר לחסוך 💡"""
        
        elif percentage >= 75:
            return f"""⚠️ עדכון תקציב

הוצאתם {current_amount:,.0f} ₪ מתוך {budget:,.0f} ₪
({percentage:.0f}% מהתקציב)

עדיין בטווח הבטוח! 💪"""
        
        return ""  # אין התראה מתחת ל-75%

    @staticmethod
    def parse_manual_entry(message: str) -> Optional[Dict]:
        """מנתח הודעה להכנסה ידנית"""
        import re
        
        # חיפוש סכום ושם ספק
        amount_patterns = [
            r'(\d+(?:\.\d+)?)\s*(?:ש"ח|₪|שקל|שקלים)',
            r'(?:שילמתי|עלה|עולה|קנה|קיבל|שילמנו)\s*(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*(?:לספק|למקום|ל)',
        ]
        
        vendor_patterns = [
            r'(?:לספק|למקום|ל|אצל|ב)\s*([א-ת\s]+)',
            r'([א-ת\s]+)\s*(?:עלה|עולה|קנה)',
            r'(?:מ|מאת|של)\s*([א-ת\s]+)',
        ]
        
        amount = None
        vendor = None
        
        # חיפוש סכום
        for pattern in amount_patterns:
            match = re.search(pattern, message)
            if match:
                try:
                    amount = float(match.group(1))
                    break
                except ValueError:
                    continue
        
        # חיפוש ספק
        for pattern in vendor_patterns:
            match = re.search(pattern, message)
            if match:
                vendor = match.group(1).strip()
                if len(vendor) > 2:
                    break
        
        if amount and vendor:
            return {
                'vendor': vendor,
                'amount': amount,
                'category': 'אחר',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'payment_method': None,
                'confidence': 60,
                'needs_review': True
            }
        
        return None

    @staticmethod
    def format_expense_for_display(expense: Dict) -> str:
        """מעצב הוצאה לתצוגה"""
        vendor = expense.get('vendor', 'ספק לא ידוע')
        amount = expense.get('amount', 0)
        category = expense.get('category', 'אחר')
        date = expense.get('date', '')
        
        emoji = WEDDING_CATEGORIES.get(category, "📋")
        
        # עיצוב תאריך
        date_display = ""
        if date:
            try:
                date_obj = datetime.strptime(date, '%Y-%m-%d')
                date_display = f" • {date_obj.strftime('%d/%m')}"
            except:
                pass
        
        return f"{emoji} {vendor} - {amount:,.0f} ₪{date_display}"

    @staticmethod
    def get_category_emoji(category: str) -> str:
        """מחזיר אמוג'י של קטגוריה"""
        return WEDDING_CATEGORIES.get(category, "📋")

    @staticmethod
    def validate_date_format(date_str: str) -> bool:
        """מאמת פורמט תאריך"""
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            return True
        except ValueError:
            return False

    @staticmethod
    def system_maintenance() -> str:
        """הודעת תחזוקה"""
        return """🔧 המערכת בתחזוקה זמנית

נחזור בקרוב! 
בינתיים אפשר לשמור קבלות בצד ולשלוח אחר כך 📸"""

    @staticmethod
    def ai_fallback_message() -> str:
        """הודעה כש-AI לא זמין"""
        return """🤖 מערכת הזיהוי האוטומטי זמנית לא זמינה

אבל אל תדאגו! כתבו לי את הפרטים:
💰 כמה שילמתם?
🏪 איזה ספק?

ואני אשמור בשבילכם! ✨"""