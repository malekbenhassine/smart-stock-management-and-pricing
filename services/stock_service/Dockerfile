FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --retries 10 --default-timeout=300 --progress-bar off -r requirements.txt

COPY . .

ENV DB_HOST=postgres_stock \
    DB_PORT=5432 \
    DB_NAME=stock_db \
    DB_USER=postgres \
    DB_PASSWORD=postgres

EXPOSE 2004

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "2004"]