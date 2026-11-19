"use strict";

const $ = (id) => document.getElementById(id);
const STATUS = { active: "Kullanımda", in_repair: "Tamirde", retired: "Emekli" };
const FIELDS = ["name", "asset_tag", "device_type", "owner", "location"];
let token = null;
let editingId = null;
let allDevices = [];
const view = { mode: "list", sortKey: "id", sortDir: 1 };

function loadToken() {
  try { return sessionStorage.getItem("token"); } catch (e) { return null; }
}

function saveToken(value) {
  try {
    if (value) sessionStorage.setItem("token", value);
    else sessionStorage.removeItem("token");
  } catch (e) { /* tarayıcı depolamayı engellemiş olabilir */ }
}

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
  render();
  closeForm();
  show(false);
}

// --- Süzme, sıralama, gruplama (saf fonksiyonlar) ---

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

function renderRows(devices) {
  const rows = $("rows");
  rows.replaceChildren();
  for (const d of devices) {
    const tr = document.createElement("tr");
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
  const current = select.value;
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

function render() {
  renderStats(allDevices);
  refreshTypeFilter(allDevices);
  const filtered = filterDevices(allDevices, $("search").value, $("filter-status").value, $("filter-type").value);
  const sorted = sortDevices(filtered, view.sortKey, view.sortDir);
  const filtering = filtered.length !== allDevices.length;
  $("count").textContent = "(" + (filtering ? filtered.length + " / " + allDevices.length : allDevices.length) + ")";
  $("empty").hidden = filtered.length > 0;
  $("empty").textContent = allDevices.length === 0 ? "Henüz cihaz yok." : "Aramaya uyan cihaz yok.";
  $("list-view").hidden = view.mode !== "list" || filtered.length === 0;
  $("owner-view").hidden = view.mode !== "owner" || filtered.length === 0;
  $("view-list").classList.toggle("active", view.mode === "list");
  $("view-owner").classList.toggle("active", view.mode === "owner");
  updateSortHeaders();
  if (view.mode === "list") renderRows(sorted);
  else renderOwners(sorted);
}

async function loadDevices() {
  $("list-error").textContent = "";
  try {
    allDevices = await api("/devices?limit=200");
    render();
  } catch (e) {
    $("list-error").textContent = e.message;
  }
}

// --- Form ve işlemler ---

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
  if (!window.confirm('"' + device.name + '" silinsin mi?')) return;
  try {
    await api("/devices/" + device.id, { method: "DELETE" });
    await loadDevices();
  } catch (e) {
    $("list-error").textContent = e.message;
  }
}

async function loadVersion() {
  try {
    const res = await fetch("/version");
    const data = await res.json();
    $("version").textContent = data.version || "-";
  } catch (e) { /* sürüm bilgisi alınamadı, sayfa yine çalışır */ }
}

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
$("search").addEventListener("input", render);
$("filter-status").addEventListener("change", render);
$("filter-type").addEventListener("change", render);
$("view-list").addEventListener("click", () => { view.mode = "list"; render(); });
$("view-owner").addEventListener("click", () => { view.mode = "owner"; render(); });

for (const b of document.querySelectorAll(".th-btn")) {
  b.addEventListener("click", () => {
    if (view.sortKey === b.dataset.sort) view.sortDir = -view.sortDir;
    else { view.sortKey = b.dataset.sort; view.sortDir = 1; }
    render();
  });
}

$("device-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("form-error").textContent = "";
  const body = JSON.stringify({
    name: $("f-name").value,
    asset_tag: $("f-asset-tag").value,
    device_type: $("f-type").value,
    owner: $("f-owner").value || null,
    location: $("f-location").value || null,
    status: $("f-status").value,
  });
  try {
    if (editingId === null) await api("/devices", { method: "POST", body });
    else await api("/devices/" + editingId, { method: "PUT", body });
    closeForm();
    await loadDevices();
  } catch (e) {
    $("form-error").textContent = e.message;
  }
});

token = loadToken();
show(Boolean(token));
if (token) loadDevices();
loadVersion();
