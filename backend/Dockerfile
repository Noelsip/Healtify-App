FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ .

# Copy training directory (needed for AI adapter)
COPY training/ /app/training/

# Collect static files
RUN python manage.py collectstatic --noinput || true

# Expose port
EXPOSE 8000

# Start command
CMD sh -c "python manage.py migrate && \
           gunicorn backend_project.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120"