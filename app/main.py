import os
import time
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

DB_URL = (
    f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@{os.environ.get('POSTGRES_HOST', 'db')}:5432/{os.environ['POSTGRES_DB']}"
)

REQUESTS = Counter(
    "http_requests_total", "HTTP istekleri", ["method", "handler", "status"]
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP istek süresi (saniye)",
    ["method", "handler"],
)


def get_conn():
    return psycopg.connect(DB_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notes ("
            "id SERIAL PRIMARY KEY, text TEXT NOT NULL, "
            "created_at TIMESTAMPTZ DEFAULT now())"
        )
    yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def collect_metrics(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
    start = time.perf_counter()
    status = 500  # işlenmeyen bir hata olursa 500 sayılır
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        # Gerçek URL yerine yol şablonu: rastgele yollar yeni etiket üretemesin
        handler = route.path if route else "unmatched"
        REQUESTS.labels(request.method, handler, str(status)).inc()
        LATENCY.labels(request.method, handler).observe(time.perf_counter() - start)


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    with get_conn() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/notes")
def add_note(text: str):
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO notes (text) VALUES (%s) RETURNING id", (text,)
        ).fetchone()
    return {"id": row[0], "text": text}


@app.get("/notes")
def list_notes():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, text, created_at FROM notes ORDER BY id DESC LIMIT 20"
        ).fetchall()
    return [{"id": r[0], "text": r[1], "created_at": r[2]} for r in rows]
