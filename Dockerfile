FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Web API
FROM base AS api
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m engine.seed && uvicorn engine.api.app:create_app --factory --host 0.0.0.0 --port 8000"]

# Background worker (queue + schedules)
FROM base AS worker
CMD ["python", "-m", "engine.worker"]
