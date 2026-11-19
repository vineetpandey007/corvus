# ============================================================
# Dark Web Threat Actor De-anonymization Toolkit — API image
# ============================================================
FROM python:3.12-slim AS base

WORKDIR /app

# System deps: gpg (python-gnupg needs the real gpg binary), build tools
# for any packages that need compiling.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gnupg \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm

COPY . .

# Non-root user for defense in depth
RUN useradd --create-home appuser \
    && mkdir -p /app/data/processed /app/data/raw \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
