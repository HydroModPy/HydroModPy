// Site chrome (loaded by _ext/hmp_site.py on every page).
(function () {
  "use strict";

  // Long dotted names in the page contents break after a dot, not mid-word.
  function breakAfterDots() {
    document.querySelectorAll(".bd-sidebar-secondary .toc-entry .pre, .bd-sidebar-secondary .toc-entry code").forEach(function (el) {
      el.childNodes.forEach(function (node) {
        if (node.nodeType === 3 && node.nodeValue.indexOf(".") >= 0 && node.nodeValue.indexOf("​") < 0) {
          node.nodeValue = node.nodeValue.replace(/\./g, ".​");
        }
      });
    });
  }

  // Hover card of the glossary terms. The cards come from _static/hmp-glossary.json,
  // written at build time. The card machinery is hmp.js (window.hmpHoverCard): it shows
  // on hover and on focus, stays while the pointer is on it, and Escape closes it. On a
  // touch screen the first tap shows the card and a second tap on the same term follows
  // the link, so the definition is read before the page changes. Without script the term
  // is an ordinary link to the glossary.
  var TERM = 'a.reference.internal[href*="#term-"]';

  function contentRoot() {
    var root = document.documentElement.dataset.content_root;
    if (root === undefined && window.DOCUMENTATION_OPTIONS) root = DOCUMENTATION_OPTIONS.URL_ROOT;
    return root || "";
  }

  function fire(link, type) {
    link.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
  }

  function termCards() {
    if (!window.hmpHoverCard || !document.querySelector(TERM)) return;
    var cards = null;
    fetch(contentRoot() + "_static/hmp-glossary.json")
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (json) { cards = json; }, function () { /* the links stay plain */ });
    window.hmpHoverCard(TERM, function (link) {
      var href = link.getAttribute("href") || "";
      var at = href.indexOf("#");
      return cards && at >= 0 ? cards[href.slice(at + 1)] || null : null;
    });

    var touch = window.matchMedia("(hover: none)");
    var armed = null;
    document.addEventListener("click", function (ev) {
      var link = ev.target.closest && ev.target.closest(TERM);
      if (link && touch.matches && cards) {
        if (armed !== link) {
          ev.preventDefault();
          if (armed) fire(armed, "mouseout");
          armed = link;
          fire(link, "mouseover");
        } else {
          armed = null;
        }
        return;
      }
      if (armed && !(ev.target.closest && ev.target.closest(".hmp-hover"))) {
        fire(armed, "mouseout");
        armed = null;
      }
    }, true);
  }

  function init() {
    breakAfterDots();
    termCards();
  }

  // A deferred script runs while readyState is "interactive", before DOMContentLoaded:
  // wait for the event so hmp.js, which defines hmpHoverCard, has run as well.
  if (document.readyState === "complete") {
    init();
  } else {
    document.addEventListener("DOMContentLoaded", init);
  }
})();
