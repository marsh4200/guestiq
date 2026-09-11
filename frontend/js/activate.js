/* GuestIQ - activation screen. Talks only to /api/license/status and
   /api/license/activate, the two endpoints reachable even on an unlicensed
   install (see the license_gate middleware in backend/main.py). */

const REASON_MESSAGES = {
  not_activated: "This install has not been activated yet.",
  invalid_or_unsigned: "That license key isn't recognised. Check it was copied in full.",
  wrong_product: "That license key is for a different product.",
  server_mismatch: "That license key was issued for a different server. Send the Server ID below to get one for this install.",
  expired: "This license has expired. Contact support for a renewal.",
};

let currentServerId = "";

function showBox(id, message) {
  const box = document.getElementById(id);
  box.textContent = message;
  box.classList.remove("hidden");
}

async function loadStatus() {
  try {
    const res = await fetch("/api/license/status");
    const s = await res.json();
    currentServerId = s.server_id || "";
    document.getElementById("serverId").textContent = currentServerId || "—";
    if (s.activated) {
      // Already licensed (e.g. someone navigated here directly after
      // activating) — nothing to do here, go to the app.
      window.location.href = "/admin";
      return;
    }
    if (s.reason && s.reason !== "not_activated") {
      showBox("warnBox", REASON_MESSAGES[s.reason] || "This install is not currently licensed.");
    }
  } catch (e) {
    // Leave the form usable even if the status check itself failed —
    // activation will surface its own error.
  }
}

async function doActivate() {
  const btn = document.getElementById("activateBtn");
  const errBox = document.getElementById("errBox");
  const key = document.getElementById("licenseKey").value.trim();
  errBox.classList.add("hidden");
  if (!key) return;

  btn.disabled = true;
  btn.textContent = "Activating…";
  try {
    const res = await fetch("/api/license/activate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ license_key: key }),
    });
    const result = await res.json();
    if (result.activated) {
      window.location.href = "/admin";
      return;
    }
    showBox("errBox", REASON_MESSAGES[result.reason] || "That license key could not be activated.");
  } catch (e) {
    showBox("errBox", "Activation failed — check your connection and try again.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Activate";
  }
}

async function copyServerId() {
  if (!currentServerId) return;
  try {
    await navigator.clipboard.writeText(currentServerId);
    const btn = document.getElementById("copyBtn");
    const old = btn.textContent;
    btn.textContent = "Copied";
    setTimeout(() => { btn.textContent = old; }, 1500);
  } catch (e) {
    // Clipboard API unavailable — the ID is still selectable text.
  }
}

loadStatus();
