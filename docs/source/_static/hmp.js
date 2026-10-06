// Prototype behaviour: open a card on #anchor, copy a path, show where text comes from, filter tables.
(function () {
  function openHash() {
    var id = decodeURIComponent(location.hash.slice(1));
    if (!id) return;
    var el = document.getElementById(id);
    if (!el) return;
    var content = el.closest(".sd-tab-content");
    if (content) {
      var label = content.previousElementSibling;
      var input = label ? label.previousElementSibling : null;
      if (input && input.type === "radio") input.checked = true;
    }
    if (el.classList.contains("tl-adv")) {
      var blk = el.closest(".tb");
      if (blk) blk.classList.add("show-adv");
    }
    var d = el.tagName === "DETAILS" ? el : el.closest("details");
    while (d) {
      d.open = true;
      d = d.parentElement ? d.parentElement.closest("details") : null;
    }
    el.scrollIntoView({ block: "start" });
  }

  function setupOrigin() {
    var saved = false;
    try { saved = localStorage.getItem("hmp-origin") === "1"; } catch (e) {}
    document.querySelectorAll(".hmp-origin-cb").forEach(function (cb) {
      cb.checked = saved;
      cb.addEventListener("change", function () {
        document.body.classList.toggle("hmp-show-origin", cb.checked);
        document.querySelectorAll(".hmp-origin-cb").forEach(function (o) { o.checked = cb.checked; });
        try { localStorage.setItem("hmp-origin", cb.checked ? "1" : "0"); } catch (e) {}
      });
    });
    if (saved && document.querySelector(".hmp-origin-cb")) document.body.classList.add("hmp-show-origin");
  }

  function setupCopy() {
    document.addEventListener("click", function (ev) {
      var b = ev.target.closest(".hmp-copy");
      if (!b) return;
      ev.preventDefault();
      if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy);
      var old = b.textContent;
      b.textContent = "copied";
      setTimeout(function () { b.textContent = old; }, 1200);
    });
  }

  function setupFilters() {
    document.querySelectorAll(".hmp-filter").forEach(function (inp) {
      var table = document.getElementById(inp.dataset.target);
      if (!table) return;
      inp.addEventListener("input", function () {
        var q = norm(inp.value);
        table.querySelectorAll("tbody tr").forEach(function (tr) {
          tr.style.display = !q || norm(tr.textContent).indexOf(q) >= 0 ? "" : "none";
        });
      });
    });
  }

  function norm(s) {
    return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  }

  function setupCatalog() {
    var root = document.getElementById("hmp-catalog");
    if (!root) return;
    var data = JSON.parse(document.getElementById("hmp-cat-data").textContent);
    var q = document.getElementById("hmp-cat-q");
    var sec = document.getElementById("hmp-cat-sec");
    var prof = document.getElementById("hmp-cat-prof");
    var cal = document.getElementById("hmp-cat-cal");
    var req = document.getElementById("hmp-cat-req");
    var body = document.getElementById("hmp-cat-body");
    var count = document.getElementById("hmp-cat-count");
    function esc(s) { var d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
    function render() {
      var nq = norm(q.value);
      var rows = [];
      var n = 0;
      for (var i = 0; i < data.length; i++) {
        var it = data[i];
        if (sec.value && it[6] !== sec.value) continue;
        if (prof.value && it[5] !== prof.value) continue;
        if (cal.checked && !it[8]) continue;
        if (req.checked && it[4] !== "required") continue;
        if (nq && norm(it[0] + " " + it[1] + " " + it[2] + " " + it[7]).indexOf(nq) < 0) continue;
        n++;
        if (rows.length < 400) {
          rows.push("<tr><td><a href=\"" + esc(it[9]) + "\">" + esc(it[0]) + "</a></td><td>" + esc(it[1]) +
            (it[2] ? "<br><span class=\"hmp-label-fr\">" + esc(it[2]) + "</span>" : "") + "</td><td>" + esc(it[3]) +
            "</td><td>" + esc(it[4]) + "</td><td>" + esc(it[7]) + "</td></tr>");
        }
      }
      body.innerHTML = rows.join("");
      count.textContent = n + " fields" + (n > 400 ? " (first 400 shown)" : "");
    }
    [q, sec, prof, cal, req].forEach(function (el) { el.addEventListener("input", render); el.addEventListener("change", render); });
    var params = new URLSearchParams(location.search);
    if (params.get("q")) { q.value = params.get("q"); prof.value = ""; }
    render();
  }

  function setupBlocks() {
    document.addEventListener("click", function (ev) {
      var adv = ev.target.closest(".tb-adv");
      if (adv) {
        var blk = adv.closest(".tb");
        var on = blk.classList.toggle("show-adv");
        var n = adv.dataset.n;
        adv.textContent = (on ? "hide " : "show ") + n + " dev/expert key" + (n > 1 ? "s" : "");
        return;
      }
      var cp = ev.target.closest(".tb-copy");
      if (cp) {
        var src = cp.closest(".tb").querySelector(".tb-src");
        if (navigator.clipboard && src) navigator.clipboard.writeText(src.textContent);
        cp.textContent = "copied";
        setTimeout(function () { cp.textContent = "copy"; }, 1200);
      }
    });
  }

  function setupExplorer() {
    var root = document.querySelector(".hmp-explorer");
    if (!root) return;
    var q = document.getElementById("ex-q");
    var adv = document.getElementById("ex-adv");
    var count = document.getElementById("ex-count");
    var top = Array.prototype.slice.call(root.querySelectorAll(":scope > ul.ex-root > li"));
    function kidsOf(li) { return Array.prototype.slice.call(li.querySelectorAll(":scope > details > ul > li")); }
    function hit(li, nq) { return norm(li.dataset.text || "").indexOf(nq) >= 0; }
    function advanced(li) { return li.dataset.profile === "dev" || li.dataset.profile === "expert"; }

    // Show where a key matched when the match is neither in its path nor on screen.
    function explain(li, nq) {
      var full = li.dataset.full || "";
      if (norm(li.dataset.path).indexOf(nq) >= 0 || norm(li.textContent).indexOf(nq) >= 0) return;
      var at = full.toLowerCase().indexOf(nq);
      if (at < 0) at = norm(full).indexOf(nq);
      if (at < 0) return;
      var a = Math.max(0, at - 70), b = Math.min(full.length, at + nq.length + 90);
      if (a > 0) { var s = full.indexOf(" ", a); if (s >= 0 && s < at) a = s + 1; }
      if (b < full.length) { var e = full.lastIndexOf(" ", b); if (e > at + nq.length) b = e; }
      var span = document.createElement("span");
      span.className = "ex-why";
      var mark = document.createElement("mark");
      mark.textContent = full.slice(at, at + nq.length);
      span.append("matched: " + (a > 0 ? "…" : "") + full.slice(a, at), mark,
                  full.slice(at + nq.length, b) + (b < full.length ? "…" : ""));
      li.appendChild(span);
    }

    // Return true when li stays visible. An empty query matches every key.
    // A table that matches by its own summary, with no matching key below,
    // stays closed and keeps all its keys.
    function visit(li, nq, tally) {
      var why = li.querySelector(":scope > .ex-why");
      if (why) why.remove();
      var keep = false;
      if (li.classList.contains("ex-leaf")) {
        keep = (adv.checked || !advanced(li)) && (!nq || hit(li, nq));
        if (keep && nq) { tally.keys++; explain(li, nq); }
      } else {
        var kids = kidsOf(li);
        kids.forEach(function (k) { if (visit(k, nq, tally)) keep = true; });
        var open = keep && !!nq;
        if (!keep && nq && hit(li, nq)) {
          kids.forEach(function (k) { if (visit(k, "", tally)) keep = true; });
          if (keep) tally.tables++;
        }
        var d = li.querySelector(":scope > details");
        if (d) d.open = open;
      }
      li.classList.toggle("ex-hide", !keep);
      return keep;
    }

    function apply() {
      var nq = norm(q.value.trim());
      root.classList.toggle("show-adv", adv.checked);
      var tally = { keys: 0, tables: 0 };
      top.forEach(function (li) { visit(li, nq, tally); });
      if (!nq) { count.textContent = ""; return; }
      var parts = [];
      if (tally.keys || !tally.tables) parts.push(tally.keys + " key" + (tally.keys === 1 ? "" : "s"));
      if (tally.tables) parts.push(tally.tables + " table" + (tally.tables === 1 ? "" : "s") + " by summary");
      count.textContent = parts.join(", ");
    }
    q.addEventListener("input", apply);
    adv.addEventListener("change", apply);
    document.getElementById("ex-open").addEventListener("click", function () { root.querySelectorAll("li:not(.ex-hide) > details").forEach(function (d) { d.open = true; }); });
    document.getElementById("ex-close").addEventListener("click", function () { root.querySelectorAll("details").forEach(function (d) { d.open = false; }); });
    var params = new URLSearchParams(location.search);
    if (params.get("adv")) adv.checked = true;
    if (params.get("q")) q.value = params.get("q");
    apply();
  }

  document.addEventListener("DOMContentLoaded", function () {
    setupBlocks();
    setupExplorer();
    setupOrigin();
    setupCopy();
    setupFilters();
    setupCatalog();
    openHash();
  });
  window.addEventListener("hashchange", openHash);
})();
