Build a frontend
================

HydroModPy is a Python library. It ships no HTTP server, no FastAPI binding and
no websocket. It exposes two stable hooks that any frontend (Angular, React, a
Jupyter widget, a desktop app) can use without importing the package:

1. a JSON Schema export of the whole configuration;
2. a check of the document the form holds, which may still be incomplete.

The code is in ``hydromodpy/schema/config_schema.py`` and
``hydromodpy/config/check.py``. The pattern behind it is a Pydantic model plus
an exported schema: the structure is declared once, in Python, and the UI never
copies it.

The schema export
-----------------

``hmp config schema --bundle --to ./schema/`` writes three files:

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

   from hydromodpy import HydroModPyConfig
   from hydromodpy.schema.config_schema import export_full_schema

   export_full_schema("./schema/", root=HydroModPyConfig)

Each field in ``config.json`` keeps what the models declare in
``json_schema_extra`` (the keys of ``FieldMetadata`` in
``hydromodpy/core/config_kit/field_metadata.py``: ``widget_type``, ``unit``,
``display_min``, ``display_max``, ``group``, ``stability``, ``value_docs``) and
carries its visibility in ``x-hmp-profile`` (``user``, ``dev`` or ``expert``), so
a form can hide the developer and expert fields. These annotations are the
contract between the models and the UI. Honor them and you need no mapping
layer. They are added to a field as described in :doc:`add-a-config-field`.

The contract of the schema is its property paths, their types and their
annotations. The names under ``$defs`` are not part of it. They are the names of
Python classes, and a class can be renamed in any version without any TOML key
changing, so follow a ``$ref`` and never match on the name it points to. The
document holds no package version: its ``$id`` is ``urn:hmp:schema:<scope>``, so
two releases that leave the models alone export the same bytes. Which changes of
a key each version number allows is in :doc:`/about/versions`.

A second schema file is committed under ``docs/source/_static/`` and published
with the site: ``hydromodpy-schema.json``, the editor schema. It accepts what
the loader reads: ``base_config``, the ``__append``, ``__delete`` and
``__merge`` directives, quantities written as text with a unit, bare dates and
files that omit required keys. ``hmp config schema --editor`` and
``python -m tools.docs.schema_export`` write it, and
``tests/unit/docs/test_docs_config_consistency.py`` keeps it equal to what the
code exports. A frontend that needs the required keys and the strict unions
reads the model schema instead: ``hmp config schema``, or the three files of
``hmp config schema --bundle --to DIR``.

The check of a document
-----------------------

``check(document, partial=True)`` is the call your form makes each time the
document changes. It takes the document as a mapping, the same tree a TOML file
gives, reads no file and asks no network, and it is meant to answer in under
10 ms when warm. From Python:

.. code-block:: python

   from hydromodpy.config.check import check, phrase


   def on_change(document: dict):
       for d in check(document):
           show(d.path, d.severity, phrase(d.code, "fr"), d.detail)

It walks the sections one by one with the validator the loader uses, so it
gives every diagnostic at once and not only the first. Each ``Diagnostic`` holds
the ``path`` of the key as the document spells it, a ``code``, a ``severity``,
the ``detail`` the validator gave for this case, the ``help`` text of the field
and the ``line`` when the document was read from a file. The ``phrase`` of a code
is read in English or French from ``hydromodpy/schema/phrases.toml``, so the form
writes the sentence in its own language. A solver that comes from a plugin has no
phrase of its own, so its keys get the description of the field as the sentence.

The severity is ``error``, ``warning`` or ``to_fill``. A ``to_fill`` is a key the
document must hold and does not hold yet. Your form shows it as a field to fill.
Rules that read several sections wait until every section they
read is complete, and they say nothing before. ``partial=False`` turns each
``to_fill`` into an ``error``, which is what a run needs. ``inputs=True`` also reads
the header of each input file, a local path or an URL, and nothing else. It is
slower, so keep it for the submit button.

A frontend that is not written in Python gives the document to the command line,
or to any transport the integrator chooses:

.. code-block:: bash

   hmp config check --partial --format json draft.toml

The output is ``{ok, diagnostics, workspace}``, and each entry of ``diagnostics`` has
the keys of ``Diagnostic``. There is no check of one field on its own. Send the
document, so a rule that crosses two sections is seen.

A form on the schema
--------------------

Angular applications usually pair the schema with ``ngx-formly`` or
``@rjsf/core``. Export the schema at each HydroModPy release and serve
``config.json`` as a static asset:

.. code-block:: bash

   hmp config schema --bundle --to ./src/app/api/schema/

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
4. Results come back through the project: open it with
   ``hmp.open(project_dir)`` and read its runs with ``proj.runs()``. Expose the
   metrics, figures and exports the UI needs.

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
- A smoke call of ``check`` on a complete document, a document with a key left
  out and a document with a wrong value, at each release. The first gives no
  ``error``, the second a ``to_fill`` at that key, the third an ``error``.

See also
--------

- :doc:`../packages/schema` for the schema package map.
- :doc:`add-a-config-field` for the annotations the frontend reads.
- :doc:`/reference/parameters/explorer` for the interactive browser of the same
  models.
