FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --retries 10 --default-timeout=300 --progress-bar off -r requirements.txt

COPY . .

ENV DB_HOST=postgres_inference \
    DB_PORT=5432 \
    DB_NAME=inference_db \
    DB_USER=postgres \
    DB_PASSWORD=postgres \
    STOCK_SERVICE_URL=http://stock_service:2004 \
    DEFAULT_STORE_ID=STORE_Nord \
    DEFAULT_REGION=UNKNOWN

EXPOSE 8020

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]