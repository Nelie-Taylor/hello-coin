(function () {
  var charts = {};

  function renderSkewCharts() {
    var canvases = document.querySelectorAll("canvas.skew-chart");
    canvases.forEach(function (canvas) {
      var existing = charts[canvas.id];
      if (existing) {
        existing.destroy();
        delete charts[canvas.id];
      }
      var history;
      try {
        history = JSON.parse(canvas.dataset.skew || "[]");
      } catch (error) {
        history = [];
      }
      if (!history.length) {
        return;
      }
      charts[canvas.id] = new Chart(canvas, {
        type: "line",
        data: {
          labels: history.map(function (row) { return row.timestamp; }),
          datasets: [
            {
              label: "LONG %",
              data: history.map(function (row) { return row.long_pct * 100; }),
              borderColor: "#4ade80",
              backgroundColor: "#4ade80",
              pointRadius: 0,
              borderWidth: 1.5,
            },
            {
              label: "SHORT %",
              data: history.map(function (row) { return row.short_pct * 100; }),
              borderColor: "#ff5c5c",
              backgroundColor: "#ff5c5c",
              pointRadius: 0,
              borderWidth: 1.5,
            },
            {
              label: "Price",
              data: history.map(function (row) { return row.price; }),
              borderColor: "#60a5fa",
              backgroundColor: "#60a5fa",
              pointRadius: 0,
              borderWidth: 1.5,
              yAxisID: "y1",
            },
          ],
        },
        options: {
          animation: false,
          scales: {
            x: { display: false },
            y: {
              min: 0,
              max: 100,
              ticks: { callback: function (value) { return value + "%"; } },
            },
            y1: {
              position: "right",
              grid: { drawOnChartArea: false },
            },
          },
          plugins: { legend: { labels: { boxWidth: 10 } } },
        },
      });
    });
  }

  renderSkewCharts();

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail && event.detail.target && event.detail.target.id === "panels") {
      renderSkewCharts();
    }
  });
})();
