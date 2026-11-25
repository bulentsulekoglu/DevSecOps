"use strict";
const PAGE = 25;
const KINDS = { in: "Giriş", out: "Çıkış", adjust: "Sayım" };
const state = { offset: 0, total: 0, items: [] };
const $ = (id) => document.getElementById(id);

function el(tag, text, attrs) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (attrs) for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function say(text, cls) {
  const m = $("msg");
  m.textContent = text || "";
  m.className = cls || "";
}

function errorText(data) {
  if (data && typeof data.detail === "string") return data.detail;
  if (data && Array.isArray(data.detail) && data.detail.length) {
    return data.detail.map((d) => String(d.msg || "").replace(/^Value error, /, "")).join("; ");
  }
  return "İşlem başarısız";
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) throw new Error(errorText(data));
  return data;
}

function sendJson(method, body) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function fmtDate(iso) {
  return new Date(iso).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });
}

async function loadSummary() {
  const s = await api("/api/summary");
  $("c-products").textContent = s.products;
  $("c-units").textContent = s.units;
  $("c-low").textContent = s.low;
  $("c-empty").textContent = s.empty;
  $("c-loans").textContent = s.loans_open;
  $("c-overdue").textContent = s.loans_overdue;
}

async function loadCategories() {
  const sel = $("cat");
  const keep = sel.value;
  const cats = await api("/api/categories");
  while (sel.options.length > 1) sel.remove(1);
  for (const c of cats) sel.appendChild(el("option", c, { value: c }));
  sel.value = cats.includes(keep) ? keep : "";
}

async function loadProducts() {
  const p = new URLSearchParams({ limit: PAGE, offset: state.offset });
  if ($("q").value.trim()) p.set("q", $("q").value.trim());
  if ($("cat").value) p.set("category", $("cat").value);
  if ($("low").checked) p.set("low", "true");
  const data = await api("/api/products?" + p.toString());
  state.items = data.items;
  state.total = data.total;
  renderRows();
}

function renderRows() {
  const body = $("rows");
  body.replaceChildren();
  if (!state.items.length) {
    const tr = el("tr");
    tr.appendChild(el("td", "Ürün bulunamadı", { colspan: "7" }));
    body.appendChild(tr);
  }
  for (const it of state.items) {
    const tr = el("tr");
    if (it.quantity === 0) tr.className = "empty";
    else if (it.min_quantity > 0 && it.quantity <= it.min_quantity) tr.className = "low";
    tr.appendChild(el("td", it.name));
    tr.appendChild(el("td", it.sku || "-"));
    tr.appendChild(el("td", it.category));
    tr.appendChild(el("td", it.location));
    const q = el("td", null, { class: "num qty" });
    const box = el("span", null, { class: "qtybox" });
    const minus = el("button", "−", { type: "button", "aria-label": "1 azalt" });
    minus.addEventListener("click", () => quickMove(it, "out"));
    box.appendChild(minus);
    box.appendChild(el("span", it.quantity + " " + it.unit));
    const plus = el("button", "+", { type: "button", "aria-label": "1 artır" });
    plus.addEventListener("click", () => quickMove(it, "in"));
    box.appendChild(plus);
    q.appendChild(box);
    tr.appendChild(q);
    tr.appendChild(el("td", it.min_quantity, { class: "num" }));
    const act = el("td", null, { class: "actions" });
    for (const kind of ["in", "out", "adjust"]) {
      const b = el("button", KINDS[kind], { type: "button" });
      b.addEventListener("click", () => openMovement(it, kind));
      act.appendChild(b);
    }
    const h = el("button", "Geçmiş", { type: "button" });
    h.addEventListener("click", () => openHistory(it));
    act.appendChild(h);
    const e = el("button", "Düzenle", { type: "button" });
    e.addEventListener("click", () => openProductForm(it));
    act.appendChild(e);
    tr.appendChild(act);
    body.appendChild(tr);
  }
  const from = state.total ? state.offset + 1 : 0;
  $("page-info").textContent = from + "-" + (state.offset + state.items.length) + " / " + state.total;
  $("prev").disabled = state.offset === 0;
  $("next").disabled = state.offset + PAGE >= state.total;
}

async function refresh() {
  try {
    await Promise.all([loadSummary(), loadCategories(), loadProducts()]);
  } catch (e) {
    say(e.message, "err");
  }
}

// ---------- Panel ----------
function field(label, input) {
  const l = el("label", label);
  l.appendChild(input);
  return l;
}

function openPanel(title) {
  $("panel-title").textContent = title;
  $("form").replaceChildren();
  $("history").replaceChildren();
  $("panel").hidden = false;
  $("panel").scrollIntoView({ block: "nearest" });
}

function closePanel() {
  $("panel").hidden = true;
  $("q").focus();
}

function openMovement(product, kind) {
  openPanel(KINDS[kind] + ": " + product.name + " (elde " + product.quantity + " " + product.unit + ")");
  const form = $("form");
  const qty = el("input", null, { type: "number", min: kind === "adjust" ? "0" : "1", max: "1000000", required: "required" });
  const note = el("input", null, { type: "text", maxlength: "200", placeholder: kind === "adjust" ? "Zorunlu: neden düzeltiliyor?" : "İsteğe bağlı" });
  form.appendChild(field(kind === "adjust" ? "Sayılan miktar" : "Miktar", qty));
  form.appendChild(field("Açıklama", note));
  const ok = el("button", "Kaydet", { type: "submit", class: "primary" });
  form.appendChild(ok);
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    ok.disabled = true;
    try {
      await api("/api/products/" + product.id + "/movements",
        sendJson("POST", { kind, quantity: Number(qty.value), note: note.value }));
      say(KINDS[kind] + " kaydedildi", "ok");
      closePanel();
      await refresh();
    } catch (e) {
      say(e.message, "err");
    } finally {
      ok.disabled = false;
    }
  };
  qty.focus();
}

function openProductForm(product) {
  const isNew = !product;
  openPanel(isNew ? "Yeni ürün" : "Ürünü düzenle: " + product.name);
  const form = $("form");
  const inputs = {
    sku: el("input", null, { type: "text", maxlength: "64" }),
    name: el("input", null, { type: "text", maxlength: "120", required: "required" }),
    category: el("input", null, { type: "text", maxlength: "60" }),
    unit: el("input", null, { type: "text", maxlength: "20", required: "required" }),
    location: el("input", null, { type: "text", maxlength: "60" }),
    min_quantity: el("input", null, { type: "number", min: "0", max: "1000000" }),
    quantity: el("input", null, { type: "number", min: "0", max: "1000000" }),
  };
  inputs.unit.value = product ? product.unit : "adet";
  inputs.min_quantity.value = product ? product.min_quantity : 0;
  inputs.quantity.value = 0;
  if (product) {
    inputs.sku.value = product.sku || "";
    inputs.name.value = product.name;
    inputs.category.value = product.category;
    inputs.location.value = product.location;
  }
  form.appendChild(field("Kod / barkod (isteğe bağlı)", inputs.sku));
  form.appendChild(field("Ürün adı", inputs.name));
  form.appendChild(field("Kategori", inputs.category));
  form.appendChild(field("Birim", inputs.unit));
  form.appendChild(field("Konum (raf)", inputs.location));
  form.appendChild(field("Minimum stok", inputs.min_quantity));
  if (isNew) form.appendChild(field("Açılış miktarı", inputs.quantity));
  const ok = el("button", "Kaydet", { type: "submit", class: "primary" });
  form.appendChild(ok);
  if (!isNew) {
    const del = el("button", "Ürünü arşivle", { type: "button" });
    del.addEventListener("click", async () => {
      try {
        await api("/api/products/" + product.id, { method: "DELETE" });
        say("Ürün arşivlendi", "ok");
        closePanel();
        await refresh();
      } catch (e) {
        say(e.message, "err");
      }
    });
    form.appendChild(del);
  }
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    ok.disabled = true;
    const body = {
      sku: inputs.sku.value,
      name: inputs.name.value,
      category: inputs.category.value,
      unit: inputs.unit.value,
      location: inputs.location.value,
      min_quantity: Number(inputs.min_quantity.value || 0),
    };
    try {
      if (isNew) {
        body.quantity = Number(inputs.quantity.value || 0);
        await api("/api/products", sendJson("POST", body));
      } else {
        await api("/api/products/" + product.id, sendJson("PUT", body));
      }
      say("Ürün kaydedildi", "ok");
      closePanel();
      await refresh();
    } catch (e) {
      say(e.message, "err");
    } finally {
      ok.disabled = false;
    }
  };
  inputs.name.focus();
}

async function openHistory(product) {
  openPanel("Hareket geçmişi: " + product.name);
  try {
    const rows = await api("/api/products/" + product.id + "/movements?limit=50");
    const table = el("table");
    const head = el("tr");
    for (const h of ["Zaman", "Tür", "Değişim", "Sonra", "Kim", "Açıklama"]) head.appendChild(el("th", h));
    table.appendChild(head);
    for (const r of rows) {
      const tr = el("tr");
      tr.appendChild(el("td", fmtDate(r.created_at)));
      tr.appendChild(el("td", KINDS[r.kind]));
      tr.appendChild(el("td", (r.delta > 0 ? "+" : "") + r.delta, { class: "num" }));
      tr.appendChild(el("td", r.quantity_after, { class: "num" }));
      tr.appendChild(el("td", r.username));
      tr.appendChild(el("td", r.note));
      table.appendChild(tr);
    }
    $("history").appendChild(table);
  } catch (e) {
    say(e.message, "err");
  }
}

// ---------- Olaylar ----------
let timer = null;
function searchSoon() {
  clearTimeout(timer);
  timer = setTimeout(() => { state.offset = 0; refresh(); }, 250);
}

$("q").addEventListener("input", searchSoon);
$("q").addEventListener("keydown", async (ev) => {
  if (ev.key !== "Enter") return;
  ev.preventDefault();
  clearTimeout(timer);
  state.offset = 0;
  await refresh();
  // Barkod okuyucu kodu yazıp Enter'a basar: tek ürün bulunduysa doğrudan hareket paneli açılır
  if (state.items.length === 1) openMovement(state.items[0], "in");
});
$("cat").addEventListener("change", () => { state.offset = 0; refresh(); });
$("low").addEventListener("change", () => { state.offset = 0; refresh(); });
$("new-btn").addEventListener("click", () => openProductForm(null));
$("panel-close").addEventListener("click", closePanel);
$("prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - PAGE); refresh(); });
$("next").addEventListener("click", () => { state.offset += PAGE; refresh(); });

api("/api/me").then((m) => { $("who").textContent = m.username; }).catch((e) => say(e.message, "err"));
refresh();

// ---------- Hızlı artır / azalt ----------
async function quickMove(product, kind) {
  try {
    await api("/api/products/" + product.id + "/movements",
      sendJson("POST", { kind, quantity: 1, note: kind === "in" ? "Hızlı giriş" : "Hızlı çıkış" }));
    say(product.name + ": " + (kind === "in" ? "+1" : "-1"), "ok");
    await refresh();
  } catch (e) {
    say(e.message, "err");
  }
}

// ---------- Ödünç verilenler ----------
function fmtDay(day) {
  return new Date(day + "T00:00:00").toLocaleDateString("tr-TR");
}

function showView(name) {
  const stock = name === "stock";
  $("view-stock").hidden = !stock;
  $("view-loans").hidden = stock;
  $("tab-stock").classList.toggle("active", stock);
  $("tab-loans").classList.toggle("active", !stock);
  $("panel").hidden = true;
  say("");
  if (stock) $("q").focus();
  else loadLoans();
}

async function loadLoans() {
  try {
    renderLoans(await api("/api/loans?status=" + encodeURIComponent($("loan-status").value)));
  } catch (e) {
    say(e.message, "err");
  }
}

function renderLoans(items) {
  const body = $("loan-rows");
  body.replaceChildren();
  if (!items.length) {
    const tr = el("tr");
    tr.appendChild(el("td", "Kayıt yok", { colspan: "7" }));
    body.appendChild(tr);
  }
  for (const l of items) {
    const tr = el("tr");
    if (l.overdue) tr.className = "overdue";
    tr.appendChild(el("td", l.item));
    tr.appendChild(el("td", l.quantity, { class: "num" }));
    tr.appendChild(el("td", l.borrower));
    tr.appendChild(el("td", fmtDate(l.lent_at) + " (" + l.lent_by + ")"));
    tr.appendChild(el("td", l.due_date ? fmtDay(l.due_date) : "-"));
    tr.appendChild(el("td", l.note));
    const act = el("td", null, { class: "actions" });
    if (l.returned_at) {
      act.textContent = "Geri alındı: " + fmtDate(l.returned_at) + " (" + l.returned_by + ")";
    } else {
      const b = el("button", "Geri alındı", { type: "button" });
      b.addEventListener("click", () => returnLoan(l));
      act.appendChild(b);
    }
    tr.appendChild(act);
    body.appendChild(tr);
  }
}

async function returnLoan(loan) {
  try {
    await api("/api/loans/" + loan.id + "/return", { method: "POST" });
    say(loan.item + " geri alındı", "ok");
    await Promise.all([loadLoans(), loadSummary()]);
  } catch (e) {
    say(e.message, "err");
  }
}

function openLoanForm() {
  const form = $("loan-form");
  form.replaceChildren();
  const item = el("input", null, { type: "text", maxlength: "120", required: "required" });
  const qty = el("input", null, { type: "number", min: "1", max: "1000000" });
  qty.value = 1;
  const who = el("input", null, { type: "text", maxlength: "80", required: "required" });
  const due = el("input", null, { type: "date" });
  const note = el("input", null, { type: "text", maxlength: "200" });
  form.appendChild(field("Ne verildi", item));
  form.appendChild(field("Adet", qty));
  form.appendChild(field("Kime", who));
  form.appendChild(field("Geri gelme tarihi (isteğe bağlı)", due));
  form.appendChild(field("Not", note));
  const ok = el("button", "Kaydet", { type: "submit", class: "primary" });
  const cancel = el("button", "Vazgeç", { type: "button" });
  cancel.addEventListener("click", () => { form.hidden = true; });
  form.appendChild(ok);
  form.appendChild(cancel);
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    ok.disabled = true;
    try {
      await api("/api/loans", sendJson("POST", {
        item: item.value,
        quantity: Number(qty.value || 1),
        borrower: who.value,
        due_date: due.value || null,
        note: note.value,
      }));
      say("Kayıt eklendi", "ok");
      form.hidden = true;
      await Promise.all([loadLoans(), loadSummary()]);
    } catch (e) {
      say(e.message, "err");
    } finally {
      ok.disabled = false;
    }
  };
  form.hidden = false;
  item.focus();
}

$("tab-stock").addEventListener("click", () => showView("stock"));
$("tab-loans").addEventListener("click", () => showView("loans"));
$("loan-status").addEventListener("change", loadLoans);
$("loan-new-btn").addEventListener("click", openLoanForm);
