# MediProof API image. Light on purpose: the digital-PDF path needs no OCR/Chromium.
# Build context is the repo root (see docker-compose.yml).
FROM python:3.11-slim

WORKDIR /app

# Only the code the API imports (no datagen/Chromium, no UI).
COPY pyproject.toml README.md ./
COPY schemas ./schemas
COPY pipeline ./pipeline
COPY api ./api

RUN pip install --no-cache-dir -e ".[api,pipeline]"

ENV DATABASE_URL=sqlite:////data/mediproof.db \
    MEDIPROOF_STORAGE=/data/uploads \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
