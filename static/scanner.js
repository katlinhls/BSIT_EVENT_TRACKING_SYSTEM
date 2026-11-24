// Keep the camera, scan mode, and event schedule in sync with Django.
(() => {
  const panel = document.querySelector("[data-attendance-scanner]");
  const modes = {
    IN: { button: document.getElementById("inBtn"), flag: "time_in_allowed", label: "Time In" },
    OUT: { button: document.getElementById("outBtn"), flag: "time_out_allowed", label: "Time Out" },
    EXCUSED_OUT: {
      button: document.getElementById("excusedOutBtn"),
      flag: "excused_time_out_allowed",
      label: "Excused Time Out",
    },
  };
  const timingMessage = document.getElementById("scan-timing-message");
  const result = document.getElementById("result");
  const attendanceChannel = typeof BroadcastChannel === "function"
    ? new BroadcastChannel("attendance-" + panel.dataset.attendanceScanner)
    : null;
  const reminder = panel.querySelector("[data-end-reminder]");
  const endLabel = reminder.querySelector("[data-scheduled-end]");
  const csrfToken = panel.querySelector("[name=csrfmiddlewaretoken]").value;
  let timing = JSON.parse(document.getElementById("scanner-timing").textContent);
  let scanType = timing.time_in_allowed ? "IN" : "OUT";
  let submitting = false;
  let queuedScan;
  const recentDecodes = new Map();
  // Bound the QR cache while quieting repeated camera reads.
  const recentDecodeLimit = 128;
  const repeatDelay = 750;
  let timingTimer;
  let timingVersion = 0;
  let camera;
  let cameraRunning = false;

  function setResult(message, kind = "") {
    result.textContent = message;
    result.className = "scan-result " + kind;
    if (kind) {
      document.dispatchEvent(new CustomEvent("bsit:feedback", {
        detail: { message, level: kind },
      }));
    }
  }

  function setScanType(type) {
    if (scanType !== type) queuedScan = undefined;
    scanType = type;
    for (const [mode, { button }] of Object.entries(modes)) {
      button.setAttribute("aria-pressed", String(type === mode));
    }
    if (type) setResult(`Ready for ${modes[type].label}.`);
  }

  function stopCamera() {
    if (!cameraRunning) return;
    cameraRunning = false;
    camera.stop().catch(() => {});
  }

  function applyTiming(updated) {
    timingVersion += 1;
    timing = updated;
    for (const { button, flag } of Object.values(modes)) button.disabled = !timing[flag];
    modes.EXCUSED_OUT.button.hidden = !timing.excused_time_out_allowed;
    if (timingMessage.textContent !== timing.message) timingMessage.textContent = timing.message;
    if (endLabel.textContent !== timing.end_label) endLabel.textContent = timing.end_label;
    reminder.hidden = !timing.show_end_reminder;

    if (!timing.scanning_open) {
      setScanType(null);
      setResult(timing.message);
      stopCamera();
    } else if (!timing.time_in_allowed && scanType !== "OUT") {
      // Keep the camera running for pending Time Outs after the selected day ends.
      setScanType("OUT");
    } else if (scanType && !timing[modes[scanType].flag]) {
      // If a selected mode closes, wait for the organizer to choose another.
      setScanType(null);
      setResult("Choose an available scan mode.");
    }
    if (queuedScan && !timing[modes[queuedScan.type].flag]) queuedScan = undefined;
  }

  function scheduleTimingRefresh(delay) {
    window.clearTimeout(timingTimer);
    if (timing.scanning_open) timingTimer = window.setTimeout(refreshTiming, delay);
  }

  async function refreshTiming() {
    const version = timingVersion;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    let delay = 3000;
    try {
      const response = await fetch(panel.dataset.timingUrl, { cache: "no-store", signal: controller.signal });
      if (version !== timingVersion) return;
      if (response.redirected || response.status === 403 || response.status === 404) {
        applyTiming({
          scanning_open: false, time_in_allowed: false, time_out_allowed: false,
          excused_time_out_allowed: false, show_end_reminder: false,
          end_label: timing.end_label, message: "This scanner is no longer available.",
        });
      } else if (response.ok) {
        const updated = await response.json();
        if (version !== timingVersion) return;
        applyTiming(updated);
        delay = timing.refresh_after_ms;
      }
    } catch {
      // Retry after a temporary connection failure. Each scan is still checked by Django.
      if (version !== timingVersion) return;
    } finally {
      window.clearTimeout(timeout);
    }
    scheduleTimingRefresh(delay);
  }

  function scanDetected(token) {
    if (!scanType || !timing[modes[scanType].flag]) return;
    const key = timing.day + ":" + scanType + ":" + token;
    if ((recentDecodes.get(key) ?? 0) > performance.now()) return;

    const scan = { token, day: timing.day, type: scanType, key };
    if (!submitting) submitScan(scan);
    // Keep at most the next code during a save. Excused Time Out is a one-student action.
    else if (!queuedScan && scanType !== "EXCUSED_OUT") queuedScan = scan;
  }

  function rememberDecode(key, duration) {
    recentDecodes.delete(key);
    recentDecodes.set(key, performance.now() + duration);
    if (recentDecodes.size > recentDecodeLimit) {
      recentDecodes.delete(recentDecodes.keys().next().value);
    }
  }

  async function submitScan({ token, day, type, key }) {
    if (day !== timing.day || type !== scanType || !timing[modes[type].flag]) return;
    submitting = true;
    rememberDecode(key, Infinity);
    const body = new URLSearchParams({
      token, day, scan_type: type, csrfmiddlewaretoken: csrfToken,
    });
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(panel.dataset.scanUrl, { method: "POST", body, signal: controller.signal });
      const data = await response.json();
      rememberDecode(key, data.ok || data.already_recorded ? Infinity : repeatDelay);
      if (data.ok) attendanceChannel?.postMessage("attendance-updated");
      if (data.timing && timing.scanning_open) {
        applyTiming(data.timing);
        scheduleTimingRefresh(timing.refresh_after_ms);
      }
      // Select Excused Time Out separately for each emergency departure.
      if (data.ok && data.scan_type === "EXCUSED_OUT" && scanType === "EXCUSED_OUT") {
        setScanType(null);
      }
      setResult(data.message || "Scan processed.", data.ok ? "success" : "error");
    } catch {
      rememberDecode(key, repeatDelay);
      setResult("Could not contact the server.", "error");
    } finally {
      window.clearTimeout(timeout);
      submitting = false;
      // A different code can be submitted as soon as the current save finishes.
      const next = queuedScan;
      queuedScan = undefined;
      if (next) submitScan(next);
    }
  }

  for (const [mode, { button }] of Object.entries(modes)) {
    button.addEventListener("click", () => setScanType(mode));
  }
  applyTiming(timing);
  scheduleTimingRefresh(timing.refresh_after_ms);

  if (typeof Html5Qrcode === "undefined") {
    setResult("The camera scanner could not load. Refresh the page to try again.", "error");
    return;
  }

  // Prefer the rear camera and use a scan box sized to the screen.
  camera = new Html5Qrcode("reader");
  const qrSize = Math.min(260, Math.max(160, Math.floor(window.innerWidth * 0.72)));
  camera.start(
    { facingMode: "environment" },
    { fps: 15, qrbox: { width: qrSize, height: qrSize } },
    scanDetected,
    () => {},
  ).then(() => {
    cameraRunning = true;
    if (!timing.scanning_open) stopCamera();
  }).catch(() => {
    if (timing.scanning_open) {
      setResult("Camera could not start. Allow camera permission and use HTTPS/localhost.", "error");
    }
  });
})();
