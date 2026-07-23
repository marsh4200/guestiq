/* ============================ GuestIQ admin ============================ */
let TOKEN = localStorage.getItem('giq_token') || '';
let ROOMS = [];

function esc(s) {
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
/* ---- time / duration helpers (v1.4.0) ---- */
function fmtTs(v, fallback) {
  if (!v) return fallback === undefined ? '\u2014' : fallback;
  return String(v).replace('T', ' ').slice(0, 16);
}
function humanMins(m) {
  m = Math.abs(parseInt(m || 0, 10));
  const d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60), mm = m % 60;
  const p = [];
  if (d) p.push(d + 'd');
  if (h) p.push(h + 'h');
  if (mm || !p.length) p.push(mm + 'm');
  return p.join(' ');
}
function nowLocalInput(plusHours) {
  const d = new Date();
  if (plusHours) d.setHours(d.getHours() + plusHours);
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function toast(msg) {
  const el = document.createElement('div');
  el.className = 'toast'; el.textContent = msg;
  document.getElementById('toastRoot').appendChild(el);
  setTimeout(() => el.remove(), 2600);
}

async function api(path, opts = {}) {
  opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  if (TOKEN) opts.headers['X-Auth-Token'] = TOKEN;
  const r = await fetch(path, opts);
  if (r.status === 401) { logoutLocal(); throw new Error('unauthorized'); }
  if (!r.ok) {
    let msg = 'Request failed';
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : r.text();
}

/* ------------------------------ auth ------------------------------ */
async function doLogin() {
  const pw = document.getElementById('loginPw').value;
  const err = document.getElementById('loginErr');
  err.textContent = '';
  try {
    const r = await fetch('/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    if (!r.ok) throw new Error('Wrong password');
    const d = await r.json();
    TOKEN = d.token; localStorage.setItem('giq_token', TOKEN);
    showApp();
  } catch (e) { err.textContent = e.message; }
}
function logoutLocal() {
  TOKEN = ''; localStorage.removeItem('giq_token');
  document.getElementById('app').classList.add('hidden');
  document.getElementById('loginScreen').classList.remove('hidden');
}
async function doLogout() {
  try { await api('/api/logout', { method: 'POST' }); } catch (e) {}
  logoutLocal();
}

/* ------------------------------ nav ------------------------------ */
const ICONS = {
  checkins: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><polyline points="16 11 18 13 22 9"/></svg>',
  rooms: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6"/></svg>',
  guests: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
  qr: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3z"/><path d="M20 14h1v1h-1z"/><path d="M14 20h1v1h-1z"/><path d="M20 20h1v1h-1z"/></svg>',
  automation: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  updates: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>',
};
const NAV = [
  { id: 'checkins', label: 'Check-ins' },
  { id: 'rooms', label: 'Rooms' },
  { id: 'guests', label: 'Guests' },
  { id: 'qr', label: 'QR Codes' },
  { id: 'automation', label: 'Automation' },
  { id: 'settings', label: 'Settings' },
  { id: 'updates', label: 'Updates' },
];
function renderNav() {
  document.getElementById('tabs').innerHTML = NAV.map(n => `
    <button class="nav-item" data-tab="${n.id}" onclick="switchTab('${n.id}')">
      ${ICONS[n.id] || ''}<span>${n.label}</span>
      <span class="nav-badge hidden" id="navBadge-${n.id}"></span>
    </button>`).join('');
}
function setNavBadge(tab, count) {
  const b = document.getElementById('navBadge-' + tab);
  if (!b) return;
  if (count > 0) { b.textContent = count; b.classList.remove('hidden'); }
  else b.classList.add('hidden');
}

/* ------------------------------ shell ------------------------------ */
async function showApp() {
  document.getElementById('loginScreen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  renderNav();
  await loadVersion();
  switchTab('checkins');
  checkUpdatesQuietly();
}

async function loadVersion() {
  try {
    const v = await api('/api/version');
    document.getElementById('verBadge').textContent = 'v' + v.version;
  } catch (e) {}
}

const TABS = NAV.map(n => n.id);
function switchTab(name) {
  TABS.forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('hidden', t !== name);
  });
  document.querySelectorAll('.nav-item').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === name));
  const fn = { checkins: renderCheckins, rooms: renderRooms, guests: renderGuests,
    qr: renderQR, automation: renderAutomation, settings: renderSettings,
    updates: renderUpdates }[name];
  if (fn) fn();
}

/* --------------------------- modal system --------------------------- */
function openModal(html, opts = {}) {
  const { title = '', icon = '', iconClass = '' } = opts;
  const head = title ? `
    <div class="modal-head">
      ${icon ? `<div class="modal-ico ${iconClass}">${icon}</div>` : ''}
      <h3>${title}</h3>
      <button class="modal-x" onclick="closeModal()" title="Close">✕</button>
    </div>` : '';
  document.getElementById('modalRoot').innerHTML =
    `<div class="overlay" onclick="if(event.target===this)closeModal()">
       <div class="modal">${head}<div class="modal-body">${html}</div></div>
     </div>`;
}
function closeModal() { document.getElementById('modalRoot').innerHTML = ''; }

/* styled confirm — replaces window.confirm() */
let _confirmCb = null;
function confirmModal({ title, message, detailHtml = '', okText = 'Confirm',
                        okClass = '', icon = '!', iconClass = 'amber', onOk }) {
  _confirmCb = onOk;
  openModal(`
    ${message ? `<p style="margin:4px 0 10px;font-size:14px;">${message}</p>` : ''}
    ${detailHtml}
    <div class="row end" style="margin-top:18px;">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn ${okClass}" onclick="_runConfirm(this)">${okText}</button>
    </div>`, { title, icon, iconClass });
}
async function _runConfirm(btn) {
  if (!_confirmCb) { closeModal(); return; }
  btn.disabled = true;
  try { await _confirmCb(); } finally { _confirmCb = null; }
}

/* ========================== CHECK-INS TAB ========================== */
let _checkinTimer = null;

function startCheckinAutoRefresh() {
  clearInterval(_checkinTimer);
  _checkinTimer = setInterval(() => {
    const tab = document.getElementById('tab-checkins');
    if (!tab || tab.classList.contains('hidden')) return;
    if (document.hidden) return;
    if (document.getElementById('modalRoot').innerHTML) return; // don't yank a modal
    renderCheckins(true);
  }, 60000);
}

async function renderCheckins(quiet) {
  const el = document.getElementById('tab-checkins');
  if (!quiet) el.innerHTML = '<div class="empty">Loading…</div>';
  const [pending, active, departures, alerts] = await Promise.all([
    api('/api/stays?status=pending'),
    api('/api/stays?status=checked_in'),
    api('/api/stays?status=checked_out&limit=12').catch(() => []),
    api('/api/alerts').catch(() => []),
  ]);
  ROOMS = await api('/api/rooms');
  window._pending = pending;
  window._active = active;
  window._departures = departures;

  const overdue = active.filter(s => s.overdue);
  setNavBadge('checkins', pending.length + overdue.length);
  const freeRooms = ROOMS.filter(r => r.status === 'available').length;

  /* ---------------- alert banner ---------------- */
  const alertHtml = alerts.length ? `
    <div class="alert-bar">
      <div class="alert-ico">!</div>
      <div style="flex:1;min-width:0;">
        <div class="alert-title">${alerts.length} open alert${alerts.length > 1 ? 's' : ''}</div>
        ${alerts.slice(0, 4).map(a => `
          <div class="alert-line">
            <span>${esc(a.message || a.title)}</span>
            <button class="btn ghost sm" onclick="ackAlert(${a.id})">Dismiss</button>
          </div>`).join('')}
        ${alerts.length > 4 ? `<div class="alert-line muted">+ ${alerts.length - 4} more…</div>` : ''}
      </div>
      <button class="btn ghost sm" onclick="ackAllAlerts()">Clear all</button>
    </div>` : '';

  /* ---------------- pending ---------------- */
  const pendingRows = pending.length ? pending.map(s => `
    <tr>
      <td><b>${esc(s.full_name)}</b><br><span class="muted" style="font-size:12px;">
        ${esc(s.phone || s.email || '')}</span></td>
      <td>${esc(s.id_number || '—')}</td>
      <td>${s.num_guests || 1}</td>
      <td class="muted" style="font-size:12px;">${esc(fmtTs(s.created_at))}</td>
      <td class="row end">
        <button class="btn green sm" onclick="openAssign(${s.id})">Assign room</button>
        <button class="btn ghost sm" onclick="cancelStay(${s.id})">✕</button>
      </td>
    </tr>`).join('') : `<tr><td colspan="5" class="empty">No pending check-ins</td></tr>`;

  /* ---------------- in-house (overdue first) ---------------- */
  const sorted = active.slice().sort((a, b) =>
    (b.minutes_over || 0) - (a.minutes_over || 0));
  const activeRows = sorted.length ? sorted.map(s => `
    <tr class="${s.overdue ? 'row-overdue' : ''}">
      <td><b>${esc(s.full_name)}</b>
        ${s.overdue ? '<br><span class="pill overdue">Overdue ' + esc(s.overdue_text) + '</span>' : ''}</td>
      <td>${s.room_number ? esc(s.room_number) + (s.room_name ? ' · ' + esc(s.room_name) : '') : '—'}</td>
      <td>${esc(fmtTs(s.check_in_at))}</td>
      <td class="${s.overdue ? 'txt-red' : ''}">${esc(fmtTs(s.check_out_at))}</td>
      <td class="row end">
        ${s.overdue ? `<button class="btn ghost sm" onclick="openExtend(${s.id})">Extend</button>` : ''}
        <button class="btn ${s.overdue ? 'red' : 'amber'} sm" onclick="openCheckout(${s.id})">Check out</button>
      </td>
    </tr>`).join('') : `<tr><td colspan="5" class="empty">No active guests</td></tr>`;

  /* ---------------- departures ---------------- */
  const depRows = departures.length ? departures.map(s => `
    <tr>
      <td><b>${esc(s.full_name)}</b></td>
      <td>${s.room_number ? esc(s.room_number) + (s.room_name ? ' · ' + esc(s.room_name) : '') : '—'}</td>
      <td>${esc(fmtTs(s.check_in_at))}</td>
      <td>${esc(fmtTs(s.check_out_at))}</td>
      <td>${esc(fmtTs(s.checked_out_at))}</td>
      <td>${!s.checked_out_at ? '<span class="muted">—</span>'
            : s.overstayed_minutes
              ? '<span class="pill overdue">+' + esc(s.overstayed_text) + '</span>'
              : '<span class="pill checked_in">On time</span>'}</td>
    </tr>`).join('') : `<tr><td colspan="6" class="empty">No departures yet</td></tr>`;

  el.innerHTML = `
    ${alertHtml}
    <div class="stats">
      <div class="stat amber"><div class="num">${pending.length}</div><div class="lbl">Pending arrivals</div></div>
      <div class="stat green"><div class="num">${active.length}</div><div class="lbl">Guests in-house</div></div>
      <div class="stat red"><div class="num">${overdue.length}</div><div class="lbl">Overdue checkout</div></div>
      <div class="stat blue"><div class="num">${freeRooms}</div><div class="lbl">Rooms available</div></div>
      <div class="stat"><div class="num">${ROOMS.length}</div><div class="lbl">Total rooms</div></div>
    </div>
    <div class="grid">
      <div class="card">
        <h2>Pending arrivals ${pending.length ? '· ' + pending.length : ''}</h2>
        <table><thead><tr><th>Guest</th><th>ID / Passport</th><th>Pax</th>
          <th>Submitted</th><th></th></tr></thead>
          <tbody>${pendingRows}</tbody></table>
      </div>
      <div class="card">
        <div class="row"><h2 style="margin:0;flex:1;">Currently checked in ${active.length ? '· ' + active.length : ''}</h2>
          <button class="btn sm" onclick="openManualStay()">+ Manual check-in</button></div>
        <table style="margin-top:12px;"><thead><tr><th>Guest</th><th>Room</th>
          <th>Checked in</th><th>Due out</th><th></th></tr></thead>
          <tbody>${activeRows}</tbody></table>
      </div>
      <div class="card">
        <h2>Recent departures</h2>
        <table><thead><tr><th>Guest</th><th>Room</th><th>Checked in</th>
          <th>Due out</th><th>Checked out</th><th>Overstay</th></tr></thead>
          <tbody>${depRows}</tbody></table>
      </div>
    </div>`;
  startCheckinAutoRefresh();
}

/* ---------------------------- alerts ---------------------------- */
async function ackAlert(id) {
  try { await api('/api/alerts/' + id + '/ack', { method: 'POST' }); renderCheckins(true); }
  catch (e) { toast(e.message); }
}
async function ackAllAlerts() {
  try { await api('/api/alerts/ack-all', { method: 'POST' }); renderCheckins(true); }
  catch (e) { toast(e.message); }
}

function roomOptions(selected) {
  const avail = ROOMS.filter(r => r.status === 'available' || r.id === selected);
  return avail.map(r => `<option value="${r.id}" ${r.id===selected?'selected':''}>
    ${esc(r.room_number)}${r.room_name ? ' · ' + esc(r.room_name) : ''}
    ${r.status==='occupied'?' (occupied)':''}</option>`).join('');
}

function defaultCheckout() {
  const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(10, 0, 0, 0);
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function noRoomsModal() {
  const total = ROOMS.length;
  const occupied = ROOMS.filter(r => r.status === 'occupied').length;
  openModal(`
    <p style="margin:4px 0 10px;font-size:14px;">
      ${total
        ? `Every room is currently occupied — <b>${occupied} of ${total}</b> rooms are in use.
           Check a guest out (or extend nothing) before checking anyone else in.`
        : `There are no rooms set up yet. Add a room before checking guests in.`}</p>
    ${total ? `<div class="sumbox">
      ${ROOMS.filter(r => r.status === 'occupied').slice(0, 8).map(r => `
        <div class="sumrow"><span class="k">${esc(r.room_number)}</span>
          <span class="v">${esc((r.occupant && r.occupant.full_name) || 'Occupied')}</span></div>`).join('')}
      ${occupied > 8 ? `<div class="sumrow"><span class="k">…</span>
        <span class="v muted">+ ${occupied - 8} more</span></div>` : ''}
    </div>` : ''}
    <div class="row end" style="margin-top:18px;">
      <button class="btn ghost" onclick="closeModal()">Close</button>
      <button class="btn" onclick="closeModal();switchTab('rooms')">${total ? 'Manage rooms' : 'Add a room'}</button>
    </div>`, { title: total ? 'No rooms available' : 'No rooms set up',
               icon: '⛔', iconClass: 'red' });
}

async function openAssign(stayId) {
  try { ROOMS = await api('/api/rooms'); } catch (e) {}
  if (!ROOMS.some(r => r.status === 'available')) { noRoomsModal(); return; }
  const s = (window._pending || []).find(x => x.id === stayId) || {};
  openModal(`
    ${s.full_name ? `<div class="sumbox"><div class="sumrow">
      <span class="k">Guest</span><span class="v">${esc(s.full_name)}</span></div></div>` : ''}
    <label>Room</label>
    <select id="asRoom">${roomOptions(null)}</select>
    <label>Check-out (how long they stay)</label>
    <input id="asOut" type="datetime-local" value="${defaultCheckout()}">
    <div class="row end" style="margin-top:16px;">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn green" onclick="submitAssign(${stayId})">Check in guest</button>
    </div>`, { title: 'Assign room', icon: '🛏', iconClass: 'green' });
}
async function submitAssign(stayId) {
  const room_id = parseInt(document.getElementById('asRoom').value, 10);
  const out = document.getElementById('asOut').value;
  if (!room_id) { toast('Pick a room'); return; }
  if (!out) { toast('Set a checkout date'); return; }
  try {
    await api(`/api/stays/${stayId}/assign`, { method: 'POST',
      body: JSON.stringify({ room_id, check_out_at: out }) });
    closeModal(); toast('Guest checked in'); renderCheckins();
  } catch (e) { toast(e.message); renderCheckins(true); }
}

let _pickedGuest = null;

async function openManualStay() {
  try { ROOMS = await api('/api/rooms'); } catch (e) {}
  if (!ROOMS.some(r => r.status === 'available')) { noRoomsModal(); return; }
  _pickedGuest = null;
  openModal(`
    <label>Existing contact</label>
    <div class="picker">
      <input id="mSearch" autocomplete="off" placeholder="Search saved guests by name, phone or ID…"
        oninput="searchContacts(this.value)" onfocus="searchContacts(this.value)"
        onblur="setTimeout(hideContacts, 150)">
      <div class="picker-list hidden" id="mResults"></div>
    </div>
    <div id="mPicked"></div>
    <div class="picker-or"><span>or capture a new guest</span></div>
    <label>Full name *</label><input id="mName" oninput="onManualNameTyped()">
    <div class="grid cols-2">
      <div><label>Phone</label><input id="mPhone"></div>
      <div><label>Email</label><input id="mEmail"></div>
    </div>
    <label>ID / Passport</label><input id="mId">
    <label>Room</label><select id="mRoom">${roomOptions(null)}</select>
    <div class="grid cols-2">
      <div><label>Guests</label><input id="mPax" type="number" min="1" value="1"></div>
      <div><label>Check-out</label><input id="mOut" type="datetime-local" value="${defaultCheckout()}"></div>
    </div>
    <div class="row end" style="margin-top:16px;">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn green" onclick="submitManualStay()">Check in</button>
    </div>`, { title: 'Manual check-in', icon: '✍️', iconClass: 'blue' });
  searchContacts('');   // preload the most recent contacts
}

/* ---- existing-contact picker ---- */
function hideContacts() {
  const box = document.getElementById('mResults');
  if (box) box.classList.add('hidden');
}
async function searchContacts(q) {
  clearTimeout(window._cs);
  window._cs = setTimeout(async () => {
    const box = document.getElementById('mResults');
    if (!box) return;
    let list = [];
    try {
      list = await api('/api/guests?limit=8' + (q ? '&q=' + encodeURIComponent(q) : ''));
    } catch (e) { return; }
    window._pickList = list;
    box.innerHTML = list.length ? list.map(g => `
      <div class="picker-item" onmousedown="pickContact(${g.id})">
        <div style="flex:1;min-width:0;">
          <div class="pi-name">${esc(g.full_name)}
            ${g.in_house ? '<span class="pill occupied" style="margin-left:6px;">in-house</span>' : ''}</div>
          <div class="pi-sub">${esc([g.phone, g.email, g.id_number].filter(Boolean).join(' · ') || 'No contact details')}</div>
        </div>
        <div class="pi-meta">${g.visits ? g.visits + (g.visits > 1 ? ' stays' : ' stay') : 'New'}
          ${g.last_stay ? '<br>' + esc(String(g.last_stay).slice(0, 10)) : ''}</div>
      </div>`).join('')
      : `<div class="picker-empty">No saved guest matches that</div>`;
    box.classList.remove('hidden');
  }, 200);
}
function pickContact(id) {
  const g = (window._pickList || []).find(x => x.id === id);
  if (!g) return;
  _pickedGuest = g;
  document.getElementById('mName').value = g.full_name || '';
  document.getElementById('mPhone').value = g.phone || '';
  document.getElementById('mEmail').value = g.email || '';
  document.getElementById('mId').value = g.id_number || '';
  document.getElementById('mSearch').value = '';
  hideContacts();
  document.getElementById('mPicked').innerHTML = `
    <div class="picked-chip">
      <div class="pc-ico">👤</div>
      <div style="flex:1;min-width:0;">
        <div class="pi-name">${esc(g.full_name)}</div>
        <div class="pi-sub">${g.visits ? esc(g.visits + (g.visits > 1 ? ' previous stays' : ' previous stay')) : 'First stay'}
          ${g.last_stay ? ' · last ' + esc(String(g.last_stay).slice(0, 10)) : ''}
          ${g.vehicle_reg ? ' · ' + esc(g.vehicle_reg) : ''}</div>
        ${g.in_house ? '<div class="pi-sub txt-red">Already checked in — check them out first</div>' : ''}
      </div>
      <button class="modal-x" onclick="clearContact()" title="Clear">✕</button>
    </div>`;
}
function clearContact() {
  _pickedGuest = null;
  document.getElementById('mPicked').innerHTML = '';
  ['mName', 'mPhone', 'mEmail', 'mId'].forEach(id => document.getElementById(id).value = '');
}
function onManualNameTyped() {
  // typing over a picked contact detaches it, so a new record is created
  if (_pickedGuest && document.getElementById('mName').value.trim() !== _pickedGuest.full_name) {
    _pickedGuest = null;
    document.getElementById('mPicked').innerHTML = '';
  }
}

async function submitManualStay() {
  const name = document.getElementById('mName').value.trim();
  const room_id = parseInt(document.getElementById('mRoom').value, 10);
  const out = document.getElementById('mOut').value;
  if (!name) { toast('Name required'); return; }
  if (!room_id) { toast('Pick a room'); return; }
  try {
    await api('/api/stays', { method: 'POST', body: JSON.stringify({
      guest: { full_name: name, phone: document.getElementById('mPhone').value.trim(),
        email: document.getElementById('mEmail').value.trim(),
        id_number: document.getElementById('mId').value.trim() },
      guest_id: _pickedGuest ? _pickedGuest.id : null,
      room_id, check_out_at: out,
      num_guests: parseInt(document.getElementById('mPax').value || '1', 10),
    })});
    closeModal(); toast(_pickedGuest ? 'Returning guest checked in' : 'Checked in');
    _pickedGuest = null;
    renderCheckins();
  } catch (e) { toast(e.message); renderCheckins(true); }
}

/* checkout modal — full stay timeline (v1.4.0) */
function openCheckout(id) {
  const s = (window._active || []).find(x => x.id === id) || {};
  const room = s.room_number
    ? esc(s.room_number) + (s.room_name ? ' · ' + esc(s.room_name) : '') : '—';
  const over = s.overdue && s.minutes_over;
  confirmModal({
    title: 'Check out guest',
    icon: over ? '⏰' : '👋', iconClass: over ? 'red' : 'amber',
    message: '',
    detailHtml: `
      <div class="sumbox">
        <div class="sumrow"><span class="k">Guest</span><span class="v">${esc(s.full_name || '—')}</span></div>
        <div class="sumrow"><span class="k">Room</span><span class="v">${room}</span></div>
        <div class="sumrow"><span class="k">Checked in</span><span class="v">${esc(fmtTs(s.check_in_at))}</span></div>
        <div class="sumrow"><span class="k">Due out</span>
          <span class="v ${over ? 'txt-red' : ''}">${esc(fmtTs(s.check_out_at))}</span></div>
        <div class="sumrow"><span class="k">Checking out</span><span class="v">${esc(fmtTs(nowLocalInput()))}</span></div>
        <div class="sumrow"><span class="k">Status</span><span class="v">
          ${over
            ? '<span class="pill overdue">Overstayed ' + esc(s.overdue_text) + '</span>'
            : '<span class="pill checked_in">On time</span>'}</span></div>
        ${s.duration_text ? `<div class="sumrow"><span class="k">Booked for</span>
          <span class="v">${esc(s.duration_text)}</span></div>` : ''}
      </div>
      <p class="muted" style="font-size:13px;margin:10px 0 0;">
        The room becomes <b style="color:var(--green);">available</b>, Home Assistant
        switches it to unoccupied, and the room QR code stops showing Wi-Fi,
        the menu and stay details until the next guest checks in.</p>`,
    okText: 'Check out', okClass: over ? 'red' : 'amber',
    onOk: async () => {
      try {
        const r = await api(`/api/stays/${id}/checkout`, { method: 'POST' });
        toast('Guest checked out');
        showCheckoutSummary(s, r);
        renderCheckins(true);
      } catch (e) { toast(e.message); closeModal(); }
    },
  });
}

/* post-checkout receipt: in / due / actual out / overstay */
function showCheckoutSummary(s, r) {
  const st = (r && r.stay) || {};
  const room = st.room_number || s.room_number
    ? esc(st.room_number || s.room_number) +
      ((st.room_name || s.room_name) ? ' · ' + esc(st.room_name || s.room_name) : '')
    : '—';
  const overMins = (r && r.overstayed_minutes) || 0;
  openModal(`
    <div class="sumbox">
      <div class="sumrow"><span class="k">Guest</span><span class="v">${esc(st.full_name || s.full_name || '—')}</span></div>
      <div class="sumrow"><span class="k">Room</span><span class="v">${room}</span></div>
      <div class="sumrow"><span class="k">Checked in</span><span class="v">${esc(fmtTs(st.check_in_at || s.check_in_at))}</span></div>
      <div class="sumrow"><span class="k">Due out</span><span class="v">${esc(fmtTs(st.check_out_at || s.check_out_at))}</span></div>
      <div class="sumrow"><span class="k">Checked out</span>
        <span class="v" style="color:var(--green);">${esc(fmtTs(r && r.checked_out_at))}</span></div>
      <div class="sumrow"><span class="k">Overstay</span><span class="v">
        ${overMins
          ? '<span class="pill overdue">+' + esc(r.overstayed_text) + '</span>'
          : '<span class="pill checked_in">None — on time</span>'}</span></div>
      ${st.duration_text ? `<div class="sumrow"><span class="k">Total stay</span>
        <span class="v">${esc(st.duration_text)}</span></div>` : ''}
    </div>
    <p class="muted" style="font-size:12.5px;margin:12px 0 0;">
      Room QR access revoked · room marked available.</p>
    <div class="row end" style="margin-top:16px;">
      <button class="btn" onclick="closeModal()">Done</button>
    </div>`, { title: 'Checked out', icon: '✓', iconClass: 'green' });
}

/* extend a stay straight from the overdue row */
function openExtend(id) {
  const s = (window._active || []).find(x => x.id === id) || {};
  openModal(`
    <div class="sumbox">
      <div class="sumrow"><span class="k">Guest</span><span class="v">${esc(s.full_name || '—')}</span></div>
      <div class="sumrow"><span class="k">Was due</span>
        <span class="v txt-red">${esc(fmtTs(s.check_out_at))}</span></div>
      ${s.overdue_text ? `<div class="sumrow"><span class="k">Overdue by</span>
        <span class="v">${esc(s.overdue_text)}</span></div>` : ''}
    </div>
    <label>New check-out</label>
    <input id="exOut" type="datetime-local" value="${defaultCheckout()}">
    <div class="row" style="margin-top:8px;">
      <button class="btn ghost sm" onclick="document.getElementById('exOut').value='${nowLocalInput(2)}'">+2 hours</button>
      <button class="btn ghost sm" onclick="document.getElementById('exOut').value='${nowLocalInput(24)}'">+1 day</button>
    </div>
    <div class="row end" style="margin-top:16px;">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn green" onclick="submitExtend(${id})">Extend stay</button>
    </div>`, { title: 'Extend stay', icon: '⏱', iconClass: 'blue' });
}
async function submitExtend(id) {
  const out = document.getElementById('exOut').value;
  if (!out) { toast('Pick a new checkout time'); return; }
  try {
    await api(`/api/stays/${id}/extend`, { method: 'POST',
      body: JSON.stringify({ check_out_at: out }) });
    closeModal(); toast('Stay extended'); renderCheckins(true);
  } catch (e) { toast(e.message); }
}

function cancelStay(id) {
  const s = (window._pending || []).find(x => x.id === id) || {};
  confirmModal({
    title: 'Cancel check-in',
    icon: '✕', iconClass: 'red',
    message: `Cancel the pending check-in for <b>${esc(s.full_name || 'this guest')}</b>?`,
    okText: 'Cancel check-in', okClass: 'red',
    onOk: async () => {
      try {
        await api(`/api/stays/${id}/cancel`, { method: 'POST' });
        closeModal(); toast('Check-in cancelled'); renderCheckins();
      } catch (e) { toast(e.message); closeModal(); }
    },
  });
}

/* ============================ ROOMS TAB ============================ */
async function renderRooms() {
  const el = document.getElementById('tab-rooms');
  el.innerHTML = '<div class="empty">Loading…</div>';
  ROOMS = await api('/api/rooms');
  const rows = ROOMS.length ? ROOMS.map(r => `
    <tr>
      <td><b>${esc(r.room_number)}</b> ${r.room_name ? '· ' + esc(r.room_name) : ''}</td>
      <td>${esc(r.floor || '—')}</td>
      <td>${esc(r.wifi_ssid || '—')}</td>
      <td><span class="pill ${r.status}">${r.status}</span>
        ${r.occupant ? '<br><span class="muted" style="font-size:11px;">'+esc(r.occupant.full_name)+'</span>' : ''}</td>
      <td class="row end">
        <button class="btn ghost sm" onclick="showRoomQR('${r.room_code}','${esc(r.room_number)}')">QR</button>
        <button class="btn ghost sm" onclick="editRoom(${r.id})">Edit</button>
        <button class="btn ghost sm" onclick="delRoom(${r.id})">✕</button>
      </td>
    </tr>`).join('') : `<tr><td colspan="5" class="empty">No rooms yet — add one</td></tr>`;

  el.innerHTML = `<div class="card">
      <div class="row"><h2 style="flex:1;margin:0;">Rooms · ${ROOMS.length}</h2>
        <button class="btn sm" onclick="editRoom(null)">+ Add room</button></div>
      <table style="margin-top:12px;"><thead><tr><th>Room</th><th>Floor</th>
        <th>Wi-Fi SSID</th><th>Status</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table>
    </div>`;
}

function editRoom(id) {
  const r = id ? ROOMS.find(x => x.id === id) : {};
  openModal(`
    <div class="grid cols-2">
      <div><label>Room number *</label><input id="rNum" value="${esc(r.room_number||'')}"></div>
      <div><label>Room name</label><input id="rName" value="${esc(r.room_name||'')}"></div>
    </div>
    <label>Floor</label><input id="rFloor" value="${esc(r.floor||'')}">
    <div class="grid cols-2">
      <div><label>Wi-Fi SSID</label><input id="rSsid" value="${esc(r.wifi_ssid||'')}"></div>
      <div><label>Wi-Fi password</label><input id="rPw" value="${esc(r.wifi_password||'')}"></div>
    </div>
    <label>Room notes (shown to guest)</label><textarea id="rDesc">${esc(r.description||'')}</textarea>
    <div class="row end" style="margin-top:16px;">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" onclick="saveRoom(${id||'null'})">Save</button>
    </div>`, { title: (id ? 'Edit' : 'Add') + ' room', icon: '🛏', iconClass: 'blue' });
}
async function saveRoom(id) {
  const body = {
    room_number: document.getElementById('rNum').value.trim(),
    room_name: document.getElementById('rName').value.trim(),
    floor: document.getElementById('rFloor').value.trim(),
    wifi_ssid: document.getElementById('rSsid').value.trim(),
    wifi_password: document.getElementById('rPw').value.trim(),
    description: document.getElementById('rDesc').value.trim(),
  };
  if (!body.room_number) { toast('Room number required'); return; }
  try {
    if (id) await api('/api/rooms/' + id, { method: 'PUT', body: JSON.stringify(body) });
    else await api('/api/rooms', { method: 'POST', body: JSON.stringify(body) });
    closeModal(); toast('Saved'); renderRooms();
  } catch (e) { toast(e.message); }
}
function delRoom(id) {
  const r = ROOMS.find(x => x.id === id) || {};
  confirmModal({
    title: 'Delete room',
    icon: '🗑', iconClass: 'red',
    message: `Delete room <b>${esc(r.room_number || '')}</b>${r.room_name ? ' · ' + esc(r.room_name) : ''}?
      This can't be undone.`,
    okText: 'Delete', okClass: 'red',
    onOk: async () => {
      try {
        await api('/api/rooms/' + id, { method: 'DELETE' });
        closeModal(); toast('Room deleted'); renderRooms();
      } catch (e) { toast(e.message); closeModal(); }
    },
  });
}
function showRoomQR(code, num) {
  const url = location.origin + '/room/' + code;
  openModal(`
    <div class="qr-box">
      <img src="/api/qr/room/${encodeURIComponent(code)}.png" alt="QR">
      <div class="url">${esc(url)}</div>
    </div>
    <p class="muted" style="font-size:13px;">Print this and place it in the room. Scanning shows
      Wi-Fi, restaurant, menu and contacts.</p>
    <div class="row end">
      <a class="btn ghost" href="/api/qr/room/${encodeURIComponent(code)}.png" download="room-${esc(num)}-qr.png">Download PNG</a>
      <button class="btn" onclick="closeModal()">Close</button>
    </div>`, { title: `Room ${esc(num)} — guest QR`, icon: '▦', iconClass: 'blue' });
}

/* ============================ GUESTS TAB ============================ */
async function renderGuests(q) {
  const el = document.getElementById('tab-guests');
  const guests = await api('/api/guests' + (q ? '?q=' + encodeURIComponent(q) : ''));
  const rows = guests.length ? guests.map(g => `
    <tr>
      <td><b>${esc(g.full_name)}</b></td>
      <td>${esc(g.phone || '—')}</td>
      <td>${esc(g.email || '—')}</td>
      <td>${esc(g.id_number || '—')}</td>
      <td class="row end">
        <button class="btn ghost sm" onclick="editGuest(${g.id})">Edit</button>
        <button class="btn ghost sm" onclick="delGuest(${g.id})">✕</button>
      </td>
    </tr>`).join('') : `<tr><td colspan="5" class="empty">No guests found</td></tr>`;

  el.innerHTML = `<div class="card">
      <div class="row"><h2 style="flex:1;margin:0;">Guest records · ${guests.length}</h2>
        <input id="gSearch" placeholder="Search name / phone / ID…" style="max-width:260px;"
          oninput="clearTimeout(window._gs);window._gs=setTimeout(()=>renderGuests(this.value),300)"
          value="${esc(q||'')}"></div>
      <table style="margin-top:12px;"><thead><tr><th>Name</th><th>Phone</th>
        <th>Email</th><th>ID</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table>
      <p class="muted" style="font-size:12px;">Saved automatically on check-in for faster returns.</p>
    </div>`;
  window._guests = guests;
}
function editGuest(id) {
  const g = (window._guests || []).find(x => x.id === id) || {};
  openModal(`
    <label>Full name</label><input id="egName" value="${esc(g.full_name||'')}">
    <div class="grid cols-2">
      <div><label>Phone</label><input id="egPhone" value="${esc(g.phone||'')}"></div>
      <div><label>Email</label><input id="egEmail" value="${esc(g.email||'')}"></div>
    </div>
    <label>ID / Passport</label><input id="egId" value="${esc(g.id_number||'')}">
    <label>Address</label><textarea id="egAddr">${esc(g.address||'')}</textarea>
    <label>Vehicle reg</label><input id="egVeh" value="${esc(g.vehicle_reg||'')}">
    <label>Notes</label><textarea id="egNotes">${esc(g.notes||'')}</textarea>
    <div class="row end" style="margin-top:16px;">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" onclick="saveGuest(${id})">Save</button>
    </div>`, { title: 'Edit guest', icon: '👤', iconClass: 'blue' });
}
async function saveGuest(id) {
  const body = {
    full_name: document.getElementById('egName').value.trim(),
    phone: document.getElementById('egPhone').value.trim(),
    email: document.getElementById('egEmail').value.trim(),
    id_number: document.getElementById('egId').value.trim(),
    address: document.getElementById('egAddr').value.trim(),
    vehicle_reg: document.getElementById('egVeh').value.trim(),
    notes: document.getElementById('egNotes').value.trim(),
  };
  if (!body.full_name) { toast('Name required'); return; }
  await api('/api/guests/' + id, { method: 'PUT', body: JSON.stringify(body) });
  closeModal(); toast('Saved'); renderGuests();
}
function delGuest(id) {
  const g = (window._guests || []).find(x => x.id === id) || {};
  confirmModal({
    title: 'Delete guest record',
    icon: '🗑', iconClass: 'red',
    message: `Delete the record for <b>${esc(g.full_name || 'this guest')}</b>? This can't be undone.`,
    okText: 'Delete', okClass: 'red',
    onOk: async () => {
      try {
        await api('/api/guests/' + id, { method: 'DELETE' });
        closeModal(); toast('Guest deleted'); renderGuests();
      } catch (e) { toast(e.message); closeModal(); }
    },
  });
}

/* ============================== QR TAB ============================== */
async function renderQR() {
  const el = document.getElementById('tab-qr');
  ROOMS = await api('/api/rooms');
  const roomCards = ROOMS.map(r => `
    <div class="card qr-box">
      <h3>${esc(r.room_number)}${r.room_name ? ' · ' + esc(r.room_name) : ''}</h3>
      <img src="/api/qr/room/${encodeURIComponent(r.room_code)}.png">
      <div class="row end" style="justify-content:center;margin-top:10px;">
        <a class="btn ghost sm" href="/api/qr/room/${encodeURIComponent(r.room_code)}.png"
           download="room-${esc(r.room_number)}-qr.png">Download</a>
      </div>
    </div>`).join('');

  el.innerHTML = `
    <div class="grid cols-2">
      <div class="card qr-box">
        <h2 style="text-align:left;">Arrival check-in QR</h2>
        <p class="muted" style="text-align:left;font-size:13px;">
          Display at reception / entrance. Guests scan to fill in their details.</p>
        <img src="/api/qr/checkin.png">
        <div class="url">${location.origin}/checkin</div>
        <div class="row end" style="justify-content:center;margin-top:10px;">
          <a class="btn ghost sm" href="/api/qr/checkin.png" download="checkin-qr.png">Download</a>
        </div>
      </div>
      <div class="card">
        <h2>Tip</h2>
        <p class="muted" style="font-size:14px;">If your public URL differs from this device's
          address, set it under <b>Settings → Public URL</b> so QR links point to the right domain
          (e.g. your Cloudflare tunnel).</p>
      </div>
    </div>
    <h2 class="muted" style="margin:26px 0 12px;">Per-room QR codes</h2>
    <div class="grid cols-3">${roomCards || '<div class="empty">Add rooms to generate their QR codes</div>'}</div>`;
}

/* =========================== SETTINGS TAB =========================== */
async function renderSettings() {
  const el = document.getElementById('tab-settings');
  const s = await api('/api/settings');
  const f = (id, v) => `value="${esc(v||'')}"`;
  el.innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h2>Hotel details</h2>
        <label>Hotel name</label><input id="sName" ${f('',s.hotel_name)}>
        <label>Address</label><textarea id="sAddr">${esc(s.address||'')}</textarea>
        <label>Public URL (for QR links, e.g. Cloudflare tunnel)</label>
        <input id="sUrl" placeholder="https://guestiq.yourdomain.co.za" ${f('',s.public_url)}>
        <label>Reception phone</label><input id="sRec" ${f('',s.reception_phone)}>
        <label>Emergency number</label><input id="sEmg" ${f('',s.emergency_number)}>
        <label>Welcome message (shown to guests)</label>
        <textarea id="sWelcome">${esc(s.welcome_message||'')}</textarea>
        <label>Default checkout time</label><input id="sCheckout" ${f('',s.checkout_time)}>
      </div>
      <div class="card">
        <h2>Dining</h2>
        <label>Restaurant name</label><input id="sResName" ${f('',s.restaurant_name)}>
        <label>Restaurant phone</label><input id="sResPhone" ${f('',s.restaurant_phone)}>
        <label>Online menu URL</label><input id="sMenu" placeholder="https://…" ${f('',s.menu_url)}>
        <p class="muted" style="font-size:12px;margin-top:4px;">
          Opened by the &ldquo;View Menu&rdquo; button on the room QR page.
          <b>https://</b> is added automatically if you leave it off.</p>
        <div class="row end" style="margin-top:18px;">
          <button class="btn" onclick="saveSettings()">Save settings</button>
        </div>
        <hr style="border:none;border-top:1px solid var(--border);margin:22px 0;">
        <h2>Change admin password</h2>
        <label>New password</label><input id="sNewPw" type="password">
        <div class="row end" style="margin-top:12px;">
          <button class="btn ghost" onclick="changePw()">Update password</button>
        </div>
      </div>
      <div class="card">
        <h2>Overdue checkout alerts</h2>
        <p class="muted" style="margin-top:0;font-size:13px;">
          Reception is notified when a guest is still in-house past their
          check-out time. Alerts also raise a notification in Home Assistant
          when the Automation tab is connected.</p>
        <label style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" id="sOverdueOn" style="width:auto;"
            ${s.overdue_alerts_enabled ? 'checked' : ''}> Notify on overdue check-outs
        </label>
        <div class="grid cols-2">
          <div><label>Grace period (minutes)</label>
            <input id="sGrace" type="number" min="0" value="${s.overdue_grace_minutes == null ? 15 : s.overdue_grace_minutes}"></div>
          <div><label>Re-notify every (hours, 0 = once)</label>
            <input id="sRepeat" type="number" min="0" value="${s.overdue_repeat_hours == null ? 6 : s.overdue_repeat_hours}"></div>
        </div>
        <label>Time zone offset from UTC (minutes)</label>
        <input id="sTz" type="number" value="${s.tz_offset_minutes == null ? 120 : s.tz_offset_minutes}">
        <p class="muted" style="font-size:12px;margin-top:4px;">
          120 = UTC+2 (South Africa). This is what check-in / check-out times are
          stamped and compared in.</p>
        <div class="row end" style="margin-top:12px;">
          <button class="btn ghost" onclick="scanOverdueNow()">Check for overdue now</button>
        </div>
      </div>
      <div class="card">
        <h2>Room QR access</h2>
        <label style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" id="sLockQr" style="width:auto;"
            ${s.room_lock_on_checkout ? 'checked' : ''}> Lock room QR codes on check-out
        </label>
        <p class="muted" style="font-size:12px;margin-top:6px;">
          Once the guest checks out, scanning the room QR no longer shows Wi-Fi,
          the bar / restaurant menu or stay details — it shows a "see reception"
          message instead. The printed code keeps working for the next guest.</p>
        <label>Grace period after check-out (minutes)</label>
        <input id="sLockGrace" type="number" min="0" value="${s.room_lock_grace_minutes == null ? 0 : s.room_lock_grace_minutes}">
        <label>Message shown on a locked room page</label>
        <textarea id="sLockMsg">${esc(s.room_lock_message || '')}</textarea>
        <div class="row end" style="margin-top:12px;">
          <button class="btn" onclick="saveSettings()">Save settings</button>
        </div>
      </div>
    </div>`;
}
async function scanOverdueNow() {
  try {
    const r = await api('/api/alerts/scan', { method: 'POST' });
    toast(r.overdue
      ? `${r.overdue} overdue · ${r.notified} new alert(s)`
      : 'No overdue check-outs');
  } catch (e) { toast(e.message); }
}
async function saveSettings() {
  const body = {
    hotel_name: document.getElementById('sName').value,
    address: document.getElementById('sAddr').value,
    public_url: document.getElementById('sUrl').value.trim(),
    reception_phone: document.getElementById('sRec').value,
    emergency_number: document.getElementById('sEmg').value,
    welcome_message: document.getElementById('sWelcome').value,
    checkout_time: document.getElementById('sCheckout').value,
    restaurant_name: document.getElementById('sResName').value,
    restaurant_phone: document.getElementById('sResPhone').value,
    menu_url: document.getElementById('sMenu').value.trim(),
    tz_offset_minutes: parseInt(document.getElementById('sTz').value || '120', 10),
    overdue_alerts_enabled: document.getElementById('sOverdueOn').checked,
    overdue_grace_minutes: parseInt(document.getElementById('sGrace').value || '0', 10),
    overdue_repeat_hours: parseInt(document.getElementById('sRepeat').value || '0', 10),
    room_lock_on_checkout: document.getElementById('sLockQr').checked,
    room_lock_grace_minutes: parseInt(document.getElementById('sLockGrace').value || '0', 10),
    room_lock_message: document.getElementById('sLockMsg').value,
  };
  await api('/api/settings', { method: 'PUT', body: JSON.stringify(body) });
  toast('Settings saved');
}
async function changePw() {
  const pw = document.getElementById('sNewPw').value;
  if (pw.length < 4) { toast('Password too short'); return; }
  await api('/api/settings/password', { method: 'POST', body: JSON.stringify({ new_password: pw }) });
  document.getElementById('sNewPw').value = '';
  toast('Password updated');
}

/* ============================ UPDATES TAB ============================ */
async function checkUpdatesQuietly() {
  try {
    const u = await api('/api/update/check');
    const btn = document.getElementById('updateBtn');
    if (u.update_available) {
      btn.innerHTML = `<span class="update-dot"></span>Update to v${u.remote}`;
      btn.classList.add('has-update');
      setNavBadge('updates', 1);
    } else {
      btn.textContent = 'Up to date';
      btn.classList.remove('has-update');
      setNavBadge('updates', 0);
    }
  } catch (e) {}
}
async function renderUpdates() {
  const el = document.getElementById('tab-updates');
  el.innerHTML = '<div class="empty">Checking for updates…</div>';
  let u;
  try { u = await api('/api/update/check'); }
  catch (e) { el.innerHTML = `<div class="card"><p class="muted">Could not reach the update server. Check this machine's internet connection and try again.</p>
      <button class="btn ghost sm" style="margin-top:10px;" onclick="renderUpdates()">Retry</button></div>`; return; }

  el.innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h2>Version</h2>
        <p style="font-size:15px;">Installed: <b>v${u.local}</b></p>
        <p style="font-size:15px;">Latest on ${esc(u.source || 'AR Smart server')}:
          <b>${u.remote ? 'v'+u.remote : 'unknown'}</b></p>
        ${u.update_available ? `
          <div class="row" style="margin-top:12px;">
            <button class="btn green" onclick="applyUpdate('${esc(u.local)}','${esc(u.remote)}')">Update now</button>
            <button class="btn ghost" onclick="renderUpdates()">Re-check</button>
          </div>` : `
          <p style="color:var(--green);font-weight:600;">✓ You're on the latest version.</p>
          <button class="btn ghost sm" onclick="renderUpdates()">Re-check</button>`}
      </div>
      <div class="card">
        <h2>${u.update_available ? "What's new" : 'Update channel'}</h2>
        <pre style="white-space:pre-wrap;font-family:inherit;color:var(--muted);font-size:13px;margin:0;">${
          esc(u.remote_changelog || 'GuestIQ checks the ' + (u.source || 'AR Smart server') +
             ' for a newer release, then downloads it and rebuilds itself automatically.')}</pre>
      </div>
    </div>`;
}

/* ---------------------- live update progress ---------------------- */
const UP_STEPS = [
  { id: 'queue', label: 'Queue update request' },
  { id: 'watcher', label: 'Update service picks it up' },
  { id: 'rebuild', label: 'Download latest & rebuild' },
  { id: 'verify', label: 'Service back online — verify version' },
];
let _up = null;

function applyUpdate(fromVer, toVer) {
  confirmModal({
    title: `Update to v${toVer}`,
    icon: '⬆', iconClass: 'green',
    message: `Download <b>v${toVer}</b> from the AR Smart server and rebuild?
      The service restarts briefly and this page reloads automatically when done.`,
    okText: 'Start update', okClass: 'green',
    onOk: async () => { closeModal(); startUpdateFlow(fromVer, toVer); },
  });
}

function upUI() {
  const root = document.getElementById('updateOverlayRoot');
  root.innerHTML = `
    <div class="up-overlay">
      <div class="up-card">
        <div class="up-head">
          <div class="up-spin" id="upSpin">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
              stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a9 9 0 1 1-6.2-8.56"/></svg>
          </div>
          <div>
            <h3 id="upTitle">Updating GuestIQ…</h3>
            <p id="upSub">v${esc(_up.from)} → v${esc(_up.to)}</p>
          </div>
        </div>
        <div class="progress"><div class="bar" id="upBar"></div></div>
        <div class="up-pct"><span id="upPhase">Starting…</span><span id="upPct">0%</span></div>
        <div class="up-steps" id="upSteps">
          ${UP_STEPS.map(s => `
            <div class="up-step" id="upStep-${s.id}"><span class="dot"></span>${s.label}</div>`).join('')}
        </div>
        <div class="up-log" id="upLog"></div>
        <div class="up-foot row end" id="upFoot"></div>
      </div>
    </div>`;
}
function upLog(msg, cls) {
  const el = document.getElementById('upLog');
  if (!el) return;
  const t = new Date().toTimeString().slice(0, 8);
  el.innerHTML += `<span class="${cls || ''}">[${t}] ${esc(msg)}</span>\n`;
  el.scrollTop = el.scrollHeight;
}
function upSetProgress(pct, phase) {
  const bar = document.getElementById('upBar');
  if (bar) bar.style.width = Math.min(pct, 100) + '%';
  const p = document.getElementById('upPct');
  if (p) p.textContent = Math.round(Math.min(pct, 100)) + '%';
  if (phase) {
    const ph = document.getElementById('upPhase');
    if (ph) ph.textContent = phase;
  }
}
function upStep(id, state) { // 'active' | 'done'
  const el = document.getElementById('upStep-' + id);
  if (!el) return;
  el.classList.remove('active', 'done');
  if (state) el.classList.add(state);
}
function upCreep(from, to, ms) {
  // slowly creep the bar between phase bounds while we wait
  clearInterval(_up.creep);
  let pct = from;
  const stepAmt = (to - from) / (ms / 400);
  _up.creep = setInterval(() => {
    pct = Math.min(pct + stepAmt, to);
    upSetProgress(pct);
  }, 400);
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function startUpdateFlow(fromVer, toVer) {
  _up = { from: fromVer, to: toVer, creep: null, cancelled: false };
  upUI();

  try {
    /* ---- Phase 1: queue ---- */
    upStep('queue', 'active');
    upSetProgress(3, 'Queuing update request');
    upLog('Requesting update via API…');
    const r = await api('/api/update/apply', { method: 'POST' });
    _up.manual = r.manual_command || '';
    upLog('Update queued — waiting for the update service.', 'ok');
    upStep('queue', 'done');

    /* ---- Phase 2: wait for watcher to consume the flag ---- */
    upStep('watcher', 'active');
    upSetProgress(10, 'Waiting for the update service (checks every 30s)');
    upCreep(10, 34, 40000);
    const t0 = Date.now();
    let picked = false, warned = false;
    while (!picked) {
      await sleep(3000);
      try {
        const st = await api('/api/update/status');
        if (!st.flag_pending) { picked = true; break; }
      } catch (e) {
        // container may already be restarting — treat as picked up
        picked = true; break;
      }
      const secs = Math.round((Date.now() - t0) / 1000);
      if (secs > 45 && !warned) {
        warned = true;
        upLog('Still waiting… the update service polls every 30s, hang tight.', 'warn');
      }
      if (secs > 180) {
        return upFail('The update service never picked up the request. ' +
          'Check that the GuestIQ update service is running on this server.');
      }
    }
    clearInterval(_up.creep);
    upLog('Request picked up — downloading & rebuilding.', 'ok');
    upStep('watcher', 'done');

    /* ---- Phase 3: rebuild — poll health, expect downtime ---- */
    upStep('rebuild', 'active');
    upSetProgress(38, 'Downloading latest & rebuilding');
    upCreep(38, 84, 90000);
    const t1 = Date.now();
    let wentDown = false, newVer = null;
    while (true) {
      await sleep(2500);
      let h = null;
      try {
        const resp = await fetch('/api/health', { cache: 'no-store' });
        if (resp.ok) h = await resp.json();
      } catch (e) { /* down */ }
      if (!h) {
        if (!wentDown) { wentDown = true; upLog('Service restarting…'); }
      } else {
        if (wentDown) upLog('Service is back online.', 'ok');
        if (h.version && h.version !== fromVer) { newVer = h.version; break; }
        // no downtime observed yet but version already changed
        if (h.version && h.version === toVer) { newVer = h.version; break; }
      }
      if (Date.now() - t1 > 5 * 60 * 1000) {
        return upFail('The rebuild is taking longer than 5 minutes. It may still ' +
          'finish in the background — check the update service logs on this server.');
      }
    }
    clearInterval(_up.creep);
    upStep('rebuild', 'done');

    /* ---- Phase 4: verify + reload ---- */
    upStep('verify', 'active');
    upSetProgress(92, 'Verifying new version');
    upLog(`Now running v${newVer}.`, 'ok');
    await sleep(800);
    upStep('verify', 'done');
    upSetProgress(100, 'Update complete');
    const bar = document.getElementById('upBar'); if (bar) bar.classList.add('done');
    const spin = document.getElementById('upSpin');
    if (spin) {
      spin.classList.add('done');
      spin.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    }
    const title = document.getElementById('upTitle');
    if (title) title.textContent = `Updated to v${newVer}`;
    upLog('Reloading in 3 seconds…');
    let n = 3;
    const foot = document.getElementById('upFoot');
    foot.innerHTML = `<button class="btn green" onclick="location.reload()">Reload now</button>`;
    const cd = setInterval(() => {
      n--; if (n <= 0) { clearInterval(cd); location.reload(); }
    }, 1000);

  } catch (e) {
    upFail(e.message || 'Update failed');
  }
}

function upFail(msg) {
  clearInterval(_up && _up.creep);
  upLog(msg, 'warn');
  const bar = document.getElementById('upBar'); if (bar) bar.classList.add('err');
  const spin = document.getElementById('upSpin');
  if (spin) {
    spin.classList.add('err');
    spin.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
  }
  const title = document.getElementById('upTitle');
  if (title) title.textContent = 'Update did not complete';
  const ph = document.getElementById('upPhase');
  if (ph) ph.textContent = 'Stopped';
  const foot = document.getElementById('upFoot');
  if (foot) foot.innerHTML = `
    ${_up && _up.manual ? `<button class="btn ghost" onclick="upShowManual()">Manual command</button>` : ''}
    <button class="btn" onclick="upClose()">Close</button>`;
}
function upShowManual() {
  upLog('Run on the host: ' + (_up.manual || 'git pull && docker compose up -d --build'));
}
function upClose() {
  clearInterval(_up && _up.creep);
  document.getElementById('updateOverlayRoot').innerHTML = '';
  renderUpdates();
}

/* ============================== boot ============================== */
(async function boot() {
  if (TOKEN) {
    try { await api('/api/version'); showApp(); }
    catch (e) { logoutLocal(); }
  }
})();


/* ------------------------------ automation ------------------------------ */
async function renderAutomation() {
  const el = document.getElementById('tab-automation');
  let a;
  try {
    a = await api('/api/automation');
  } catch (e) {
    el.innerHTML = `<div class="card"><h2>Automation</h2>
      <p class="muted">Could not load automation settings: ${esc(e.message)}</p>
      <p class="muted" style="font-size:13px;">The backend may still be on an
      older version — make sure the container was rebuilt after updating
      (backend/main.py, backend/database.py, backend/ha_sync.py) and that
      httpx installed (requirements.txt).</p>
      <button class="btn ghost" onclick="renderAutomation()">Retry</button></div>`;
    return;
  }
  el.innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h2>Home Assistant connection</h2>
        <p class="muted" style="margin-top:0;font-size:13px;">
          When a guest is checked in, their room's geyser (and any other
          automations) switch on in Home Assistant. Check-out switches them back.
        </p>
        <label style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" id="haEnabled" ${a.ha_enabled ? 'checked' : ''}
                 style="width:auto;"> Enable Home Assistant sync
        </label>
        <label>Home Assistant URL (IP or hostname, with port)</label>
        <input id="haUrl" placeholder="http://192.168.1.50:8123" value="${esc(a.ha_url || '')}">
        <label>Long-lived access token</label>
        <input id="haToken" type="password" placeholder="Paste token from HA"
               value="${esc(a.ha_token || '')}">
        <p class="muted" style="font-size:12px;margin-top:4px;">
          In HA: click your user name (bottom left) → Security →
          Long-lived access tokens → Create token. Paste it here.
        </p>
        <label>Webhook ID (fallback, only used if no token)</label>
        <input id="haWebhook" placeholder="ar_smart_loadmanager_xxxxxxxx" value="${esc(a.ha_webhook_id || '')}">
        <div class="row end" style="margin-top:14px;gap:8px;">
          <button class="btn ghost" onclick="testAutomation()">Test connection</button>
          <button class="btn" onclick="saveAutomation()">Save</button>
        </div>
        <p class="muted" id="haStatus" style="min-height:18px;font-size:13px;"></p>
      </div>
      <div class="card">
        <h2>Room mapping & sync</h2>
        <label>Room name prefix sent to HA</label>
        <input id="haPrefix" value="${esc(a.ha_room_prefix == null ? 'Room ' : a.ha_room_prefix)}">
        <p class="muted" style="font-size:12px;margin-top:4px;">
          GuestIQ room 3 → "Room 3" in Home Assistant. Must match the room
          names configured in the Load Manager.
        </p>
        <label style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" id="haUseName" ${a.ha_use_room_name ? 'checked' : ''}
                 style="width:auto;"> Use the room's name instead of its number
        </label>
        <label>Full sync interval (minutes, 0 = off)</label>
        <input id="haMins" type="number" min="0" value="${a.ha_sync_minutes == null ? 15 : a.ha_sync_minutes}">
        <p class="muted" style="font-size:12px;margin-top:4px;">
          Pushes every room's occupancy on a timer so a missed event
          self-heals automatically.
        </p>
        <div class="row end" style="margin-top:14px;">
          <button class="btn ghost" onclick="syncAutomationNow()">Sync all rooms now</button>
        </div>
      </div>
    </div>`;
}

function _autoBody() {
  return {
    ha_enabled: document.getElementById('haEnabled').checked,
    ha_url: document.getElementById('haUrl').value.trim(),
    ha_webhook_id: document.getElementById('haWebhook').value.trim(),
    ha_token: document.getElementById('haToken').value.trim(),
    ha_room_prefix: document.getElementById('haPrefix').value,
    ha_use_room_name: document.getElementById('haUseName').checked,
    ha_sync_minutes: parseInt(document.getElementById('haMins').value || '15', 10),
  };
}

async function saveAutomation() {
  try {
    await api('/api/automation', { method: 'PUT', body: JSON.stringify(_autoBody()) });
    toast('Automation settings saved');
  } catch (e) { toast(e.message); }
}

async function testAutomation() {
  const st = document.getElementById('haStatus');
  st.textContent = 'Saving & testing…';
  try {
    await api('/api/automation', { method: 'PUT', body: JSON.stringify(_autoBody()) });
    const r = await api('/api/automation/test', { method: 'POST' });
    st.textContent = r.message;
    st.style.color = r.ok ? 'var(--green, #3fb950)' : 'var(--red)';
  } catch (e) {
    st.textContent = e.message; st.style.color = 'var(--red)';
  }
}

async function syncAutomationNow() {
  try {
    const r = await api('/api/automation/sync', { method: 'POST' });
    toast(r.message);
  } catch (e) { toast(e.message); }
}
