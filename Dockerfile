FROM python:3.11-slim

WORKDIR /app

# התקנות מערכתיות ללקוח גוגל
RUN apt-get update && apt-get install -y build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# התקנת חבילות פייתון
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# העתקת קוד האפליקציה
COPY . .


# קובעים שהלוגים לא ישמרו בבאפר
ENV PYTHONUNBUFFERED=1

# ברירת מחדל – Cloud Run מאזין בפורט 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

