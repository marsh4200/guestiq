function esc(s) {
  return (s || '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

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

function render(d) {
  const h = d.hotel, room = d.room;
  document.getElementById('hotelName').textContent = h.hotel_name || 'Your Room';
  document.getElementById('logo').textContent =
    (h.hotel_name || 'GIQ').split(/\s+/).map(w => w[0]).join('').slice(0, 3).toUpperCase();
  const rn = room.room_name ? `${room.room_number} · ${room.room_name}` : `Room ${room.room_number}`;
  document.getElementById('roomLine').textContent = rn + (room.floor ? ` · Floor ${room.floor}` : '');

  /* ---- locked: the stay has ended, this QR no longer hands anything out ---- */
  if (d.locked) {
    let lk = `<div class="g-card locked-card">
        <div class="lock-ico">&#128274;</div>
        <h3 style="margin:0 0 6px;">Stay ended</h3>
        <p style="margin:0;color:#3a4763;font-size:15px;">
          ${esc(h.locked_message || 'Please contact reception.')}</p>
      </div>`;
    let c = '';
    c += infoRow('&#127976;', 'Reception', h.reception_phone, { copy: !!h.reception_phone });
    c += infoRow('&#128680;', 'Emergency', h.emergency_number, { copy: !!h.emergency_number });
    c += infoRow('&#128205;', 'Address', h.address);
    if (c) lk += `<div class="g-card"><h3 style="margin:0 0 4px;">Contact</h3>${c}</div>`;
    const calls = [];
    if (h.reception_phone) calls.push(`<a href="tel:${esc(h.reception_phone)}">&#128222; Call reception</a>`);
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
  wifi += infoRow('&#128246;', 'Wi-Fi network', room.wifi_ssid);
  wifi += infoRow('&#128273;', 'Wi-Fi password', room.wifi_password, { mono: true, copy: true });
  if (wifi) html += `<div class="g-card"><h3 style="margin:0 0 4px;">Wi-Fi</h3>${wifi}</div>`;

  // Stay details
  let stay = '';
  if (d.occupant && d.occupant.check_in_at) {
    stay += infoRow('&#128100;', 'Checked in', d.occupant.check_in_at.replace('T', ' ').slice(0, 16));
  }
  if (d.occupant && d.occupant.check_out_at) {
    stay += infoRow('&#128197;', 'Checkout date',
      d.occupant.check_out_at.replace('T', ' ').slice(0, 16));
  }
  stay += infoRow('&#9200;', 'Checkout time', h.checkout_time);
  if (stay) html += `<div class="g-card"><h3 style="margin:0 0 4px;">Your stay</h3>${stay}</div>`;

  // Dining
  let dine = '';
  dine += infoRow('&#127869;', h.restaurant_name || 'Restaurant', h.restaurant_phone,
    { copy: !!h.restaurant_phone });
  if (dine || h.menu_url) {
    html += `<div class="g-card"><h3 style="margin:0 0 4px;">Dining</h3>${dine}
      ${h.menu_url ? `<div class="g-actions" style="margin-top:12px;">
        <a href="${esc(safeUrl(h.menu_url))}" target="_blank" rel="noopener">&#128220; View Menu</a>
        ${h.restaurant_phone ? `<a class="alt" href="tel:${esc(h.restaurant_phone)}">&#128222; Call</a>` : ''}
      </div>` : ''}</div>`;
  }

  // Contacts
  let contact = '';
  contact += infoRow('&#127976;', 'Reception', h.reception_phone, { copy: !!h.reception_phone });
  contact += infoRow('&#128680;', 'Emergency', h.emergency_number, { copy: !!h.emergency_number });
  contact += infoRow('&#128205;', 'Address', h.address);
  if (contact) html += `<div class="g-card"><h3 style="margin:0 0 4px;">Contact</h3>${contact}</div>`;

  if (room.description) {
    html += `<div class="g-card"><h3 style="margin:0 0 4px;">Room notes</h3>
      <p style="margin:0;color:#3a4763;">${esc(room.description)}</p></div>`;
  }

  // quick-call actions
  const calls = [];
  if (h.reception_phone) calls.push(`<a href="tel:${esc(h.reception_phone)}">&#128222; Reception</a>`);
  if (h.restaurant_phone) calls.push(`<a class="alt" href="tel:${esc(h.restaurant_phone)}">&#127869; Restaurant</a>`);
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
