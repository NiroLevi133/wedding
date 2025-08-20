FROM python:3.11-slim

WORKDIR /app

# התקנות מערכתיות בסיסיות
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# העתק requirements ראשון
COPY requirements.txt .

# התקן חבילות פייתון
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# העתק קוד
COPY . .

# הגדרות סביבה
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# הרץ עם timeout ארוך יותר
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-keep-alive", "300"]