Build a frontend
================

HydroModPy is a Python library. It ships no HTTP server, no FastAPI binding and
no websocket. It exposes two stable hooks that any frontend (Angular, React, a
Jupyter widget, a desktop app) can use without importing the package:

1. a JSON Schema export of the whole configuration;
2. a partial validator that checks one field at a time.

The code is in ``hydromodpy/schema/export.py`` and
``hydromodpy/schema/partial_validator.py``. The pattern behind it is a Pydantic
model plus an exported schema: the structure is declared once, in Python, and
the UI never copies it.

The schema export
-----------------

``hmp dev schema export --output ./schema/`` writes three files:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - File
     - Role
   * - ``config.json``
     - Full JSON Schema of ``HydroModPyConfig``.
   * - ``config_meta.json``
     - Ordered TOML sections, UI groups and titles. A section with
       ``repeated: true`` (``[[export]]``) is an array of tables, one block per
       entry, and its ``ref`` names the model of one entry.
   * - ``field_validators.json``
     - Flat mapping from a field path to its validator type.

From Python:

.. code-block:: python

   from hydromodpy.schema import export_full_schema, validate_field

   export_full_schema("./schema/")

Each field in ``config.json`` keeps what the models declare in
``json_schema_extra`` (the keys of ``FieldMetadata`` in
``hydromodpy/core/config_kit/field_metadata.py``: ``widget_type``, ``unit``,
``display_min``, ``display_max``, ``group``, ``stability``, ``value_docs``) and
carries its visibility in ``x-hmp-profile`` (``user``, ``dev`` or ``expert``), so
a form can hide the developer and expert fields. These annotations are the
contract between the models and the UI. Honour them and you need no mapping
layer. They are added to a field as described in :doc:`add-a-config-field`.

A second schema file is committed under ``docs/source/_static/`` and published
with the site: ``hydromodpy-schema.json``, the editor schema. It accepts what
the loader reads: ``base_config``, the ``__append``, ``__delete`` and
``__merge`` directives, quantities written as text with a unit, bare dates and
files that omit required keys. ``hmp config schema --editor`` and
``python -m tools.docs.schema_export`` write it, and
``tests/unit/docs/test_docs_config_consistency.py`` keeps it equal to what the
code exports. A frontend that needs the required keys and the strict unions
reads the model schema instead: ``hmp config schema``, or the three files of
``hmp dev schema export``.

The partial validator
---------------------

``hmp dev schema validate-field <path> <value>`` runs the validator your form
should call on each change, in well under 50 ms and without I/O. From Python:

.. code-block:: python

   from hydromodpy.schema import validate_field


   def on_change(path: str, value):
       result = validate_field(path, value)
       if not result.valid:
           show_error(path, result.error)

It resolves the dotted path on ``HydroModPyConfig``, picks the matching
``pydantic.TypeAdapter`` and returns a ``ValidationResult`` with ``valid``,
``error``, ``warnings`` and ``dependent_fields_affected``. Lookups are memoised,
so a repeated call on the same path is free. A frontend that is not written in
Python reaches it through the CLI in a subprocess, or through any transport the
integrator chooses.

A form on the schema
--------------------

Angular applications usually pair the schema with ``ngx-formly`` or
``@rjsf/core``. Export the schema at each HydroModPy release and serve
``config.json`` as a static asset:

.. code-block:: bash

   hmp dev schema export --output ./src/app/api/schema/

React, with ``@rjsf/core``:

.. code-block:: tsx

   import Form from '@rjsf/core';
   import validator from '@rjsf/validator-ajv8';
   import schema from './schema/config.json';

   export function SchemaForm() {
     return <Form schema={schema} validator={validator} />;
   }

A custom widget can switch on the ``widget_type`` annotation to choose between
an input, a select and a checkbox.

Submission flow
---------------

1. The frontend builds a TOML payload from the form values, keeping the section
   structure (``[flow]``, ``[geographic]``, ...).
2. A thin service you write receives it, writes it to a file and calls
   ``hmp.run`` on that file.
3. The service returns the simulation id to the frontend, which polls it.
4. Results come back through the catalog: open the workspace with
   ``hmp.open(workspace)`` and read the ``Run`` rows. Expose the metrics,
   figures and exports the UI needs.

What HydroModPy does not ship
-----------------------------

- No FastAPI, uvicorn or websocket dependency.
- No OpenAPI endpoint: the exported JSON Schema is the contract.
- No server-sent events. Wire one yourself when a stream is needed.

Any HTTP layer written downstream can rely on these hooks without touching the
core package.

Tests to add
------------

- A unit test for any Python service that wraps the exports.
- A schema diff in your CI: export again and fail on a difference you did not
  commit.
- A smoke call of ``validate_field`` on a few valid and invalid pairs at each
  release.

See also
--------

- :doc:`../packages/schema` for the schema package map.
- :doc:`add-a-config-field` for the annotations the frontend reads.
- :doc:`/reference/parameters/explorer` for the interactive browser of the same
  models.
