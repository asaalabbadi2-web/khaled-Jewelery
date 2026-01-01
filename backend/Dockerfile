FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for psycopg2 + general
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python deps first (better layer caching)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend source
COPY backend /app/backend

EXPOSE 8001

# Default: run via gunicorn (production)
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8001", "backend.wsgi:app"]
