FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements
COPY backend/requirements.txt /app/backend/requirements.txt

# Install Python packages
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend code
COPY backend/ /app/backend/

# Set working directory to backend
WORKDIR /app/backend

# Run migrations and start server
CMD sh -c "python manage.py makemigrations && \
            python manage.py migrate && \
            python manage.py collectstatic --noinput && \
            gunicorn backend_project.wsgi:application --bind 0.0.0.0:8000 --workers 3"