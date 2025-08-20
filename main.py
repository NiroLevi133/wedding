import os
import logging
from fastapi import FastAPI, Request

# הגדר logging פשוט
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

@app.get("/")
def home():
    return {"status": "ok", "message": "מערכת ניהול הוצאות חתונה פעילה! 💒✨"}

@app.get("/health")
def health():
    return {
        "status": "healthy", 
        "message": "Everything is working!"
    }

@app.get("/debug")
def debug():
    return {
        "google_project_id": bool(os.getenv("GOOGLE_PROJECT_ID")),
        "google_client_email": bool(os.getenv("GOOGLE_CLIENT_EMAIL")),
        "private_key_exists": bool(os.getenv("GOOGLE_PRIVATE_KEY")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "status": "minimal_version_working"
    }

@app.post("/webhook")
async def webhook(request: Request):
    """webhook פשוט שמחזיר הצלחה"""
    try:
        payload = await request.json()
        logger.info(f"Webhook received: {payload.get('messageData', {}).get('typeMessage', 'unknown')}")
        return {"status": "received", "message": "webhook is working but features disabled"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)