import re
import json
import logging
import httpx
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from database_manager import DatabaseManager
from ai_analyzer import AIAnalyzer
from bot_messages import BotMessages
from config import *

logger = logging.getLogger(__name__)

class WebhookHandler:
    """מנהל את כל הודעות WhatsApp הנכנסות ויוצאות"""
    
    def __init__(self):
        self.db = DatabaseManager()
        self.ai = AIAnalyzer()
        self.messages = BotMessages()
        
        # cache לקבוצות פעילות
        self.active_groups_cache = {}
        self.last_cache_update = None
        
        # מעקב אחר הודעות אחרונות לעדכונים
        self.last_expenses_by_group = {}
    
    def _is_authorized_phone(self, sender_data: Dict) -> bool:
        """בודק אם המשתמש מורשה לקבל הודעות"""
        try:
            phone = sender_data.get("sender", "")
            if not phone:
                return False
            
            # אם אין רשימת טלפונים מורשים - מאשר הכל (למטרות בדיקה)
            if not ALLOWED_PHONES:
                logger.warning("No ALLOWED_PHONES configured - allowing all users (not recommended for production)")
                return True
            
            # נרמול מספר טלפון
            clean_phone = phone.replace("@c.us", "").replace("-", "").replace(" ", "")
            
            # בדיקה מול רשימת הטלפונים המורשים
            for allowed in ALLOWED_PHONES:
                clean_allowed = allowed.replace("+", "").replace("-", "").replace(" ", "")
                if clean_allowed in clean_phone or clean_phone in clean_allowed:
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Phone authorization check failed: {e}")
            return False
    
    async def process_webhook(self, payload: Dict) -> Dict[str, any]:
        """מעבד webhook נכנס מWhatsApp"""
        try:
            # חילוץ נתונים בסיסיים
            print("🔍 FULL WEBHOOK PAYLOAD:", json.dumps(payload, indent=2, ensure_ascii=False))
            message_data = payload.get("messageData", {})
            sender_data = payload.get("senderData", {})
            
            message_type = message_data.get("typeMessage")
            chat_id = sender_data.get("chatId", "")
            
            if not chat_id:
                logger.warning("No chat_id in webhook")
                return {"status": "ignored", "reason": "no_chat_id"}
            
            # בדיקת הרשאה - אם לא מורשה, התעלם בדממה
            if not self._is_authorized_phone(sender_data):
                logger.info(f"Unauthorized phone attempted to use bot: {sender_data.get('sender', 'unknown')}")
                return {"status": "unauthorized", "reason": "phone_not_allowed"}
            
            # בדיקת קבוצה פעילה
            group_info = await self._get_group_info(chat_id)
            if not group_info:
                # לא שולח הודעה - פשוט מתעלם
                logger.info(f"Message from unregistered group: {chat_id}")
                return {"status": "group_not_found", "chat_id": chat_id}
            
            logger.info(f"Processing {message_type} from group {group_info['whatsapp_group_id']}")
            
            # עיבוד לפי סוג הודעה
            if message_type == "textMessage":
                return await self._handle_text_message(chat_id, message_data, group_info)
            
            elif message_type == "imageMessage":
                return await self._handle_image_message(chat_id, message_data, group_info)
            
            else:
                logger.info(f"Unsupported message type: {message_type}")
                return {"status": "ignored", "message_type": message_type}
            
        except Exception as e:
            logger.error(f"Webhook processing failed: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _handle_text_message(self, chat_id: str, message_data: Dict, group_info: Dict) -> Dict:
        """מטפל בהודעות טקסט משופר"""
        try:
            text = message_data.get("textMessageData", {}).get("textMessage", "").strip()
            
            if not text:
                return {"status": "empty_message"}
            
            group_id = group_info["whatsapp_group_id"]
            
            # בדיקת הודעות מערכת ותהליך רישום
            if await self._handle_system_commands(chat_id, text, group_info):
                return {"status": "system_command_handled"}
            
            # בדיקת בקשת עדכון לקבלה אחרונה
            recent_expense = self._get_recent_expense(group_id)
            if recent_expense and await self._handle_update_request(chat_id, text, recent_expense, group_info):
                return {"status": "update_handled"}
            
            # ניסיון להכנסה ידנית - עם פרסור משופר
            manual_entry = self.messages.parse_manual_entry(text)
            if manual_entry:
                # שיפור נתוני הספק
                manual_entry = await self._enhance_vendor_data(manual_entry, group_id)
                
                # בדיקת מקדמות אם רלוונטי
                if manual_entry.get('payment_type') in ['advance', 'final']:
                    manual_entry = await self._handle_advance_payments(manual_entry, group_id)
                
                return await self._save_manual_expense(chat_id, manual_entry, group_info)
            
            # אם זה נראה כמו ניסיון להכניס הוצאה אבל נכשל
            if any(word in text for word in ['שילמתי', 'שילמנו', 'עלה', 'קניתי', 'הזמנתי']):
                await self._send_message(
                    chat_id,
                    """😅 לא הצלחתי להבין את ההוצאה.
                    
    נסו לכתוב בפורמט:
    💰 שילמתי 2000 לצלם
    💰 5000 מקדמה לאולם
    💰 עלה לנו 1500 בחנות פרחים"""
                )
                return {"status": "parse_failed"}
            
            # הודעה רגילה - לא שולח עזרה אוטומטית
            return {"status": "regular_message"}
            
        except Exception as e:
            logger.error(f"Text message handling failed: {e}")
            await self._send_message(chat_id, self.messages.error_general())
            return {"status": "error", "error": str(e)}
    
    async def _handle_image_message(self, chat_id: str, message_data: Dict, group_info: Dict) -> Dict:
        """מטפל בתמונות קבלות"""
        try:
            # הורדת תמונה
            image_data = await self._download_image(message_data)
            if not image_data:
                await self._send_message(chat_id, "שגיאה בהורדת התמונה. נסו שוב!")
                return {"status": "download_failed"}
            
            # ניתוח עם AI
            receipt_data = self.ai.analyze_receipt_image(image_data)
            
            # בדיקה אם התמונה לא ברורה (חסרים נתונים חשובים)
            if self._is_image_unclear(receipt_data):
                await self._send_message(chat_id, self.messages.image_unclear_request())
                return {"status": "image_unclear"}
            
            # שיפור ספק עם למידה
            receipt_data = await self._enhance_vendor_data(receipt_data, group_info["whatsapp_group_id"])
            
            # בדיקת מקדמות
            receipt_data = await self._handle_advance_payments(receipt_data, group_info["whatsapp_group_id"])
            
            # שמירה בדאטה בייס
            success = await self._save_expense(receipt_data, group_info)
            
            if success:
                # שליחת הודעת אישור
                message = self.messages.receipt_saved_success(receipt_data)
                
                # הוספת הודעה על מקדמות אם רלוונטי
                if receipt_data.get('payment_type') in ['advance', 'final']:
                    related_expenses = self.db.find_related_expenses(
                        receipt_data['vendor'], 
                        group_info["whatsapp_group_id"]
                    )
                    if len(related_expenses) > 1:
                        advance_msg = self.messages.advance_payment_detected(
                            receipt_data['vendor'], 
                            len(related_expenses)
                        )
                        message += f"\n\n{advance_msg}"
                
                await self._send_message(chat_id, message)
                
                # עדכון cache של הוצאה אחרונה
                self.last_expenses_by_group[group_info["whatsapp_group_id"]] = receipt_data
                
                return {"status": "receipt_saved", "expense_data": receipt_data}
            else:
                await self._send_message(chat_id, "שגיאה בשמירה. נסו שוב!")
                return {"status": "save_failed"}
            
        except Exception as e:
            logger.error(f"Image message handling failed: {e}")
            await self._send_message(chat_id, self.messages.error_general())
            return {"status": "error", "error": str(e)}
    
    async def _handle_system_commands(self, chat_id: str, text: str, group_info: Dict) -> bool:
        """מטפל בפקודות מערכת ותהליך רישום"""
        text_lower = text.lower().strip()
        
        # בדיקה אם אנחנו בתהליך רישום
        if not group_info.get('wedding_date'):
            # שלב 1: קבלת תאריך חתונה
            date_match = re.search(r'(\d{1,2})[/./-](\d{1,2})[/./-](\d{2,4})', text)
            if date_match:
                day, month, year = date_match.groups()
                if len(year) == 2:
                    year = f"20{year}"
                wedding_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                
                # עדכון בדאטה בייס
                self.db.update_couple_field(group_info['whatsapp_group_id'], 'wedding_date', wedding_date)
                
                # שאלה על תקציב
                await self._send_message(
                    chat_id, 
                    f"""✨ מעולה! התאריך נשמר: {day}/{month}/{year}

    💰 עכשיו בואו נגדיר תקציב - כמה תכננתם להוציא על החתונה?
    (אם עדיין לא החלטתם, כתבו "אין עדיין")"""
                )
                return True
        
        elif not group_info.get('budget') or group_info['budget'] == 'אין עדיין':
            # שלב 2: קבלת תקציב
            if text_lower in ['אין', 'אין עדיין', 'לא יודע', 'לא יודעים']:
                # עדכון שאין תקציב
                self.db.update_couple_field(group_info['whatsapp_group_id'], 'budget', 'אין עדיין')
                
                await self._send_message(
                    chat_id,
                    """✅ אין בעיה! תמיד אפשר להוסיף תקציב מאוחר יותר.

    🎉 הכל מוכן! מעכשיו פשוט שלחו תמונות של קבלות ואני אדאג לכל השאר!

    💡 טיפ: אפשר גם לכתוב "שילמתי 2000 לצלם" ואני אשמור את זה"""
                )
                return True
                
            budget_match = re.search(r'(\d+(?:,?\d{3})*(?:\.\d+)?)', text)
            if budget_match:
                budget = float(budget_match.group(1).replace(',', ''))
                
                # עדכון בדאטה בייס
                self.db.update_couple_field(group_info['whatsapp_group_id'], 'budget', str(budget))
                
                await self._send_message(
                    chat_id,
                    f"""✅ תקציב נשמר: {budget:,.0f} ₪

    🎉 מושלם! המערכת מוכנה לעבודה!

    📸 שלחו תמונות קבלות או כתבו הוצאות ואני אסדר הכל
    💡 דוגמה: "שילמתי 5000 מקדמה לצלם" """
                )
                return True
        
        # פקודות רגילות
        if text_lower in ["עזרה", "help", "מה אתה עושה"]:
            await self._send_message(chat_id, self.messages.help_message())
            return True
        
        return False
    

async def _handle_update_request(self, chat_id: str, text: str, recent_expense: Dict, group_info: Dict) -> bool:
    """מטפל בבקשות עדכון עם שמירה לדאטה בייס"""
    try:
        # בדיקת חלון זמן (10 דקות)
        if not self._is_within_edit_window(recent_expense):
            return False
        
        # ניתוח הודעה עם AI
        update_request = self.ai.analyze_message_for_updates(text, recent_expense)
        
        if not update_request or not update_request.get('is_update'):
            return False
        
        update_type = update_request.get('update_type')
        new_value = update_request.get('new_value')
        
        # ביצוע העדכון
        if update_type == "delete":
            # מחיקה אמיתית
            success = self.db.delete_expense(recent_expense['expense_id'])
            if success:
                await self._send_message(chat_id, self.messages.receipt_deleted_success(recent_expense))
                # הסר מ-cache
                if group_info["whatsapp_group_id"] in self.last_expenses_by_group:
                    del self.last_expenses_by_group[group_info["whatsapp_group_id"]]
                return True
        
        else:
            # הכן עדכונים
            updates = {}
            
            if update_type == "vendor":
                updates['vendor'] = new_value
                # נסה לשפר קטגוריה
                enhanced = self.ai.enhance_vendor_with_category(new_value)
                if enhanced['confidence'] > 70:
                    updates['category'] = enhanced['category']
                    
            elif update_type == "amount":
                try:
                    updates['amount'] = float(new_value)
                except ValueError:
                    return False
                    
            elif update_type == "category":
                if new_value in CATEGORY_LIST:
                    updates['category'] = new_value
                else:
                    return False
            
            # עדכון בדאטה בייס
            success = self.db.update_expense(recent_expense['expense_id'], updates)
            
            if success:
                # עדכן את recent_expense
                recent_expense.update(updates)
                
                message = self.messages.receipt_updated_success(recent_expense, update_type)
                await self._send_message(chat_id, message)
                
                # עדכון cache
                self.last_expenses_by_group[group_info["whatsapp_group_id"]] = recent_expense
                return True
        
    except Exception as e:
        logger.error(f"Update request handling failed: {e}")
    
    return False
    
    def _is_image_unclear(self, receipt_data: Dict) -> bool:
        """בודק אם התמונה לא ברורה (חסרים 2+ שדות חשובים)"""
        important_fields = ['vendor', 'amount']
        missing_count = 0
        
        for field in important_fields:
            value = receipt_data.get(field)
            if not value or (field == 'amount' and value == 0):
                missing_count += 1
        
        return missing_count >= 2
    
    async def _enhance_vendor_data(self, receipt_data: Dict, group_id: str) -> Dict:
        """משפר נתוני ספק עם למידה מהדאטה בייס"""
        vendor = receipt_data.get('vendor')
        if not vendor:
            return receipt_data
        
        # חיפוש קטגוריה קיימת
        existing_category = self.db.get_vendor_category(vendor)
        
        if existing_category and existing_category in CATEGORY_LIST:
            receipt_data['category'] = existing_category
            receipt_data['confidence'] = min(95, receipt_data.get('confidence', 80) + 15)
        else:
            # ספק חדש - שיפור עם AI
            enhanced = self.ai.enhance_vendor_with_category(vendor, receipt_data.get('category'))
            
            if enhanced.get('confidence', 0) > 70:
                receipt_data['category'] = enhanced['category']
                receipt_data['confidence'] = enhanced['confidence']
                
                # שמירה למידה עתידית
                self.db.save_vendor_category(
                    vendor, 
                    enhanced['category'], 
                    enhanced['confidence'], 
                    group_id
                )
        
        return receipt_data
    
    async def _handle_advance_payments(self, receipt_data: Dict, group_id: str) -> Dict:
        """מטפל בזיהוי מקדמות אוטומטי"""
        vendor = receipt_data.get('vendor')
        if not vendor:
            return receipt_data
        
        # מחפש תשלומים קודמים לאותו ספק
        related_expenses = self.db.find_related_expenses(vendor, group_id)
        
        if not related_expenses:
            # תשלום ראשון
            receipt_data['payment_type'] = 'full'
        else:
            # תשלום נוסף - הופך הכל למקדמות
            receipt_data['payment_type'] = 'final'
            
            # עדכון התשלומים הקודמים
            self.db.update_payment_types(related_expenses + [receipt_data])
        
        return receipt_data
    
    async def _save_expense(self, receipt_data: Dict, group_info: Dict) -> bool:
        """שומר הוצאה בדאטה בייס"""
        try:
            # הוספת נתוני קבוצה
            receipt_data['group_id'] = group_info['whatsapp_group_id']
            
            # שמירה
            success = self.db.save_expense(receipt_data)
            
            if success:
                logger.info(f"Saved expense for group {group_info['whatsapp_group_id']}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to save expense: {e}")
            return False
    
    async def _save_manual_expense(self, chat_id: str, manual_data: Dict, group_info: Dict) -> Dict:
        """שומר הוצאה שהוכנסה ידנית"""
        try:
            manual_data['group_id'] = group_info['whatsapp_group_id']
            manual_data['source'] = 'manual_entry'
            
            success = self.db.save_expense(manual_data)
            
            if success:
                message = self.messages.manual_entry_saved(
                    manual_data['vendor'], 
                    manual_data['amount']
                )
                await self._send_message(chat_id, message)
                
                # עדכון cache
                self.last_expenses_by_group[group_info["whatsapp_group_id"]] = manual_data
                
                return {"status": "manual_saved", "expense_data": manual_data}
            else:
                await self._send_message(chat_id, "שגיאה בשמירה. נסו שוב!")
                return {"status": "save_failed"}
                
        except Exception as e:
            logger.error(f"Manual expense save failed: {e}")
            await self._send_message(chat_id, self.messages.error_general())
            return {"status": "error", "error": str(e)}
    
    async def _update_expense(self, expense_data: Dict) -> bool:
        """מעדכן הוצאה קיימת"""
        try:
            # כאן צריך לממש עדכון בדאטה בייס
            # לעת עתה נחזיר True
            return True
            
        except Exception as e:
            logger.error(f"Failed to update expense: {e}")
            return False
    
    def _delete_expense(self, expense_id: str) -> bool:
        """מוחק הוצאה (מעדכן סטטוס)"""
        try:
            deleted_at = datetime.now().isoformat()
            return self.db.update_expense_status(expense_id, "deleted", deleted_at)
            
        except Exception as e:
            logger.error(f"Failed to delete expense: {e}")
            return False
    
    async def _get_group_info(self, chat_id: str) -> Optional[Dict]:
        """מחזיר מידע על קבוצה פעילה"""
        try:
            # עדכון cache אם נדרש
            if (not self.last_cache_update or 
                datetime.now() - self.last_cache_update > timedelta(minutes=5)):
                await self._refresh_groups_cache()
            
            return self.active_groups_cache.get(chat_id)
            
        except Exception as e:
            logger.error(f"Failed to get group info: {e}")
            return None
    
    async def _refresh_groups_cache(self):
        """מרענן cache של קבוצות פעילות"""
        try:
            couples = self.db.get_all_active_couples()
            self.active_groups_cache = {}
            
            for couple in couples:
                group_id = couple.get('whatsapp_group_id')
                if group_id:
                    self.active_groups_cache[group_id] = couple
            
            self.last_cache_update = datetime.now()
            logger.debug(f"Refreshed groups cache: {len(self.active_groups_cache)} groups")
            
        except Exception as e:
            logger.error(f"Failed to refresh groups cache: {e}")
    
    def _get_recent_expense(self, group_id: str) -> Optional[Dict]:
        """מחזיר הוצאה אחרונה של קבוצה"""
        return self.last_expenses_by_group.get(group_id)
    
    def _is_within_edit_window(self, expense: Dict) -> bool:
        """בודק אם ההוצאה בטווח זמן לעריכה"""
        try:
            created_at = expense.get('created_at')
            if not created_at:
                return False
            
            expense_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            now = datetime.now(expense_time.tzinfo)
            
            time_diff = now - expense_time
            return time_diff.total_seconds() <= WHATSAPP_SETTINGS["edit_window_minutes"] * 60
            
        except Exception as e:
            logger.error(f"Failed to check edit window: {e}")
            return False
    
    async def _download_image(self, message_data: Dict) -> Optional[bytes]:
        """מוריד תמונה מWhatsApp"""
        try:
            download_url = None
            
            # מחפש URL להורדה
            if "imageMessage" in message_data:
                download_url = message_data["imageMessage"].get("downloadUrl")
            elif "fileMessageData" in message_data:
                download_url = message_data["fileMessageData"].get("downloadUrl")
            
            if not download_url:
                logger.error("No download URL found in message")
                return None
            
            # הורדת הקובץ
            async with httpx.AsyncClient(timeout=WHATSAPP_SETTINGS["api_timeout"]) as client:
                response = await client.get(download_url)
                response.raise_for_status()
                
                image_data = response.content
                logger.info(f"Downloaded image: {len(image_data)} bytes")
                return image_data
                
        except Exception as e:
            logger.error(f"Failed to download image: {e}")
            return None
    
    async def _send_message(self, chat_id: str, message: str) -> bool:
        """שולח הודעה בWhatsApp"""
        try:
            # אם ההודעה ריקה או None - אל תשלח כלום
            if not message or message.strip() == "":
                return True
            
            url = f"https://api.green-api.com/waInstance{GREENAPI_INSTANCE_ID}/sendMessage/{GREENAPI_TOKEN}"
            
            payload = {
                "chatId": chat_id,
                "message": message
            }
            
            async with httpx.AsyncClient(timeout=WHATSAPP_SETTINGS["api_timeout"]) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                
                logger.info(f"Message sent to {chat_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")
            return False
async def _handle_advance_payments(self, receipt_data: Dict, group_id: str) -> Dict:
    """מטפל בזיהוי מקדמות רק לספקים רלוונטיים"""
    vendor = receipt_data.get('vendor', '').lower()
    category = receipt_data.get('category', '')
    
    if not vendor:
        return receipt_data
    
    # בדיקה אם זה ספק שמקבל מקדמות
    is_advance_vendor = False
    
    # בדיקה לפי קטגוריה
    if category in ['אולם', 'צילום', 'מוזיקה', 'מזון']:
        is_advance_vendor = True
    else:
        # בדיקה לפי שם הספק
        for cat, keywords in ADVANCE_PAYMENT_VENDORS.items():
            if any(keyword in vendor for keyword in keywords):
                is_advance_vendor = True
                break
    
    # אם זה לא ספק של מקדמות - תמיד תשלום מלא
    if not is_advance_vendor:
        receipt_data['payment_type'] = 'full'
        return receipt_data
    
    # אם כן - בדוק תשלומים קודמים
    related_expenses = self.db.find_related_expenses(vendor, group_id)
    
    if not related_expenses:
        # תשלום ראשון לספק מקדמות - מקדמה
        receipt_data['payment_type'] = 'advance'
    else:
        # תשלום נוסף - הופך לסופי
        receipt_data['payment_type'] = 'final'
        
        # עדכון התשלומים הקודמים למקדמות
        for i, expense in enumerate(related_expenses):
            payment_type = f"advance_{i+1}" if len(related_expenses) > 1 else "advance"
            self.db.update_expense(expense['expense_id'], {'payment_type': payment_type})
    
    return receipt_data

    # === סיכומים שבועיים ===
    
    async def send_weekly_summaries(self) -> Dict[str, int]:
        """שולח סיכומים שבועיים לכל הקבוצות הפעילות"""
        results = {"sent": 0, "failed": 0}
        
        try:
            couples = self.db.get_all_active_couples()
            
            for couple in couples:
                group_id = couple.get('whatsapp_group_id')
                if not group_id:
                    continue
                
                try:
                    summary_data = await self._calculate_weekly_summary(group_id, couple)
                    message = self.messages.weekly_summary(summary_data)
                    
                    success = await self._send_message(group_id, message)
                    
                    if success:
                        results["sent"] += 1
                    else:
                        results["failed"] += 1
                        
                except Exception as e:
                    logger.error(f"Failed to send weekly summary to {group_id}: {e}")
                    results["failed"] += 1
            
            logger.info(f"Weekly summaries: {results['sent']} sent, {results['failed']} failed")
            
        except Exception as e:
            logger.error(f"Weekly summaries process failed: {e}")
        
        return results
    
    async def _calculate_weekly_summary(self, group_id: str, couple: Dict) -> Dict:
        """מחשב נתוני סיכום שבועי"""
        try:
            # כל ההוצאות של הקבוצה
            expenses = self.db.get_expenses_by_group(group_id)
            
            # סינון השבוע האחרון
            week_ago = datetime.now() - timedelta(days=7)
            week_expenses = []
            
            total_amount = 0
            categories = {}
            
            for expense in expenses:
                if expense.get('status') != 'active':
                    continue
                
                amount = float(expense.get('amount', 0))
                total_amount += amount
                
                category = expense.get('category', 'אחר')
                categories[category] = categories.get(category, 0) + amount
                
                # בדיקה אם ההוצאה מהשבוע האחרון
                created_at = expense.get('created_at', '')
                if created_at:
                    try:
                        expense_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        if expense_date >= week_ago:
                            week_expenses.append(expense)
                    except:
                        pass
            
            week_total = sum(float(exp.get('amount', 0)) for exp in week_expenses)
            
            # חישוב ימים לחתונה
            days_to_wedding = 0
            wedding_date = couple.get('wedding_date')
            if wedding_date:
                try:
                    wedding_dt = datetime.strptime(wedding_date, '%Y-%m-%d')
                    days_to_wedding = max(0, (wedding_dt - datetime.now()).days)
                except:
                    pass
            
            # חישוב אחוז תקציב
            budget_percentage = 0
            budget = couple.get('budget')
            if budget and budget != 'אין עדיין':
                try:
                    budget_amount = float(budget)
                    if budget_amount > 0:
                        budget_percentage = (total_amount / budget_amount) * 100
                except:
                    pass
            
            return {
                'week_total': week_total,
                'overall_total': total_amount,
                'categories': categories,
                'days_to_wedding': days_to_wedding,
                'budget_percentage': budget_percentage
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate weekly summary: {e}")
            return {
                'week_total': 0,
                'overall_total': 0,
                'categories': {},
                'days_to_wedding': 0,
                'budget_percentage': 0
            }
            