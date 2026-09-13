function esc(s) {
  return (s || '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* line icons (replacing emoji glyphs) */
const RICON = {
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
  phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0Z"/><circle cx="12" cy="10" r="3"/></svg>',
  wifi: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>',
  key: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="7.5" cy="15.5" r="5.5"/><path d="M21 2 11.4 11.6"/><path d="M15.5 7.5l3 3L22 7l-3-3"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  calendar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/></svg>',
  utensils: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v7c0 1.1.9 2 2 2h1a2 2 0 0 0 2-2V2"/><path d="M6 11v11"/><path d="M18 2c-1.1 0-2 1.79-2 4v5a2 2 0 0 0 2 2v9"/></svg>',
  doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>',
};

/* a link without a scheme resolves relative to /room/<code> and lands the
   guest on "this code is invalid" — always give it one */
function safeUrl(u) {
  const v = (u || '').trim();
  if (!v) return '';
  if (/^(https?:\/\/|mailto:|tel:)/i.test(v)) return v;
  if (v.startsWith('/')) return v;
  return 'https://' + v.replace(/^\/+/, '');
}

function infoRow(icon, label, value, opts = {}) {
  if (!value) return '';
  const mono = opts.mono ? ' mono' : '';
  const copy = opts.copy
    ? `<button class="copy-btn" data-copy="${esc(value)}">Copy</button>` : '';
  return `<div class="info-row">
      <div class="info-ico">${icon}</div>
      <div style="flex:1;min-width:0;">
        <div class="lbl">${esc(label)}</div>
        <div class="val${mono}">${esc(value)}</div>
      </div>${copy}
    </div>`;
}

async function load() {
  const code = decodeURIComponent(location.pathname.split('/room/')[1] || '');
  try {
    const r = await fetch('/api/room/' + encodeURIComponent(code));
    if (!r.ok) throw new Error('nf');
    const d = await r.json();
    render(d);
  } catch (e) {
    document.getElementById('hotelName').textContent = 'Room not found';
    document.getElementById('roomLine').textContent =
      'This code is invalid. Please contact reception.';
  }
}

function paintLogo(h) {
  const el = document.getElementById('logo');
  if (!el) return;
  const initials = (h.hotel_name || 'GIQ').split(/\s+/)
    .map(w => w[0]).join('').slice(0, 3).toUpperCase() || 'GIQ';
  el.textContent = '';
  if (h.logo_url) {
    el.classList.add('has-img');
    const img = new Image();
    img.alt = h.hotel_name || '';
    img.onerror = () => { el.classList.remove('has-img'); el.textContent = initials; };
    img.src = h.logo_url;
    el.appendChild(img);
  } else {
    el.classList.remove('has-img');
    el.textContent = initials;
  }
}

function render(d) {
  const h = d.hotel, room = d.room;
  document.getElementById('hotelName').textContent = h.hotel_name || 'Your Room';
  paintLogo(h);
  const rn = room.room_name ? `${room.room_number} · ${room.room_name}` : `Room ${room.room_number}`;
  document.getElementById('roomLine').textContent = rn + (room.floor ? ` · Floor ${room.floor}` : '');

  /* ---- locked: the stay has ended, this QR no longer hands anything out ---- */
  if (d.locked) {
    let lk = `<div class="g-card locked-card">
        <div class="lock-ico">${RICON.lock}</div>
        <h3 style="margin:0 0 6px;">Stay ended</h3>
        <p style="margin:0;color:#3a4763;font-size:15px;">
          ${esc(h.locked_message || 'Please contact reception.')}</p>
      </div>`;
    let c = '';
    c += infoRow(RICON.phone, 'Reception', h.reception_phone, { copy: !!h.reception_phone });
    c += infoRow(RICON.alert, 'Emergency', h.emergency_number, { copy: !!h.emergency_number });
    c += infoRow(RICON.pin, 'Address', h.address);
    if (c) lk += `<div class="g-card"><h3 style="margin:0 0 4px;">Contact</h3>${c}</div>`;
    const calls = [];
    if (h.reception_phone) calls.push(`<a href="tel:${esc(h.reception_phone)}">${RICON.phone} Call reception</a>`);
    if (calls.length) lk += `<div class="g-actions">${calls.join('')}</div>`;
    document.getElementById('body').innerHTML = lk;
    bindCopy();
    return;
  }

  let html = '';

  if (h.welcome_message) {
    html += `<div class="g-card"><p style="margin:0;color:#3a4763;font-size:15px;">
      ${esc(h.welcome_message)}</p></div>`;
  }

  // Wi-Fi
  let wifi = '';
  wifi += infoRow(RICON.wifi, 'Wi-Fi network', room.wifi_ssid);
  wifi += infoRow(RICON.key, 'Wi-Fi password', room.wifi_password, { mono: true, copy: true });
  if (wifi) html += `<div class="g-card"><h3 style="margin:0 0 4px;">Wi-Fi</h3>${wifi}</div>`;

  // Stay details
  let stay = '';
  if (d.occupant && d.occupant.check_in_at) {
    stay += infoRow(RICON.user, 'Checked in', d.occupant.check_in_at.replace('T', ' ').slice(0, 16));
  }
  if (d.occupant && d.occupant.check_out_at) {
    stay += infoRow(RICON.calendar, 'Checkout date',
      d.occupant.check_out_at.replace('T', ' ').slice(0, 16));
  }
  stay += infoRow(RICON.clock, 'Checkout time', h.checkout_time);
  if (stay) html += `<div class="g-card"><h3 style="margin:0 0 4px;">Your stay</h3>${stay}</div>`;

  // Dining
  let dine = '';
  dine += infoRow(RICON.utensils, h.restaurant_name || 'Restaurant', h.restaurant_phone,
    { copy: !!h.restaurant_phone });
  if (dine || h.menu_url) {
    html += `<div class="g-card"><h3 style="margin:0 0 4px;">Dining</h3>${dine}
      ${h.menu_url ? `<div class="g-actions" style="margin-top:12px;">
        <a href="${esc(safeUrl(h.menu_url))}" target="_blank" rel="noopener">${RICON.doc} View Menu</a>
        ${h.restaurant_phone ? `<a class="alt" href="tel:${esc(h.restaurant_phone)}">${RICON.phone} Call</a>` : ''}
      </div>` : ''}</div>`;
  }

  // Contacts
  let contact = '';
  contact += infoRow(RICON.phone, 'Reception', h.reception_phone, { copy: !!h.reception_phone });
  contact += infoRow(RICON.alert, 'Emergency', h.emergency_number, { copy: !!h.emergency_number });
  contact += infoRow(RICON.pin, 'Address', h.address);
  if (contact) html += `<div class="g-card"><h3 style="margin:0 0 4px;">Contact</h3>${contact}</div>`;

  if (room.description) {
    html += `<div class="g-card"><h3 style="margin:0 0 4px;">Room notes</h3>
      <p style="margin:0;color:#3a4763;">${esc(room.description)}</p></div>`;
  }

  // quick-call actions
  const calls = [];
  if (h.reception_phone) calls.push(`<a href="tel:${esc(h.reception_phone)}">${RICON.phone} Reception</a>`);
  if (h.restaurant_phone) calls.push(`<a class="alt" href="tel:${esc(h.restaurant_phone)}">${RICON.utensils} Restaurant</a>`);
  if (calls.length) html += `<div class="g-actions">${calls.join('')}</div>`;

  document.getElementById('body').innerHTML = html;
  bindCopy();
}

function bindCopy() {
  document.querySelectorAll('.copy-btn').forEach(b => {
    b.addEventListener('click', () => {
      navigator.clipboard.writeText(b.dataset.copy).then(() => {
        const t = b.textContent; b.textContent = 'Copied!';
        setTimeout(() => b.textContent = t, 1200);
      });
    });
  });
}

load();
