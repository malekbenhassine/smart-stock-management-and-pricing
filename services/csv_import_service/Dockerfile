FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --retries 10 --default-timeout=300 --progress-bar off -r requirements.txt

COPY . .

ENV DB_HOST=postgres_csv_import \
    DB_PORT=5432 \
    DB_NAME=csv_import_db \
    DB_USER=postgres \
    DB_PASS=postgres \
    STOCK_SERVICE_URL=http://stock_service:2004 \
    INFERENCE_SERVICE_URL=http://inference_service:8020

EXPOSE 8030

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8030"]