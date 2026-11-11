# config

The root of the configuration. `HydroModPyConfig` is the one Pydantic model that aggregates every section of a project TOML file, and anything a user can write in a project file must load through it and round-trip. The package is thin on purpose. Each section model lives next to the code it configures, and this package is the only place where the section types of the other packages are imported together. Every other layer refers to its own section model, never to the root.

`loading.py` is the one place that reads a configuration, from a path, a mapping or JSON text, and it applies the same migration and the same refusals to each form. `check.py` gives every diagnostic of a document at once, and `from_toml` is that check followed by the building of the root. `cross_checks.py` holds the rules that read several sections, including the checks of a document against the traits that its flow solver supports. `config_migration.py` loads a file written against an earlier grammar.

`config` reads every layer it composes and nothing above them. Only the root facade, `workflow`, `project` and `cli` read it. A lower layer receives the root model or class as an argument, and `calibration` loads configuration through `trial_pipeline()`.

The page of the package in the developer docs lists the modules and tells how a TOML file becomes a validated object, which section is owned by which package and where to add what.
