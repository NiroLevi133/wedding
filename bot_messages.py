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
        """הודעת אישור קצרה ויפה"""
        vendor = expense_data.get('vendor', 'ספק')
        amount = expense_data.get('amount', 0)
        category = expense_data.get('category', 'אחר')
        emoji = WEDDING_CATEGORIES.get(category, "📋")
        
        return f"""✅ *נשמר!*
{emoji} {vendor} • {amount:,.0f} ₪"""

    @staticmethod
    def receipt_updated_success(expense_data: Dict, changed_field: str = "") -> str:
        """הודעת עדכון קצרה"""
        vendor = expense_data.get('vendor', 'ספק')
        amount = expense_data.get('amount', 0)
        
        field_names = {
            'amount': 'סכום',
            'vendor': 'ספק',
            'category': 'קטגוריה'
        }
        
        changed_text = f" ({field_names.get(changed_field, 'עודכן')})" if changed_field else ""
        
        return f"""✏️ *עודכן{changed_text}*
{vendor} • {amount:,.0f} ₪"""

    @staticmethod
    def receipt_deleted_success(expense_data: Dict) -> str:
        """הודעת מחיקה קצרה"""
        vendor = expense_data.get('vendor', 'ספק')
        return f"🗑️ *נמחק* • {vendor}"

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
        """אישור הכנסה ידנית"""
        return f"""✅ *נוסף ידנית*
{vendor} • {amount:,.0f} ₪"""

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
        """הודעה כשקבוצה לא נמצאת במערכת - לא שולח כלום"""
        return ""

    @staticmethod
    def advance_payment_detected(vendor: str, total_payments: int) -> str:
        """הודעה קצרה על זיהוי מקדמה"""
        if total_payments == 2:
            return f"💡 זוהתה מקדמה ל{vendor}"
        else:
            return f"💡 {total_payments} תשלומים ל{vendor}"

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

💰 סה"כ עד כה: {total_overall:,.0f} ש״ח
⏰ נותרו {days_left} יום לחתונה

שבוע טוב! 😊"""
        
        # יצירת רשימת קטגוריות
        categories_text = ""
        for category, amount in sorted(categories.items(), key=lambda x: x[1], reverse=True):
            emoji = WEDDING_CATEGORIES.get(category, "📋")
            categories_text += f"{emoji} {category}: {amount:,.0f} ש״ח\n"
        
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

💰 הוצאות השבוע: {total_week:,.0f} ש״ח
📈 סה"כ עד כה: {total_overall:,.0f} ש״ח

{categories_text.strip()}

⏰ נותרו {days_left} יום לחתונה
{budget_status}

שבוע טוב! 😊"""

    @staticmethod
    def budget_alert_warning(current_amount: float, budget: float) -> str:
        """התראת תקציב"""
        percentage = (current_amount / budget) * 100
        
        if percentage >= 90:
            return f"""🚨 התראת תקציב!

הוצאתם כבר {current_amount:,.0f} ש״ח מתוך {budget:,.0f} ש״ח
({percentage:.0f}% מהתקציב)

כדאי לבדוק את הדשבורד ולראות איפה אפשר לחסוך 💡"""
        
        elif percentage >= 75:
            return f"""⚠️ עדכון תקציב

הוצאתם {current_amount:,.0f} ש״ח מתוך {budget:,.0f} ש״ח
({percentage:.0f}% מהתקציב)

עדיין בטווח הבטוח! 💪"""
        
        return ""  # אין התראה מתחת ל-75%

    @staticmethod
    def parse_manual_entry(message: str) -> Optional[Dict]:
        """מנתח הודעה להכנסה ידנית משופרת"""
        import re
        from datetime import datetime
        
        # נרמול הטקסט
        text = message.strip()
        
        # דפוסים לזיהוי סכום
        amount_patterns = [
            r'(\d+(?:,?\d{3})*(?:\.\d+)?)\s*(?:ש"ח|שח|שקל|שקלים|₪)',
            r'(?:שילמתי|שילמנו|עלה|עולה|היה|עלות)\s+(\d+(?:,?\d{3})*(?:\.\d+)?)',
            r'(\d+(?:,?\d{3})*(?:\.\d+)?)\s+(?:ל|עבור|בשביל)',
            r'(\d{4,})',  # מספר של לפחות 4 ספרות
        ]
        
        # דפוסים לזיהוי ספק
        vendor_patterns = [
            r'(?:ל|עבור|בשביל|אצל|ב|מ|של)\s*([א-ת\s]+?)(?:\s+|$)',
            r'(צלם|אולם|דיג׳יי|קייטרינג|להקה|זמר|פרחים|שמלה|חליפה|עוגה|הזמנות)',
            r'([א-ת]{2,}(?:\s+[א-ת]+)?)',  # כל מילה בעברית
        ]
        
        # דפוסים לזיהוי סוג תשלום
        payment_type_keywords = {
            'מקדמה': 'advance',
            'קדימה': 'advance',
            'ראשון': 'advance',
            'סופי': 'final',
            'אחרון': 'final',
            'יתרה': 'final'
        }
        
        amount = None
        vendor = None
        payment_type = 'full'
        category = 'אחר'
        
        # חיפוש סכום
        for pattern in amount_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    amount_str = match.group(1).replace(',', '')
                    amount = float(amount_str)
                    if amount > 0:
                        break
                except (ValueError, AttributeError):
                    continue
        
        # חיפוש ספק
        for pattern in vendor_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                potential_vendor = match.group(1).strip()
                # ניקוי מילים מיותרות
                stop_words = ['שילמתי', 'שילמנו', 'עלה', 'עולה', 'ש"ח', 'שקל', 'שקלים']
                if potential_vendor and len(potential_vendor) > 1:
                    if not any(word in potential_vendor for word in stop_words):
                        vendor = potential_vendor
                        break
        
        # זיהוי סוג תשלום
        for keyword, ptype in payment_type_keywords.items():
            if keyword in text:
                payment_type = ptype
                break
        
        # זיהוי קטגוריה לפי מילות מפתח
        category_keywords = {
            'צלם': 'צילום',
            'צילום': 'צילום',
            'אולם': 'אולם',
            'גן': 'אולם',
            'דיג׳יי': 'מוזיקה',
            'DJ': 'מוזיקה',
            'להקה': 'מוזיקה',
            'זמר': 'מוזיקה',
            'קייטרינג': 'מזון',
            'אוכל': 'מזון',
            'עוגה': 'מזון',
            'פרחים': 'עיצוב',
            'עיצוב': 'עיצוב',
            'שמלה': 'לבוש',
            'חליפה': 'לבוש',
            'הזמנות': 'הדפסות'
        }
        
        for keyword, cat in category_keywords.items():
            if keyword in text:
                category = cat
                break
        
        # אם מצאנו גם סכום וגם ספק
        if amount and vendor:
            return {
                'vendor': vendor,
                'amount': amount,
                'category': category,
                'date': datetime.now().strftime('%Y-%m-%d'),
                'payment_type': payment_type,
                'payment_method': None,
                'confidence': 70,
                'needs_review': False,
                'source': 'manual_text'
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
        
        return f"{emoji} {vendor} - {amount:,.0f} ש״ח{date_display}"

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