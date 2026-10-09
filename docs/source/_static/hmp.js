// Parameter reference: cards on #anchor, copy buttons, the dev/expert switch,
// the explorer search, filters, the changes page and the hover card of {toml} links.
(function () {
  "use strict";

  var ADV_KEY = "hmp-adv";

  function norm(s) {
    return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  }

  function contentRoot() {
    var root = document.documentElement.dataset.content_root;
    if (root === undefined && window.DOCUMENTATION_OPTIONS) root = DOCUMENTATION_OPTIONS.URL_ROOT;
    return root || "";
  }

  // ------------------------------------------------------------ keys file

  var keysPromise = null;
  function loadKeys() {
    if (!keysPromise) {
      keysPromise = fetch(contentRoot() + "_static/hmp-keys.json")
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (list) {
          var byAnchor = {};
          list.forEach(function (k) {
            var at = k.w.indexOf("#");
            byAnchor[k.w.slice(at + 1)] = k;
            k.np = norm(k.p);
            k.nn = norm(k.n);
            k.segs = k.np.split(/[.<>]+/).filter(Boolean);
            k.parts = k.nn.split(/[_\-]+/).filter(Boolean);
            k.lab = norm(k.l || "").split(/\s+/).filter(Boolean);
            k.sum = norm(k.s).split(/[^a-z0-9_]+/).filter(Boolean);
            k.rest = norm(k.x || "").split(/[^a-z0-9_]+/).filter(Boolean);
          });
          return { list: list, byAnchor: byAnchor };
        });
      keysPromise.catch(function () { keysPromise = null; });
    }
    return keysPromise;
  }

  // ------------------------------------------------------------ open a card on #anchor

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
    if (el.classList.contains("tl-adv")) setAdv(true, false);
    var d = el.tagName === "DETAILS" ? el : el.closest("details");
    while (d) {
      d.open = true;
      d = d.parentElement ? d.parentElement.closest("details") : null;
    }
    el.scrollIntoView({ block: "start" });
  }

  // ------------------------------------------------------------ copy

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(area);
      if (ok) { resolve(); } else { reject(new Error("copy refused")); }
    });
  }

  var live = null;
  function announce(msg) {
    if (!live) {
      live = document.createElement("div");
      live.className = "hmp-sr";
      live.setAttribute("role", "status");
      live.setAttribute("aria-live", "polite");
      document.body.appendChild(live);
    }
    live.textContent = "";
    setTimeout(function () { live.textContent = msg; }, 30);
  }

  function setupCopy() {
    document.addEventListener("click", function (ev) {
      var b = ev.target.closest(".hmp-copy");
      if (!b) return;
      ev.preventDefault();
      var text;
      if (b.classList.contains("tb-copy")) {
        var src = b.closest(".tb").querySelector(".tb-src");
        text = src ? src.textContent : "";
      } else if (b.dataset.anchor) {
        text = location.origin + location.pathname + "#" + b.dataset.anchor;
      } else {
        text = b.dataset.copy || "";
      }
      copyText(text).then(function () {
        b.classList.add("hmp-done");
        announce("Copied");
        setTimeout(function () { b.classList.remove("hmp-done"); }, 1200);
      }, function () {
        b.classList.add("hmp-fail");
        announce("Copy failed: select the text and copy it by hand");
        setTimeout(function () { b.classList.remove("hmp-fail"); }, 2000);
      });
    });
  }

  // ------------------------------------------------------------ dev/expert switch, site-wide

  var advListeners = [];
  function advOn() { return document.documentElement.classList.contains("hmp-adv"); }

  function setAdv(on, store) {
    document.documentElement.classList.toggle("hmp-adv", on);
    document.querySelectorAll(".hmp-adv-switch, .tb-adv").forEach(function (b) {
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    if (store) {
      try { localStorage.setItem(ADV_KEY, on ? "1" : "0"); } catch (e) { /* private window */ }
    }
    advListeners.forEach(function (f) { f(on); });
  }

  function setupAdv() {
    var on = false;
    try { on = localStorage.getItem(ADV_KEY) === "1"; } catch (e) { on = false; }
    var param = new URLSearchParams(location.search).get("adv");
    if (param !== null) on = param === "1" || param === "true";
    setAdv(on, false);
    document.addEventListener("click", function (ev) {
      var b = ev.target.closest(".hmp-adv-switch, .tb-adv");
      if (!b) return;
      setAdv(!advOn(), true);
    });
  }

  // ------------------------------------------------------------ fold on narrow screens

  function setupFold() {
    if (!window.matchMedia("(max-width: 760px)").matches) return;
    document.querySelectorAll("details[data-fold-narrow]").forEach(function (d) { d.open = false; });
  }

  // ------------------------------------------------------------ filter of a table

  function setupFilters() {
    document.querySelectorAll(".hmp-filter").forEach(function (inp) {
      var scope = document.querySelector(inp.dataset.target);
      if (!scope) return;
      var count = inp.parentElement.querySelector(".hmp-filter-count");
      var rows = Array.prototype.slice.call(scope.querySelectorAll("tbody tr"));
      var texts = rows.map(function (tr) { return norm(tr.textContent); });
      function apply() {
        var tokens = norm(inp.value).split(/\s+/).filter(Boolean);
        var shown = 0;
        rows.forEach(function (tr, i) {
          var keep = tokens.every(function (t) { return texts[i].indexOf(t) >= 0; });
          tr.hidden = !keep;
          if (keep) shown++;
        });
        scope.querySelectorAll(".hmp-qgroup").forEach(function (g) {
          g.hidden = !g.querySelector("tbody tr:not([hidden])");
        });
        if (count) count.textContent = tokens.length ? shown + " of " + rows.length + " keys" : "";
      }
      inp.addEventListener("input", apply);
    });
  }

  // ------------------------------------------------------------ explorer

  // Score of one key for the query tokens, 0 when a token matches nothing.
  // A token weighs most on the name, then on a path segment, then the summary,
  // then the rest of the text.
  function score(k, tokens) {
    var total = 0;
    for (var i = 0; i < tokens.length; i++) {
      var t = tokens[i], s = 0;
      if (k.nn === t) s = 100;
      else if (k.parts.indexOf(t) >= 0 || k.lab.indexOf(t) >= 0) s = 60;
      else if (k.nn.indexOf(t) === 0) s = 50;
      else if (k.segs.indexOf(t) >= 0) s = 40;
      else if (k.lab.some(function (w) { return w.indexOf(t) === 0; })) s = 35;
      else if (k.parts.some(function (w) { return w.indexOf(t) === 0; })) s = 30;
      else if (k.segs.some(function (w) { return w.indexOf(t) === 0; })) s = 25;
      else if (k.sum.some(function (w) { return w.indexOf(t) === 0; })) s = 15;
      else if (k.rest.some(function (w) { return w.indexOf(t) === 0; })) s = 5;
      if (!s) return 0;
      total += s;
    }
    if (k.l) total += 8;
    if (!k.a) total += 3;
    if (k.r) total += 2;
    return total - k.segs.length * 0.5;
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function snippet(k, tokens) {
    var text = k.x || "";
    var low = norm(text);
    for (var i = 0; i < tokens.length; i++) {
      var re = new RegExp("(^|[^a-z0-9_])" + tokens[i].replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
      var m = re.exec(low);
      if (!m) continue;
      var at = m.index + m[1].length;
      if (norm(k.s).indexOf(tokens[i]) >= 0 || k.np.indexOf(tokens[i]) >= 0) continue;
      var a = Math.max(0, at - 60), b = Math.min(text.length, at + tokens[i].length + 80);
      var span = el("span", "ex-why");
      var mark = el("mark", "", text.slice(at, at + tokens[i].length));
      span.append("matched: " + (a > 0 ? "..." : "") + text.slice(a, at), mark,
                  text.slice(at + tokens[i].length, b) + (b < text.length ? "..." : ""));
      return span;
    }
    return null;
  }

  function setupExplorer() {
    var root = document.querySelector(".hmp-explorer");
    if (!root) return;
    var q = document.getElementById("ex-q");
    var count = document.getElementById("ex-count");
    var results = root.querySelector(".ex-results");
    var tree = root.querySelector(".ex-root");
    var base = contentRoot();
    var timer = null;

    function render(keys) {
      var tokens = norm(q.value).split(/[\s.\[\]=]+/).filter(Boolean);
      var url = new URL(location.href);
      if (tokens.length) url.searchParams.set("q", q.value.trim()); else url.searchParams.delete("q");
      history.replaceState(null, "", url);
      if (!tokens.length) {
        results.hidden = true;
        tree.hidden = false;
        count.textContent = "";
        return;
      }
      var adv = advOn();
      var hits = [];
      keys.list.forEach(function (k) {
        if (k.a && !adv) return;
        var s = score(k, tokens);
        if (s > 0) hits.push([s, k]);
      });
      hits.sort(function (x, y) { return y[0] - x[0] || x[1].p.length - y[1].p.length; });
      results.textContent = "";
      hits.slice(0, 60).forEach(function (h) {
        var k = h[1];
        var li = el("li", "ex-hit");
        var a = el("a", "");
        a.href = base + k.w;
        var code = el("code", "", k.t === "l" ? k.p : (k.t === "a" ? "[[" + k.p + "]]" : "[" + k.p + "]"));
        a.appendChild(code);
        li.appendChild(a);
        if (k.l) li.appendChild(el("span", "ex-label", k.l));
        if (k.u) li.appendChild(el("span", "tc tc-unit", k.u));
        if (k.r) li.appendChild(el("span", "tc tc-req", "required"));
        if (k.a) li.appendChild(el("span", "tc tc-prof", k.a));
        if (k.s) li.appendChild(el("span", "ex-sum", k.s.replace(/`/g, "")));
        var why = snippet(k, tokens);
        if (why) li.appendChild(why);
        results.appendChild(li);
      });
      results.hidden = false;
      tree.hidden = true;
      var n = hits.length;
      count.textContent = n === 0 ? "no key matches every word" :
        n + " key" + (n === 1 ? "" : "s") + (n > 60 ? ", the first 60 shown" : "");
    }

    function schedule() {
      clearTimeout(timer);
      timer = setTimeout(function () {
        loadKeys().then(render, function () {
          count.textContent = "The search index could not be loaded.";
        });
      }, 120);
    }

    q.addEventListener("input", schedule);
    advListeners.push(function () { if (q.value.trim()) schedule(); });
    document.getElementById("ex-open").addEventListener("click", function () {
      tree.querySelectorAll("details").forEach(function (d) { d.open = true; });
    });
    document.getElementById("ex-close").addEventListener("click", function () {
      tree.querySelectorAll("details").forEach(function (d) { d.open = false; });
    });
    var param = new URLSearchParams(location.search).get("q");
    if (param) { q.value = param; schedule(); }
  }

  // ------------------------------------------------------------ changes between two versions

  function setupChanges() {
    var form = document.querySelector(".hmp-ch-form");
    if (!form) return;
    var from = form.querySelector(".hmp-ch-from");
    var to = form.querySelector(".hmp-ch-to");
    var same = form.querySelector(".hmp-ch-same");
    var lead = document.querySelector(".hmp-ch-lead");
    var pairs = Array.prototype.slice.call(document.querySelectorAll(".hmp-ch-pair"));
    var order = Array.prototype.map.call(to.options, function (o) { return o.value; });
    function name(sel) { return sel.options[sel.selectedIndex].text; }
    function apply() {
      var ok = false;
      pairs.forEach(function (p) {
        var show = p.dataset.from === from.value && p.dataset.to === to.value;
        p.hidden = !show;
        if (show) ok = true;
      });
      same.hidden = ok;
      if (lead) lead.hidden = !ok;
      if (lead && ok) lead.innerHTML = "From <b>" + name(from) + "</b> to <b>" + name(to) + "</b>.";
    }
    form.hidden = false;
    form.addEventListener("change", apply);
    var params = new URLSearchParams(location.search);
    if (params.get("from")) from.value = params.get("from");
    if (params.get("to") && order.indexOf(params.get("to")) >= 0) to.value = params.get("to");
    apply();
  }

  // ------------------------------------------------------------ hover card of {toml} links

  // Reusable: hoverCard(selector, lookup, id) shows a small card for each link the
  // selector matches; lookup(link, data) returns the entry to show, or null.
  // Each instance owns one card element with its own id, so two instances on a page
  // (the {toml} links and the glossary terms) never share an id. Pass `id` to name it;
  // without one the first instance is "hmp-hover" and the next ones "hmp-hover-2", ...
  // The same id goes in aria-describedby of the link the card describes.
  var cardCount = 0;
  function hoverCard(selector, lookup, id) {
    var card = null, current = null, hideTimer = null;
    cardCount += 1;
    var cardId = id || (cardCount === 1 ? "hmp-hover" : "hmp-hover-" + cardCount);
    function hide() {
      if (card) card.hidden = true;
      current = null;
    }
    function show(link) {
      loadKeys().then(function (data) {
        var k = lookup(link, data);
        if (!k || current !== link) return;
        if (!card) {
          card = el("div", "hmp-hover");
          card.setAttribute("role", "tooltip");
          card.id = cardId;
          card.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
          card.addEventListener("mouseleave", hide);
          document.body.appendChild(card);
        }
        card.textContent = "";
        card.appendChild(el("code", "hmp-hover-path", k.p));
        var meta = el("div", "hmp-hover-meta");
        if (k.l) meta.appendChild(el("span", "", k.l));
        if (k.f) meta.appendChild(el("span", "", k.f));
        if (k.u) meta.appendChild(el("span", "tc tc-unit", k.u));
        if (k.r) meta.appendChild(el("span", "tc tc-req", "required"));
        else if (k.d) meta.appendChild(el("span", "", "default " + k.d));
        if (k.a) meta.appendChild(el("span", "tc tc-prof", k.a));
        card.appendChild(meta);
        if (k.s) card.appendChild(el("div", "hmp-hover-sum", k.s.replace(/`/g, "")));
        link.setAttribute("aria-describedby", cardId);
        var r = link.getBoundingClientRect();
        card.hidden = false;
        var top = window.scrollY + r.bottom + 6;
        var left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - card.offsetWidth - 12);
        card.style.top = top + "px";
        card.style.left = Math.max(window.scrollX + 8, left) + "px";
      }, function () { /* no keys file: the title attribute stays */ });
    }
    function enter(ev) {
      var link = ev.target.closest && ev.target.closest(selector);
      if (!link) return;
      clearTimeout(hideTimer);
      if (link.title) { link.dataset.title = link.title; link.removeAttribute("title"); }
      current = link;
      show(link);
    }
    function leave(ev) {
      var link = ev.target.closest && ev.target.closest(selector);
      if (!link) return;
      hideTimer = setTimeout(hide, 150);
    }
    document.addEventListener("mouseover", enter);
    document.addEventListener("focusin", enter);
    document.addEventListener("mouseout", leave);
    document.addEventListener("focusout", leave);
    document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") hide(); });
  }

  function keyOfLink(link, data) {
    var href = link.getAttribute("href") || "";
    var at = href.indexOf("#");
    return at >= 0 ? data.byAnchor[href.slice(at + 1)] || null : null;
  }

  document.addEventListener("DOMContentLoaded", function () {
    setupAdv();
    setupCopy();
    setupFold();
    setupFilters();
    setupExplorer();
    setupChanges();
    if (window.matchMedia("(hover: hover)").matches) hoverCard("a.hmp-toml-ref", keyOfLink);
    openHash();
  });
  window.addEventListener("hashchange", openHash);
  window.hmpHoverCard = hoverCard;
})();
