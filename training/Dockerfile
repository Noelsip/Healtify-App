FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ /app/

# Copy training folder - PASTIKAN PATH BENAR
COPY training/ /app/training/

# Verify training directory (debugging)
RUN echo "=== Verifying training directory ===" && \
    ls -la /app/training/ && \
    echo "=== Scripts directory ===" && \
    ls -la /app/training/scripts/ || echo "Scripts directory not found"

# Create directories
RUN mkdir -p /app/staticfiles /app/media /app/logs

# Collect static files
RUN python manage.py collectstatic --noinput

EXPOSE $PORT

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health/ || exit 1

# Start command
CMD python manage.py makemigrations --noinput && \
    python manage.py migrate --noinput && \
    gunicorn backend_project.wsgi:application \
    --bind 0.0.0.0:${PORT} \
    --workers 2 \
    --timeout 180 \
    --log-level info \
    --access-logfile - \
    --error-logfile - \
    --capture-output