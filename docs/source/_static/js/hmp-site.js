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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", breakAfterDots);
  } else {
    breakAfterDots();
  }
})();
