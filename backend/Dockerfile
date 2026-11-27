FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY scripts ./scripts

# S-10 的 Celery app；任务名见 backend.tasks
CMD ["celery", "-A", "backend.worker", "worker", "--loglevel=info", "--concurrency=1"]
