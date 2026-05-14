FROM python:3.11-slim

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=1000
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y gcc libpq-dev

COPY requirements.txt .

RUN pip install --upgrade pip

RUN pip install --default-timeout=1000 --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8006

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]