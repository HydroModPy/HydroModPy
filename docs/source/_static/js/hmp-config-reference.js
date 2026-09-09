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
    var LEVEL_ORDER = ["user", "dev", "expert"];

    function applyLevel(level, persist) {
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
        updateFilteredGroups();
        if (persist === false) return;
        try {
            localStorage.setItem(STORAGE_KEY, level);
        } catch (e) {
            /* localStorage may be disabled (private mode); ignore. */
        }
    }

    function currentLevel() {
        var body = document.body;
        if (!body) return DEFAULT_LEVEL;
        for (var i = LEVEL_ORDER.length - 1; i >= 0; i--) {
            if (body.classList.contains(BODY_CLASSES[LEVEL_ORDER[i]])) {
                return LEVEL_ORDER[i];
            }
        }
        return DEFAULT_LEVEL;
    }

    /* The deepest profile level required to see `el`.
     *
     * A field block is hidden with `display: none` by the level classes, so a
     * deep link, a search hit or a browser Find landing on a dev/expert field
     * used to show nothing at all.
     *
     * The ancestor chain is the answer whenever `el` sits inside a field. An
     * anchor that does not -- a bare `<span id="index-N">` between two blocks,
     * were sphinx ever to place one there -- has nothing above it to read, so
     * the following block is consulted instead. Doing that unconditionally
     * would be wrong: a dev field followed by an expert one would report
     * expert, and updateFilteredGroups would then count it as hidden at the
     * dev level. */
    function levelOfChain(start) {
        var deepest = 0;
        var node = start;
        while (node && node.classList) {
            if (node.classList.contains("hmp-field-level-expert")) {
                deepest = Math.max(deepest, 2);
            } else if (node.classList.contains("hmp-field-level-dev")) {
                deepest = Math.max(deepest, 1);
            }
            node = node.parentElement;
        }
        return deepest;
    }

    function requiredLevel(el) {
        if (el.closest && el.closest(".hmp-field")) {
            return LEVEL_ORDER[levelOfChain(el)];
        }
        var deepest = levelOfChain(el);
        if (el.nextElementSibling) {
            deepest = Math.max(deepest, levelOfChain(el.nextElementSibling));
        }
        return LEVEL_ORDER[deepest];
    }

    var LEVEL_LABELS = { user: "User", dev: "User + Dev", expert: "All" };

    /* Annotate the collapsible field groups with what the current profile level
     * is hiding.
     *
     * A nested block can be tagged `user` while every field inside it is `dev`:
     * `transport.modpath.parameters` is the clearest case, and 13 of the 171
     * dropdowns in the reference are in that situation. The dropdown then opens
     * onto nothing, which reads as a broken page rather than as a filter doing
     * its job. Each group now carries a count of what is filtered out, and a
     * group that is entirely filtered says so and offers the level that reveals
     * it. */
    function updateFilteredGroups() {
        var current = LEVEL_ORDER.indexOf(currentLevel());
        document.querySelectorAll("details.sd-dropdown").forEach(function (details) {
            var body = details.querySelector(".sd-summary-content");
            if (!body) return;
            var fields = body.querySelectorAll(":scope > .hmp-field");
            if (!fields.length) return;

            var hidden = 0;
            var deepest = 0;
            fields.forEach(function (field) {
                var needed = LEVEL_ORDER.indexOf(requiredLevel(field));
                if (needed > current) {
                    hidden += 1;
                    deepest = Math.max(deepest, needed);
                }
            });

            var summary = details.querySelector(".sd-summary-text");
            if (summary) {
                var counter = summary.querySelector(".hmp-hidden-count");
                if (hidden > 0) {
                    if (!counter) {
                        counter = document.createElement("span");
                        counter.className = "hmp-hidden-count";
                        summary.appendChild(counter);
                    }
                    counter.textContent =
                        hidden + (hidden > 1 ? " fields hidden" : " field hidden");
                    counter.hidden = false;
                } else if (counter) {
                    counter.hidden = true;
                }
            }

            var notice = body.querySelector(".hmp-level-notice");
            if (hidden === fields.length) {
                if (!notice) {
                    notice = document.createElement("p");
                    notice.className = "hmp-level-notice";
                    body.insertBefore(notice, body.firstChild);
                }
                var target = LEVEL_ORDER[deepest];
                notice.textContent =
                    "Every field in this block is " +
                    target +
                    "-level. ";
                var button = document.createElement("button");
                button.type = "button";
                button.className = "hmp-level-notice-btn";
                button.textContent = "Show " + LEVEL_LABELS[target];
                button.addEventListener("click", function (event) {
                    event.preventDefault();
                    event.stopPropagation();
                    applyLevel(target, true);
                });
                notice.appendChild(button);
                notice.hidden = false;
            } else if (notice) {
                notice.hidden = true;
            }
        });
    }

    function openAncestorDetails(el) {
        var node = el;
        while (node) {
            if (node.tagName === "DETAILS" && !node.open) node.open = true;
            node = node.parentElement;
        }
    }

    /* Make whatever the URL fragment points at actually visible: raise the
     * profile level if the target is filtered out, and open every collapsed
     * dropdown above it. The level is raised for this view only and is not
     * written to localStorage, so following one deep link does not silently
     * change the reader's preference on every other page. */
    function revealHashTarget() {
        var raw = window.location.hash;
        if (!raw || raw.length < 2) return;
        var id;
        try {
            id = decodeURIComponent(raw.slice(1));
        } catch (e) {
            id = raw.slice(1);
        }
        var target = document.getElementById(id);
        if (!target) return;
        var needed = requiredLevel(target);
        if (LEVEL_ORDER.indexOf(needed) > LEVEL_ORDER.indexOf(currentLevel())) {
            applyLevel(needed, false);
        }
        openAncestorDetails(target);
        if (target.scrollIntoView) target.scrollIntoView();
    }

    /* Paper has no toggle and no way to expand a dropdown, so print
     * everything. @media print handles the level classes; the collapsed
     * <details> elements need JS because a closed <details> hides its content
     * through the UA stylesheet, which a print rule cannot reliably override. */
    function bindPrintExpansion() {
        var reopened = [];
        window.addEventListener("beforeprint", function () {
            reopened = [];
            document.querySelectorAll("details:not([open])").forEach(function (el) {
                el.open = true;
                reopened.push(el);
            });
        });
        window.addEventListener("afterprint", function () {
            reopened.forEach(function (el) {
                el.open = false;
            });
            reopened = [];
        });
    }

    function bindLevelButtons() {
        document
            .querySelectorAll(".hmp-level-toggle .hmp-level-btn")
            .forEach(function (btn) {
                btn.addEventListener("click", function () {
                    applyLevel(btn.dataset.level || DEFAULT_LEVEL, true);
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
        applyLevel(initialLevel(), true);
        bindLevelButtons();
        bindAnchorCopy();
        buildBreadcrumb();
        buildTomlChiplets();
        bindPrintExpansion();
        revealHashTarget();
        window.addEventListener("hashchange", revealHashTarget);
    });
})();
