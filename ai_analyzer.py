import re
import json
import base64
import logging
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from openai import OpenAI
from config import *

logger = logging.getLogger(__name__)

class AIAnalyzer:
    """מנתח תמונות קבלות עם OpenAI ומזהה עדכונים"""
    
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
        if not self.client:
            logger.warning("OpenAI client not initialized - API key missing")
    
    def analyze_receipt_image(self, image_bytes: bytes) -> Dict:
        """מנתח תמונת קבלה ומחזיר נתונים מובנים"""
        
        if not self.client:
            return self._create_fallback_receipt()
        
        try:
            # המרה ל-base64
            b64_image = base64.b64encode(image_bytes).decode('utf-8')
            
            # הכנת הפרומפט
            system_prompt = self._get_receipt_analysis_prompt()
            user_prompt = "נתח את תמונת הקבלה הזו ותחזיר JSON עם הנתונים:"
            
            # קריאה ל-OpenAI
            response = self.client.chat.completions.create(
                model=AI_SETTINGS["model"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
                    ]}
                ],
                temperature=AI_SETTINGS["temperature"],
                max_tokens=AI_SETTINGS["max_tokens"]
            )
            
            # עיבוד התשובה
            content = response.choices[0].message.content.strip()
            receipt_data = self._parse_ai_response(content)
            
            # ניקוי ואימות
            receipt_data = self._clean_and_validate_receipt(receipt_data)
            
            logger.info(f"Successfully analyzed receipt: {receipt_data.get('vendor', 'Unknown')}")
            return receipt_data
            
        except Exception as e:
            logger.error(f"Receipt analysis failed: {e}")
            return self._create_fallback_receipt()
    
    def _get_receipt_analysis_prompt(self) -> str:
        """יוצר פרומפט מפורט לניתוח קבלות"""
        categories_text = ", ".join(CATEGORY_LIST)
        
        return f"""אתה מומחה בניתוח קבלות ותמונות חשבוניות לחתונות בישראל.

חוקי ניתוח קריטיים:
1. תאריך - בישראל התאריך הוא יום/חודש/שנה (DD/MM/YYYY)
2. סכום - חפש את הסכום הסופי בלבד! מילים כמו "סה״כ", "סך הכל", "לתשלום", "Total"
3. ספק - שם העסק הראשי בראש הקבלה או על החשבונית
4. מטבע - ₪, שקל, NIS = ILS; $ = USD; € = EUR
5. קטגוריה - בחר מהרשימה: {categories_text}

כללי קטגוריזציה:
- אולם: אולמות, גנים, מתחמי אירועים
- מזון: קייטרינג, מסעדות, פירות, עוגות, פיצוחים, משקאות
- צילום: צלמים, וידאו, דרונים, עריכה, אלבומים
- לבוש: שמלות כלה, חליפות, נעליים, בגדים לחתונה
- עיצוב: פרחים, זרים, דקורציה, קישוטים
- הדפסות: הזמנות, שלטים, תפריטים, מדיה
- אקססוריז: תכשיטים, תיקים, עניבות, חפצים קטנים
- מוזיקה: דיג'יי, להקות, זמרים, כלי נגינה
- הסעות: מוניות, אוטובוסים, לינה, נסיעות
- אחר: כל דבר שלא מתאים לקטגוריות האחרות

עקרונות חשובים:
- אם לא בטוח - תן null ולא תמציא מידע
- סכום חייב להיות מספר חיובי או null
- תאריך בפורמט YYYY-MM-DD או null
- ספק - שם נקי בלי "בע״מ" או תוספות מיותרות

JSON נדרש:
{{
  "vendor": "שם הספק או null",
  "amount": מספר_חיובי או null,
  "date": "YYYY-MM-DD" או null,
  "category": "קטגוריה_מהרשימה",
  "payment_method": "card/cash/bank או null",
  "invoice_number": "מספר חשבונית או null",
  "confidence": מספר בין 0-100
}}

החזר רק JSON, בלי טקסט נוסף!"""
    
    def _parse_ai_response(self, content: str) -> Dict:
        """מפרסר תשובה של AI ומחזיר dict"""
        try:
            # ניקוי מארקדאון
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
            content = re.sub(r"\s*```$", "", content)
            content = content.strip()
            
            # ניסיון לפרסר JSON
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # ניסיון תיקון בסיסי
                content = content.replace("'", '"')
                content = re.sub(r',\s*}', '}', content)
                data = json.loads(content)
            
            return data
            
        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}")
            return {}
    
    def _clean_and_validate_receipt(self, data: Dict) -> Dict:
        """מנקה ומאמת נתוני קבלה"""
        cleaned = {}
        
        # ניקוי ספק
        vendor = data.get('vendor')
        if vendor and len(str(vendor).strip()) >= 2:
            vendor = str(vendor).strip()
            # הסר ביטויים מיותרים
            vendor = re.sub(r'(בע"מ|בעמ|ltd|inc).*$', '', vendor, flags=re.IGNORECASE).strip()
            cleaned['vendor'] = vendor
        else:
            cleaned['vendor'] = self._generate_fallback_vendor_name(data)
        
        # ניקוי סכום
        amount = data.get('amount')
        if amount is not None:
            try:
                if isinstance(amount, str):
                    amount = re.sub(r'[^\d.]', '', amount.replace(',', ''))
                amount = float(amount)
                cleaned['amount'] = amount if amount > 0 else 0
            except (ValueError, TypeError):
                cleaned['amount'] = 0
        else:
            cleaned['amount'] = 0
        
        # ניקוי תאריך
        date_str = data.get('date')
        cleaned['date'] = self._normalize_date(date_str)
        
        # ניקוי קטגוריה
        category = data.get('category', 'אחר')
        if category in CATEGORY_LIST:
            cleaned['category'] = category
        else:
            cleaned['category'] = 'אחר'
        
        # ניקוי דרך תשלום
        payment = data.get('payment_method')
        cleaned['payment_method'] = self._normalize_payment_method(payment)
        
        # מספר חשבונית
        invoice = data.get('invoice_number')
        if invoice and len(str(invoice).strip()) >= 2:
            cleaned['invoice_number'] = str(invoice).strip()
        else:
            cleaned['invoice_number'] = None
        
        # רמת ביטחון
        confidence = data.get('confidence', 80)
        try:
            cleaned['confidence'] = max(0, min(100, int(confidence)))
        except:
            cleaned['confidence'] = 80
        
        # קביעת needs_review
        cleaned['needs_review'] = (
            cleaned['amount'] == 0 or 
            not cleaned['vendor'] or
            cleaned['confidence'] < 70
        )
        
        return cleaned
    
    def _generate_fallback_vendor_name(self, data: Dict) -> str:
        """יוצר שם ספק יפה כשלא מזהה"""
        category = data.get('category', 'אחר')
        
        fallbacks = {
            'מזון': 'מסעדה',
            'לבוש': 'חנות בגדים', 
            'צילום': 'סטודיו צילום',
            'עיצוב': 'חנות פרחים',
            'הדפסות': 'בית דפוס',
            'אקססוריז': 'חנות אקססוריז',
            'מוזיקה': 'אמן מוזיקלי',
            'הסעות': 'שירות הסעות',
            'אולם': 'אולם אירועים'
        }
        
        return fallbacks.get(category, 'ספק שירותים')
    
    def _normalize_date(self, date_str: str) -> Optional[str]:
        """מנרמל תאריך לפורמט ISO"""
        if not date_str:
            return datetime.now().strftime('%Y-%m-%d')
        
        try:
            date_str = str(date_str).strip()
            
            # פטרנים ישראליים
            patterns = [
                (r'(\d{1,2})[/./-](\d{1,2})[/./-](\d{4})', 'DMY'),  # DD/MM/YYYY
                (r'(\d{4})[/./-](\d{1,2})[/./-](\d{1,2})', 'YMD'),  # YYYY/MM/DD
                (r'(\d{1,2})[/./-](\d{1,2})[/./-](\d{2})', 'DMY2'), # DD/MM/YY
            ]
            
            for pattern, format_type in patterns:
                match = re.search(pattern, date_str)
                if match:
                    groups = [int(g) for g in match.groups()]
                    
                    if format_type == 'DMY':
                        day, month, year = groups
                    elif format_type == 'YMD':
                        year, month, day = groups
                    elif format_type == 'DMY2':
                        day, month, year = groups
                        year = 2000 + year if year < 50 else 1900 + year
                    
                    # אימות תאריך
                    if 1 <= day <= 31 and 1 <= month <= 12 and 2020 <= year <= 2030:
                        return f"{year:04d}-{month:02d}-{day:02d}"
            
            # אם לא מצליח - השתמש בהיום
            return datetime.now().strftime('%Y-%m-%d')
            
        except Exception as e:
            logger.debug(f"Date normalization failed: {e}")
            return datetime.now().strftime('%Y-%m-%d')
    
    def _normalize_payment_method(self, payment: str) -> Optional[str]:
        """מנרמל דרך תשלום"""
        if not payment:
            return None
        
        payment = str(payment).lower().strip()
        
        if any(word in payment for word in ['אשראי', 'כרטיס', 'card', 'ויזה', 'מאסטר', 'visa', 'master']):
            return 'card'
        elif any(word in payment for word in ['מזומן', 'cash', 'כסף']):
            return 'cash'
        elif any(word in payment for word in ['העברה', 'בנק', 'bank', 'ביט', 'bit']):
            return 'bank'
        
        return None
    
    def _create_fallback_receipt(self) -> Dict:
        """יוצר קבלה בסיסית כשה-AI נכשל"""
        return {
            'vendor': 'ספק לא זוהה',
            'amount': 0,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'category': 'אחר',
            'payment_method': None,
            'invoice_number': None,
            'confidence': 0,
            'needs_review': True
        }
    
    # === זיהוי עדכונים בהודעות ===
    
    def analyze_message_for_updates(self, message: str, recent_expense: Dict) -> Optional[Dict]:
        """מנתח הודעה לזיהוי בקשות עדכון"""
        
        if not self.client or not message.strip():
            return None
        
        try:
            prompt = f"""אנתח הודעה כדי לראות אם זה בקשת עדכון לקבלה אחרונה.

הקבלה האחרונה:
ספק: {recent_expense.get('vendor', 'לא ידוע')}
סכום: {recent_expense.get('amount', 0)} ש"ח
קטגוריה: {recent_expense.get('category', 'אחר')}

ההודעה: "{message}"

קטגוריות זמינות: {', '.join(CATEGORY_LIST)}

אם זה בקשת עדכון, החזר JSON:
{{
  "is_update": true,
  "update_type": "vendor/amount/category/delete",
  "new_value": "הערך החדש",
  "confidence": מספר 0-100
}}

אם זה לא בקשת עדכון:
{{
  "is_update": false
}}

דוגמאות לעדכונים:
- "זה בגדים לא צילום" → update_type: "category", new_value: "לבוש"
- "2500 לא 2000" → update_type: "amount", new_value: "2500"
- "זה רמי לוי" → update_type: "vendor", new_value: "רמי לוי"
- "מחק את זה" → update_type: "delete", new_value: null

החזר רק JSON!"""

            response = self.client.chat.completions.create(
                model=AI_SETTINGS["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200
            )
            
            content = response.choices[0].message.content.strip()
            result = self._parse_ai_response(content)
            
            if result.get('is_update') and result.get('confidence', 0) > 60:
                logger.info(f"Detected update request: {result.get('update_type')}")
                return result
            
            return None
            
        except Exception as e:
            logger.error(f"Message analysis failed: {e}")
            return None
    
    # === בדיקת זיהוי ספקים ===
    
    # תיקונים ל-ai_analyzer.py
# החלף את enhance_vendor_with_category:

    def enhance_vendor_with_category(self, vendor_name: str, existing_category: str = None) -> Dict:
        """מנתח ספק ומציע קטגוריה מתאימה עם למידה משופרת"""
        
        VENDOR_KEYWORDS = {
            'אולם': ['אולם', 'גן אירועים', 'מתחם', 'אולמי', 'גני'],
            'מזון': ['קייטרינג', 'מסעדה', 'שף', 'מטבח', 'אוכל', 'בר', 'משקאות', 'יין', 'עוגה', 'קונדיטור'],
            'צילום': ['צלם', 'צילום', 'וידאו', 'סטודיו', 'סטילס', 'דרון', 'אלבום'],
            'לבוש': ['שמלה', 'חליפה', 'בגדים', 'נעליים', 'חנות אופנה', 'בוטיק', 'חייט'],
            'עיצוב': ['פרחים', 'עיצוב', 'דקורציה', 'קישוט', 'זר', 'סידור'],
            'הדפסות': ['הזמנות', 'דפוס', 'הדפסה', 'גרפיקה', 'עיצוב גרפי'],
            'אקססוריז': ['תכשיטים', 'טבעת', 'שעון', 'אקססוריז', 'מאקס', 'max', 'תיק'],
            'מוזיקה': ['דיג׳יי', 'DJ', 'להקה', 'זמר', 'נגן', 'מוזיקה', 'הגברה'],
            'הסעות': ['הסעה', 'אוטובוס', 'מונית', 'רכב', 'טיולים', 'נסיעות']
        }
        
        vendor_lower = vendor_name.lower()
        
        for category, keywords in VENDOR_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in vendor_lower:
                    return {
                        'vendor_name': vendor_name,
                        'category': category,
                        'confidence': 95
                    }
        
        KNOWN_VENDORS = {
            'מאקס': 'אקססוריז',
            'max': 'אקססוריז',
            'זארה': 'לבוש',
            'רמי לוי': 'מזון',
            'שופרסל': 'מזון',
            'איקאה': 'עיצוב'
        }
        
        for vendor_key, category in KNOWN_VENDORS.items():
            if vendor_key in vendor_lower:
                return {
                    'vendor_name': vendor_name,
                    'category': category,
                    'confidence': 90
                }
        
        if self.client:
            try:
                prompt = f"""נתח את שם הספק וקבע קטגוריה לחתונה.

ספק: "{vendor_name}"

קטגוריות אפשריות: {', '.join(CATEGORY_LIST)}

תן משקל למילים האלה:
- מאקס/MAX = חנות אקססוריז
- פרחים/זר = עיצוב
- צלם/סטודיו = צילום
- אולם/גן = אולם

החזר JSON:
{{
  "vendor_name": "{vendor_name}",
  "category": "קטגוריה מהרשימה",
  "confidence": 80-100
}}"""

                response = self.client.chat.completions.create(
                    model=AI_SETTINGS["model"],
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=150
                )
                
                content = response.choices[0].message.content.strip()
                result = self._parse_ai_response(content)
                
                if result.get('category') in CATEGORY_LIST:
                    return result
                    
            except Exception as e:
                logger.error(f"AI vendor categorization failed: {e}")
        
        return {
            'vendor_name': vendor_name,
            'category': existing_category or 'אחר',
            'confidence': 50
        }

    def health_check(self) -> Dict[str, bool]:
        """בודק שה-AI עובד"""
        checks = {
            "openai_configured": bool(self.client),
            "can_analyze_text": False,
            "model_accessible": False
        }
        
        if self.client:
            try:
                response = self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": "Test"}],
                    max_tokens=10
                )
                
                if response.choices:
                    checks["can_analyze_text"] = True
                    checks["model_accessible"] = True
                    
            except Exception as e:
                logger.error(f"AI health check failed: {e}")
        
        return checks