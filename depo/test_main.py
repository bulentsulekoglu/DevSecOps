import main
from conftest import USER


def make(client, sku="ABC-1", name="Vida M6", quantity=0, **extra):
    body = {"sku": sku, "name": name, "quantity": quantity, **extra}
    res = client.post("/api/products", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def move(client, pid, kind, quantity, note=""):
    return client.post(f"/api/products/{pid}/movements", json={"kind": kind, "quantity": quantity, "note": note})


# ---------- Açık uçlar ve kimlik ----------
def test_health_and_version_need_no_user(client):
    anon = {"X-Remote-User": ""}
    assert client.get("/health", headers=anon).json() == {"status": "ok"}
    body = client.get("/version", headers=anon).json()
    assert set(body) == {"release", "version", "image"}


def test_api_requires_user_header(client):
    client.headers.pop("X-Remote-User")
    for path in ("/api/me", "/api/products", "/api/summary", "/api/export.csv"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/products", json={"sku": "X", "name": "Y"}).status_code == 401


def test_api_rejects_malformed_user_header(client):
    for bad in ("", "a b", "x;drop", "a" * 65, "<script>"):
        assert client.get("/api/me", headers={"X-Remote-User": bad}).status_code == 401, bad


def test_me_returns_username(client):
    assert client.get("/api/me").json() == {"username": USER["X-Remote-User"]}


def test_security_headers_and_no_docs(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "script-src 'self'" in res.headers["content-security-policy"]
    assert res.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/summary").headers["cache-control"] == "no-store"
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_ui_files_served(client):
    assert "text/html" in client.get("/").headers["content-type"]
    assert "text/css" in client.get("/ui.css").headers["content-type"]
    assert "javascript" in client.get("/ui.js").headers["content-type"]


def test_metrics_counts_requests(client):
    client.get("/health")
    text = client.get("/metrics").text
    assert 'http_requests_total{handler="/health",method="GET",status="200"}' in text


# ---------- Ürünler ----------
def test_create_normalizes_and_records_opening_stock(client):
    p = make(client, sku=" abc/9 ", name="  Somun   M8 ", quantity=40, min_quantity=10)
    assert p["sku"] == "ABC/9"
    assert p["name"] == "Somun M8"
    assert p["quantity"] == 40
    hist = client.get(f"/api/products/{p['id']}/movements").json()
    assert len(hist) == 1
    assert hist[0]["delta"] == 40 and hist[0]["username"] == USER["X-Remote-User"]


def test_duplicate_sku_is_conflict_case_insensitive(client):
    make(client, sku="abc-1")
    res = client.post("/api/products", json={"sku": "ABC-1", "name": "Başka"})
    assert res.status_code == 409


def test_validation_errors(client):
    bad = [
        {"sku": "a b", "name": "x"},
        {"sku": "A1", "name": "   "},
        {"sku": "A1", "name": "x", "quantity": -1},
        {"sku": "A1", "name": "x", "min_quantity": -5},
        {"sku": "A1", "name": "x", "unit": "  "},
    ]
    for body in bad:
        assert client.post("/api/products", json=body).status_code == 422, body


def test_update_changes_details_not_quantity(client):
    p = make(client, quantity=5)
    res = client.put(f"/api/products/{p['id']}", json={"sku": "ABC-1", "name": "Yeni ad", "location": "A-01", "min_quantity": 3})
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Yeni ad" and body["location"] == "A-01" and body["quantity"] == 5


def test_update_to_existing_sku_conflicts(client):
    make(client, sku="A1")
    b = make(client, sku="B1")
    res = client.put(f"/api/products/{b['id']}", json={"sku": "a1", "name": "x"})
    assert res.status_code == 409


def test_unknown_product_is_404(client):
    assert client.get("/api/products/99999").status_code == 404
    assert client.put("/api/products/99999", json={"sku": "Z", "name": "z"}).status_code == 404
    assert move(client, 99999, "in", 1).status_code == 404
    assert client.delete("/api/products/99999").status_code == 404


# ---------- Arama ----------
def test_search_by_name_sku_location_category(client):
    make(client, sku="VD-006", name="Vida M6", location="Raf-A1", category="Bağlantı")
    make(client, sku="LS-100", name="Lastik Conta", location="Raf-B2", category="Sızdırmazlık")

    def names(**params):
        return sorted(i["name"] for i in client.get("/api/products", params=params).json()["items"])

    assert names(q="vida") == ["Vida M6"]
    assert names(q="LS-100") == ["Lastik Conta"]
    assert names(q="raf-b") == ["Lastik Conta"]
    assert names(q="sızdır") == ["Lastik Conta"]
    assert names(q="yok-böyle-bir-şey") == []
    assert len(names()) == 2


def test_search_treats_special_characters_literally(client):
    make(client, sku="A1", name="Normal")
    for q in ("%", "_", "' OR 1=1 --", "\\"):
        res = client.get("/api/products", params={"q": q})
        assert res.status_code == 200, q
        assert res.json()["total"] == 0, q


def test_category_filter_and_categories_list(client):
    make(client, sku="A1", category="Boya")
    make(client, sku="A2", category="Vida")
    assert client.get("/api/categories").json() == ["Boya", "Vida"]
    res = client.get("/api/products", params={"category": "Boya"}).json()
    assert [i["sku"] for i in res["items"]] == ["A1"]


def test_low_stock_filter(client):
    make(client, sku="OK", quantity=50, min_quantity=10)
    make(client, sku="LOW", quantity=10, min_quantity=10)
    make(client, sku="ZERO", quantity=0, min_quantity=5)
    make(client, sku="NOMIN", quantity=0, min_quantity=0)
    res = client.get("/api/products", params={"low": "true"}).json()
    assert sorted(i["sku"] for i in res["items"]) == ["LOW", "ZERO"]


def test_pagination(client):
    for i in range(5):
        make(client, sku=f"P{i}", name=f"Ürün {i}")
    first = client.get("/api/products", params={"limit": 2, "offset": 0}).json()
    last = client.get("/api/products", params={"limit": 2, "offset": 4}).json()
    assert first["total"] == 5 and len(first["items"]) == 2 and len(last["items"]) == 1
    assert client.get("/api/products", params={"limit": 0}).status_code == 422
    assert client.get("/api/products", params={"limit": 201}).status_code == 422


# ---------- Stok hareketleri ----------
def test_in_out_adjust_flow(client):
    p = make(client, quantity=10)
    assert move(client, p["id"], "in", 5, "Sevkiyat").json()["quantity_after"] == 15
    out = move(client, p["id"], "out", 3).json()
    assert out["quantity_after"] == 12 and out["delta"] == -3
    adj = move(client, p["id"], "adjust", 20, "Sayım farkı").json()
    assert adj["quantity_after"] == 20 and adj["delta"] == 8
    assert client.get(f"/api/products/{p['id']}").json()["quantity"] == 20


def test_cannot_take_more_than_stock(client):
    p = make(client, quantity=2)
    res = move(client, p["id"], "out", 3)
    assert res.status_code == 409
    assert client.get(f"/api/products/{p['id']}").json()["quantity"] == 2
    assert len(client.get(f"/api/products/{p['id']}/movements").json()) == 1


def test_movement_validation(client):
    p = make(client, quantity=5)
    assert move(client, p["id"], "in", 0).status_code == 422
    assert move(client, p["id"], "out", -1).status_code == 422
    assert move(client, p["id"], "adjust", 4, "").status_code == 422
    assert move(client, p["id"], "adjust", 4, "ab").status_code == 422
    assert move(client, p["id"], "teleport", 1).status_code == 422
    assert move(client, p["id"], "in", 1_000_001).status_code == 422
    assert client.get(f"/api/products/{p['id']}").json()["quantity"] == 5


def test_quantity_upper_bound(client):
    p = make(client, quantity=1)
    with main.db() as conn:
        conn.execute("UPDATE products SET quantity = %s WHERE id = %s", (main.MAX_QTY - 5, p["id"]))
    assert move(client, p["id"], "in", 5).status_code == 201
    assert move(client, p["id"], "in", 1).status_code == 409
    assert client.get(f"/api/products/{p['id']}").json()["quantity"] == main.MAX_QTY


def test_history_newest_first_with_user(client):
    p = make(client, quantity=1)
    move(client, p["id"], "in", 2)
    move(client, p["id"], "out", 1, "Üretime verildi")
    hist = client.get(f"/api/products/{p['id']}/movements").json()
    assert [h["kind"] for h in hist] == ["out", "in", "in"]
    assert hist[0]["note"] == "Üretime verildi"
    assert all(h["username"] == USER["X-Remote-User"] for h in hist)


def test_recent_movements_lists_product_names(client):
    p = make(client, name="Boru", quantity=3)
    rows = client.get("/api/movements").json()
    assert rows[0]["name"] == "Boru" and rows[0]["sku"] == p["sku"]


# ---------- Arşivleme ----------
def test_archive_refused_with_stock_then_allowed_at_zero(client):
    p = make(client, quantity=2)
    assert client.delete(f"/api/products/{p['id']}").status_code == 409
    move(client, p["id"], "out", 2)
    assert client.delete(f"/api/products/{p['id']}").status_code == 204
    assert client.get(f"/api/products/{p['id']}").status_code == 404
    assert client.get("/api/products").json()["total"] == 0
    assert move(client, p["id"], "in", 1).status_code == 404


def test_archived_sku_stays_reserved(client):
    p = make(client, sku="OLD-1")
    client.delete(f"/api/products/{p['id']}")
    assert client.post("/api/products", json={"sku": "old-1", "name": "Yeni"}).status_code == 409


# ---------- Özet ve CSV ----------
def test_summary_counts(client):
    make(client, sku="A", quantity=10, min_quantity=5)
    make(client, sku="B", quantity=5, min_quantity=5)
    make(client, sku="C", quantity=0)
    s = client.get("/api/summary").json()
    assert (s["products"], s["units"], s["low"], s["empty"]) == (3, 15, 1, 1)


def test_csv_export_blocks_formula_injection(client):
    make(client, sku="F1", name="=HYPERLINK(\"http://x\")", quantity=1)
    make(client, sku="F2", name="+cmd", quantity=1)
    res = client.get("/api/export.csv")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    text = res.content.decode("utf-8-sig")
    assert text.splitlines()[0] == "kod,ad,kategori,birim,konum,miktar,minimum"
    assert "'=HYPERLINK" in text and "'+cmd" in text
    assert ",=HYPERLINK" not in text


# ---------- Ürün kodu isteğe bağlı ----------
def test_sku_is_optional(client):
    r1 = client.post("/api/products", json={"name": "Kodsuz vida", "quantity": 3})
    r2 = client.post("/api/products", json={"name": "Kodsuz somun", "sku": "   "})
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["sku"] is None and r2.json()["sku"] is None
    assert client.get("/api/products", params={"q": "kodsuz"}).json()["total"] == 2
    pid = r1.json()["id"]
    up = client.put(f"/api/products/{pid}", json={"name": "Kodsuz vida", "sku": "kv-1"})
    assert up.json()["sku"] == "KV-1"
    up = client.put(f"/api/products/{pid}", json={"name": "Kodsuz vida"})
    assert up.json()["sku"] is None


def test_csv_handles_products_without_code(client):
    client.post("/api/products", json={"name": "Kodsuz"})
    text = client.get("/api/export.csv").content.decode("utf-8-sig")
    assert "None" not in text
    assert ",Kodsuz,,adet" in text


# ---------- Ödünç verilenler ----------
def lend(client, item="Matkap", borrower="Ali", **extra):
    res = client.post("/api/loans", json={"item": item, "borrower": borrower, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def test_loan_create_and_list_open(client):
    loan = lend(client, quantity=2, due_date="2099-01-01", note="  hafta sonu  ")
    assert loan["item"] == "Matkap" and loan["quantity"] == 2 and loan["borrower"] == "Ali"
    assert loan["note"] == "hafta sonu" and loan["lent_by"] == USER["X-Remote-User"]
    assert loan["returned_at"] is None and loan["overdue"] is False
    assert [r["id"] for r in client.get("/api/loans").json()] == [loan["id"]]


def test_loan_validation(client):
    bad = [
        {"item": "", "borrower": "Ali"},
        {"item": "x", "borrower": "   "},
        {"item": "x", "borrower": "a", "quantity": 0},
        {"item": "x", "borrower": "a", "due_date": "yarın"},
        {"borrower": "Ali"},
    ]
    for body in bad:
        assert client.post("/api/loans", json=body).status_code == 422, body
    assert client.get("/api/loans", params={"status": "bogus"}).status_code == 422


def test_loan_return_flow(client):
    loan = lend(client)
    res = client.post(f"/api/loans/{loan['id']}/return")
    assert res.status_code == 200
    body = res.json()
    assert body["returned_at"] is not None and body["returned_by"] == USER["X-Remote-User"]
    assert client.get("/api/loans").json() == []
    assert len(client.get("/api/loans", params={"status": "returned"}).json()) == 1
    assert len(client.get("/api/loans", params={"status": "all"}).json()) == 1
    assert client.post(f"/api/loans/{loan['id']}/return").status_code == 409
    assert client.post("/api/loans/99999/return").status_code == 404


def test_loan_overdue_order_and_summary(client):
    lend(client, item="Tarihsiz")
    lend(client, item="Zamanı var", due_date="2099-01-01")
    lend(client, item="Gecikmiş", due_date="2000-01-01")
    rows = client.get("/api/loans").json()
    assert [r["item"] for r in rows] == ["Gecikmiş", "Zamanı var", "Tarihsiz"]
    assert [r["overdue"] for r in rows] == [True, False, False]
    s = client.get("/api/summary").json()
    assert (s["loans_open"], s["loans_overdue"]) == (3, 1)


def test_loans_do_not_touch_stock(client):
    p = make(client, quantity=5)
    lend(client, item=p["name"], quantity=3)
    assert client.get(f"/api/products/{p['id']}").json()["quantity"] == 5


def test_loans_require_user(client):
    client.headers.pop("X-Remote-User")
    assert client.get("/api/loans").status_code == 401
    assert client.post("/api/loans", json={"item": "x", "borrower": "y"}).status_code == 401
    assert client.post("/api/loans/1/return").status_code == 401


# ---------- Açılış dayanıklılığı ----------
def _fake_db(failures):
    import contextlib

    import psycopg

    state = {"left": failures, "ran": 0}

    class Conn:
        def execute(self, _sql):
            state["ran"] += 1

    @contextlib.contextmanager
    def fake():
        if state["left"] > 0:
            state["left"] -= 1
            raise psycopg.OperationalError("henüz hazır değil")
        yield Conn()

    return fake, state


def test_init_schema_waits_for_database(monkeypatch):
    fake, state = _fake_db(failures=2)
    monkeypatch.setattr(main, "db", fake)
    monkeypatch.setattr(main.time, "sleep", lambda _s: None)
    main.init_schema(attempts=5, delay=0)
    assert state["ran"] == 1 and state["left"] == 0


def test_init_schema_gives_up_after_attempts(monkeypatch):
    import psycopg
    import pytest

    fake, state = _fake_db(failures=99)
    monkeypatch.setattr(main, "db", fake)
    monkeypatch.setattr(main.time, "sleep", lambda _s: None)
    with pytest.raises(psycopg.OperationalError):
        main.init_schema(attempts=3, delay=0)
    assert state["left"] == 96


# ---------- Son hareketi geri al ----------
def undo(client, pid, mid):
    return client.post(f"/api/products/{pid}/movements/{mid}/undo")


def test_undo_last_movement_restores_stock_and_keeps_history(client):
    p = make(client, quantity=5)
    m = move(client, p["id"], "in", 3).json()
    res = undo(client, p["id"], m["id"])
    assert res.status_code == 201
    body = res.json()
    assert body["delta"] == -3 and body["kind"] == "out" and body["undoes"] == m["id"]
    assert client.get(f"/api/products/{p['id']}").json()["quantity"] == 5
    hist = client.get(f"/api/products/{p['id']}/movements").json()
    assert len(hist) == 3 and hist[0]["undoes"] == m["id"]


def test_undo_an_out_movement_adds_stock_back(client):
    p = make(client, quantity=5)
    m = move(client, p["id"], "out", 2).json()
    assert undo(client, p["id"], m["id"]).json()["kind"] == "in"
    assert client.get(f"/api/products/{p['id']}").json()["quantity"] == 5


def test_undo_only_works_on_latest_movement(client):
    p = make(client, quantity=1)
    first = move(client, p["id"], "in", 1).json()
    move(client, p["id"], "in", 1)
    assert undo(client, p["id"], first["id"]).status_code == 409
    assert client.get(f"/api/products/{p['id']}").json()["quantity"] == 3


def test_undo_cannot_be_undone_again(client):
    p = make(client, quantity=1)
    m = move(client, p["id"], "in", 1).json()
    u = undo(client, p["id"], m["id"]).json()
    assert undo(client, p["id"], u["id"]).status_code == 409
    assert undo(client, p["id"], m["id"]).status_code == 409


def test_undo_unknown_and_requires_user(client):
    assert undo(client, 99999, 1).status_code == 404
    p = make(client, quantity=1)
    client.headers.pop("X-Remote-User")
    assert undo(client, p["id"], 1).status_code == 401


# ---------- CSV içe aktarma ----------
def test_import_creates_products_with_opening_stock(client):
    rows = [
        {"sku": "i-1", "name": "Vida", "quantity": "10", "min_quantity": "2", "_line": 2},
        {"name": "Kodsuz somun", "unit": "kutu"},
    ]
    res = client.post("/api/import", json={"items": rows})
    assert res.status_code == 200 and res.json() == {"created": 2, "skipped": 0}
    items = client.get("/api/products").json()["items"]
    assert sorted(i["name"] for i in items) == ["Kodsuz somun", "Vida"]
    vida = next(i for i in items if i["name"] == "Vida")
    assert vida["sku"] == "I-1" and vida["quantity"] == 10
    hist = client.get(f"/api/products/{vida['id']}/movements").json()
    assert hist[0]["note"] == "CSV içe aktarma"


def test_import_skips_existing_codes(client):
    make(client, sku="DUP-1", name="Eski", quantity=1)
    res = client.post("/api/import", json={"items": [{"sku": "dup-1", "name": "Yeni"}, {"sku": "N-1", "name": "Başka"}]})
    assert res.json() == {"created": 1, "skipped": 1}
    assert client.get("/api/products", params={"q": "eski"}).json()["total"] == 1
    assert client.get("/api/products", params={"q": "yeni"}).json()["total"] == 0


def test_import_rejects_whole_file_on_bad_row(client):
    rows = [{"sku": "OK-1", "name": "İyi"}, {"sku": "a b", "name": "Kötü", "_line": 7}, {"sku": "X", "name": "  "}]
    res = client.post("/api/import", json={"items": rows})
    assert res.status_code == 422
    assert "Satır 7" in res.json()["detail"]
    assert client.get("/api/products").json()["total"] == 0


def test_import_limits_and_auth(client):
    assert client.post("/api/import", json={"items": []}).status_code == 422
    too_many = [{"name": f"u{i}"} for i in range(501)]
    assert client.post("/api/import", json={"items": too_many}).status_code == 422
    client.headers.pop("X-Remote-User")
    assert client.post("/api/import", json={"items": [{"name": "x"}]}).status_code == 401


# ---------- Sayım ----------
def count(client, items, note="Raf A sayımı"):
    return client.post("/api/count", json={"note": note, "items": items})


def test_count_applies_only_differences(client):
    a = make(client, sku="A", quantity=10)
    b = make(client, sku="B", quantity=5)
    res = count(client, [
        {"product_id": a["id"], "expected": 10, "counted": 8},
        {"product_id": b["id"], "expected": 5, "counted": 5},
    ])
    assert res.status_code == 200
    body = res.json()
    assert body["changed"] == 1 and body["items"][0]["before"] == 10 and body["items"][0]["after"] == 8
    assert client.get(f"/api/products/{a['id']}").json()["quantity"] == 8
    assert len(client.get(f"/api/products/{b['id']}/movements").json()) == 1
    top = client.get(f"/api/products/{a['id']}/movements").json()[0]
    assert top["kind"] == "adjust" and top["delta"] == -2 and top["note"] == "Sayım: Raf A sayımı"


def test_count_rejects_changed_stock_and_changes_nothing(client):
    a = make(client, sku="A", quantity=10)
    b = make(client, sku="B", quantity=5)
    move(client, b["id"], "out", 1)
    res = count(client, [
        {"product_id": a["id"], "expected": 10, "counted": 9},
        {"product_id": b["id"], "expected": 5, "counted": 5},
    ])
    assert res.status_code == 409
    assert client.get(f"/api/products/{a['id']}").json()["quantity"] == 10


def test_count_validation(client):
    a = make(client, quantity=1)
    ok = {"product_id": a["id"], "expected": 1, "counted": 2}
    assert count(client, [ok], note="ab").status_code == 422
    assert count(client, [ok, ok]).status_code == 422
    assert count(client, []).status_code == 422
    assert count(client, [{"product_id": a["id"], "expected": 1, "counted": -1}]).status_code == 422
    assert count(client, [{"product_id": 99999, "expected": 0, "counted": 1}]).status_code == 404
    client.headers.pop("X-Remote-User")
    assert count(client, [ok]).status_code == 401


# ---------- Ödünç düzenleme ve gecikenler ----------
def test_loan_edit_open_record(client):
    loan = lend(client, item="Matkap", borrower="Ali")
    res = client.put(f"/api/loans/{loan['id']}", json={
        "item": "Şarjlı matkap", "borrower": "Veli", "quantity": 2, "due_date": "2000-01-01", "note": "kutusuyla",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["item"] == "Şarjlı matkap" and body["borrower"] == "Veli" and body["overdue"] is True
    assert body["lent_by"] == loan["lent_by"] and body["lent_at"] == loan["lent_at"]


def test_loan_edit_rules(client):
    loan = lend(client)
    ok = {"item": "x", "borrower": "y"}
    assert client.put(f"/api/loans/{loan['id']}", json={"item": "", "borrower": "y"}).status_code == 422
    assert client.put("/api/loans/99999", json=ok).status_code == 404
    client.post(f"/api/loans/{loan['id']}/return")
    assert client.put(f"/api/loans/{loan['id']}", json=ok).status_code == 409


def test_loans_overdue_filter(client):
    lend(client, item="Gecikmiş", due_date="2000-01-01")
    lend(client, item="Zamanı var", due_date="2099-01-01")
    lend(client, item="Tarihsiz")
    rows = client.get("/api/loans", params={"status": "overdue"}).json()
    assert [r["item"] for r in rows] == ["Gecikmiş"]
