// Refresh visible attendance lists, check-ins, and badges when scans are recorded.
(() => {
  const list = document.querySelector("[data-live-attendance]");
  const timeIns = document.querySelector("[data-live-student-time-ins]");
  const badges = [...document.querySelectorAll("[data-live-student-event]")];
  const panel = list ?? timeIns;
  if (!panel && !badges.length) return;

  const connection = panel?.querySelector("[data-attendance-connection]");
  const parts = panel?.querySelectorAll("[data-attendance-part]") ?? [];
  const url = list ? window.location.href : (timeIns ?? badges[0]).dataset.studentAttendanceUrl;
  const rendered = new Map();
  const interval = 1000;
  let etag;
  let timer;
  let refreshing = false;
  let refreshRequested = false;

  function showConnection(message) {
    if (!connection) return;
    if (connection.textContent !== message) connection.textContent = message;
    connection.hidden = !message;
  }

  function renderAttendance(updated) {
    if (!list && badges.length) {
      const checkedIn = new Set(updated.in_event_ids.map(String));
      for (const badge of badges) {
        const hidden = !checkedIn.has(badge.dataset.liveStudentEvent);
        if (badge.hidden !== hidden) badge.hidden = hidden;
      }
    }
    for (const part of parts) {
      const name = part.dataset.attendancePart;
      const html = updated[name];
      if (typeof html !== "string" || rendered.get(name) === html) continue;
      part.innerHTML = html;
      rendered.set(name, html);
    }
  }

  async function refresh() {
    window.clearTimeout(timer);
    if (document.hidden) return;
    if (refreshing) {
      refreshRequested = true;
      return;
    }

    const controller = new AbortController();
    refreshing = true;
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    let delay = interval;
    try {
      const headers = { Accept: "application/json" };
      if (etag) headers["If-None-Match"] = etag;
      const response = await fetch(url, {
        headers, cache: "no-store", signal: controller.signal,
      });
      if (response.redirected || [401, 403, 404].includes(response.status)) {
        showConnection("Live updates stopped. Reload this page to check access.");
        return;
      }
      if (response.status !== 304) {
        if (!response.ok) throw new Error("Attendance refresh failed.");
        renderAttendance(await response.json());
        etag = response.headers.get("ETag");
      }
      showConnection("");
    } catch {
      showConnection("Live updates paused. Reconnecting…");
      delay = 3000;
    } finally {
      window.clearTimeout(timeout);
      refreshing = false;
    }

    if (refreshRequested) delay = 0;
    refreshRequested = false;
    if (!document.hidden) timer = window.setTimeout(refresh, delay);
  }

  function refreshWhenVisible() {
    if (document.hidden) window.clearTimeout(timer);
    else refresh();
  }

  if (typeof BroadcastChannel === "function") {
    const eventIds = list
      ? [list.dataset.liveAttendance]
      : new Set(badges.map(badge => badge.dataset.liveStudentEvent));
    for (const eventId of eventIds) {
      const channel = new BroadcastChannel("attendance-" + eventId);
      channel.onmessage = () => refresh();
    }
  }
  document.addEventListener("visibilitychange", refreshWhenVisible);
  window.addEventListener("online", refreshWhenVisible);
  refresh();
})();
