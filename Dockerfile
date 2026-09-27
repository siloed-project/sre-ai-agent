FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/siloed-project/sre-ai-agent"
LABEL org.opencontainers.image.description="Read-only Kubernetes SRE Telegram agent"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENTRYPOINT ["python", "-m", "app.main"]
