/* Filters of the catalog pages: figures, data sources by provider, data sources by section. */
(function () {
  "use strict";

  function norm(s) {
    return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  }

  function setupCards(input) {
    var root = document.getElementById(input.dataset.cards);
    if (!root) return;
    var items = Array.prototype.slice.call(root.querySelectorAll("[data-text]"));
    var groups = Array.prototype.slice.call(root.querySelectorAll(".hmp-fig-kind"));
    var buttons = Array.prototype.slice.call(document.querySelectorAll("button.hmp-chip-btn"));
    var shown = document.querySelector(".hmp-cat-shown");
    var kind = "";

    function apply() {
      var q = norm(input.value);
      var count = 0;
      items.forEach(function (el) {
        var ok = (!q || norm(el.dataset.text).indexOf(q) >= 0) && (!kind || el.dataset.kind === kind);
        el.hidden = !ok;
        if (ok) count++;
      });
      groups.forEach(function (g) {
        g.hidden = !g.querySelector("[data-text]:not([hidden])");
      });
      if (shown) {
        var total = shown.dataset.total;
        shown.textContent = q || kind ? count + " of " + total + " shown" : "";
      }
    }

    input.addEventListener("input", apply);
    buttons.forEach(function (b) {
      b.addEventListener("click", function () {
        var same = b.getAttribute("aria-pressed") === "true";
        buttons.forEach(function (o) { o.setAttribute("aria-pressed", "false"); });
        kind = same ? "" : b.dataset.kind;
        if (!same) b.setAttribute("aria-pressed", "true");
        apply();
      });
    });
    var target = location.hash && document.getElementById(location.hash.slice(1));
    if (target && target.tagName === "DETAILS") target.open = true;
  }

  function setupRows(input) {
    var table = document.getElementById(input.dataset.rows);
    if (!table) return;
    input.addEventListener("input", function () {
      var q = norm(input.value);
      table.querySelectorAll("tbody > tr").forEach(function (tr) {
        tr.hidden = !!q && norm(tr.textContent).indexOf(q) < 0;
      });
    });
  }

  document.querySelectorAll(".hmp-filter[data-cards]").forEach(setupCards);
  document.querySelectorAll(".hmp-filter[data-rows]").forEach(setupRows);
})();
