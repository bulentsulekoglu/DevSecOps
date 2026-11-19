"use strict";

const $ = (id) => document.getElementById(id);
const STATUS = { active: "Kullanımda", in_repair: "Tamirde", retired: "Emekli" };
let token = null;
let editingId = null;

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
  $("rows").replaceChildren();
  closeForm();
  show(false);
}

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

function renderRows(devices) {
  const rows = $("rows");
  rows.replaceChildren();
  for (const d of devices) {
    const tr = document.createElement("tr");
    tr.append(cell(d.name), cell(d.asset_tag), cell(d.device_type), cell(d.owner), cell(d.location));
    const statusCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = "badge " + (STATUS[d.status] ? d.status : "");
    badge.textContent = STATUS[d.status] || d.status;
    statusCell.append(badge);
    const actions = document.createElement("td");
    actions.className = "actions";
    actions.append(
      button("Düzenle", "secondary", () => openForm(d)),
      button("Sil", "danger", () => removeDevice(d)),
    );
    tr.append(statusCell, actions);
    rows.append(tr);
  }
  $("count").textContent = "(" + devices.length + ")";
  $("empty").hidden = devices.length > 0;
}

async function loadDevices() {
  $("list-error").textContent = "";
  try {
    renderRows(await api("/devices?limit=200"));
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
