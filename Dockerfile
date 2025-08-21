FROM python:3.11-slim

WORKDIR /app

# התקנות מערכתיות + curl לhealth checks
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    curl \
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
ENV PYTHONPATH=/app

# צור user לא-root לאבטחה
RUN useradd -r -s /bin/false appuser && chown -R appuser:appuser /app
USER appuser

# הגדר health check עם startup endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8080/startup || exit 1

# expose port
EXPOSE 8080

# הרץ עם הגדרות משופרות
CMD ["sh", "-c", "streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0 & uvicorn main:app --host 0.0.0.0 --port 8080 --timeout-keep-alive 300"]