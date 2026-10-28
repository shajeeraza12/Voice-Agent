FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Migrate and seed on boot (both are idempotent), then serve. Railway sets $PORT.
# A migration failure is logged but does not stop the server, so a database outage
# produces spoken apologies on calls instead of a dead webhook.
CMD ["sh", "-c", "alembic upgrade head && python scripts/seed.py || echo 'startup: migration or seed failed, starting anyway'; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
