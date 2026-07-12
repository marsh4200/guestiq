/* ============================ GuestIQ admin ============================ */
let TOKEN = localStorage.getItem('giq_token') || '';
let ROOMS = [];

function esc(s) {
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
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

/* ------------------------------ shell ------------------------------ */
async function showApp() {
  document.getElementById('loginScreen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
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

const TABS = ['checkins', 'rooms', 'guests', 'qr', 'automation', 'settings', 'updates'];
function switchTab(name) {
  TABS.forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('hidden', t !== name);
  });
  document.querySelectorAll('.tab').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === name));
  const fn = { checkins: renderCheckins, rooms: renderRooms, guests: renderGuests,
    qr: renderQR, automation: renderAutomation, settings: renderSettings,
    updates: renderUpdates }[name];
  if (fn) fn();
}

/* modal helper */
function openModal(html) {
  document.getElementById('modalRoot').innerHTML =
    `<div class="overlay" onclick="if(event.target===this)closeModal()"><div class="modal">${html}</div></div>`;
}
function closeModal() { document.getElementById('modalRoot').innerHTML = ''; }

/* ========================== CHECK-INS TAB ========================== */
async function renderCheckins() {
  const el = document.getElementById('tab-checkins');
  el.innerHTML = '<div class="empty">Loading…</div>';
  const [pending, active] = await Promise.all([
    api('/api/stays?status=pending'),
    api('/api/stays?status=checked_in'),
  ]);
  ROOMS = await api('/api/rooms');

  const pendingRows = pending.length ? pending.map(s => `
    <tr>
      <td><b>${esc(s.full_name)}</b><br><span class="muted" style="font-size:12px;">
        ${esc(s.phone || s.email || '')}</span></td>
      <td>${esc(s.id_number || '—')}</td>
      <td>${s.num_guests || 1}</td>
      <td class="muted" style="font-size:12px;">${esc((s.created_at||'').replace('T',' '))}</td>
      <td class="row end">
        <button class="btn green sm" onclick="openAssign(${s.id})">Assign room</button>
        <button class="btn ghost sm" onclick="cancelStay(${s.id})">✕</button>
      </td>
    </tr>`).join('') : `<tr><td colspan="5" class="empty">No pending check-ins</td></tr>`;

  const activeRows = active.length ? active.map(s => `
    <tr>
      <td><b>${esc(s.full_name)}</b></td>
      <td>${s.room_number ? esc(s.room_number) + (s.room_name ? ' · ' + esc(s.room_name) : '') : '—'}</td>
      <td>${esc((s.check_in_at||'').replace('T',' ').slice(0,16))}</td>
      <td>${esc((s.check_out_at||'').replace('T',' ').slice(0,16))}</td>
      <td class="row end">
        <button class="btn amber sm" onclick="checkoutStay(${s.id})">Check out</button>
      </td>
    </tr>`).join('') : `<tr><td colspan="5" class="empty">No active guests</td></tr>`;

  el.innerHTML = `
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
          <th>Checked in</th><th>Checkout</th><th></th></tr></thead>
          <tbody>${activeRows}</tbody></table>
      </div>
    </div>`;
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

function openAssign(stayId) {
  if (!ROOMS.some(r => r.status === 'available')) {
    toast('No available rooms — add or free one up first');
  }
  openModal(`
    <h3>Assign room</h3>
    <label>Room</label>
    <select id="asRoom">${roomOptions(null)}</select>
    <label>Check-out (how long they stay)</label>
    <input id="asOut" type="datetime-local" value="${defaultCheckout()}">
    <div class="row end" style="margin-top:16px;">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn green" onclick="submitAssign(${stayId})">Check in guest</button>
    </div>`);
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
  } catch (e) { toast(e.message); }
}

function openManualStay() {
  openModal(`
    <h3>Manual check-in</h3>
    <label>Full name *</label><input id="mName">
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
    </div>`);
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
      room_id, check_out_at: out,
      num_guests: parseInt(document.getElementById('mPax').value || '1', 10),
    })});
    closeModal(); toast('Checked in'); renderCheckins();
  } catch (e) { toast(e.message); }
}

async function checkoutStay(id) {
  if (!confirm('Check out this guest and free the room?')) return;
  await api(`/api/stays/${id}/checkout`, { method: 'POST' });
  toast('Checked out'); renderCheckins();
}
async function cancelStay(id) {
  if (!confirm('Cancel this pending check-in?')) return;
  await api(`/api/stays/${id}/cancel`, { method: 'POST' });
  renderCheckins();
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
    <h3>${id ? 'Edit' : 'Add'} room</h3>
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
    </div>`);
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
async function delRoom(id) {
  if (!confirm('Delete this room?')) return;
  await api('/api/rooms/' + id, { method: 'DELETE' });
  renderRooms();
}
function showRoomQR(code, num) {
  const url = location.origin + '/room/' + code;
  openModal(`
    <h3>Room ${esc(num)} — guest QR</h3>
    <div class="qr-box">
      <img src="/api/qr/room/${encodeURIComponent(code)}.png" alt="QR">
      <div class="url">${esc(url)}</div>
    </div>
    <p class="muted" style="font-size:13px;">Print this and place it in the room. Scanning shows
      Wi-Fi, restaurant, menu and contacts.</p>
    <div class="row end">
      <a class="btn ghost" href="/api/qr/room/${encodeURIComponent(code)}.png" download="room-${esc(num)}-qr.png">Download PNG</a>
      <button class="btn" onclick="closeModal()">Close</button>
    </div>`);
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
    <h3>Edit guest</h3>
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
    </div>`);
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
async function delGuest(id) {
  if (!confirm('Delete this guest record?')) return;
  await api('/api/guests/' + id, { method: 'DELETE' });
  renderGuests();
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
    </div>`;
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
    } else {
      btn.textContent = 'Up to date';
    }
  } catch (e) {}
}
async function renderUpdates() {
  const el = document.getElementById('tab-updates');
  el.innerHTML = '<div class="empty">Checking for updates…</div>';
  let u;
  try { u = await api('/api/update/check'); }
  catch (e) { el.innerHTML = `<div class="card"><p class="muted">Could not reach GitHub to check for updates.</p></div>`; return; }

  el.innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h2>Version</h2>
        <p style="font-size:15px;">Installed: <b>v${u.local}</b></p>
        <p style="font-size:15px;">Latest on GitHub: <b>${u.remote ? 'v'+u.remote : 'unknown'}</b></p>
        <p class="muted" style="font-size:13px;">Repo: ${esc(u.repo)} · ${esc(u.branch)}</p>
        ${u.update_available ? `
          <div class="row" style="margin-top:12px;">
            <button class="btn green" onclick="applyUpdate()">Update now</button>
            <button class="btn ghost" onclick="renderUpdates()">Re-check</button>
          </div>` : `
          <p style="color:var(--green);font-weight:600;">✓ You're on the latest version.</p>
          <button class="btn ghost sm" onclick="renderUpdates()">Re-check</button>`}
      </div>
      <div class="card">
        <h2>${u.update_available ? "What's new" : 'Update channel'}</h2>
        <pre style="white-space:pre-wrap;font-family:inherit;color:var(--muted);font-size:13px;margin:0;">${
          esc(u.remote_changelog || 'The updater checks GitHub for a newer VERSION and pulls it via the host watcher, then rebuilds the container.')}</pre>
      </div>
    </div>`;
}
async function applyUpdate() {
  if (!confirm('Pull the latest version and rebuild? The service will restart briefly.')) return;
  try {
    const r = await api('/api/update/apply', { method: 'POST' });
    toast(r.message || 'Update queued');
    openModal(`<h3>Update queued</h3>
      <p class="muted">${esc(r.message)}</p>
      <p class="muted" style="font-size:12.5px;">Manual fallback on the host:</p>
      <pre style="background:var(--panel-2);padding:12px;border-radius:10px;font-size:12px;overflow:auto;">${esc(r.manual_command)}</pre>
      <div class="row end"><button class="btn" onclick="closeModal()">OK</button></div>`);
  } catch (e) { toast(e.message); }
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
