FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/ /app/backend/
WORKDIR /app/backend
CMD sh -c "python manage.py migrate && python manage.py collectstatic --noinput && gunicorn backend_project.wsgi:application --bind 0.0.0.0:8000 --workers 3"