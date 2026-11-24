// Refresh the visible organizer page at the next schedule transition.
(() => {
  const delay = JSON.parse(document.getElementById("organizer-event-refresh").textContent);
  const deadline = performance.now() + delay;
  let timer;

  function refreshAtTransition() {
    window.clearTimeout(timer);
    if (document.hidden) return;
    const remaining = Math.ceil(deadline - performance.now());
    if (remaining <= 0) window.location.reload();
    else timer = window.setTimeout(refreshAtTransition, Math.min(remaining, 2147483647));
  }

  document.addEventListener("visibilitychange", refreshAtTransition);
  refreshAtTransition();
})();
