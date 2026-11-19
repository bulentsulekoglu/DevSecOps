import os

import pytest
from fastapi.testclient import TestClient

import main

ADMIN = {
    "username": os.environ["ADMIN_USERNAME"],
    "password": os.environ["ADMIN_PASSWORD"],
}


@pytest.fixture(scope="module")
def client():
    # "with" bloğu uygulamanın başlangıç adımlarını çalıştırır (tablolar, ilk yönetici)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_state(client):
    with main.get_conn() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM devices")
        conn.execute("DELETE FROM device_history")
        conn.execute("DELETE FROM user_events")
        conn.execute("DELETE FROM users WHERE username <> %s", (ADMIN["username"],))
        conn.execute(
            "UPDATE users SET role = 'admin', active = TRUE, failed_attempts = 0, "
            "locked_until = NULL WHERE username = %s",
            (ADMIN["username"],),
        )


@pytest.fixture()
def auth(client):
    r = client.post("/login", json=ADMIN)
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def new_device(**overrides):
    device = {
        "name": "Dizüstü 1",
        "asset_tag": "LT-0001",
        "device_type": "laptop",
        "owner": "ayse",
        "location": "Ankara",
        "status": "active",
    }
    device.update(overrides)
    return device


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_version_reports_build_info(client, monkeypatch):
    monkeypatch.setenv("APP_VERSION", "abc1234")
    monkeypatch.setenv("APP_IMAGE", "ghcr.io/ornek/uygulama@sha256:" + "0" * 64)
    r = client.get("/version")
    assert r.status_code == 200
    assert r.json()["version"] == "abc1234"
    assert r.json()["image"].startswith("ghcr.io/")


def test_password_hash_is_salted_and_verifiable():
    h1 = main.hash_password("gizli")
    h2 = main.hash_password("gizli")
    assert h1 != h2
    assert main.verify_password("gizli", h1)
    assert not main.verify_password("yanlis", h1)


def test_verify_password_rejects_malformed_hash():
    assert not main.verify_password("x", "bozuk")
    assert not main.verify_password("x", "md5$1$2$3$aa$bb")


def test_login_success_returns_token(client):
    r = client.post("/login", json=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20


def test_login_rejects_wrong_password_and_unknown_user(client):
    assert client.post("/login", json={**ADMIN, "password": "yanlis"}).status_code == 401
    assert client.post("/login", json={"username": "yok", "password": "x"}).status_code == 401


def test_devices_require_authentication(client):
    assert client.get("/devices").status_code == 401
    assert client.get("/devices", headers={"Authorization": "Bearer sahte"}).status_code == 401
    assert client.post("/devices", json=new_device()).status_code == 401


def test_logout_invalidates_token(client, auth):
    assert client.get("/devices", headers=auth).status_code == 200
    assert client.post("/logout", headers=auth).status_code == 204
    assert client.get("/devices", headers=auth).status_code == 401


def test_expired_session_is_rejected(client, auth):
    with main.get_conn() as conn:
        conn.execute("UPDATE sessions SET expires_at = now() - interval '1 minute'")
    assert client.get("/devices", headers=auth).status_code == 401


def test_device_crud_flow(client, auth):
    created = client.post("/devices", json=new_device(), headers=auth)
    assert created.status_code == 201
    device_id = created.json()["id"]
    assert created.json()["asset_tag"] == "LT-0001"

    assert client.get(f"/devices/{device_id}", headers=auth).json()["name"] == "Dizüstü 1"
    listed = client.get("/devices", headers=auth).json()
    assert [d["asset_tag"] for d in listed] == ["LT-0001"]

    updated = client.put(
        f"/devices/{device_id}",
        json=new_device(owner="mehmet", status="in_repair"),
        headers=auth,
    )
    assert updated.status_code == 200
    assert updated.json()["owner"] == "mehmet"
    assert updated.json()["status"] == "in_repair"

    assert client.delete(f"/devices/{device_id}", headers=auth).status_code == 204
    assert client.get(f"/devices/{device_id}", headers=auth).status_code == 404


def test_unknown_device_returns_404(client, auth):
    assert client.get("/devices/999999", headers=auth).status_code == 404
    assert client.put("/devices/999999", json=new_device(), headers=auth).status_code == 404
    assert client.delete("/devices/999999", headers=auth).status_code == 404


def test_duplicate_asset_tag_is_conflict(client, auth):
    assert client.post("/devices", json=new_device(), headers=auth).status_code == 201
    assert client.post("/devices", json=new_device(name="Başka"), headers=auth).status_code == 409


def test_invalid_device_is_rejected(client, auth):
    assert client.post("/devices", json=new_device(name=""), headers=auth).status_code == 422
    assert client.post("/devices", json=new_device(status="kayip"), headers=auth).status_code == 422


def test_metrics_use_route_templates(client):
    client.get("/health")
    client.get("/devices/123")  # token'sız: 401, ama yol şablonu etiketlenir
    text = client.get("/metrics").text
    assert "http_requests_total" in text
    assert 'handler="/health"' in text
    assert 'handler="/devices/{device_id}"' in text
    assert 'handler="/devices/123"' not in text


def test_unknown_paths_do_not_create_new_labels(client):
    client.get("/yok-boyle-bir-yol-123")
    text = client.get("/metrics").text
    assert 'handler="unmatched"' in text
    assert "yok-boyle-bir-yol-123" not in text


def test_server_errors_are_counted(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(main, "get_conn", boom)
    failing = TestClient(main.app, raise_server_exceptions=False)
    assert failing.get("/health").status_code == 500
    assert 'status="500"' in failing.get("/metrics").text


def test_ui_sayfasi_giris_istemez_ve_basliklari_dogru(client):
    r = client.get("/ui")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_ui_dosyalari_sunuluyor(client):
    for path, kind in (("/ui/app.css", "text/css"), ("/ui/app.js", "text/javascript")):
        r = client.get(path)
        assert r.status_code == 200
        assert kind in r.headers["content-type"]


def test_ana_adres_arayuzu_sunar(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "IT Asset Portal" in r.text
    assert r.text == client.get("/ui").text


def test_yeni_alanlar_kaydedilir_ve_okunur(client, auth):
    body = {
        "name": "Dizüstü X",
        "asset_tag": "LT-9001",
        "device_type": "laptop",
        "serial_number": "SN-123",
        "notes": "Yeni alındı",
        "purchase_date": "2026-01-15",
        "warranty_until": "2029-01-15",
    }
    r = client.post("/devices", json=body, headers=auth)
    assert r.status_code == 201
    created = r.json()
    assert created["serial_number"] == "SN-123"
    assert created["notes"] == "Yeni alındı"
    assert created["purchase_date"] == "2026-01-15"
    assert created["warranty_until"] == "2029-01-15"
    got = client.get(f"/devices/{created['id']}", headers=auth).json()
    assert got["serial_number"] == "SN-123"
    assert got["warranty_until"] == "2029-01-15"


def test_yeni_alanlar_istege_baglidir(client, auth):
    r = client.post(
        "/devices",
        json={"name": "A", "asset_tag": "LT-9002", "device_type": "laptop"},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["serial_number"] is None
    assert r.json()["warranty_until"] is None


def test_ayni_seri_numarasi_409(client, auth):
    base = {"name": "A", "device_type": "laptop", "serial_number": "SN-DUP"}
    first = client.post("/devices", json={**base, "asset_tag": "LT-9003"}, headers=auth)
    assert first.status_code == 201
    second = client.post("/devices", json={**base, "asset_tag": "LT-9004"}, headers=auth)
    assert second.status_code == 409
    assert "seri numarası" in second.json()["detail"]


def test_ayni_etiket_hala_etiket_mesaji_verir(client, auth):
    body = {"name": "A", "asset_tag": "LT-9007", "device_type": "laptop"}
    assert client.post("/devices", json=body, headers=auth).status_code == 201
    r = client.post("/devices", json=body, headers=auth)
    assert r.status_code == 409
    assert "etiketi" in r.json()["detail"]


def test_bos_seri_numarasi_bos_sayilir(client, auth):
    for tag in ("LT-9005", "LT-9006"):
        body = {"name": "A", "asset_tag": tag, "device_type": "laptop", "serial_number": "  "}
        r = client.post("/devices", json=body, headers=auth)
        assert r.status_code == 201
        assert r.json()["serial_number"] is None


def test_garanti_satin_almadan_once_olamaz(client, auth):
    body = {
        "name": "A",
        "asset_tag": "LT-9008",
        "device_type": "laptop",
        "purchase_date": "2026-05-01",
        "warranty_until": "2026-01-01",
    }
    assert client.post("/devices", json=body, headers=auth).status_code == 422


def test_guncelleme_yeni_alanlari_degistirir(client, auth):
    body = {"name": "A", "asset_tag": "LT-9009", "device_type": "laptop"}
    device_id = client.post("/devices", json=body, headers=auth).json()["id"]
    r = client.put(
        f"/devices/{device_id}",
        json={**body, "serial_number": "SN-NEW", "notes": "güncellendi"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["serial_number"] == "SN-NEW"
    assert r.json()["notes"] == "güncellendi"


def test_gecmis_olusturma_guncelleme_silme(client, auth):
    body = {"name": "G", "asset_tag": "LT-9100", "device_type": "laptop", "owner": "ayse"}
    device_id = client.post("/devices", json=body, headers=auth).json()["id"]
    r = client.put(
        f"/devices/{device_id}",
        json={**body, "owner": "mehmet", "status": "in_repair"},
        headers=auth,
    )
    assert r.status_code == 200
    assert client.delete(f"/devices/{device_id}", headers=auth).status_code == 204
    r = client.get(f"/devices/{device_id}/history", headers=auth)
    assert r.status_code == 200
    entries = r.json()
    assert [e["action"] for e in entries] == ["delete", "update", "create"]
    assert entries[1]["changes"]["owner"] == ["ayse", "mehmet"]
    assert entries[1]["changes"]["status"] == ["active", "in_repair"]
    assert entries[0]["username"] == ADMIN["username"]
    assert entries[0]["asset_tag"] == "LT-9100"


def test_degisiklik_yoksa_gecmis_eklenmez(client, auth):
    body = {"name": "G", "asset_tag": "LT-9101", "device_type": "laptop"}
    device_id = client.post("/devices", json=body, headers=auth).json()["id"]
    assert client.put(f"/devices/{device_id}", json=body, headers=auth).status_code == 200
    entries = client.get(f"/devices/{device_id}/history", headers=auth).json()
    assert [e["action"] for e in entries] == ["create"]


def test_son_hareketler_listesi(client, auth):
    body = {"name": "G", "asset_tag": "LT-9102", "device_type": "laptop"}
    client.post("/devices", json=body, headers=auth)
    r = client.get("/history", headers=auth)
    assert r.status_code == 200
    assert r.json()[0]["action"] == "create"
    assert r.json()[0]["asset_tag"] == "LT-9102"


def test_gecmis_giris_ister(client):
    assert client.get("/history").status_code == 401
    assert client.get("/devices/1/history").status_code == 401


# --- Roller, kullanıcı yönetimi, parola, kilitleme ---
PASS = "Cok-Guclu-Parola-1"
NEW_PASS = PASS + "-yeni"


def make_user(client, auth, name, role, password=None):
    password = password or PASS
    r = client.post(
        "/users",
        json={"username": name, "password": password, "role": role},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


def login_as(client, name, password=None):
    password = password or PASS
    r = client.post("/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def admin_id(client, auth):
    users = client.get("/users", headers=auth).json()
    return next(u["id"] for u in users if u["username"] == ADMIN["username"])


def test_me_reports_role(client, auth):
    r = client.get("/me", headers=auth)
    assert r.status_code == 200
    assert r.json() == {"username": ADMIN["username"], "role": "admin"}


def test_viewer_can_read_but_not_change(client, auth):
    d = client.post("/devices", json=new_device(), headers=auth).json()
    make_user(client, auth, "izleyici", "viewer")
    v = login_as(client, "izleyici")
    assert client.get("/devices", headers=v).status_code == 200
    assert client.get("/devices/%d/history" % d["id"], headers=v).status_code == 200
    assert client.post("/devices", json=new_device(asset_tag="X-1"), headers=v).status_code == 403
    assert client.put("/devices/%d" % d["id"], json=new_device(), headers=v).status_code == 403
    assert client.delete("/devices/%d" % d["id"], headers=v).status_code == 403
    assert client.get("/me", headers=v).json()["role"] == "viewer"


def test_editor_can_change_devices_but_not_users(client, auth):
    make_user(client, auth, "duzenleyen", "editor")
    e = login_as(client, "duzenleyen")
    r = client.post("/devices", json=new_device(), headers=e)
    assert r.status_code == 201
    did = r.json()["id"]
    assert client.put("/devices/%d" % did, json=new_device(owner="can"), headers=e).status_code == 200
    assert client.delete("/devices/%d" % did, headers=e).status_code == 204
    assert client.get("/users", headers=e).status_code == 403
    assert client.get("/user-events", headers=e).status_code == 403
    r = client.post(
        "/users",
        json={"username": "yeni-kisi", "password": PASS, "role": "viewer"},
        headers=e,
    )
    assert r.status_code == 403


def test_users_need_login(client):
    assert client.get("/users").status_code == 401
    assert client.post("/me/password", json={}).status_code == 401


def test_create_user_validation(client, auth):
    make_user(client, auth, "ali", "viewer")
    base = {"username": "ali", "password": PASS, "role": "viewer"}
    assert client.post("/users", json=base, headers=auth).status_code == 409
    short = dict(base, username="veli", password="kisa")
    assert client.post("/users", json=short, headers=auth).status_code == 422
    bad_name = dict(base, username="bo ş!")
    assert client.post("/users", json=bad_name, headers=auth).status_code == 422
    bad_role = dict(base, username="veli", role="root")
    assert client.post("/users", json=bad_role, headers=auth).status_code == 422


def test_last_admin_is_protected(client, auth):
    aid = admin_id(client, auth)
    r = client.put("/users/%d" % aid, json={"role": "viewer", "active": True}, headers=auth)
    assert r.status_code == 409
    r = client.put("/users/%d" % aid, json={"role": "admin", "active": False}, headers=auth)
    assert r.status_code == 409
    # İkinci yönetici varsa birincisi düşürülebilir
    make_user(client, auth, "ikinci-admin", "admin")
    r = client.put("/users/%d" % aid, json={"role": "viewer", "active": True}, headers=auth)
    assert r.status_code == 200


def test_update_unknown_user_is_404(client, auth):
    r = client.put("/users/999999", json={"role": "viewer", "active": True}, headers=auth)
    assert r.status_code == 404


def test_deactivated_user_cannot_login_and_loses_session(client, auth):
    u = make_user(client, auth, "gecici", "editor")
    h = login_as(client, "gecici")
    assert client.get("/devices", headers=h).status_code == 200
    r = client.put("/users/%d" % u["id"], json={"role": "editor", "active": False}, headers=auth)
    assert r.status_code == 200
    assert client.get("/devices", headers=h).status_code == 401
    r = client.post("/login", json={"username": "gecici", "password": PASS})
    assert r.status_code == 401
    client.put("/users/%d" % u["id"], json={"role": "editor", "active": True}, headers=auth)
    login_as(client, "gecici")


def test_role_change_closes_sessions(client, auth):
    u = make_user(client, auth, "terfi", "viewer")
    h = login_as(client, "terfi")
    client.put("/users/%d" % u["id"], json={"role": "editor", "active": True}, headers=auth)
    assert client.get("/devices", headers=h).status_code == 401
    h2 = login_as(client, "terfi")
    assert client.get("/me", headers=h2).json()["role"] == "editor"


def test_admin_resets_password(client, auth):
    u = make_user(client, auth, "unutkan", "viewer")
    old = login_as(client, "unutkan")
    r = client.post(
        "/users/%d/password" % u["id"], json={"new_password": NEW_PASS}, headers=auth
    )
    assert r.status_code == 204
    assert client.get("/devices", headers=old).status_code == 401
    assert client.post("/login", json={"username": "unutkan", "password": PASS}).status_code == 401
    login_as(client, "unutkan", NEW_PASS)
    short = client.post("/users/%d/password" % u["id"], json={"new_password": "kisa"}, headers=auth)
    assert short.status_code == 422
    missing = client.post("/users/999999/password", json={"new_password": PASS}, headers=auth)
    assert missing.status_code == 404


def test_change_own_password(client, auth):
    make_user(client, auth, "kendi", "editor")
    a = login_as(client, "kendi")
    b = login_as(client, "kendi")
    wrong = client.post(
        "/me/password", json={"old_password": "yanlis", "new_password": NEW_PASS}, headers=a
    )
    assert wrong.status_code == 403
    weak = client.post("/me/password", json={"old_password": PASS, "new_password": "kisa"}, headers=a)
    assert weak.status_code == 422
    ok = client.post(
        "/me/password", json={"old_password": PASS, "new_password": NEW_PASS}, headers=a
    )
    assert ok.status_code == 204
    assert client.get("/devices", headers=a).status_code == 200
    assert client.get("/devices", headers=b).status_code == 401
    assert client.post("/login", json={"username": "kendi", "password": PASS}).status_code == 401
    login_as(client, "kendi", NEW_PASS)


def test_failed_logins_lock_account(client, auth):
    u = make_user(client, auth, "kilitli", "viewer")
    for _ in range(main.MAX_FAILED_LOGINS):
        r = client.post("/login", json={"username": "kilitli", "password": "yanlis-parola"})
        assert r.status_code == 401
    # Doğru parola bile kilit sürerken kabul edilmez
    assert client.post("/login", json={"username": "kilitli", "password": PASS}).status_code == 401
    locked = next(x for x in client.get("/users", headers=auth).json() if x["id"] == u["id"])
    assert locked["locked"] is True
    # Yönetici parolayı sıfırlayınca kilit kalkar
    client.post("/users/%d/password" % u["id"], json={"new_password": PASS}, headers=auth)
    login_as(client, "kilitli")


def test_success_resets_failed_counter(client, auth):
    make_user(client, auth, "dikkatli", "viewer")
    for _ in range(main.MAX_FAILED_LOGINS - 1):
        client.post("/login", json={"username": "dikkatli", "password": "yanlis"})
    login_as(client, "dikkatli")
    for _ in range(main.MAX_FAILED_LOGINS - 1):
        client.post("/login", json={"username": "dikkatli", "password": "yanlis"})
    login_as(client, "dikkatli")


def test_unknown_user_gets_same_error(client):
    a = client.post("/login", json={"username": "yok-boyle-biri", "password": "x"})
    assert a.status_code == 401
    assert a.json()["detail"] == main.LOGIN_ERROR


def test_user_events_are_recorded(client, auth):
    u = make_user(client, auth, "kayitli", "viewer")
    client.put("/users/%d" % u["id"], json={"role": "editor", "active": True}, headers=auth)
    client.put("/users/%d" % u["id"], json={"role": "editor", "active": False}, headers=auth)
    client.post("/users/%d/password" % u["id"], json={"new_password": PASS}, headers=auth)
    events = client.get("/user-events", headers=auth).json()
    actions = [e["action"] for e in events if e["target"] == "kayitli"]
    assert actions == ["password_reset", "deactivate", "role", "create"]
    assert all(e["username"] == ADMIN["username"] for e in events)
    role_event = next(e for e in events if e["action"] == "role")
    assert role_event["detail"] == "viewer -> editor"
