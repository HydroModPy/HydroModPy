schema
======

``hydromodpy.schema`` exposes the JSON Schema export and the
partial-field validator that any frontend (Streamlit, Angular,
React, Jupyter widget) consumes. It is the only public, stable
contract for non-Python integrations.

Sub-modules
-----------

- ``schema/export.py`` -- ``export_full_schema(output_dir)`` writes
  three JSON files under ``output_dir/``:

  - ``config.json`` -- full JSON Schema of ``HydroModPyConfig``;
  - ``config_meta.json`` -- ordered TOML sections, UI groups,
    titles;
  - ``field_validators.json`` -- flat
    ``field_path -> validator_type`` (enum, number, date, ...).

- ``schema/partial_validator.py`` -- ``validate_field(path,
  value)`` resolves the dotted path on ``HydroModPyConfig``, picks
  the matching ``pydantic.TypeAdapter``, and returns a lightweight
  ``ValidationResult``. Lookups are memoised, runs under 50 ms.

Annotations carried by the schema
---------------------------------

Each field of ``config.json`` keeps the ``json_schema_extra``
annotations declared by the Pydantic models:

- ``widget_type`` (``slider``, ``text``, ``select``, ``date``,
  ``file``, ``map``);
- ``unit`` (canonical SI: ``m``, ``m/s``, ``1/m``);
- ``display_name_fr`` and ``display_name_en``;
- ``help_text_fr`` and ``help_text_en``;
- ``display_min`` and ``display_max`` for sliders;
- ``profile`` (``user`` / ``dev`` / ``expert``).

These annotations are the contract between the Pydantic models and
any UI integration. Honour them and you avoid a custom mapping
layer.

Key public symbols
------------------

- ``hydromodpy.schema.export.export_full_schema``
- ``hydromodpy.schema.partial_validator.validate_field``
- ``hydromodpy.schema.partial_validator.ValidationResult``

CLI bindings
------------

- ``hmp schema export --output ./schema/`` -> three JSON files.
- ``hmp schema validate-field <path> <value>`` -> JSON
  ``ValidationResult``.

Both subcommands live under ``hydromodpy/cli/commands/schema.py``.

Recommended reading path
------------------------

1. ``hydromodpy/schema/export.py``
2. ``hydromodpy/schema/partial_validator.py``
3. The composition root ``hydromodpy/config/hydromodpy_config.py``
   to see what is exported.
4. One model that ships rich annotations (for example
   ``hydromodpy/physics/flow/flow_config.py``).

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``config``.
- Allowed sources: every other layer (the schema export is the
  most central public contract).
- The schema export must stay deterministic. Do not introduce
  side-effects or environment-dependent fields.

See also
--------

- :doc:`/architecture/overview/frontend-hooks` -- design rationale
  for the integration surface.
- :doc:`/architecture/how-to/build-a-frontend` -- step-by-step
  recipe (Streamlit, Angular, React).
- :doc:`/architecture/how-to/add-a-config-field` -- adding a field
  with the annotations the schema consumes.
- :doc:`/user_guide/config_reference/schema_explorer` -- user-facing
  schema viewer.
