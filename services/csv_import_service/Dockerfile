FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --retries 10 --default-timeout=300 --progress-bar off -r requirements.txt
COPY . .

# Variables d'environnement par défaut (surchargeables dans docker-compose)
ENV DB_HOST=smart_postgres \
    DB_PORT=5432 \
    DB_NAME=smartdb \
    DB_USER=postgres \
    DB_PASS=postgres \
    ML_INFERENCE_URL=http://ml_inference_service:8020

EXPOSE 8030

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8030"]FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --retries 10 --default-timeout=300 --progress-bar off -r requirements.txt
COPY . .

# Variables d'environnement par défaut (surchargeables dans docker-compose)
ENV DB_HOST=smart_postgres \
    DB_PORT=5432 \
    DB_NAME=smartdb \
    DB_USER=postgres \
    DB_PASS=postgres \
    ML_INFERENCE_URL=http://ml_inference_service:8020

EXPOSE 8030

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8030"]