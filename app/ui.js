"use strict";

const $ = (id) => document.getElementById(id);
const STATUS = { active: "Kullanımda", in_repair: "Tamirde", retired: "Emekli" };
const FIELDS = ["name", "asset_tag", "device_type", "owner", "location"];
const SORT_KEYS = ["id", "name", "asset_tag", "device_type", "owner", "location", "status"];
const PREF_KEY = "ui-prefs";
let token = null;
let editingId = null;
let allDevices = [];
let visibleDevices = [];
let pendingType = "";
let toastTimer = null;
const selected = new Set();
const view = { mode: "list", sortKey: "id", sortDir: 1 };

// --- Tarayıcı depolaması (engellenmiş olabilir, her yerde try/catch) ---

function loadToken() {
  try { return sessionStorage.getItem("token"); } catch (e) { return null; }
}

function saveToken(value) {
  try {
    if (value) sessionStorage.setItem("token", value);
    else sessionStorage.removeItem("token");
  } catch (e) { /* tarayıcı depolamayı engellemiş olabilir */ }
}

function savePrefs() {
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify({
      mode: view.mode,
      sortKey: view.sortKey,
      sortDir: view.sortDir,
      status: $("filter-status").value,
      type: $("filter-type").value || pendingType,
      theme: document.documentElement.dataset.theme || "",
    }));
  } catch (e) { /* tercihler kaydedilemedi, sorun değil */ }
}

function restorePrefs() {
  let prefs = {};
  try { prefs = JSON.parse(localStorage.getItem(PREF_KEY) || "{}") || {}; } catch (e) { prefs = {}; }
  if (prefs.mode === "list" || prefs.mode === "owner") view.mode = prefs.mode;
  if (SORT_KEYS.includes(prefs.sortKey)) view.sortKey = prefs.sortKey;
  if (prefs.sortDir === 1 || prefs.sortDir === -1) view.sortDir = prefs.sortDir;
  if (prefs.status in STATUS) $("filter-status").value = prefs.status;
  if (typeof prefs.type === "string") pendingType = prefs.type;
  if (prefs.theme === "dark" || prefs.theme === "light") document.documentElement.dataset.theme = prefs.theme;
}

// --- API ---

async function api(path, options = {}) {
  const headers = {};
  if (options.body) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401 && token) {
    signOut();
    throw new Error("Oturum süresi doldu, tekrar giriş yapın");
  }
  if (!res.ok) {
    let msg = "İşlem başarısız (" + res.status + ")";
    try {
      const data = await res.json();
      if (typeof data.detail === "string") msg = data.detail;
    } catch (e) { /* yanıt gövdesi yok */ }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

function show(loggedIn) {
  $("login-view").hidden = loggedIn;
  $("app-view").hidden = !loggedIn;
  $("logout").hidden = !loggedIn;
}

function signOut() {
  token = null;
  saveToken(null);
  allDevices = [];
  selected.clear();
  render();
  closeForm();
  show(false);
}

// --- Süzme, sıralama, gruplama, CSV (saf fonksiyonlar) ---

function filterDevices(devices, query, status, type) {
  const q = (query || "").trim().toLowerCase();
  return devices.filter((d) => {
    if (status && d.status !== status) return false;
    if (type && d.device_type !== type) return false;
    if (!q) return true;
    return FIELDS.some((f) => (d[f] || "").toLowerCase().includes(q));
  });
}

function sortDevices(devices, key, dir) {
  const copy = devices.slice();
  copy.sort((a, b) => {
    if (key === "id") return (a.id - b.id) * dir;
    const x = a[key] || "";
    const y = b[key] || "";
    if (!x && y) return 1;
    if (x && !y) return -1;
    return x.localeCompare(y, "tr") * dir;
  });
  return copy;
}

function groupByOwner(devices) {
  const groups = new Map();
  for (const d of devices) {
    const owner = (d.owner || "").trim();
    if (!groups.has(owner)) groups.set(owner, []);
    groups.get(owner).push(d);
  }
  const named = [...groups.keys()].filter((o) => o).sort((a, b) => a.localeCompare(b, "tr"));
  const result = named.map((o) => ({ owner: o, devices: groups.get(o) }));
  if (groups.has("")) result.push({ owner: "", devices: groups.get("") });
  return result;
}

function countByStatus(devices) {
  const counts = { total: devices.length, active: 0, in_repair: 0, retired: 0 };
  for (const d of devices) {
    if (d.status in counts) counts[d.status] += 1;
  }
  return counts;
}

// Excel'de formül olarak çalışabilecek hücreler (=, +, -, @ ile başlayanlar) başına ' konur.
function csvCell(value) {
  let s = value === null || value === undefined ? "" : String(value);
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  if (/[";\n\r]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"';
  return s;
}

function toCsv(devices) {
  const header = ["ID", "Ad", "Demirbaş etiketi", "Tür", "Sahibi", "Konum", "Durum", "Oluşturulma", "Güncellenme"];
  const lines = [header.map(csvCell).join(";")];
  for (const d of devices) {
    lines.push([
      d.id, d.name, d.asset_tag, d.device_type, d.owner, d.location,
      STATUS[d.status] || d.status, d.created_at, d.updated_at,
    ].map(csvCell).join(";"));
  }
  return lines.join("\r\n");
}

function bulkBody(device, changes) {
  return {
    name: device.name,
    asset_tag: device.asset_tag,
    device_type: device.device_type,
    owner: device.owner || null,
    location: device.location || null,
    status: device.status,
    ...changes,
  };
}

// --- Ekrana çizim (metinler her zaman textContent ile yazılır) ---

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text || "-";
  return td;
}

function button(label, className, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = className;
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

function statusBadge(status) {
  const badge = document.createElement("span");
  badge.className = "badge " + (STATUS[status] ? status : "");
  badge.textContent = STATUS[status] || status;
  return badge;
}

function selectCell(device) {
  const td = document.createElement("td");
  td.className = "sel";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = selected.has(device.id);
  box.setAttribute("aria-label", device.name + " seç");
  box.addEventListener("change", () => {
    if (box.checked) selected.add(device.id);
    else selected.delete(device.id);
    updateBulkBar();
  });
  td.append(box);
  return td;
}

function renderRows(devices) {
  const rows = $("rows");
  rows.replaceChildren();
  for (const d of devices) {
    const tr = document.createElement("tr");
    tr.append(selectCell(d));
    tr.append(cell(d.name), cell(d.asset_tag), cell(d.device_type), cell(d.owner), cell(d.location));
    const statusCell = document.createElement("td");
    statusCell.append(statusBadge(d.status));
    const actions = document.createElement("td");
    actions.className = "actions";
    actions.append(
      button("Düzenle", "secondary", () => openForm(d)),
      button("Sil", "danger", () => removeDevice(d)),
    );
    tr.append(statusCell, actions);
    rows.append(tr);
  }
}

function renderOwners(devices) {
  const container = $("owner-view");
  container.replaceChildren();
  for (const group of groupByOwner(devices)) {
    const card = document.createElement("div");
    card.className = "owner-card" + (group.owner ? "" : " unassigned");
    const title = document.createElement("h3");
    const name = document.createElement("span");
    name.textContent = group.owner || "Atanmamış cihazlar";
    const total = document.createElement("span");
    total.className = "meta";
    total.textContent = group.devices.length + " cihaz";
    title.append(name, total);
    const list = document.createElement("ul");
    for (const d of group.devices) {
      const li = document.createElement("li");
      const info = document.createElement("div");
      const itemName = document.createElement("span");
      itemName.className = "item-name";
      itemName.textContent = d.name;
      const meta = document.createElement("span");
      meta.className = "meta";
      meta.textContent = d.asset_tag + " · " + d.device_type;
      info.append(itemName, meta);
      li.append(info, statusBadge(d.status), button("Düzenle", "secondary", () => openForm(d)));
      list.append(li);
    }
    card.append(title, list);
    container.append(card);
  }
}

function renderStats(devices) {
  const counts = countByStatus(devices);
  $("s-total").textContent = String(counts.total);
  $("s-active").textContent = String(counts.active);
  $("s-in_repair").textContent = String(counts.in_repair);
  $("s-retired").textContent = String(counts.retired);
}

function refreshTypeFilter(devices) {
  const select = $("filter-type");
  const current = select.value || pendingType;
  pendingType = "";
  const types = [...new Set(devices.map((d) => d.device_type))].sort((a, b) => a.localeCompare(b, "tr"));
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "Tüm türler";
  select.append(all);
  for (const t of types) {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    select.append(opt);
  }
  select.value = types.includes(current) ? current : "";
}

function updateSortHeaders() {
  for (const b of document.querySelectorAll(".th-btn")) {
    if (!b.dataset.label) b.dataset.label = b.textContent;
    const mark = b.dataset.sort === view.sortKey ? (view.sortDir === 1 ? " ▲" : " ▼") : "";
    b.textContent = b.dataset.label + mark;
  }
}

function updateBulkBar() {
  const count = selected.size;
  $("bulk-count").textContent = String(count);
  $("bulk-bar").hidden = count === 0 || view.mode !== "list";
  const all = visibleDevices.length > 0 && visibleDevices.every((d) => selected.has(d.id));
  $("select-all").checked = all;
}

function render() {
  const existing = new Set(allDevices.map((d) => d.id));
  for (const id of [...selected]) {
    if (!existing.has(id)) selected.delete(id);
  }
  renderStats(allDevices);
  refreshTypeFilter(allDevices);
  const filtered = filterDevices(allDevices, $("search").value, $("filter-status").value, $("filter-type").value);
  visibleDevices = sortDevices(filtered, view.sortKey, view.sortDir);
  const filtering = filtered.length !== allDevices.length;
  $("count").textContent = "(" + (filtering ? filtered.length + " / " + allDevices.length : allDevices.length) + ")";
  $("empty").hidden = filtered.length > 0;
  $("empty").textContent = allDevices.length === 0 ? "Henüz cihaz yok." : "Aramaya uyan cihaz yok.";
  $("list-view").hidden = view.mode !== "list" || filtered.length === 0;
  $("owner-view").hidden = view.mode !== "owner" || filtered.length === 0;
  $("view-list").classList.toggle("active", view.mode === "list");
  $("view-owner").classList.toggle("active", view.mode === "owner");
  updateSortHeaders();
  if (view.mode === "list") renderRows(visibleDevices);
  else renderOwners(visibleDevices);
  updateBulkBar();
  savePrefs();
}

// --- Bildirim ve onay penceresi ---

function showToast(message, isError) {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = "toast" + (isError ? " error" : "");
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 3500);
}

function confirmDialog(text) {
  return new Promise((resolve) => {
    const dialog = $("confirm-dialog");
    $("confirm-text").textContent = text;
    const finish = (answer) => {
      dialog.close();
      resolve(answer);
    };
    $("confirm-yes").onclick = () => finish(true);
    $("confirm-no").onclick = () => finish(false);
    dialog.addEventListener("cancel", () => resolve(false), { once: true });
    dialog.showModal();
  });
}

// --- Veri işlemleri ---

async function loadDevices() {
  $("list-error").textContent = "";
  try {
    allDevices = await api("/devices?limit=200");
    render();
  } catch (e) {
    $("list-error").textContent = e.message;
  }
}

function openForm(device) {
  editingId = device ? device.id : null;
  $("form-title").textContent = device ? "Cihazı düzenle" : "Yeni cihaz";
  $("f-name").value = device ? device.name : "";
  $("f-asset-tag").value = device ? device.asset_tag : "";
  $("f-type").value = device ? device.device_type : "";
  $("f-owner").value = device && device.owner ? device.owner : "";
  $("f-location").value = device && device.location ? device.location : "";
  $("f-status").value = device ? device.status : "active";
  $("form-error").textContent = "";
  $("device-form").hidden = false;
  $("f-name").focus();
}

function closeForm() {
  editingId = null;
  $("device-form").hidden = true;
}

async function removeDevice(device) {
  if (!(await confirmDialog('"' + device.name + '" silinsin mi?'))) return;
  try {
    await api("/devices/" + device.id, { method: "DELETE" });
    selected.delete(device.id);
    await loadDevices();
    showToast("Cihaz silindi", false);
  } catch (e) {
    $("list-error").textContent = e.message;
  }
}

async function bulkRun(label, action) {
  const targets = allDevices.filter((d) => selected.has(d.id));
  if (targets.length === 0) return;
  if (!(await confirmDialog(targets.length + " cihaz için işlem: " + label + ". Devam edilsin mi?"))) return;
  let ok = 0;
  let failed = 0;
  for (const d of targets) {
    try {
      await action(d);
      ok += 1;
    } catch (e) {
      failed += 1;
    }
  }
  selected.clear();
  await loadDevices();
  showToast(ok + " cihaz işlendi" + (failed ? ", " + failed + " başarısız" : ""), failed > 0);
}

function bulkUpdate(label, changes) {
  return bulkRun(label, (d) => api("/devices/" + d.id, { method: "PUT", body: JSON.stringify(bulkBody(d, changes)) }));
}

function downloadCsv() {
  const blob = new Blob(["\uFEFF" + toCsv(visibleDevices)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "cihazlar-" + new Date().toISOString().slice(0, 10) + ".csv";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  showToast(visibleDevices.length + " cihaz CSV olarak indirildi", false);
}

function toggleTheme() {
  const root = document.documentElement;
  const effective = root.dataset.theme || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  root.dataset.theme = effective === "dark" ? "light" : "dark";
  savePrefs();
}

async function loadVersion() {
  try {
    const res = await fetch("/version");
    const data = await res.json();
    $("version").textContent = data.version || "-";
  } catch (e) { /* sürüm bilgisi alınamadı, sayfa yine çalışır */ }
}

// --- Olaylar ---

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("login-error").textContent = "";
  try {
    const data = await api("/login", {
      method: "POST",
      body: JSON.stringify({
        username: $("username").value,
        password: $("password").value,
      }),
    });
    token = data.access_token;
    saveToken(token);
    $("password").value = "";
    show(true);
    await loadDevices();
  } catch (e) {
    $("login-error").textContent = e.message;
  }
});

$("logout").addEventListener("click", async () => {
  try { await api("/logout", { method: "POST" }); } catch (e) { /* oturum zaten kapanmış olabilir */ }
  signOut();
});

$("new-btn").addEventListener("click", () => openForm(null));
$("cancel-btn").addEventListener("click", closeForm);
$("csv-btn").addEventListener("click", downloadCsv);
$("print-btn").addEventListener("click", () => window.print());
$("theme-btn").addEventListener("click", toggleTheme);
$("search").addEventListener("input", render);
$("filter-status").addEventListener("change", render);
$("filter-type").addEventListener("change", render);
$("view-list").addEventListener("click", () => { view.mode = "list"; render(); });
$("view-owner").addEventListener("click", () => { view.mode = "owner"; render(); });

$("select-all").addEventListener("change", () => {
  for (const d of visibleDevices) {
    if ($("select-all").checked) selected.add(d.id);
    else selected.delete(d.id);
  }
  render();
});

$("bulk-owner-btn").addEventListener("click", () => {
  const owner = $("bulk-owner").value.trim();
  if (!owner) { showToast("Önce yeni sahibin adını yaz", true); return; }
  bulkUpdate("sahibi \"" + owner + "\" yap", { owner });
});

$("bulk-owner-clear").addEventListener("click", () => bulkUpdate("sahibini boşalt", { owner: null }));

$("bulk-status-btn").addEventListener("click", () => {
  const status = $("bulk-status").value;
  if (!status) { showToast("Önce bir durum seç", true); return; }
  bulkUpdate("durumu \"" + STATUS[status] + "\" yap", { status });
});

$("bulk-delete").addEventListener("click", () => {
  bulkRun("sil", (d) => api("/devices/" + d.id, { method: "DELETE" }));
});

for (const b of document.querySelectorAll(".th-btn")) {
  b.addEventListener("click", () => {
    if (view.sortKey === b.dataset.sort) view.sortDir = -view.sortDir;
    else { view.sortKey = b.dataset.sort; view.sortDir = 1; }
    render();
  });
}

for (const card of document.querySelectorAll(".stat")) {
  card.addEventListener("click", () => {
    $("filter-status").value = card.dataset.filter;
    render();
  });
}

$("device-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("form-error").textContent = "";
  const isNew = editingId === null;
  const body = JSON.stringify({
    name: $("f-name").value,
    asset_tag: $("f-asset-tag").value,
    device_type: $("f-type").value,
    owner: $("f-owner").value || null,
    location: $("f-location").value || null,
    status: $("f-status").value,
  });
  try {
    if (isNew) await api("/devices", { method: "POST", body });
    else await api("/devices/" + editingId, { method: "PUT", body });
    closeForm();
    await loadDevices();
    showToast(isNew ? "Cihaz eklendi" : "Cihaz güncellendi", false);
  } catch (e) {
    $("form-error").textContent = e.message;
  }
});

restorePrefs();
token = loadToken();
show(Boolean(token));
if (token) loadDevices();
loadVersion();
