FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Core deps first so the layer caches independently of the app code
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# OCR extras
COPY requirements-ocr.txt .
RUN pip install --no-cache-dir -r requirements-ocr.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head || echo 'MIGRATION FAILED - see logs above'; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 120"]
