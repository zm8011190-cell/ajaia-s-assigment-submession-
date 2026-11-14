FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOCSAPP_DATABASE_PATH=/var/data/docsapp.db

WORKDIR /app

COPY app/dependencies.txt /app/app/dependencies.txt
RUN python -m pip install --no-cache-dir -r /app/app/dependencies.txt

COPY app /app/app

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
