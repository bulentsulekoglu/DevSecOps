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
        {"sku": "", "name": "x"},
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
