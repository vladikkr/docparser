# Hugging Face Spaces Docker image.
# Free CPU tier, no payment method required.

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        libmagic1 \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-rus \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# OCR stack first: keeps the heavy layer cached across code changes
COPY requirements-ocr.txt ./
RUN pip install --no-cache-dir -r requirements-ocr.txt

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "python scripts/bootstrap.py && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 120"]
