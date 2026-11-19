# --- Aşama 1: bağımlılıkları kur ---
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# --- Aşama 2: çalışma imajı ---
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Taban imajdaki zlib1g açıkları için güvenlik yaması
RUN apt-get update \
    && apt-get install -y --only-upgrade zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Root olmayan kullanıcı
RUN groupadd -r app && useradd -r -g app -u 10001 app

# Yalnızca kurulu paketleri al. pip çalışma imajında gerekmez, saldırı yüzeyini küçültmek için kaldırılır
COPY --from=build /install /usr/local
RUN python -m pip uninstall -y pip

WORKDIR /app
COPY main.py ui.html ui.css ui.js VERSION ./

ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
