import hashlib
import hmac
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field, field_validator, model_validator

DB_URL = (
    f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@{os.environ.get('POSTGRES_HOST', 'db')}:5432/{os.environ['POSTGRES_DB']}"
)

SESSION_TTL_SECONDS = 8 * 3600
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1

REQUESTS = Counter(
    "http_requests_total", "HTTP istekleri", ["method", "handler", "status"]
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP istek süresi (saniye)",
    ["method", "handler"],
)

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS devices (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        asset_tag TEXT NOT NULL UNIQUE,
        device_type TEXT NOT NULL,
        owner TEXT,
        location TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS serial_number TEXT",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS notes TEXT",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS purchase_date DATE",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS warranty_until DATE",
    "CREATE UNIQUE INDEX IF NOT EXISTS devices_serial_uidx "
    "ON devices (serial_number) WHERE serial_number IS NOT NULL",
]


def get_conn():
    return psycopg.connect(DB_URL)


# --- Parola ve oturum yardımcıları ---


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# Kullanıcı yokken de aynı işlem süresini harcamak için sahte özet
DUMMY_HASH = hash_password("kullanici-yok")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def bootstrap_admin(conn):
    if conn.execute("SELECT count(*) FROM users").fetchone()[0] > 0:
        return
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("Hiç kullanıcı yok ve ADMIN_PASSWORD tanımlı değil")
    conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
        (username, hash_password(password)),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_conn() as conn:
        for statement in SCHEMA:
            conn.execute(statement)
        bootstrap_admin(conn)
    yield


app = FastAPI(title="IT Asset Portal", lifespan=lifespan)
bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    unauthorized = HTTPException(
        status_code=401,
        detail="Geçersiz ya da süresi dolmuş oturum",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauthorized
    with get_conn() as conn:
        row = conn.execute(
            "SELECT u.id, u.username FROM sessions s "
            "JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = %s AND s.expires_at > now()",
            (token_hash(creds.credentials),),
        ).fetchone()
    if row is None:
        raise unauthorized
    return {"id": row[0], "username": row[1]}


# --- Metrik ara katmanı ---


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


# --- Açık uç noktalar ---


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    with get_conn() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/version")
def version():
    return {
        "version": os.environ.get("APP_VERSION", "dev"),
        "image": os.environ.get("APP_IMAGE", "unknown"),
    }


# --- Giriş ve çıkış ---


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@app.post("/login")
def login(body: LoginIn):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE username = %s",
            (body.username,),
        ).fetchone()
        password_ok = verify_password(body.password, row[1] if row else DUMMY_HASH)
        if row is None or not password_ok:
            raise HTTPException(status_code=401, detail="Kullanıcı adı ya da parola hatalı")
        conn.execute("DELETE FROM sessions WHERE expires_at < now()")
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) "
            "VALUES (%s, %s, now() + (%s::float8) * interval '1 second')",
            (token_hash(token), row[0], float(SESSION_TTL_SECONDS)),
        )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": SESSION_TTL_SECONDS,
    }


@app.post("/logout", status_code=204)
def logout(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    user: dict = Depends(current_user),
):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE token_hash = %s",
            (token_hash(creds.credentials),),
        )
    return Response(status_code=204)


# --- Cihaz envanteri (giriş gerektirir) ---


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    asset_tag: str = Field(min_length=1, max_length=50)
    device_type: str = Field(min_length=1, max_length=50)
    owner: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    status: Literal["active", "in_repair", "retired"] = "active"
    serial_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)
    purchase_date: date | None = None
    warranty_until: date | None = None

    @field_validator("serial_number", "notes", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def check_dates(self):
        if (
            self.purchase_date
            and self.warranty_until
            and self.warranty_until < self.purchase_date
        ):
            raise ValueError("Garanti bitişi satın alma tarihinden önce olamaz")
        return self


def device_dict(r) -> dict:
    return {
        "id": r[0],
        "name": r[1],
        "asset_tag": r[2],
        "device_type": r[3],
        "owner": r[4],
        "location": r[5],
        "status": r[6],
        "created_at": r[7],
        "updated_at": r[8],
        "serial_number": r[9],
        "notes": r[10],
        "purchase_date": r[11],
        "warranty_until": r[12],
    }


def unique_message(exc: psycopg.errors.UniqueViolation) -> str:
    if exc.diag.constraint_name == "devices_serial_uidx":
        return "Bu seri numarası zaten kayıtlı"
    return "Bu envanter etiketi zaten kayıtlı"


@app.get("/devices")
def list_devices(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(current_user),
):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, asset_tag, device_type, owner, location, status, "
            "created_at, updated_at, serial_number, notes, purchase_date, "
            "warranty_until FROM devices ORDER BY id LIMIT %s OFFSET %s",
            (limit, offset),
        ).fetchall()
    return [device_dict(r) for r in rows]


@app.post("/devices", status_code=201)
def create_device(device: DeviceIn, user: dict = Depends(current_user)):
    try:
        with get_conn() as conn:
            row = conn.execute(
                "INSERT INTO devices (name, asset_tag, device_type, owner, location, "
                "status, serial_number, notes, purchase_date, warranty_until) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id, name, asset_tag, device_type, owner, location, status, "
                "created_at, updated_at, serial_number, notes, purchase_date, "
                "warranty_until",
                (
                    device.name,
                    device.asset_tag,
                    device.device_type,
                    device.owner,
                    device.location,
                    device.status,
                    device.serial_number,
                    device.notes,
                    device.purchase_date,
                    device.warranty_until,
                ),
            ).fetchone()
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail=unique_message(exc)) from None
    return device_dict(row)


@app.get("/devices/{device_id}")
def get_device(device_id: int, user: dict = Depends(current_user)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, asset_tag, device_type, owner, location, status, "
            "created_at, updated_at, serial_number, notes, purchase_date, "
            "warranty_until FROM devices WHERE id = %s",
            (device_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Cihaz bulunamadı")
    return device_dict(row)


@app.put("/devices/{device_id}")
def update_device(
    device_id: int, device: DeviceIn, user: dict = Depends(current_user)
):
    try:
        with get_conn() as conn:
            row = conn.execute(
                "UPDATE devices SET name = %s, asset_tag = %s, device_type = %s, "
                "owner = %s, location = %s, status = %s, serial_number = %s, "
                "notes = %s, purchase_date = %s, warranty_until = %s, "
                "updated_at = now() "
                "WHERE id = %s "
                "RETURNING id, name, asset_tag, device_type, owner, location, status, "
                "created_at, updated_at, serial_number, notes, purchase_date, "
                "warranty_until",
                (
                    device.name,
                    device.asset_tag,
                    device.device_type,
                    device.owner,
                    device.location,
                    device.status,
                    device.serial_number,
                    device.notes,
                    device.purchase_date,
                    device.warranty_until,
                    device_id,
                ),
            ).fetchone()
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail=unique_message(exc)) from None
    if row is None:
        raise HTTPException(status_code=404, detail="Cihaz bulunamadı")
    return device_dict(row)


@app.delete("/devices/{device_id}", status_code=204)
def delete_device(device_id: int, user: dict = Depends(current_user)):
    with get_conn() as conn:
        row = conn.execute(
            "DELETE FROM devices WHERE id = %s RETURNING id", (device_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Cihaz bulunamadı")
    return Response(status_code=204)


# --- Web arayüzü (sayfa giriş istemez, veri yine korumalı API'den gelir) ---

UI_DIR = os.path.dirname(os.path.abspath(__file__))
UI_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def ui_response(filename: str, media_type: str) -> Response:
    with open(os.path.join(UI_DIR, filename), "rb") as f:
        content = f.read()
    return Response(content=content, media_type=media_type, headers=UI_HEADERS)


@app.get("/ui", include_in_schema=False)
def ui_page():
    return ui_response("ui.html", "text/html; charset=utf-8")


@app.get("/ui/app.css", include_in_schema=False)
def ui_css():
    return ui_response("ui.css", "text/css; charset=utf-8")


@app.get("/ui/app.js", include_in_schema=False)
def ui_js():
    return ui_response("ui.js", "text/javascript; charset=utf-8")


@app.get("/", include_in_schema=False)
def ui_root():
    return ui_response("ui.html", "text/html; charset=utf-8")
