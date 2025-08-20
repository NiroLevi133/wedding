FROM python:3.11-slim

WORKDIR /app

# System deps for google client
RUN apt-get update && apt-get install -y build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY app ./app
# Copy credentials at deploy time or mount secret in Cloud Run:
# COPY gcp_credentials.json /app/gcp_credentials.json

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
