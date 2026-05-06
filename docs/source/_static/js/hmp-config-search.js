/* ----------------------------------------------------------------------
 * Configuration reference: scoped Ctrl+F search.
 * Reads _static/hmp-config-search.json (built by tools/doc_config) and
 * renders a small, fast, fuzzy-style match against TOML paths.
 * ---------------------------------------------------------------------- */

(function () {
    "use strict";

    var INDEX_URL_REL = "../../_static/hmp-config-search.json";
    var MAX_RESULTS = 30;

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function highlight(text, query) {
        if (!query) return escapeHtml(text);
        var lower = text.toLowerCase();
        var qlower = query.toLowerCase();
        var idx = lower.indexOf(qlower);
        if (idx === -1) return escapeHtml(text);
        return (
            escapeHtml(text.slice(0, idx)) +
            "<mark>" +
            escapeHtml(text.slice(idx, idx + query.length)) +
            "</mark>" +
            escapeHtml(text.slice(idx + query.length))
        );
    }

    function score(entry, terms) {
        var path = entry.path.toLowerCase();
        var description = (entry.description || "").toLowerCase();
        var total = 0;
        for (var i = 0; i < terms.length; i++) {
            var t = terms[i];
            if (!t) continue;
            if (path.indexOf(t) === -1 && description.indexOf(t) === -1) {
                return -1;
            }
            if (path === t) total += 100;
            else if (path.endsWith("." + t)) total += 60;
            else if (path.indexOf(t) !== -1) total += 30;
            else total += 5;
        }
        return total;
    }

    function render(results, container, query) {
        if (!results.length) {
            container.innerHTML = query
                ? '<div class="hmp-config-search-empty">No match.</div>'
                : "";
            return;
        }
        var html = '<ul class="hmp-config-search-list">';
        for (var i = 0; i < results.length; i++) {
            var r = results[i];
            var url = r.page + "#" + r.anchor;
            var profileBadge =
                '<span class="hmp-config-search-profile hmp-config-search-profile-' +
                r.profile +
                '">' +
                r.profile +
                "</span>";
            html +=
                '<li class="hmp-config-search-item">' +
                '<a href="' +
                escapeHtml(url) +
                '" class="hmp-config-search-link">' +
                '<code class="hmp-config-search-path">' +
                highlight(r.path, query) +
                "</code>" +
                profileBadge +
                '<span class="hmp-config-search-type">' +
                escapeHtml(r.type) +
                "</span>" +
                "</a>";
            if (r.description) {
                html +=
                    '<div class="hmp-config-search-desc">' +
                    escapeHtml(r.description) +
                    "</div>";
            }
            html += "</li>";
        }
        html += "</ul>";
        container.innerHTML = html;
    }

    function debounce(fn, delay) {
        var t;
        return function () {
            var args = arguments;
            var ctx = this;
            clearTimeout(t);
            t = setTimeout(function () {
                fn.apply(ctx, args);
            }, delay);
        };
    }

    function init() {
        var input = document.getElementById("hmp-config-search-input");
        var output = document.getElementById("hmp-config-search-results");
        if (!input || !output) return;

        var index = null;
        function loadIndex() {
            return fetch(INDEX_URL_REL)
                .then(function (resp) {
                    if (!resp.ok) throw new Error("HTTP " + resp.status);
                    return resp.json();
                })
                .then(function (json) {
                    index = json;
                })
                .catch(function (err) {
                    output.innerHTML =
                        '<div class="hmp-config-search-empty">Search index could not load: ' +
                        escapeHtml(err.message) +
                        "</div>";
                });
        }

        function run() {
            if (!index) return;
            var query = input.value.trim();
            if (!query) {
                output.innerHTML = "";
                return;
            }
            var terms = query.toLowerCase().split(/\s+/).filter(Boolean);
            var hits = [];
            for (var i = 0; i < index.length; i++) {
                var s = score(index[i], terms);
                if (s > 0) hits.push({ entry: index[i], score: s });
            }
            hits.sort(function (a, b) {
                return b.score - a.score;
            });
            render(
                hits.slice(0, MAX_RESULTS).map(function (h) {
                    return h.entry;
                }),
                output,
                terms[0]
            );
        }

        loadIndex().then(run);
        input.addEventListener("input", debounce(run, 80));
    }

    document.addEventListener("DOMContentLoaded", init);
})();
