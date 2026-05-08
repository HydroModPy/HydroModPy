/* ----------------------------------------------------------------------
 * Configuration reference: profile toggle + click-to-copy anchors.
 * Loaded on every doc page; safely no-ops on pages without the markup.
 * ---------------------------------------------------------------------- */

(function () {
    "use strict";

    var STORAGE_KEY = "hmp.configReference.level";
    var BODY_CLASSES = {
        user: "hmp-show-user",
        dev: "hmp-show-dev",
        expert: "hmp-show-expert",
    };
    var DEFAULT_LEVEL = "user";

    function applyLevel(level) {
        var body = document.body;
        if (!body) return;
        Object.values(BODY_CLASSES).forEach(function (cls) {
            body.classList.remove(cls);
        });
        var cls = BODY_CLASSES[level];
        if (cls) body.classList.add(cls);
        document
            .querySelectorAll(".hmp-level-toggle .hmp-level-btn")
            .forEach(function (btn) {
                var isActive = btn.dataset.level === level;
                btn.classList.toggle("is-active", isActive);
            });
        try {
            localStorage.setItem(STORAGE_KEY, level);
        } catch (e) {
            /* localStorage may be disabled (private mode); ignore. */
        }
    }

    function bindLevelButtons() {
        document
            .querySelectorAll(".hmp-level-toggle .hmp-level-btn")
            .forEach(function (btn) {
                btn.addEventListener("click", function () {
                    applyLevel(btn.dataset.level || DEFAULT_LEVEL);
                });
            });
    }

    function initialLevel() {
        try {
            var stored = localStorage.getItem(STORAGE_KEY);
            if (stored && BODY_CLASSES[stored]) return stored;
        } catch (e) {
            /* ignore */
        }
        return DEFAULT_LEVEL;
    }

    function bindAnchorCopy() {
        document.querySelectorAll(".hmp-field[id]").forEach(function (el) {
            el.addEventListener("click", function (event) {
                if (event.target.closest("a, button, summary, input, select")) {
                    return;
                }
                var anchorTarget = event.target.closest(".hmp-field");
                if (!anchorTarget || anchorTarget !== el) return;
                if (event.detail !== 2) return;
                var url =
                    window.location.origin +
                    window.location.pathname +
                    "#" +
                    el.id;
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(url).catch(function () {});
                }
                history.replaceState(null, "", "#" + el.id);
            });
        });
    }

    function buildBreadcrumb() {
        var firstField = document.querySelector(".hmp-field[data-toml-path]");
        if (!firstField) return;
        var pathRoot = firstField.dataset.tomlPath.split(".")[0];
        if (!pathRoot) return;
        var anchor = document.querySelector(".hmp-config-fields");
        if (!anchor || anchor.previousElementSibling?.classList.contains("hmp-toml-breadcrumb")) {
            return;
        }
        var crumb = document.createElement("nav");
        crumb.className = "hmp-toml-breadcrumb";
        crumb.setAttribute("aria-label", "TOML path");
        crumb.innerHTML =
            '<span class="hmp-toml-breadcrumb-sep">[</span>' +
            '<a href="index.html">config</a>' +
            '<span class="hmp-toml-breadcrumb-sep"> / </span>' +
            '<a href="' + pathRoot + '.html">' + pathRoot + "</a>" +
            '<span class="hmp-toml-breadcrumb-sep">]</span>';
        anchor.parentNode.insertBefore(crumb, anchor);
    }

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function buildTomlChiplets() {
        // Replace each <code class="hmp-field-toml">[a.b.<c>]</code> by a
        // chiplet trail. Chips for static segments link back to the section
        // page anchor; dynamic placeholders (<id>, <name>) keep a distinct
        // style and no link.
        var pageRoot = (document.body.dataset.pageRoot || "").trim();
        document
            .querySelectorAll("code.hmp-field-toml")
            .forEach(function (codeEl) {
                if (codeEl.dataset.chipped === "1") return;
                var raw = (codeEl.textContent || "").trim();
                var match = raw.match(/^(\[+)([^\]]+)(\]+)$/);
                if (!match) return;
                var openB = match[1];
                var path = match[2];
                var closeB = match[3];
                var segments = path.split(".");
                if (!segments.length) return;
                if (!pageRoot) pageRoot = segments[0];

                var anchorParts = [];
                var html = '<span class="hmp-toml-chips">';
                html +=
                    '<span class="hmp-toml-bracket">' +
                    escapeHtml(openB) +
                    "</span>";
                segments.forEach(function (seg, index) {
                    var isDynamic = seg.indexOf("<") === 0;
                    if (index > 0) {
                        html +=
                            '<span class="hmp-toml-sep" aria-hidden="true">›</span>';
                    }
                    if (isDynamic) {
                        html +=
                            '<span class="hmp-toml-chip hmp-toml-chip-dyn">' +
                            escapeHtml(seg) +
                            "</span>";
                    } else {
                        anchorParts.push(
                            seg.toLowerCase().replace(/_/g, "-")
                        );
                        var anchor = anchorParts.join("-");
                        var page = pageRoot + ".html";
                        html +=
                            '<a class="hmp-toml-chip" href="' +
                            page +
                            "#" +
                            anchor +
                            '">' +
                            escapeHtml(seg) +
                            "</a>";
                    }
                });
                html +=
                    '<span class="hmp-toml-bracket">' +
                    escapeHtml(closeB) +
                    "</span></span>";
                codeEl.outerHTML = html;
            });
    }

    document.addEventListener("DOMContentLoaded", function () {
        applyLevel(initialLevel());
        bindLevelButtons();
        bindAnchorCopy();
        buildBreadcrumb();
        buildTomlChiplets();
    });
})();
