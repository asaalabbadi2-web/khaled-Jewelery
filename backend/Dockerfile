FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Riyadh

WORKDIR /app

# System deps for psycopg2 + tzdata for timezone support
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      libpq-dev \
      postgresql-client \
      tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Install python deps first (better layer caching)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend source — ARG here forces cache-bust when BUILD_DATE changes
ARG BUILD_DATE=unknown
COPY backend /app/backend

EXPOSE 8001

# Default: run via gunicorn (production)
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8001", "--timeout", "120", "backend.wsgi:app"]
