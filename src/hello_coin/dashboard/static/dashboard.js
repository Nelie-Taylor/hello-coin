(function () {
  var statusEl = document.getElementById("refresh-status");
  if (!statusEl) {
    return;
  }
  var totalSeconds = parseInt(statusEl.dataset.refreshSeconds, 10) || 60;
  var remaining = totalSeconds;

  function render() {
    statusEl.textContent = "LIVE · Next refresh: " + remaining + "s";
  }

  function tick() {
    remaining = remaining > 0 ? remaining - 1 : totalSeconds;
    render();
  }

  render();
  setInterval(tick, 1000);

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail && event.detail.target && event.detail.target.id === "panels") {
      remaining = totalSeconds;
      render();
    }
  });
})();
