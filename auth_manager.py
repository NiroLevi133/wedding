# auth_manager.py - מערכת אימות לדשבורד

import os
import random
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import json
import logging
from collections import defaultdict
from typing import Tuple, Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class AuthManager:
    """מנהל אימות מאובטח עם קודים פשוטים לזכירה"""
    
    def __init__(self):
        # מאגר קודי אימות
        self.verification_codes: Dict[str, Dict[str, Any]] = {}
        
        # מאגר sessions
        self.sessions: Dict[str, Dict[str, Any]] = {}
        
        # מאגר ניסיונות כניסה
        self.login_attempts: Dict[str, int] = defaultdict(int)
        self.blocked_until: Dict[str, datetime] = {}
        
        # הגדרות
        self.SESSION_DURATION = timedelta(hours=1)  # שעה
        self.CODE_EXPIRY = timedelta(minutes=10)  # 10 דקות לקוד
        self.MAX_ATTEMPTS = 5
        self.BLOCK_DURATION = timedelta(minutes=30)  # חסימה ל-30 דקות
        
        # Secret key for session tokens
        self.SECRET_KEY = os.getenv("SESSION_SECRET_KEY", secrets.token_hex(32))
    
    def generate_easy_code(self) -> str:
        """יוצר קוד קל לזכירה עם ספרות כפולות"""
        patterns = [
            # תבניות של ספרות כפולות
            lambda: f"{random.randint(11, 99)}{random.randint(11, 99)}{random.randint(11, 99)}",  # כמו 224466
            lambda: f"{random.randint(111, 999)}{random.randint(111, 999)}",  # כמו 222888
            lambda: f"{random.randint(1, 9)*111}{random.randint(1, 9)*111}",  # כמו 111222
            lambda: f"{random.randint(10, 99)}{random.randint(10, 99)}{random.randint(10, 99)}",  # כמו 121314
        ]
        
        # בחר תבנית רנדומלית
        pattern = random.choice(patterns)
        code = pattern()
        
        # ודא שהקוד באורך 6 ספרות
        if len(code) < 6:
            code = code.zfill(6)
        elif len(code) > 6:
            code = code[:6]
            
        return code
    
    def is_phone_blocked(self, phone: str) -> Tuple[bool, Optional[int]]:
        """בודק אם מספר טלפון חסום"""
        if phone in self.blocked_until:
            blocked_until = self.blocked_until[phone]
            now = datetime.now(timezone.utc)
            
            if now < blocked_until:
                remaining_minutes = int((blocked_until - now).total_seconds() / 60)
                return True, remaining_minutes
            else:
                # הסר חסימה שפגה
                del self.blocked_until[phone]
                self.login_attempts[phone] = 0
        
        return False, None
    
    def create_verification_code(self, phone: str) -> tuple[bool, str, Optional[str]]:
        """יוצר קוד אימות חדש למספר טלפון"""
        
        # בדוק אם המספר חסום
        is_blocked, remaining_minutes = self.is_phone_blocked(phone)
        if is_blocked:
            return False, f"המספר חסום עוד {remaining_minutes} דקות", None
        
        # צור קוד קל לזכירה
        code = self.generate_easy_code()
        
        # שמור את הקוד
        self.verification_codes[phone] = {
            'code': code,
            'created_at': datetime.now(timezone.utc),
            'attempts': 0
        }
        
        logger.info(f"Created verification code for {phone}: {code}")
        return True, "קוד נשלח", code
    
    def verify_code(self, phone: str, code: str) -> tuple[bool, str, Optional[str]]:
        """מאמת קוד שהוזן"""
        
        # בדוק אם המספר חסום
        is_blocked, remaining_minutes = self.is_phone_blocked(phone)
        if is_blocked:
            return False, f"המספר חסום עוד {remaining_minutes} דקות", None
        
        # בדוק אם יש קוד למספר
        if phone not in self.verification_codes:
            return False, "לא נמצא קוד למספר זה", None
        
        code_data = self.verification_codes[phone]
        
        # בדוק תפוגה
        created_at = code_data['created_at']
        now = datetime.now(timezone.utc)
        if now - created_at > self.CODE_EXPIRY:
            del self.verification_codes[phone]
            return False, "הקוד פג תוקף", None
        
        # בדוק התאמה
        if code_data['code'] != code:
            # הגדל מונה ניסיונות
            code_data['attempts'] += 1
            self.login_attempts[phone] += 1
            
            remaining_attempts = self.MAX_ATTEMPTS - self.login_attempts[phone]
            
            if self.login_attempts[phone] >= self.MAX_ATTEMPTS:
                # חסום את המספר
                self.blocked_until[phone] = datetime.now(timezone.utc) + self.BLOCK_DURATION
                del self.verification_codes[phone]
                return False, "יותר מדי ניסיונות. המספר נחסם ל-30 דקות", None
            
            return False, f"קוד שגוי. נותרו {remaining_attempts} ניסיונות", None
        
        # קוד נכון! צור session
        session_token = self.create_session(phone)
        
        # נקה נתונים
        del self.verification_codes[phone]
        self.login_attempts[phone] = 0
        
        return True, "אימות הצליח", session_token
    
    def create_session(self, phone: str) -> str:
        """יוצר session חדש"""
        # צור token ייחודי
        session_token = hashlib.sha256(
            f"{phone}:{datetime.now().isoformat()}:{secrets.token_hex(16)}".encode()
        ).hexdigest()
        
        # שמור session
        self.sessions[session_token] = {
            'phone': phone,
            'created_at': datetime.now(timezone.utc),
            'last_activity': datetime.now(timezone.utc)
        }
        
        logger.info(f"Created session for {phone}")
        return session_token
    
    def validate_session(self, session_token: str) -> tuple[bool, Optional[str]]:
        """מאמת session ומחזיר את מספר הטלפון"""
        if not session_token or session_token not in self.sessions:
            return False, None
        
        session_data = self.sessions[session_token]
        now = datetime.now(timezone.utc)
        
        # בדוק תפוגה
        if now - session_data['last_activity'] > self.SESSION_DURATION:
            del self.sessions[session_token]
            logger.info(f"Session expired for {session_data['phone']}")
            return False, None
        
        # עדכן פעילות אחרונה
        session_data['last_activity'] = now
        
        return True, session_data['phone']
    
    def logout(self, session_token: str) -> bool:
        """מוחק session"""
        if session_token in self.sessions:
            phone = self.sessions[session_token]['phone']
            del self.sessions[session_token]
            logger.info(f"Logged out {phone}")
            return True
        return False
    
    def cleanup_expired(self):
        """מנקה קודים ו-sessions שפגו"""
        now = datetime.now(timezone.utc)
        
        # נקה קודים שפגו
        expired_codes = []
        for phone, code_data in self.verification_codes.items():
            if now - code_data['created_at'] > self.CODE_EXPIRY:
                expired_codes.append(phone)
        
        for phone in expired_codes:
            del self.verification_codes[phone]
        
        # נקה sessions שפגו
        expired_sessions = []
        for token, session_data in self.sessions.items():
            if now - session_data['last_activity'] > self.SESSION_DURATION:
                expired_sessions.append(token)
        
        for token in expired_sessions:
            del self.sessions[token]
        
        # נקה חסימות שפגו
        expired_blocks = []
        for phone, blocked_until in self.blocked_until.items():
            if now >= blocked_until:
                expired_blocks.append(phone)
        
        for phone in expired_blocks:
            del self.blocked_until[phone]
            self.login_attempts[phone] = 0
        
        if expired_codes or expired_sessions or expired_blocks:
            logger.info(f"Cleaned up: {len(expired_codes)} codes, {len(expired_sessions)} sessions, {len(expired_blocks)} blocks")

# Singleton instance
auth_manager = AuthManager()