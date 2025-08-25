import os
import logging
import asyncio
from datetime import datetime
from typing import Dict

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Import our modules
from config import *
from database_manager import DatabaseManager
from ai_analyzer import AIAnalyzer
from webhook_handler import WebhookHandler
from bot_messages import BotMessages
from user_dashboard import UserDashboard
from admin_panel import AdminPanel

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOGGING_CONFIG["level"]),
    format=LOGGING_CONFIG["format"]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Wedding Expenses Bot",
    description="מערכת ניהול הוצאות חתונה עם WhatsApp Bot",
    version="1.0.0",
    docs_url="/api-docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if DEBUG else ["https://your-domain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
db = DatabaseManager()
ai = AIAnalyzer()
webhook_handler = WebhookHandler()
messages = BotMessages()
user_dashboard = UserDashboard(db)
admin_panel = AdminPanel(db)

# Global state for admin authentication
ADMIN_SESSION_TOKEN = None

def verify_webhook_signature(request: Request) -> bool:
    """Verify webhook signature for security"""
    if not WEBHOOK_SHARED_SECRET:
        return True  # Allow all in dev mode
    
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    
    if not auth_header:
        return False
    
    return (auth_header.endswith(WEBHOOK_SHARED_SECRET) or 
            auth_header == f"Bearer {WEBHOOK_SHARED_SECRET}")

def get_admin_auth():
    """Simple admin authentication dependency"""
    global ADMIN_SESSION_TOKEN
    
    def check_admin_auth(request: Request):
        # Simple token-based auth for demo
        token = request.cookies.get("admin_token") or request.headers.get("X-Admin-Token")
        
        if not token or token != ADMIN_SESSION_TOKEN:
            raise HTTPException(status_code=401, detail="Admin authentication required")
        
        return True
    
    return check_admin_auth

# === WEBHOOK ENDPOINTS ===

@app.post("/webhook")
async def webhook_endpoint(request: Request):
    """Main WhatsApp webhook endpoint"""
    logger.info("Webhook received")
    
    try:
        # Verify signature
        if not verify_webhook_signature(request):
            logger.warning("Unauthorized webhook attempt")
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        # Process webhook
        payload = await request.json()
        result = await webhook_handler.process_webhook(payload)
        
        logger.info(f"Webhook processed: {result.get('status')}")
        return JSONResponse(result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# === ADMIN ENDPOINTS ===

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page():
    """Admin login page"""
    return """
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>כניסת מנהל - מערכת הוצאות חתונה</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                direction: rtl; 
                margin: 0; 
                padding: 50px; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .login-container {
                background: white;
                padding: 40px;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                max-width: 400px;
                width: 100%;
            }
            .form-group { margin-bottom: 20px; }
            .form-label { display: block; margin-bottom: 8px; font-weight: bold; }
            .form-input { 
                width: 100%; 
                padding: 12px; 
                border: 2px solid #ddd; 
                border-radius: 8px; 
                font-size: 16px;
            }
            .btn {
                width: 100%;
                padding: 12px;
                background: #667eea;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                cursor: pointer;
                margin-top: 10px;
            }
            .btn:hover { background: #5a6fd8; }
            .error { color: #d32f2f; margin-bottom: 15px; text-align: center; }
        </style>
    </head>
    <body>
        <div class="login-container">
            <h2>🛠️ כניסת מנהל</h2>
            <div id="error" class="error" style="display: none;"></div>
            <form id="loginForm">
                <div class="form-group">
                    <label class="form-label">סיסמת מנהל:</label>
                    <input type="password" id="password" class="form-input" required>
                </div>
                <button type="submit" class="btn">כניסה</button>
            </form>
        </div>
        
        <script>
            document.getElementById('loginForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                
                const password = document.getElementById('password').value;
                const errorDiv = document.getElementById('error');
                
                try {
                    const response = await fetch('/admin/auth', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ password: password })
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        window.location.href = '/admin/dashboard';
                    } else {
                        errorDiv.textContent = 'סיסמה שגויה';
                        errorDiv.style.display = 'block';
                    }
                } catch (error) {
                    errorDiv.textContent = 'שגיאה בחיבור';
                    errorDiv.style.display = 'block';
                }
            });
        </script>
    </body>
    </html>
    """

@app.post("/admin/auth")
async def admin_authenticate(request: Request):
    """Admin authentication"""
    global ADMIN_SESSION_TOKEN
    
    try:
        data = await request.json()
        password = data.get("password", "")
        
        # Simple password check (in production, use proper hashing)
        if password == os.getenv("ADMIN_PASSWORD", "admin123"):
            # Generate session token
            import secrets
            ADMIN_SESSION_TOKEN = secrets.token_urlsafe(32)
            
            response = JSONResponse({"success": True})
            response.set_cookie("admin_token", ADMIN_SESSION_TOKEN, max_age=3600*8)  # 8 hours
            
            return response
        else:
            return JSONResponse({"success": False, "message": "Invalid password"})
            
    except Exception as e:
        logger.error(f"Admin auth failed: {e}")
        return JSONResponse({"success": False, "message": "Server error"})

@app.get("/admin/dashboard", dependencies=[Depends(get_admin_auth())], response_class=HTMLResponse)
async def admin_dashboard_page():
    """Admin dashboard"""
    return await admin_panel.get_dashboard_html()

@app.get("/admin/api/stats", dependencies=[Depends(get_admin_auth())])
async def admin_stats():
    """Admin API - Get system stats"""
    return await admin_panel.get_system_stats()

@app.get("/admin/api/couples", dependencies=[Depends(get_admin_auth())])
async def admin_couples():
    """Admin API - Get all couples"""
    return await admin_panel.get_couples_data()

@app.get("/admin/api/expenses/{group_id}", dependencies=[Depends(get_admin_auth())])
async def admin_expenses(group_id: str):
    """Admin API - Get expenses for specific group"""
    return await admin_panel.get_group_expenses(group_id)

@app.post("/admin/api/send-summary/{group_id}", dependencies=[Depends(get_admin_auth())])
async def admin_send_summary(group_id: str):
    """Admin API - Send weekly summary to specific group"""
    try:
        # Get group info
        couple = db.get_couple_by_group_id(group_id)
        if not couple:
            return JSONResponse({"success": False, "error": "Group not found"})
        
        # Calculate and send summary
        summary_data = await webhook_handler._calculate_weekly_summary(group_id, couple)
        message = messages.weekly_summary(summary_data)
        
        success = await webhook_handler._send_message(group_id, message)
        
        return JSONResponse({"success": success})
        
    except Exception as e:
        logger.error(f"Manual summary send failed: {e}")
        return JSONResponse({"success": False, "error": str(e)})

# === USER DASHBOARD ENDPOINTS ===

@app.get("/dashboard/{group_id}", response_class=HTMLResponse)
async def user_dashboard_page(group_id: str):
    """User dashboard for specific group"""
    try:
        # Verify group exists and is active
        couple = db.get_couple_by_group_id(group_id)
        if not couple or couple.get('status') != 'active':
            raise HTTPException(status_code=404, detail="Group not found")
        
        return await user_dashboard.get_dashboard_html(group_id)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User dashboard failed: {e}")
        raise HTTPException(status_code=500, detail="Dashboard unavailable")

@app.get("/dashboard/{group_id}/api/data")
async def user_dashboard_data(group_id: str):
    """User dashboard API - Get dashboard data"""
    try:
        couple = db.get_couple_by_group_id(group_id)
        if not couple:
            raise HTTPException(status_code=404, detail="Group not found")
        
        return await user_dashboard.get_dashboard_data(group_id)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User dashboard data failed: {e}")
        raise HTTPException(status_code=500, detail="Data unavailable")

# === HEALTH CHECK ENDPOINTS ===

@app.get("/health")
async def health_check():
    """Comprehensive health check"""
    checks = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "components": {}
    }
    
    try:
        # Database health
        db_health = db.health_check()
        checks["components"]["database"] = db_health
        
        # AI health  
        ai_health = ai.health_check()
        checks["components"]["ai"] = ai_health
        
        # Configuration check
        config_check = validate_config()
        checks["components"]["config"] = config_check
        
        # Overall status
        all_healthy = all(
            all(component.values()) 
            for component in checks["components"].values()
        )
        
        checks["status"] = "healthy" if all_healthy else "degraded"
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        checks["status"] = "unhealthy"
        checks["error"] = str(e)
    
    return JSONResponse(checks)

@app.get("/")
async def root():
    """Root endpoint - redirect to admin login"""
    return RedirectResponse(url="/admin/login")

# === SCHEDULED TASKS ===

async def weekly_summary_task():
    """Background task for sending weekly summaries"""
    while True:
        try:
            now = datetime.now()
            
            # Check if it's the right day and time
            if (now.weekday() == WEEKLY_SUMMARY_SETTINGS["send_day"] and 
                now.hour == WEEKLY_SUMMARY_SETTINGS["send_hour"] and
                WEEKLY_SUMMARY_SETTINGS["enabled"]):
                
                logger.info("Starting weekly summaries...")
                results = await webhook_handler.send_weekly_summaries()
                logger.info(f"Weekly summaries completed: {results}")
            
            # Sleep for an hour
            await asyncio.sleep(3600)
            
        except Exception as e:
            logger.error(f"Weekly summary task failed: {e}")
            await asyncio.sleep(3600)  # Continue despite errors

async def cleanup_task():
    """Background cleanup task"""
    while True:
        try:
            # Clean up old data, refresh caches, etc.
            await webhook_handler._refresh_groups_cache()
            
            # Sleep for 5 minutes
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"Cleanup task failed: {e}")
            await asyncio.sleep(300)

# === STARTUP EVENTS ===

@app.on_event("startup")
async def startup_event():
    """Application startup"""
    logger.info("Starting Wedding Expenses Bot...")
    
    try:
        # Validate configuration
        config_checks = validate_config()
        logger.info(f"Configuration checks: {config_checks}")
        
        if not all(config_checks.values()):
            logger.warning("Some configuration checks failed - system may not work properly")
        
        # Test database connection
        db_health = db.health_check()
        logger.info(f"Database health: {db_health}")
        
        # Test AI connection
        ai_health = ai.health_check()
        logger.info(f"AI health: {ai_health}")
        
        # Start background tasks
        if not DEBUG:
            asyncio.create_task(weekly_summary_task())
            asyncio.create_task(cleanup_task())
            logger.info("Background tasks started")
        
        logger.info("Wedding Expenses Bot started successfully!")
        
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown"""
    logger.info("Shutting down Wedding Expenses Bot...")

# === ERROR HANDLERS ===

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """Custom 404 handler"""
    return JSONResponse(
        status_code=404,
        content={"error": "Not found", "message": "הדף המבוקש לא נמצא"}
    )

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception):
    """Custom 500 handler"""
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "message": "שגיאה פנימית בשרת"}
    )

# === DEVELOPMENT ENDPOINTS ===

if DEBUG:
    @app.get("/debug/config")
    async def debug_config():
        """Debug configuration (dev only)"""
        return {
            "green_api_configured": bool(GREENAPI_INSTANCE_ID and GREENAPI_TOKEN),
            "openai_configured": bool(OPENAI_API_KEY),
            "sheets_configured": bool(GSHEETS_SPREADSHEET_ID),
            "webhook_secret_configured": bool(WEBHOOK_SHARED_SECRET),
            "allowed_phones_count": len(ALLOWED_PHONES),
            "categories": list(WEDDING_CATEGORIES.keys()),
            "debug_mode": DEBUG
        }
    
    @app.post("/debug/test-webhook")
    async def debug_test_webhook(request: Request):
        """Test webhook processing (dev only)"""
        payload = await request.json()
        return await webhook_handler.process_webhook(payload)
    
    @app.get("/debug/test-ai")
    async def debug_test_ai():
        """Test AI connection (dev only)"""
        return ai.health_check()

# === RUN APPLICATION ===

if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting server on port {PORT}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=DEBUG,
        log_level="debug" if DEBUG else "info"
    )