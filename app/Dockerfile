FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Taban imajdaki zlib1g açıkları için güvenlik yaması
RUN apt-get update \
    && apt-get install -y --only-upgrade zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Root olmayan kullanıcı
RUN groupadd -r app && useradd -r -g app -u 10001 app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .

USER app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
