// api.js
const BASE_URL = "http://raspberrypi.local:8000";

export async function getStatusSummary() {
  const res = await fetch(`${BASE_URL}/api/status/summary`);
  const json = await res.json();
  return json.data;
}

export async function getAlertsLatest() {
  const res = await fetch(`${BASE_URL}/api/alerts/latest`);
  const json = await res.json();
  return json.rows;
}
