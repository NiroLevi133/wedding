FROM python:3.11-slim

WORKDIR /app

# System deps for google client
RUN apt-get update && apt-get install -y build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app (כל התוכן של התיקייה שלך)
COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
