/* Availability calendar — renders a 2-month view per cabin from /api/availability/<slug>/
   Booked nights come from the live Airbnb iCal feed. */
(function () {
  var DOW = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
  var MONTHS = ["January","February","March","April","May","June","July",
                "August","September","October","November","December"];
  var MONTHS_PER_VIEW = 2;
  var MAX_MONTHS = 12;

  function iso(y, m, d) {
    return y + "-" + String(m + 1).padStart(2, "0") + "-" + String(d).padStart(2, "0");
  }

  function renderMonth(year, month, bookedSet, today) {
    var wrap = document.createElement("div");
    wrap.className = "cal-month";
    var h = document.createElement("h4");
    h.textContent = MONTHS[month] + " " + year;
    wrap.appendChild(h);

    var grid = document.createElement("div");
    grid.className = "cal-grid";
    DOW.forEach(function (d) {
      var c = document.createElement("div");
      c.className = "cal-dow";
      c.textContent = d;
      grid.appendChild(c);
    });

    var first = new Date(year, month, 1).getDay();
    var days = new Date(year, month + 1, 0).getDate();
    for (var i = 0; i < first; i++) {
      var e = document.createElement("div");
      e.className = "cal-day empty";
      grid.appendChild(e);
    }
    var todayIso = iso(today.getFullYear(), today.getMonth(), today.getDate());
    for (var d = 1; d <= days; d++) {
      var cell = document.createElement("div");
      cell.className = "cal-day";
      cell.textContent = d;
      var key = iso(year, month, d);
      if (key < todayIso) {
        cell.className += " past";
      } else if (bookedSet.has(key)) {
        cell.className += " booked";
        cell.title = "Booked";
      } else {
        cell.title = "Available";
      }
      if (key === todayIso) cell.className += " today";
      grid.appendChild(cell);
    }
    wrap.appendChild(grid);
    return wrap;
  }

  function initCalendar(el) {
    var slug = el.getAttribute("data-slug");
    var monthsEl = el.querySelector(".avail-months");
    var statusEl = el.querySelector(".avail-status");
    var prevBtn = el.querySelector(".avail-prev");
    var nextBtn = el.querySelector(".avail-next");
    var rangeEl = el.querySelector(".avail-range");
    var offset = 0;
    var bookedSet = new Set();
    var today = new Date();

    function draw() {
      monthsEl.innerHTML = "";
      var base = new Date(today.getFullYear(), today.getMonth(), 1);
      for (var i = 0; i < MONTHS_PER_VIEW; i++) {
        var dt = new Date(base.getFullYear(), base.getMonth() + offset + i, 1);
        monthsEl.appendChild(renderMonth(dt.getFullYear(), dt.getMonth(), bookedSet, today));
      }
      var start = new Date(base.getFullYear(), base.getMonth() + offset, 1);
      var end = new Date(base.getFullYear(), base.getMonth() + offset + MONTHS_PER_VIEW - 1, 1);
      if (rangeEl) rangeEl.textContent = MONTHS[start.getMonth()].slice(0,3) + " " + start.getFullYear()
        + " – " + MONTHS[end.getMonth()].slice(0,3) + " " + end.getFullYear();
      if (prevBtn) prevBtn.disabled = offset <= 0;
      if (nextBtn) nextBtn.disabled = offset + MONTHS_PER_VIEW >= MAX_MONTHS;
    }

    if (prevBtn) prevBtn.addEventListener("click", function () {
      offset = Math.max(0, offset - MONTHS_PER_VIEW); draw();
    });
    if (nextBtn) nextBtn.addEventListener("click", function () {
      offset = Math.min(MAX_MONTHS - MONTHS_PER_VIEW, offset + MONTHS_PER_VIEW); draw();
    });

    fetch("/api/availability/" + slug + "/")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.configured) {
          el.querySelector(".avail-controls") && (el.querySelector(".avail-controls").style.display = "none");
          monthsEl.innerHTML = '<div class="avail-fallback">Live availability calendar is being connected. ' +
            'Please call or text us to check open dates.</div>';
          return;
        }
        (data.nights || []).forEach(function (n) { bookedSet.add(n); });
        draw();
        if (statusEl) {
          if (data.error) {
            statusEl.textContent = "Could not refresh live calendar right now — please call to confirm.";
          } else {
            statusEl.textContent = "Live from our booking calendar" +
              (data.updated ? " · last updated " + data.updated.slice(0, 10) : "") +
              (data.stale ? " (cached)" : "");
          }
        }
      })
      .catch(function () {
        monthsEl.innerHTML = '<div class="avail-fallback">Could not load the calendar. ' +
          'Please call or text us to check availability.</div>';
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".availability[data-slug]").forEach(initCalendar);
  });
})();
