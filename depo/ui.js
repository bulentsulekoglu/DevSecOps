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
  updateBanner(s);
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
    const lb = el("button", "Etiket", { type: "button" });
    lb.addEventListener("click", () => printLabel(it));
    act.appendChild(lb);
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
  const scanBtn = el("button", "Kamerayla oku", { type: "button" });
  scanBtn.addEventListener("click", () => startScan((code) => { inputs.sku.value = code; }));
  form.appendChild(scanBtn);
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
      const noteTd = el("td", r.note);
      if (r === rows[0] && r.undoes === null && r.delta !== 0) {
        const u = el("button", "Geri al", { type: "button" });
        u.addEventListener("click", async () => { await undoMovement(product, r); closePanel(); });
        noteTd.appendChild(document.createTextNode(" "));
        noteTd.appendChild(u);
      }
      tr.appendChild(noteTd);
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
    const move = await api("/api/products/" + product.id + "/movements",
      sendJson("POST", { kind, quantity: 1, note: kind === "in" ? "Hızlı giriş" : "Hızlı çıkış" }));
    await refresh();
    say(product.name + ": " + (kind === "in" ? "+1" : "-1"), "ok");
    offerUndo(product, move);
  } catch (e) {
    say(e.message, "err");
  }
}

// ---------- Ödünç verilenler ----------
function fmtDay(day) {
  return new Date(day + "T00:00:00").toLocaleDateString("tr-TR");
}

function showView(name) {
  stopScan();
  for (const v of ["stock", "count", "loans"]) {
    $("view-" + v).hidden = v !== name;
    $("tab-" + v).classList.toggle("active", v === name);
  }
  $("panel").hidden = true;
  say("");
  if (name === "stock") { $("q").focus(); refresh(); }
  else if (name === "count") loadCountList();
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
      const ed = el("button", "Düzenle", { type: "button" });
      ed.addEventListener("click", () => openLoanForm(l));
      act.appendChild(ed);
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

function openLoanForm(loan) {
  const form = $("loan-form");
  form.replaceChildren();
  const item = el("input", null, { type: "text", maxlength: "120", required: "required" });
  const qty = el("input", null, { type: "number", min: "1", max: "1000000" });
  qty.value = 1;
  const who = el("input", null, { type: "text", maxlength: "80", required: "required" });
  const due = el("input", null, { type: "date" });
  const note = el("input", null, { type: "text", maxlength: "200" });
  if (loan) {
    item.value = loan.item;
    qty.value = loan.quantity;
    who.value = loan.borrower;
    due.value = loan.due_date || "";
    note.value = loan.note;
  }
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
      const payload = {
        item: item.value,
        quantity: Number(qty.value || 1),
        borrower: who.value,
        due_date: due.value || null,
        note: note.value,
      };
      if (loan) await api("/api/loans/" + loan.id, sendJson("PUT", payload));
      else await api("/api/loans", sendJson("POST", payload));
      say(loan ? "Kayıt güncellendi" : "Kayıt eklendi", "ok");
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
$("loan-new-btn").addEventListener("click", () => openLoanForm(null));

// ---------- Geri al (hızlı hareketten sonra mesaj satırında) ----------
function offerUndo(product, movement) {
  const m = $("msg");
  const b = el("button", "Geri al", { type: "button" });
  b.addEventListener("click", () => undoMovement(product, movement));
  m.appendChild(document.createTextNode(" "));
  m.appendChild(b);
}

async function undoMovement(product, movement) {
  try {
    await api("/api/products/" + product.id + "/movements/" + movement.id + "/undo", { method: "POST" });
    say(product.name + ": son hareket geri alındı", "ok");
    await refresh();
  } catch (e) {
    say(e.message, "err");
  }
}

// ---------- Kamera ile barkod okuma ----------
let scanStream = null;
let scanTimer = null;

function stopScan() {
  clearInterval(scanTimer);
  scanTimer = null;
  if (scanStream) scanStream.getTracks().forEach((t) => t.stop());
  scanStream = null;
  $("scan-video").srcObject = null;
  $("scanner").hidden = true;
}

async function startScan(onCode) {
  if (!("BarcodeDetector" in window) || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    say("Bu tarayıcı kamerayla barkod okumayı desteklemiyor (Android'de Chrome gerekir). " +
        "Barkod okuyucu cihaz kullanıyorsanız arama kutusuna okutmanız yeterli.", "err");
    return;
  }
  try {
    const detector = new BarcodeDetector();
    scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    const video = $("scan-video");
    video.srcObject = scanStream;
    await video.play();
    $("scan-info").textContent = "Barkodu kameraya gösterin";
    $("scanner").hidden = false;
    $("scanner").scrollIntoView({ block: "nearest" });
    scanTimer = setInterval(async () => {
      try {
        const found = await detector.detect(video);
        if (found.length && found[0].rawValue) {
          const code = found[0].rawValue;
          stopScan();
          onCode(code);
        }
      } catch (e) {
        /* bir kare okunamadıysa sonrakini dene */
      }
    }, 300);
  } catch (e) {
    stopScan();
    say("Kamera açılamadı: izin verilmemiş ya da kamera yok", "err");
  }
}

$("scan-btn").addEventListener("click", () => startScan((code) => {
  $("q").value = code;
  state.offset = 0;
  refresh();
}));
$("scan-stop").addEventListener("click", stopScan);

// ---------- Yazdırma ----------
function printNow(kind) {
  document.body.dataset.print = kind;
  window.print();
}
window.addEventListener("afterprint", () => { delete document.body.dataset.print; });
$("print-btn").addEventListener("click", () => printNow("list"));

function printLabel(product) {
  $("label-name").textContent = product.name;
  $("label-code").textContent = product.sku || "";
  $("label-loc").textContent = product.location ? "Konum: " + product.location : "";
  $("label").hidden = false;
  printNow("label");
  $("label").hidden = true;
}

// ---------- CSV içe aktarma ----------
function parseCsv(text) {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  let line = 1;
  const lines = [];
  const push = () => { row.push(cell); cell = ""; };
  const endRow = () => { push(); rows.push(row); lines.push(line); row = []; };
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') quoted = false;
      else { if (c === "\n") line++; cell += c; }
    } else if (c === '"') quoted = true;
    else if (c === "," || c === ";") push();
    else if (c === "\n") { endRow(); line++; }
    else if (c !== "\r") cell += c;
  }
  if (cell !== "" || row.length) endRow();
  return { rows, lines };
}

const CSV_FIELDS = {
  kod: "sku", barkod: "sku", sku: "sku",
  ad: "name", "ürün": "name", "ürün adı": "name", name: "name",
  kategori: "category", birim: "unit", konum: "location",
  miktar: "quantity", adet: "quantity", minimum: "min_quantity",
};

async function importCsv(file) {
  try {
    const { rows, lines } = parseCsv(await file.text());
    if (rows.length < 2) throw new Error("Dosyada başlık satırından başka satır yok");
    const cols = rows[0].map((h) => CSV_FIELDS[h.trim().toLowerCase()] || null);
    if (!cols.includes("name")) throw new Error("Başlık satırında 'ad' sütunu bulunamadı");
    const items = [];
    for (let r = 1; r < rows.length; r++) {
      if (rows[r].every((v) => v.trim() === "")) continue;
      const item = { _line: lines[r] };
      rows[r].forEach((v, i) => { if (cols[i] && v.trim() !== "") item[cols[i]] = v.trim(); });
      items.push(item);
    }
    if (!items.length) throw new Error("İçe aktarılacak satır yok");
    const res = await api("/api/import", sendJson("POST", { items }));
    say(res.created + " ürün eklendi" + (res.skipped ? ", " + res.skipped + " satır atlandı (kod zaten kayıtlı)" : ""), "ok");
    await refresh();
  } catch (e) {
    say(e.message, "err");
  } finally {
    $("import-file").value = "";
  }
}

$("import-btn").addEventListener("click", () => $("import-file").click());
$("import-file").addEventListener("change", (ev) => { if (ev.target.files[0]) importCsv(ev.target.files[0]); });

// ---------- Sayım ----------
const countState = { items: [] };

function countDiffCell(td, input, item) {
  const v = input.value.trim();
  td.className = "num";
  if (v === "") { td.textContent = "-"; return; }
  const d = Number(v) - item.quantity;
  td.textContent = (d > 0 ? "+" : "") + d;
  td.className = "num " + (d > 0 ? "diff-pos" : d < 0 ? "diff-neg" : "");
}

async function loadCountList() {
  try {
    const p = new URLSearchParams({ limit: 200, offset: 0 });
    if ($("count-q").value.trim()) p.set("q", $("count-q").value.trim());
    const data = await api("/api/products?" + p.toString());
    countState.items = data.items;
    const body = $("count-rows");
    body.replaceChildren();
    if (!data.items.length) {
      const tr = el("tr");
      tr.appendChild(el("td", "Ürün bulunamadı", { colspan: "5" }));
      body.appendChild(tr);
    }
    for (const it of data.items) {
      const tr = el("tr");
      tr.appendChild(el("td", it.name));
      tr.appendChild(el("td", it.location));
      tr.appendChild(el("td", it.quantity + " " + it.unit, { class: "num" }));
      const inTd = el("td", null, { class: "num" });
      const input = el("input", null, { type: "number", min: "0", max: "1000000", "aria-label": it.name + " sayılan" });
      const diffTd = el("td", "-", { class: "num" });
      input.addEventListener("input", () => countDiffCell(diffTd, input, it));
      it.input = input;
      inTd.appendChild(input);
      tr.appendChild(inTd);
      tr.appendChild(diffTd);
      body.appendChild(tr);
    }
    if (data.total > data.items.length) say("İlk 200 ürün gösteriliyor, aramayı daraltın", "");
    else say("");
  } catch (e) {
    say(e.message, "err");
  }
}

async function applyCount() {
  const items = countState.items
    .filter((it) => it.input.value.trim() !== "")
    .map((it) => ({ product_id: it.id, expected: it.quantity, counted: Number(it.input.value) }));
  if (!items.length) { say("Önce en az bir ürünün sayılan miktarını girin", "err"); return; }
  try {
    const res = await api("/api/count", sendJson("POST", { note: $("count-note").value, items }));
    say(res.changed + " üründe fark bulundu ve düzeltildi", "ok");
    $("count-note").value = "";
    await Promise.all([loadCountList(), loadSummary()]);
    say(res.changed + " üründe fark bulundu ve düzeltildi", "ok");
  } catch (e) {
    say(e.message, "err");
  }
}

$("count-load").addEventListener("click", loadCountList);
$("count-q").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); loadCountList(); } });
$("count-apply").addEventListener("click", applyCount);
$("tab-count").addEventListener("click", () => { showView("count"); });

// ---------- Gecikme uyarısı ----------
function updateBanner(s) {
  const b = $("overdue-banner");
  if (s.loans_overdue > 0) {
    b.textContent = s.loans_overdue + " ödünç kaydının geri alınma tarihi geçti — görmek için tıklayın";
    b.hidden = false;
  } else {
    b.hidden = true;
  }
}
$("overdue-banner").addEventListener("click", () => {
  $("loan-status").value = "overdue";
  showView("loans");
});
