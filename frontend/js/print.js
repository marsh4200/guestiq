/* ===================== GuestIQ printable room sheets =====================
   Opened from the QR tab. Pulls its data with the admin session token that
   the console already stored, so nothing here is reachable by a guest.      */

function esc(s) {
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const TOKEN = localStorage.getItem('giq_token') || '';
let DATA = null;
let MODE = 'rooms';        // rooms | room | checkin

function parseRoute() {
  const p = location.pathname;
  if (p.indexOf('/print/checkin') === 0) return { mode: 'checkin' };
  const m = p.match(/\/print\/room\/(.+)$/);
  if (m) return { mode: 'room', code: decodeURIComponent(m[1]) };
  return { mode: 'rooms' };
}

async function load() {
  const route = parseRoute();
  MODE = route.mode;
  if (!TOKEN) return fail('Open this from the GuestIQ console — you need to be signed in.');
  const url = route.mode === 'room'
    ? '/api/print/room/' + encodeURIComponent(route.code)
    : '/api/print/rooms';
  try {
    const r = await fetch(url, { headers: { 'X-Auth-Token': TOKEN } });
    if (r.status === 401) return fail('Your session has expired — sign in again and retry.');
    if (r.status === 403) return fail("Your account can't print room sheets. Ask an administrator to enable it.");
    if (!r.ok) return fail('Could not load the details for this sheet.');
    DATA = await r.json();
  } catch (e) {
    return fail('Could not reach the server.');
  }
  ['optQr', 'optInfo', 'optWifi'].forEach(id =>
    document.getElementById(id).addEventListener('change', render));
  render();
}

function fail(msg) {
  document.getElementById('tbTitle').textContent = 'Nothing to print';
  document.getElementById('sheets').innerHTML =
    `<div class="sheet"><p class="fail">${esc(msg)}</p></div>`;
}

/* ------------------------------ rendering ------------------------------ */
function opt(id) { return document.getElementById(id).checked; }

function header(h) {
  const initials = (h.hotel_name || 'GIQ').split(/\s+/)
    .map(w => w[0]).join('').slice(0, 3).toUpperCase();
  return `<div class="sh-head">
      <div class="sh-logo">${h.logo_url
        ? `<img src="${esc(h.logo_url)}" alt="">`
        : `<span>${esc(initials)}</span>`}</div>
      <div class="sh-name">
        <h1>${esc(h.hotel_name || 'Guest information')}</h1>
        ${h.address ? `<p>${esc(h.address)}</p>` : ''}
      </div>
    </div>`;
}

function row(label, value, big) {
  if (!value) return '';
  return `<div class="sh-row">
      <div class="sh-k">${esc(label)}</div>
      <div class="sh-v ${big ? 'big' : ''}">${esc(value)}</div>
    </div>`;
}

function qrBlock(src, caption, url) {
  return `<div class="sh-qr">
      <img src="${esc(src)}" alt="QR code">
      <div class="sh-qr-cap">${esc(caption)}</div>
      ${url ? `<div class="sh-qr-url">${esc(url)}</div>` : ''}
    </div>`;
}

function roomSheet(h, r) {
  const title = r.room_name
    ? `${r.room_number} · ${r.room_name}` : `Room ${r.room_number}`;

  const info = [
    row('Wi-Fi network', r.wifi_ssid, true),
    opt('optWifi') ? row('Wi-Fi password', r.wifi_password, true) : '',
    row('Check-out time', h.checkout_time),
    row('Reception', h.reception_phone, true),
    row(h.restaurant_name || 'Restaurant', h.restaurant_phone),
    row('Menu', h.menu_url),
    row('Emergency', h.emergency_number, true),
  ].join('');

  return `<div class="sheet">
      ${header(h)}
      <div class="sh-title">
        <h2>${esc(title)}</h2>
        ${r.floor ? `<span class="sh-floor">Floor ${esc(r.floor)}</span>` : ''}
      </div>
      ${h.welcome_message ? `<p class="sh-welcome">${esc(h.welcome_message)}</p>` : ''}
      <div class="sh-body ${opt('optQr') && opt('optInfo') ? '' : 'single'}">
        ${opt('optQr') ? qrBlock(r.qr_png,
            'Scan for Wi-Fi, menu and contact numbers', r.url) : ''}
        ${opt('optInfo') ? `<div class="sh-info">${info}
          ${r.description ? `<div class="sh-note"><b>Room notes</b><p>${esc(r.description)}</p></div>` : ''}
        </div>` : ''}
      </div>
      <div class="sh-foot">${esc(h.hotel_name || '')}${h.reception_phone
        ? ' · Reception ' + esc(h.reception_phone) : ''}</div>
    </div>`;
}

function checkinSheet(h, d) {
  return `<div class="sheet">
      ${header(h)}
      <div class="sh-title"><h2>Check in</h2></div>
      ${h.welcome_message ? `<p class="sh-welcome">${esc(h.welcome_message)}</p>` : ''}
      <div class="sh-body single">
        ${qrBlock(d.checkin_qr, 'Scan to check in', d.checkin_url)}
      </div>
      ${opt('optInfo') ? `<div class="sh-info wide">
        ${row('Reception', h.reception_phone, true)}
        ${row('Emergency', h.emergency_number, true)}
        ${row('Address', h.address)}
        <div class="sh-note"><b>Can't scan?</b>
          <p>Please give your details to reception and we'll check you in.</p></div>
      </div>` : ''}
      <div class="sh-foot">${esc(h.hotel_name || '')}</div>
    </div>`;
}

function render() {
  const h = DATA.hotel;
  let html = '';
  if (MODE === 'checkin') {
    html = checkinSheet(h, DATA);
    document.getElementById('tbTitle').textContent = 'Arrival check-in sheet';
  } else {
    html = DATA.rooms.map(r => roomSheet(h, r)).join('');
    document.getElementById('tbTitle').textContent = DATA.rooms.length === 1
      ? `Room ${DATA.rooms[0].room_number} sheet`
      : `${DATA.rooms.length} room sheets`;
    if (!DATA.rooms.length) {
      html = '<div class="sheet"><p class="fail">No rooms to print yet.</p></div>';
    }
  }
  document.getElementById('sheets').innerHTML = html;
}

load();
