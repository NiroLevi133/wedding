from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"status": "ok", "message": "המערכת פעילה!"}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/debug")
def debug():
    import os
    return {
        "secret_env": "YES" if os.getenv("secret") else "NO",
        "env_vars": {
            "PORT": os.getenv("PORT"),
            "GOOGLE_APPLICATION_CREDENTIALS": os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        }
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)