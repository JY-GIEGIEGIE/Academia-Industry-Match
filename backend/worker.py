#!/usr/bin/env python3
"""Celery app（S-10）：broker / result backend 指向本地 Redis。

交接单（S-12 → S-10，2026-11-26）口径：
  - broker：        redis://127.0.0.1:6379/0
  - result backend：redis://127.0.0.1:6379/1
  - Celery app：    backend.worker:celery_app

用法（在仓库根目录）：
  celery -A backend.worker worker --loglevel=info
"""

from __future__ import annotations

import os

from celery import Celery

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")

celery_app = Celery(
    "aim",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["backend.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)
