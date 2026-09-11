async function loadBranding() {
  try {
    const r = await fetch('/api/public/branding');
    const b = await r.json();
    if (b.hotel_name) {
      document.getElementById('hotelName').textContent = b.hotel_name;
    }
    const logo = document.getElementById('logo');
    const initials = (b.hotel_name || 'GIQ').split(/\s+/)
      .map(w => w[0]).join('').slice(0, 3).toUpperCase() || 'GIQ';
    if (b.logo_url) {
      logo.classList.add('has-img');
      const img = new Image();
      img.alt = b.hotel_name || '';
      img.onerror = () => { logo.classList.remove('has-img'); logo.textContent = initials; };
      img.src = b.logo_url;
      logo.textContent = '';
      logo.appendChild(img);
    } else {
      logo.textContent = initials;
    }
    if (b.welcome_message) document.getElementById('welcomeMsg').textContent = b.welcome_message;
  } catch (e) { /* keep defaults */ }
}

async function submit() {
  const btn = document.getElementById('submitBtn');
  const name = document.getElementById('full_name').value.trim();
  if (!name) { alert('Please enter your name'); return; }
  btn.disabled = true; btn.textContent = 'Submitting...';
  const payload = {
    full_name: name,
    email: document.getElementById('email').value.trim(),
    phone: document.getElementById('phone').value.trim(),
    id_number: document.getElementById('id_number').value.trim(),
    address: document.getElementById('address').value.trim(),
    vehicle_reg: document.getElementById('vehicle_reg').value.trim(),
    num_guests: parseInt(document.getElementById('num_guests').value || '1', 10),
  };
  try {
    const r = await fetch('/api/checkin', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error('failed');
    const data = await r.json();
    document.getElementById('formCard').classList.add('hidden');
    document.getElementById('successCard').classList.remove('hidden');
    if (data.returning_guest) {
      document.getElementById('successMsg').textContent =
        'Welcome back! Reception will assign your room shortly.';
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) {
    alert('Something went wrong. Please try again or see reception.');
    btn.disabled = false; btn.textContent = 'Complete Check-in';
  }
}

document.getElementById('submitBtn').addEventListener('click', submit);
loadBranding();
