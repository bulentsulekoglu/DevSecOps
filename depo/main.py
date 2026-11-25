"""Depo Stok: depodaki ürünlerin sayısını ve hareketlerini tutan küçük uygulama.

Kimlik doğrulamayı bu uygulama yapmaz, nginx (HTTP Basic Auth) yapar. nginx doğrulanan
kullanıcı adını X-Remote-User başlığıyla iletir. Uygulama yalnızca nginx üzerinden
erişilebilir olmalıdır (Compose ağı bunu sağlar). Başlık yoksa istek reddedilir.
"""
import csv
import io
import os
import re
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, field_validator, model_validator

BASE = Path(__file__).parent
USER_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
SKU_RE = re.compile(r"^[A-Za-z0-9._/-]{1,64}$")
MAX_QTY = 2_000_000_000

REQUESTS = Counter("http_requests_total", "HTTP istekleri", ["method", "handler", "status"])
LATENCY = Histogram("http_request_duration_seconds", "İstek süresi", ["method", "handler"])

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id           BIGSERIAL PRIMARY KEY,
    sku          TEXT UNIQUE,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT '',
    unit         TEXT NOT NULL DEFAULT 'adet',
    location     TEXT NOT NULL DEFAULT '',
    quantity     INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    min_quantity INTEGER NOT NULL DEFAULT 0 CHECK (min_quantity >= 0),
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS movements (
    id             BIGSERIAL PRIMARY KEY,
    product_id     BIGINT NOT NULL REFERENCES products(id),
    kind           TEXT NOT NULL CHECK (kind IN ('in', 'out', 'adjust')),
    delta          INTEGER NOT NULL,
    quantity_after INTEGER NOT NULL,
    note           TEXT NOT NULL DEFAULT '',
    username       TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS movements_product_idx ON movements (product_id, id DESC);
-- Eski kurulumlarda ürün kodu zorunluydu: zorunluluğu kaldır (tekrar çalıştırılabilir)
ALTER TABLE products ALTER COLUMN sku DROP NOT NULL;
CREATE TABLE IF NOT EXISTS loans (
    id          BIGSERIAL PRIMARY KEY,
    item        TEXT NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    borrower    TEXT NOT NULL,
    due_date    DATE,
    note        TEXT NOT NULL DEFAULT '',
    lent_by     TEXT NOT NULL,
    lent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    returned_at TIMESTAMPTZ,
    returned_by TEXT
);
CREATE INDEX IF NOT EXISTS loans_open_idx ON loans (returned_at, due_date);
"""


@contextmanager
def db():
    conn = psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "db"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        row_factory=dict_row,
    )
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_schema(attempts: int = 30, delay: float = 2.0) -> None:
    """Tabloları kurar. Veritabanı henüz hazır değilse (ilk açılış) bekleyip tekrar dener."""
    for n in range(1, attempts + 1):
        try:
            with db() as conn:
                conn.execute(SCHEMA)
            return
        except psycopg.OperationalError:
            if n == attempts:
                raise
            time.sleep(delay)


@asynccontextmanager
async def lifespan(_app):
    init_schema()
    yield


app = FastAPI(title="Depo Stok", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# ---------- Modeller ----------
def _clean(value: str) -> str:
    return " ".join(value.split())


class ProductIn(BaseModel):
    sku: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="", max_length=60)
    unit: str = Field(default="adet", min_length=1, max_length=20)
    location: str = Field(default="", max_length=60)
    min_quantity: int = Field(default=0, ge=0, le=1_000_000)

    @field_validator("sku")
    @classmethod
    def check_sku(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper()
        if not v:
            return None
        if not SKU_RE.match(v):
            raise ValueError("Ürün kodu yalnızca harf, rakam ve . _ / - içerebilir")
        return v

    @field_validator("name", "category", "unit", "location")
    @classmethod
    def tidy(cls, v: str) -> str:
        return _clean(v)

    @model_validator(mode="after")
    def not_blank(self):
        if not self.name:
            raise ValueError("Ürün adı boş olamaz")
        if not self.unit:
            raise ValueError("Birim boş olamaz")
        return self


class ProductCreate(ProductIn):
    quantity: int = Field(default=0, ge=0, le=1_000_000)


class MovementIn(BaseModel):
    kind: Literal["in", "out", "adjust"]
    quantity: int = Field(ge=0, le=1_000_000)
    note: str = Field(default="", max_length=200)

    @field_validator("note")
    @classmethod
    def tidy_note(cls, v: str) -> str:
        return _clean(v)

    @model_validator(mode="after")
    def check(self):
        if self.kind in ("in", "out") and self.quantity < 1:
            raise ValueError("Miktar en az 1 olmalı")
        if self.kind == "adjust" and len(self.note) < 3:
            raise ValueError("Sayım düzeltmesi için bir açıklama yazın")
        return self


# ---------- Yardımcılar ----------
def current_user(request: Request) -> str:
    user = request.headers.get("x-remote-user", "")
    if not USER_RE.match(user):
        raise HTTPException(status_code=401, detail="Kimlik doğrulanamadı")
    return user


def row_or_404(row):
    if row is None:
        raise HTTPException(status_code=404, detail="Ürün bulunamadı")
    return row


def csv_safe(value) -> str:
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


# ---------- Ara katman: güvenlik başlıkları, kimlik zorunluluğu, metrikler ----------
@app.middleware("http")
async def guard(request: Request, call_next):
    start = time.perf_counter()
    path = request.url.path
    if path.startswith("/api/") and not USER_RE.match(request.headers.get("x-remote-user", "")):
        response = JSONResponse({"detail": "Kimlik doğrulanamadı"}, status_code=401)
    else:
        response = await call_next(request)
    route = request.scope.get("route")
    handler = route.path if route else "unmatched"
    REQUESTS.labels(request.method, handler, str(response.status_code)).inc()
    LATENCY.labels(request.method, handler).observe(time.perf_counter() - start)
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------- Açık uçlar: sağlık, sürüm, metrik, arayüz dosyaları ----------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    release = (BASE / "VERSION").read_text().strip() if (BASE / "VERSION").exists() else "dev"
    return {
        "release": release,
        "version": os.environ.get("APP_VERSION", "dev"),
        "image": os.environ.get("APP_IMAGE", ""),
    }


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def static_file(name: str, media_type: str) -> Response:
    return Response((BASE / name).read_bytes(), media_type=media_type)


@app.get("/", include_in_schema=False)
def ui_page():
    return static_file("ui.html", "text/html; charset=utf-8")


@app.get("/ui.css", include_in_schema=False)
def ui_css():
    return static_file("ui.css", "text/css; charset=utf-8")


@app.get("/ui.js", include_in_schema=False)
def ui_js():
    return static_file("ui.js", "application/javascript; charset=utf-8")


# ---------- API ----------
@app.get("/api/me")
def me(request: Request):
    return {"username": current_user(request)}


@app.get("/api/summary")
def summary():
    with db() as conn:
        row = conn.execute(
            """
            SELECT count(*) AS products,
                   COALESCE(sum(quantity), 0) AS units,
                   count(*) FILTER (WHERE min_quantity > 0 AND quantity <= min_quantity) AS low,
                   count(*) FILTER (WHERE quantity = 0) AS empty
            FROM products WHERE active
            """
        ).fetchone()
        loans = conn.execute(
            """
            SELECT count(*) FILTER (WHERE returned_at IS NULL) AS loans_open,
                   count(*) FILTER (WHERE returned_at IS NULL AND due_date < current_date) AS loans_overdue
            FROM loans
            """
        ).fetchone()
    return {**row, **loans}


@app.get("/api/categories")
def categories():
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM products WHERE active AND category <> '' ORDER BY category"
        ).fetchall()
    return [r["category"] for r in rows]


@app.get("/api/products")
def list_products(
    q: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=60),
    low: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    q = _clean(q).lower() if q else None
    params = {"q": q or None, "category": category or None, "low": low, "limit": limit, "offset": offset}
    with db() as conn:
        total = conn.execute(
            """
            SELECT count(*) AS n FROM products
            WHERE active
              AND (%(q)s::text IS NULL
                   OR strpos(lower(name), %(q)s::text) > 0
                   OR strpos(lower(coalesce(sku, '')), %(q)s::text) > 0
                   OR strpos(lower(category), %(q)s::text) > 0
                   OR strpos(lower(location), %(q)s::text) > 0)
              AND (%(category)s::text IS NULL OR category = %(category)s::text)
              AND (NOT %(low)s::boolean OR (min_quantity > 0 AND quantity <= min_quantity))
            """,
            params,
        ).fetchone()["n"]
        items = conn.execute(
            """
            SELECT id, sku, name, category, unit, location, quantity, min_quantity, created_at, updated_at
            FROM products
            WHERE active
              AND (%(q)s::text IS NULL
                   OR strpos(lower(name), %(q)s::text) > 0
                   OR strpos(lower(coalesce(sku, '')), %(q)s::text) > 0
                   OR strpos(lower(category), %(q)s::text) > 0
                   OR strpos(lower(location), %(q)s::text) > 0)
              AND (%(category)s::text IS NULL OR category = %(category)s::text)
              AND (NOT %(low)s::boolean OR (min_quantity > 0 AND quantity <= min_quantity))
            ORDER BY lower(name), id LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        ).fetchall()
    return {"items": items, "total": total}


@app.post("/api/products", status_code=201)
def create_product(body: ProductCreate, request: Request):
    user = current_user(request)
    try:
        with db() as conn:
            row = conn.execute(
                """
                INSERT INTO products (sku, name, category, unit, location, quantity, min_quantity)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, sku, name, category, unit, location, quantity, min_quantity, created_at, updated_at
                """,
                (body.sku, body.name, body.category, body.unit, body.location, body.quantity, body.min_quantity),
            ).fetchone()
            if body.quantity > 0:
                conn.execute(
                    """
                    INSERT INTO movements (product_id, kind, delta, quantity_after, note, username)
                    VALUES (%s, 'in', %s, %s, 'Açılış stoğu', %s)
                    """,
                    (row["id"], body.quantity, body.quantity, user),
                )
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="Bu ürün kodu zaten kayıtlı") from None
    return row


@app.get("/api/products/{product_id}")
def get_product(product_id: int):
    with db() as conn:
        row = conn.execute(
            """
            SELECT id, sku, name, category, unit, location, quantity, min_quantity, created_at, updated_at
            FROM products WHERE id = %s AND active
            """,
            (product_id,),
        ).fetchone()
    return row_or_404(row)


@app.put("/api/products/{product_id}")
def update_product(product_id: int, body: ProductIn):
    try:
        with db() as conn:
            row = conn.execute(
                """
                UPDATE products
                SET sku = %s, name = %s, category = %s, unit = %s, location = %s,
                    min_quantity = %s, updated_at = now()
                WHERE id = %s AND active
                RETURNING id, sku, name, category, unit, location, quantity, min_quantity, created_at, updated_at
                """,
                (body.sku, body.name, body.category, body.unit, body.location, body.min_quantity, product_id),
            ).fetchone()
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="Bu ürün kodu zaten kayıtlı") from None
    return row_or_404(row)


@app.delete("/api/products/{product_id}", status_code=204)
def archive_product(product_id: int, request: Request):
    user = current_user(request)
    with db() as conn:
        row = conn.execute(
            "SELECT id, quantity FROM products WHERE id = %s AND active FOR UPDATE", (product_id,)
        ).fetchone()
        row_or_404(row)
        if row["quantity"] > 0:
            raise HTTPException(status_code=409, detail="Stoğu olan ürün silinemez, önce stoğu sıfırlayın")
        conn.execute("UPDATE products SET active = FALSE, updated_at = now() WHERE id = %s", (product_id,))
        conn.execute(
            """
            INSERT INTO movements (product_id, kind, delta, quantity_after, note, username)
            VALUES (%s, 'adjust', 0, 0, 'Ürün arşivlendi', %s)
            """,
            (product_id, user),
        )
    return Response(status_code=204)


@app.post("/api/products/{product_id}/movements", status_code=201)
def add_movement(product_id: int, body: MovementIn, request: Request):
    user = current_user(request)
    with db() as conn:
        row = conn.execute(
            "SELECT id, quantity FROM products WHERE id = %s AND active FOR UPDATE", (product_id,)
        ).fetchone()
        row_or_404(row)
        old = row["quantity"]
        if body.kind == "in":
            new = old + body.quantity
        elif body.kind == "out":
            new = old - body.quantity
            if new < 0:
                raise HTTPException(status_code=409, detail=f"Yetersiz stok: elde {old} var")
        else:
            new = body.quantity
        if new > MAX_QTY:
            raise HTTPException(status_code=409, detail="Stok miktarı üst sınırı aşıyor")
        conn.execute("UPDATE products SET quantity = %s, updated_at = now() WHERE id = %s", (new, product_id))
        move = conn.execute(
            """
            INSERT INTO movements (product_id, kind, delta, quantity_after, note, username)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, product_id, kind, delta, quantity_after, note, username, created_at
            """,
            (product_id, body.kind, new - old, new, body.note, user),
        ).fetchone()
    return move


@app.get("/api/products/{product_id}/movements")
def product_movements(product_id: int, limit: int = Query(default=50, ge=1, le=200)):
    with db() as conn:
        row_or_404(conn.execute("SELECT id FROM products WHERE id = %s", (product_id,)).fetchone())
        return conn.execute(
            """
            SELECT id, kind, delta, quantity_after, note, username, created_at
            FROM movements WHERE product_id = %s ORDER BY id DESC LIMIT %s
            """,
            (product_id, limit),
        ).fetchall()


@app.get("/api/movements")
def recent_movements(limit: int = Query(default=30, ge=1, le=200)):
    with db() as conn:
        return conn.execute(
            """
            SELECT m.id, m.kind, m.delta, m.quantity_after, m.note, m.username, m.created_at,
                   p.sku, p.name
            FROM movements m JOIN products p ON p.id = m.product_id
            ORDER BY m.id DESC LIMIT %s
            """,
            (limit,),
        ).fetchall()


@app.get("/api/export.csv")
def export_csv():
    with db() as conn:
        rows = conn.execute(
            "SELECT sku, name, category, unit, location, quantity, min_quantity FROM products "
            "WHERE active ORDER BY lower(name), id"
        ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["kod", "ad", "kategori", "birim", "konum", "miktar", "minimum"])
    for r in rows:
        writer.writerow([csv_safe(r[k]) for k in ("sku", "name", "category", "unit", "location", "quantity", "min_quantity")])
    return Response(
        "\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="depo-stok.csv"'},
    )


# ---------- Ödünç verilenler (geri alınacak şeylerin takibi, stoktan bağımsız) ----------
class LoanIn(BaseModel):
    item: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=1, ge=1, le=1_000_000)
    borrower: str = Field(min_length=1, max_length=80)
    due_date: date | None = None
    note: str = Field(default="", max_length=200)

    @field_validator("item", "borrower", "note")
    @classmethod
    def tidy_text(cls, v: str) -> str:
        return _clean(v)

    @model_validator(mode="after")
    def not_blank(self):
        if not self.item:
            raise ValueError("Verilen şeyin adı boş olamaz")
        if not self.borrower:
            raise ValueError("Kime verildiği boş olamaz")
        return self


@app.get("/api/loans")
def list_loans(
    status: Literal["open", "returned", "all"] = "open",
    limit: int = Query(default=100, ge=1, le=200),
):
    with db() as conn:
        return conn.execute(
            """
            SELECT id, item, quantity, borrower, due_date, note, lent_by, lent_at, returned_at, returned_by,
                   (returned_at IS NULL AND due_date IS NOT NULL AND due_date < current_date) AS overdue
            FROM loans
            WHERE (%(status)s::text = 'all'
                   OR (%(status)s::text = 'open' AND returned_at IS NULL)
                   OR (%(status)s::text = 'returned' AND returned_at IS NOT NULL))
            ORDER BY (returned_at IS NOT NULL), returned_at DESC NULLS LAST, due_date NULLS LAST, id DESC
            LIMIT %(limit)s
            """,
            {"status": status, "limit": limit},
        ).fetchall()


@app.post("/api/loans", status_code=201)
def create_loan(body: LoanIn, request: Request):
    user = current_user(request)
    with db() as conn:
        return conn.execute(
            """
            INSERT INTO loans (item, quantity, borrower, due_date, note, lent_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, item, quantity, borrower, due_date, note, lent_by, lent_at, returned_at, returned_by,
                      (due_date IS NOT NULL AND due_date < current_date) AS overdue
            """,
            (body.item, body.quantity, body.borrower, body.due_date, body.note, user),
        ).fetchone()


@app.post("/api/loans/{loan_id}/return")
def return_loan(loan_id: int, request: Request):
    user = current_user(request)
    with db() as conn:
        row = conn.execute("SELECT id, returned_at FROM loans WHERE id = %s FOR UPDATE", (loan_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
        if row["returned_at"] is not None:
            raise HTTPException(status_code=409, detail="Bu kayıt zaten geri alınmış")
        return conn.execute(
            """
            UPDATE loans SET returned_at = now(), returned_by = %s WHERE id = %s
            RETURNING id, item, quantity, borrower, due_date, note, lent_by, lent_at, returned_at, returned_by,
                      FALSE AS overdue
            """,
            (user, loan_id),
        ).fetchone()
