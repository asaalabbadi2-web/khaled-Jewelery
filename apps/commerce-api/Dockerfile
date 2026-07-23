FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Riyadh

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libpq-dev \
       tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Build backend first (enables editable installs of workspace packages)
RUN pip install --no-cache-dir hatchling

# Workspace packages — copied separately so they form their own cache layer.
# Invalidates only when the package source changes, not when commerce-api changes.
COPY packages/platform /app/packages/platform
COPY packages/domain   /app/packages/domain

# Commerce API source
COPY apps/commerce-api /app/apps/commerce-api

# Install direct deps then editable workspace packages
RUN pip install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.32" \
        "pydantic>=2.9" \
        "sqlalchemy>=2.0" \
        "psycopg2-binary>=2.9" \
        "python-dotenv>=1.0" \
        "pyjwt>=2.8" \
        "redis>=5.0" \
        "prometheus-client>=0.21" \
        "httpx>=0.28" \
        "alembic>=1.13" \
    && pip install --no-cache-dir \
        -e /app/packages/platform \
        -e /app/packages/domain \
        -e /app/apps/commerce-api

EXPOSE 8000

# Default: API server.  Override `command:` in compose for workers.
CMD ["uvicorn", "yasargold_commerce.main:app", "--host", "0.0.0.0", "--port", "8000"]
