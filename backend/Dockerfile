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

# Copy requirements FROM backend/ (karena root context = project root)
COPY backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ /app/

# Copy training directory (sekarang accessible karena root = project root)
COPY training/ /app/training/

# Create directories
RUN mkdir -p /app/staticfiles /app/media /app/logs

# Collect static
RUN python manage.py collectstatic --noinput || echo "Collectstatic will run at startup"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health/ || exit 1

CMD python manage.py migrate --noinput && \
    gunicorn backend_project.wsgi:application \
    --bind 0.0.0.0:${PORT} \
    --workers 2 \
    --timeout 180 \
    --log-level info \
    --access-logfile - \
    --error-logfile -