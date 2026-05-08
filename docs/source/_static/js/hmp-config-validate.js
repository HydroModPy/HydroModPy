/* ----------------------------------------------------------------------
 * Configuration reference: in-browser TOML pre-flight.
 *
 * Tries to load Ajv 2020 + smol-toml from the jsdelivr ESM CDN to run a
 * real JSON Schema 2020-12 validation against the parsed TOML. When the
 * CDN is unreachable (offline build, sandbox, restricted network) the
 * widget falls back to a structural check (top-level section in schema,
 * required-fields hint).
 *
 * The Python validator (`hmp validate`) remains the source of truth: this
 * widget only catches typos before launch.
 * ---------------------------------------------------------------------- */

(function () {
    "use strict";

    var SCHEMA_URL_REL = "../../_static/hydromodpy-schema.json";
    var AJV_ESM_URL = "https://cdn.jsdelivr.net/npm/ajv@8.17.1/dist/2020.min.js";
    var SMOL_TOML_ESM_URL = "https://cdn.jsdelivr.net/npm/smol-toml@1.4.2/+esm";
    var MAX_AJV_ERRORS = 25;

    function loadModule(url) {
        return import(/* webpackIgnore: true */ url);
    }

    function loadAjv() {
        // Ajv 2020 ships a UMD bundle, not native ESM. Use the +esm wrapper
        // first; if jsdelivr stripped the helper, fall back to a tag inject.
        return loadModule("https://cdn.jsdelivr.net/npm/ajv@8.17.1/+esm")
            .then(function (mod) {
                return mod.default ? mod.default : mod.Ajv2020 || mod.Ajv;
            })
            .catch(function () {
                return injectScript(AJV_ESM_URL).then(function () {
                    if (window.Ajv2020) return window.Ajv2020;
                    if (window.ajv2020) return window.ajv2020;
                    if (window.Ajv) return window.Ajv;
                    throw new Error("Ajv2020 global not exposed");
                });
            });
    }

    function injectScript(url) {
        return new Promise(function (resolve, reject) {
            var script = document.createElement("script");
            script.src = url;
            script.async = true;
            script.onload = resolve;
            script.onerror = function () {
                reject(new Error("script load failed: " + url));
            };
            document.head.appendChild(script);
        });
    }

    function loadSmolToml() {
        return loadModule(SMOL_TOML_ESM_URL).then(function (mod) {
            if (typeof mod.parse === "function") return mod.parse;
            if (mod.default && typeof mod.default.parse === "function") {
                return mod.default.parse;
            }
            throw new Error("smol-toml.parse not found");
        });
    }

    function tokenizeFallback(input) {
        var lines = input.split(/\r?\n/);
        var sections = [];
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].replace(/\s+#.*$/, "").trim();
            if (!line || line.startsWith("#")) continue;
            var m = line.match(/^\[\[?([\w.-]+)\]?\]$/);
            if (m) sections.push({ name: m[1], line: i + 1 });
        }
        return sections;
    }

    function checkStructural(schema, input) {
        if (!input.trim()) return ["(empty)"];
        var sections = tokenizeFallback(input);
        var top = Object.keys((schema && schema.properties) || {});
        var topSet = {};
        top.forEach(function (k) {
            topSet[k] = true;
        });
        var errors = [];
        sections.forEach(function (sec) {
            var first = sec.name.split(".")[0];
            if (!topSet[first]) {
                errors.push(
                    "L" + sec.line +
                        ": unknown top-level section [" + sec.name +
                        "] (root '" + first + "' is not in the schema)"
                );
            }
        });
        return errors.length
            ? errors
            : ["Looks structurally OK (" + sections.length + " sections). " +
               "Run `hmp validate project.toml` for full Pydantic validation."];
    }

    function formatAjvErrors(errors) {
        if (!errors || !errors.length) return ["OK: payload validates against the schema."];
        var out = [];
        var limit = Math.min(errors.length, MAX_AJV_ERRORS);
        for (var i = 0; i < limit; i++) {
            var err = errors[i];
            var path = err.instancePath || "(root)";
            var msg = err.message || "invalid";
            if (err.params && err.params.additionalProperty) {
                msg += " '" + err.params.additionalProperty + "'";
            } else if (err.params && err.params.allowedValues) {
                msg += " (allowed: " + err.params.allowedValues.join(", ") + ")";
            } else if (err.params && err.params.missingProperty) {
                msg = "missing required '" + err.params.missingProperty + "'";
            }
            out.push(path + ": " + msg);
        }
        if (errors.length > limit) {
            out.push("... " + (errors.length - limit) + " more error(s) hidden.");
        }
        return out;
    }

    function checkWithAjv(validate, parseToml, input) {
        if (!input.trim()) return ["(empty)"];
        var parsed;
        try {
            parsed = parseToml(input);
        } catch (err) {
            var loc = err.line ? "L" + err.line + ":" + (err.column || "?") : "";
            return ["TOML parse error " + loc + ": " + (err.message || err)];
        }
        var ok = validate(parsed);
        if (ok) {
            return [
                "OK: TOML parses and validates against the schema.",
                "(Approximate; `hmp validate project.toml` remains authoritative.)",
            ];
        }
        return formatAjvErrors(validate.errors);
    }

    function setStatus(output, lines, kind) {
        output.textContent = lines.join("\n");
        output.dataset.kind = kind || "info";
    }

    function loadCodeMirror() {
        // Load CodeMirror 6 + the legacy stream-mode TOML grammar from the
        // jsdelivr ESM mirror. Returns a builder closure or rejects.
        return Promise.all([
            loadModule("https://esm.sh/codemirror@6.0.1"),
            loadModule("https://esm.sh/@codemirror/state@6.5.0"),
            loadModule("https://esm.sh/@codemirror/view@6.34.1"),
            loadModule("https://esm.sh/@codemirror/language@6.10.6"),
            loadModule("https://esm.sh/@codemirror/legacy-modes@6.4.2/mode/toml"),
        ]).then(function (mods) {
            var cm = mods[0];
            var stateMod = mods[1];
            var viewMod = mods[2];
            var langMod = mods[3];
            var tomlMod = mods[4];
            return function buildEditor(parent, initial) {
                var doc = initial || "";
                var view = new viewMod.EditorView({
                    parent: parent,
                    state: stateMod.EditorState.create({
                        doc: doc,
                        extensions: [
                            cm.basicSetup,
                            langMod.StreamLanguage.define(tomlMod.toml),
                        ],
                    }),
                });
                return {
                    get: function () {
                        return view.state.doc.toString();
                    },
                    set: function (text) {
                        view.dispatch({
                            changes: {
                                from: 0,
                                to: view.state.doc.length,
                                insert: text || "",
                            },
                        });
                    },
                    focus: function () {
                        view.focus();
                    },
                    destroy: function () {
                        view.destroy();
                    },
                };
            };
        });
    }

    function makeTextareaAdapter(input) {
        return {
            get: function () {
                return input.value;
            },
            set: function (text) {
                input.value = text || "";
            },
            focus: function () {
                input.focus();
            },
        };
    }

    function init() {
        var input = document.getElementById("hmp-validate-input");
        var output = document.getElementById("hmp-validate-output");
        var run = document.getElementById("hmp-validate-run");
        var clear = document.getElementById("hmp-validate-clear");
        if (!input || !output || !run || !clear) return;

        run.disabled = true;
        var schema = null;
        var ajvValidate = null;
        var parseToml = null;
        var editor = makeTextareaAdapter(input);
        var mode = "loading";

        function refreshButtonLabel() {
            if (mode === "ajv") run.textContent = "Validate (Ajv 2020)";
            else if (mode === "structural") run.textContent = "Validate structure";
            else run.textContent = "Loading...";
        }
        refreshButtonLabel();

        function tryUpgradeEditor() {
            loadCodeMirror()
                .then(function (build) {
                    var host = document.createElement("div");
                    host.className = "hmp-validate-editor";
                    host.dataset.placeholder =
                        input.getAttribute("placeholder") || "";
                    input.parentNode.insertBefore(host, input);
                    var initial = input.value;
                    input.style.display = "none";
                    editor = build(host, initial);
                })
                .catch(function () {
                    // Keep the textarea adapter; coloured editor is optional.
                });
        }

        var schemaPromise = fetch(SCHEMA_URL_REL)
            .then(function (resp) {
                if (!resp.ok) throw new Error("HTTP " + resp.status);
                return resp.json();
            })
            .then(function (json) {
                schema = json;
            });

        schemaPromise
            .then(function () {
                return Promise.all([loadAjv(), loadSmolToml()]);
            })
            .then(function (results) {
                var Ajv = results[0];
                parseToml = results[1];
                var ajv = new Ajv({
                    allErrors: true,
                    strict: false,
                    validateFormats: false,
                });
                ajvValidate = ajv.compile(schema);
                mode = "ajv";
                run.disabled = false;
                refreshButtonLabel();
                tryUpgradeEditor();
            })
            .catch(function (err) {
                if (schema) {
                    mode = "structural";
                    run.disabled = false;
                    refreshButtonLabel();
                    setStatus(
                        output,
                        [
                            "Loaded structural mode only (" + (err.message || err) + ").",
                            "Schema validation falls back to top-level section checks.",
                        ],
                        "warn"
                    );
                    tryUpgradeEditor();
                } else {
                    setStatus(
                        output,
                        ["Schema could not load: " + (err.message || err)],
                        "error"
                    );
                }
            });

        run.addEventListener("click", function () {
            var value = editor.get();
            if (mode === "ajv" && ajvValidate && parseToml) {
                setStatus(output, checkWithAjv(ajvValidate, parseToml, value), "info");
            } else if (mode === "structural" && schema) {
                setStatus(output, checkStructural(schema, value), "warn");
            } else {
                setStatus(output, ["Validators are still loading..."], "info");
            }
        });

        clear.addEventListener("click", function () {
            editor.set("");
            output.textContent = "";
            output.dataset.kind = "";
            editor.focus();
        });
    }

    document.addEventListener("DOMContentLoaded", init);
})();
