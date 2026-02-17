async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch {}
  return { ok: res.ok, status: res.status, text, json };
}

async function refreshStatus() {
  const r = await api("GET", "/health");
  const state = r.json?.state ?? "(unknown)";
  document.getElementById("state").textContent = state;
  document.getElementById("rawStatus").textContent = r.text;
}

async function showControlResult(label, r) {
  const out = `${label}: HTTP ${r.status}\n${r.text}`;
  document.getElementById("controlResult").textContent = out;
  await refreshStatus();
  await refreshFaults(); // optional: if status includes faults or separate endpoint
}

async function refreshFaults() {
  // If you have GET /control/faults or embed in /health, adjust accordingly.
  // If not available, you can keep UI "optimistic" and show last applied values.
  const r = await api("GET", "/control/faults");
  document.getElementById("faultsView").textContent = r.ok ? r.text : "(no /control/faults GET endpoint)";
}

function readFaultInputs() {
  return {
    drop_rate: parseFloat(document.getElementById("drop_rate").value || "0"),
    delay_ms: parseInt(document.getElementById("delay_ms").value || "0", 10),
    corrupt_rate: parseFloat(document.getElementById("corrupt_rate").value || "0"),
  };
}

window.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("refresh").onclick = refreshStatus;

  document.getElementById("reset").onclick = async () =>
    showControlResult("reset", await api("POST", "/control/reset"));

  document.getElementById("configure").onclick = async () =>
    showControlResult("configure", await api("POST", "/control/configure"));

  document.getElementById("streamStart").onclick = async () =>
    showControlResult("stream/start", await api("POST", "/control/stream/start"));

  document.getElementById("streamStop").onclick = async () =>
    showControlResult("stream/stop", await api("POST", "/control/stream/stop"));

  document.getElementById("applyFaults").onclick = async () => {
    const payload = readFaultInputs();
    showControlResult("faults", await api("POST", "/control/faults", payload));
  };

  document.getElementById("clearFaults").onclick = async () =>
    showControlResult("faults(clear)", await api("POST", "/control/faults", { drop_rate: 0, delay_ms: 0, corrupt_rate: 0 }));

  await refreshStatus();
  await refreshFaults();
});
