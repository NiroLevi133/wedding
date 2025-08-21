# auth_endpoints.py - נתיבי API לאימות

from fastapi import Request, Response, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from typing import Optional
import re
import logging
import httpx

logger = logging.getLogger(__name__)

# HTML templates
LOGIN_PAGE = """
<!DOCTYPE html>
<html dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>כניסה למערכת - הוצאות חתונה</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        
        .login-container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.1);
            width: 100%;
            max-width: 400px;
            overflow: hidden;
            animation: slideIn 0.5s ease;
        }
        
        @keyframes slideIn {
            from { transform: translateY(-30px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        
        .login-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        .login-header h1 {
            font-size: 2rem;
            margin-bottom: 10px;
        }
        
        .login-header p {
            opacity: 0.9;
            font-size: 0.95rem;
        }
        
        .login-form {
            padding: 30px;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 500;
        }
        
        .form-input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            font-size: 1rem;
            transition: all 0.3s ease;
            direction: ltr;
            text-align: left;
        }
        
        .form-input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .form-input.error {
            border-color: #dc3545;
        }
        
        .btn {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 1rem;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            margin-top: 10px;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(0,0,0,0.2);
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .message {
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            text-align: center;
            animation: fadeIn 0.3s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
        .message.error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        .message.success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        
        .message.info {
            background: #d1ecf1;
            color: #0c5460;
            border: 1px solid #bee5eb;
        }
        
        .help-text {
            text-align: center;
            color: #6c757d;
            font-size: 0.9rem;
            margin-top: 20px;
        }
        
        .spinner {
            display: none;
            width: 20px;
            height: 20px;
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .loading .spinner {
            display: block;
        }
        
        .loading .btn-text {
            display: none;
        }
        
        #codeSection {
            display: none;
        }
        
        .code-inputs {
            display: flex;
            gap: 10px;
            justify-content: center;
            margin: 20px 0;
            direction: ltr;
        }
        
        .code-input {
            width: 45px;
            height: 50px;
            text-align: center;
            font-size: 1.5rem;
            font-weight: bold;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            transition: all 0.3s ease;
        }
        
        .code-input:focus {
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .timer {
            text-align: center;
            color: #6c757d;
            font-size: 0.9rem;
            margin-top: 10px;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-header">
            <h1>💒 כניסה למערכת</h1>
            <p>ניהול הוצאות החתונה שלכם</p>
        </div>
        
        <div class="login-form">
            <div id="messageArea"></div>
            
            <!-- שלב 1: הזנת מספר טלפון -->
            <div id="phoneSection">
                <form id="phoneForm">
                    <div class="form-group">
                        <label class="form-label">📱 מספר טלפון</label>
                        <input type="tel" 
                               id="phoneInput" 
                               class="form-input" 
                               placeholder="+972501234567"
                               pattern="\\+972[0-9]{9}"
                               required>
                    </div>
                    
                    <button type="submit" class="btn" id="sendCodeBtn">
                        <span class="btn-text">שלח קוד אימות בווטסאפ</span>
                        <div class="spinner"></div>
                    </button>
                </form>
                
                <div class="help-text">
                    הזן את מספר הטלפון שלך<br>
                    נשלח לך קוד אימות בווטסאפ
                </div>
            </div>
            
            <!-- שלב 2: הזנת קוד -->
            <div id="codeSection">
                <form id="codeForm">
                    <div class="form-group">
                        <label class="form-label">🔐 הזן קוד אימות</label>
                        <div class="code-inputs">
                            <input type="text" class="code-input" maxlength="1" pattern="[0-9]">
                            <input type="text" class="code-input" maxlength="1" pattern="[0-9]">
                            <input type="text" class="code-input" maxlength="1" pattern="[0-9]">
                            <input type="text" class="code-input" maxlength="1" pattern="[0-9]">
                            <input type="text" class="code-input" maxlength="1" pattern="[0-9]">
                            <input type="text" class="code-input" maxlength="1" pattern="[0-9]">
                        </div>
                    </div>
                    
                    <button type="submit" class="btn" id="verifyBtn">
                        <span class="btn-text">אמת קוד</span>
                        <div class="spinner"></div>
                    </button>
                    
                    <button type="button" class="btn" id="backBtn" style="background: #6c757d; margin-top: 10px;">
                        חזור
                    </button>
                </form>
                
                <div class="timer" id="timer"></div>
                
                <div class="help-text">
                    הקוד נשלח לווטסאפ שלך<br>
                    הקוד תקף ל-10 דקות
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let currentPhone = '';
        let timerInterval;
        
        // אוטופוקוס על שדות קוד
        document.querySelectorAll('.code-input').forEach((input, index, inputs) => {
            input.addEventListener('input', (e) => {
                if (e.target.value && index < inputs.length - 1) {
                    inputs[index + 1].focus();
                }
            });
            
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Backspace' && !e.target.value && index > 0) {
                    inputs[index - 1].focus();
                }
            });
        });
        
        // טיימר
        function startTimer(seconds) {
            clearInterval(timerInterval);
            const timer = document.getElementById('timer');
            
            timerInterval = setInterval(() => {
                const minutes = Math.floor(seconds / 60);
                const secs = seconds % 60;
                timer.textContent = `זמן נותר: ${minutes}:${secs.toString().padStart(2, '0')}`;
                
                if (seconds <= 0) {
                    clearInterval(timerInterval);
                    timer.textContent = 'הקוד פג תוקף';
                    showMessage('הקוד פג תוקף. נסה שוב', 'error');
                    showPhoneSection();
                }
                
                seconds--;
            }, 1000);
        }
        
        // הצג הודעה
        function showMessage(message, type = 'info') {
            const messageArea = document.getElementById('messageArea');
            messageArea.innerHTML = `<div class="message ${type}">${message}</div>`;
            
            if (type === 'success') {
                setTimeout(() => {
                    messageArea.innerHTML = '';
                }, 3000);
            }
        }
        
        // מעבר לשלב הטלפון
        function showPhoneSection() {
            document.getElementById('phoneSection').style.display = 'block';
            document.getElementById('codeSection').style.display = 'none';
            clearInterval(timerInterval);
        }
        
        // מעבר לשלב הקוד
        function showCodeSection() {
            document.getElementById('phoneSection').style.display = 'none';
            document.getElementById('codeSection').style.display = 'block';
            document.querySelectorAll('.code-input').forEach(input => input.value = '');
            document.querySelector('.code-input').focus();
            startTimer(600); // 10 דקות
        }
        
        // שליחת מספר טלפון
        document.getElementById('phoneForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const phoneInput = document.getElementById('phoneInput');
            const phone = phoneInput.value.trim();
            
            if (!phone.match(/^\\+972[0-9]{9}$/)) {
                showMessage('מספר טלפון לא תקין. הזן בפורמט +972501234567', 'error');
                return;
            }
            
            currentPhone = phone;
            const btn = document.getElementById('sendCodeBtn');
            btn.classList.add('loading');
            btn.disabled = true;
            
            try {
                const response = await fetch('/auth/send-code', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({phone: phone})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showMessage('קוד אימות נשלח לווטסאפ שלך', 'success');
                    showCodeSection();
                } else {
                    showMessage(data.message || 'שגיאה בשליחת קוד', 'error');
                }
            } catch (error) {
                showMessage('שגיאה בחיבור לשרת', 'error');
            } finally {
                btn.classList.remove('loading');
                btn.disabled = false;
            }
        });
        
        // אימות קוד
        document.getElementById('codeForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const codeInputs = document.querySelectorAll('.code-input');
            const code = Array.from(codeInputs).map(input => input.value).join('');
            
            if (code.length !== 6) {
                showMessage('יש להזין קוד בן 6 ספרות', 'error');
                return;
            }
            
            const btn = document.getElementById('verifyBtn');
            btn.classList.add('loading');
            btn.disabled = true;
            
            try {
                const response = await fetch('/auth/verify-code', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        phone: currentPhone,
                        code: code
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showMessage('אימות הצליח! מעביר לדשבורד...', 'success');
                    setTimeout(() => {
                        window.location.href = '/dashboard';
                    }, 1000);
                } else {
                    showMessage(data.message || 'קוד שגוי', 'error');
                    codeInputs.forEach(input => input.value = '');
                    codeInputs[0].focus();
                }
            } catch (error) {
                showMessage('שגיאה בחיבור לשרת', 'error');
            } finally {
                btn.classList.remove('loading');
                btn.disabled = false;
            }
        });
        
        // כפתור חזור
        document.getElementById('backBtn').addEventListener('click', () => {
            showPhoneSection();
        });
    </script>
</body>
</html>
"""

def setup_auth_routes(app, auth_manager, GREEN_ID, GREEN_TOKEN):
    """מוסיף את נתיבי האימות לאפליקציה"""
    
    @app.get("/login", response_class=HTMLResponse)
    async def login_page():
        """דף הכניסה"""
        return LOGIN_PAGE
    
    @app.post("/auth/send-code")
    async def send_verification_code(request: Request):
        """שולח קוד אימות בווטסאפ"""
        try:
            data = await request.json()
            phone = data.get('phone', '').strip()
            
            # ולידציה
            if not re.match(r'^\+972[0-9]{9}$', phone):
                return JSONResponse({
                    "success": False,
                    "message": "מספר טלפון לא תקין"
                })
            
            # צור קוד
            success, message, code = auth_manager.create_verification_code(phone)
            
            if not success:
                return JSONResponse({
                    "success": False,
                    "message": message
                })
            
            # שלח בווטסאפ
            if GREEN_ID and GREEN_TOKEN:
                try:
                    chat_id = phone.replace('+', '') + '@c.us'
                    url = f"https://api.green-api.com/waInstance{GREEN_ID}/sendMessage/{GREEN_TOKEN}"
                    
                    whatsapp_message = f"""🔐 *קוד אימות למערכת הוצאות החתונה*

הקוד שלך: *{code}*

הקוד תקף ל-10 דקות.
אל תשתף קוד זה עם אף אחד.

💡 טיפ: הקוד קל לזכירה - שים לב לתבנית הספרות הכפולות!"""
                    
                    async with httpx.AsyncClient(timeout=30) as client:
                        response = await client.post(url, json={
                            "chatId": chat_id,
                            "message": whatsapp_message
                        })
                        response.raise_for_status()
                    
                    logger.info(f"Verification code sent to {phone}: {code}")
                    
                    return JSONResponse({
                        "success": True,
                        "message": "קוד נשלח בווטסאפ"
                    })
                    
                except Exception as e:
                    logger.error(f"Failed to send WhatsApp message: {e}")
                    return JSONResponse({
                        "success": False,
                        "message": "שגיאה בשליחת הודעת ווטסאפ"
                    })
            else:
                # מצב פיתוח - הצג בלוג
                logger.info(f"DEV MODE - Verification code for {phone}: {code}")
                return JSONResponse({
                    "success": True,
                    "message": f"קוד לפיתוח: {code}"
                })
                
        except Exception as e:
            logger.error(f"Error in send_verification_code: {e}")
            return JSONResponse({
                "success": False,
                "message": "שגיאה בשרת"
            })
    
    @app.post("/auth/verify-code")
    async def verify_code(request: Request, response: Response):
        """מאמת קוד שהוזן"""
        try:
            data = await request.json()
            phone = data.get('phone', '').strip()
            code = data.get('code', '').strip()
            
            # אמת קוד
            success, message, session_token = auth_manager.verify_code(phone, code)
            
            if success:
                # הצב cookie
                response.set_cookie(
                    key="session_token",
                    value=session_token,
                    max_age=3600,  # שעה
                    httponly=True,
                    secure=True,
                    samesite="lax"
                )
                
                return JSONResponse({
                    "success": True,
                    "message": "אימות הצליח"
                })
            else:
                return JSONResponse({
                    "success": False,
                    "message": message
                })
                
        except Exception as e:
            logger.error(f"Error in verify_code: {e}")
            return JSONResponse({
                "success": False,
                "message": "שגיאה בשרת"
            })
    
    @app.post("/auth/logout")
    async def logout(request: Request, response: Response):
        """יציאה מהמערכת"""
        session_token = request.cookies.get("session_token")
        
        if session_token:
            auth_manager.logout(session_token)
        
        response.delete_cookie("session_token")
        
        return JSONResponse({
            "success": True,
            "message": "יצאת מהמערכת"
        })
    
    @app.get("/auth/check")
    async def check_auth(request: Request):
        """בדיקת סטטוס התחברות"""
        session_token = request.cookies.get("session_token")
        
        if not session_token:
            return JSONResponse({
                "authenticated": False
            })
        
        is_valid, phone = auth_manager.validate_session(session_token)
        
        return JSONResponse({
            "authenticated": is_valid,
            "phone": phone if is_valid else None
        })
    
    # Middleware לבדיקת אימות
    def require_auth(request: Request):
        """Dependency לדרישת אימות"""
        session_token = request.cookies.get("session_token")
        
        if not session_token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        is_valid, phone = auth_manager.validate_session(session_token)
        
        if not is_valid:
            raise HTTPException(status_code=401, detail="Session expired")
        
        # הוסף את מספר הטלפון ל-request state
        request.state.user_phone = phone
        return phone
    
    return require_auth