import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI

DB_URL = (
    f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@{os.environ.get('POSTGRES_HOST', 'db')}:5432/{os.environ['POSTGRES_DB']}"
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
