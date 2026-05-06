/* ----------------------------------------------------------------------
 * Configuration reference: in-browser TOML structural pre-flight.
 * Lightweight, schema-aware structure checker. Not a substitute for the
 * Python validator, but catches typos, unknown sections, and bad keys.
 * ---------------------------------------------------------------------- */

(function () {
    "use strict";

    var SCHEMA_URL_REL = "../../_static/hydromodpy-schema.json";

    function tokenize(input) {
        var lines = input.split(/\r?\n/);
        var sections = [];
        var keys = [];
        var currentSection = null;
        for (var i = 0; i < lines.length; i++) {
            var raw = lines[i];
            var line = raw.replace(/\s+#.*$/, "").trim();
            if (!line || line.startsWith("#")) continue;
            var m = line.match(/^\[\[?([\w.-]+)\]?\]$/);
            if (m) {
                currentSection = m[1];
                sections.push({ name: currentSection, line: i + 1 });
                continue;
            }
            var kv = line.match(/^([A-Za-z_][\w-]*)\s*=/);
            if (kv) {
                keys.push({
                    section: currentSection || "(root)",
                    key: kv[1],
                    line: i + 1,
                });
            }
        }
        return { sections: sections, keys: keys };
    }

    function knownTopSections(schema) {
        var props = (schema && schema.properties) || {};
        return Object.keys(props);
    }

    function check(schema, input) {
        if (!input.trim()) return ["(empty)"];
        var parsed = tokenize(input);
        var top = knownTopSections(schema);
        var topSet = {};
        top.forEach(function (k) {
            topSet[k] = true;
        });
        var errors = [];

        parsed.sections.forEach(function (sec) {
            var first = sec.name.split(".")[0];
            if (!topSet[first]) {
                errors.push(
                    "L" +
                        sec.line +
                        ": unknown top-level section [" +
                        sec.name +
                        "] (root '" +
                        first +
                        "' is not in the schema)"
                );
            }
        });

        return errors.length
            ? errors
            : ["Looks structurally OK (" +
                  parsed.sections.length +
                  " sections, " +
                  parsed.keys.length +
                  " keys)."];
    }

    function init() {
        var input = document.getElementById("hmp-validate-input");
        var output = document.getElementById("hmp-validate-output");
        var run = document.getElementById("hmp-validate-run");
        var clear = document.getElementById("hmp-validate-clear");
        if (!input || !output || !run || !clear) return;

        var schema = null;
        fetch(SCHEMA_URL_REL)
            .then(function (resp) {
                if (!resp.ok) throw new Error("HTTP " + resp.status);
                return resp.json();
            })
            .then(function (json) {
                schema = json;
                run.disabled = false;
            })
            .catch(function (err) {
                output.textContent =
                    "Schema could not load: " + err.message;
            });

        run.addEventListener("click", function () {
            if (!schema) {
                output.textContent = "Schema is still loading...";
                return;
            }
            var lines = check(schema, input.value);
            output.textContent = lines.join("\n");
        });

        clear.addEventListener("click", function () {
            input.value = "";
            output.textContent = "";
        });
    }

    document.addEventListener("DOMContentLoaded", init);
})();
