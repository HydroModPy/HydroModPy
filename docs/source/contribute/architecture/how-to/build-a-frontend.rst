Build a frontend
================

HydroModPy is a Python library. Its wheel ships no HTTP server, no FastAPI binding
and no websocket. A source checkout carries a thin HTTP layer beside the wheel,
``hydromodpy_server``, which :doc:`serve-over-http` describes. The library exposes
two stable hooks that any frontend (Angular, React, a Jupyter widget, a desktop
app) can use without importing the package:

1. a JSON Schema export of the whole configuration;
2. a check of the document the form holds, which may still be incomplete.

A third piece plays the run: the run request, one JSON object that ``hmp run`` reads, that the
Python call ``hmp.run`` takes as a mapping, and that a Docker container receives as a file.

The fifteen verbs of ``hydromodpy.project.api`` are typed for a service. Each parameter is text,
a number, a boolean, a path, a literal, a mapping or a list of those, and each value a verb
returns has ``to_dict()``, which ``json.dumps`` writes, or is a path, a list of paths or a list of
diagnostics. ``hmp.run`` returns the ``RunOutcome`` of the run, ``hmp.status`` the outcomes of a
project, and ``hmp.show(ref, what=..., save=path)`` writes what it reads to a file. A verb never
looks for a project above the working directory, so a service passes ``workspace=`` or a path.

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

``check(document, base=folder, partial=True)`` is the call your form makes each time the
document changes. It takes the document as a mapping, the same tree a TOML file
gives, reads no file and asks no network, and it is meant to answer in under
10 ms when warm. The ``base`` is the folder the relative paths of the document are read from.
A document in memory has no folder of its own, so the call has no default for it and never
reads the current folder. From Python:

.. code-block:: python

   from hydromodpy.config.check import check, phrase


   def on_change(document: dict):
       for d in check(document, base=project_dir):
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

   hmp check --partial --format json draft.toml

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

The run request
---------------

A request is the unit of work of a run, whether it comes from a TOML file, a Python call, a
server or a container. It is a JSON object of the schema ``hydromodpy.request.v1``, and
``RunRequest.model_json_schema()`` of ``hydromodpy.project.request`` describes it. The site
publishes that schema as ``_static/hydromodpy-request-schema.json``.

.. code-block:: text

   {
     "schema": "hydromodpy.request.v1",
     "config": {"workflow": {"mode": "simulation"}, "geographic": {...}, "flow": {...}},
     "set": {"flow.param.K.field.value": 2e-5},
     "name": "baseline"
   }

``schema`` and ``config`` are required. ``config`` holds the whole document, the same tree a TOML
file gives, with its ``base_config`` chain and its overlays already merged: a ``base_config`` key
in it is refused. ``set`` holds dotted changes applied once at the load, and the other members
are the options of ``hmp run`` (``name``, ``resume``, ``from_step``, ``until_step``, ``force``,
``fresh``, ``frozen``, ``dry_run``, ``phase``). A JSON file without ``schema`` is refused with a
sentence that says to put the document under ``config``.

The request does not hold the base of the relative paths, and it does not hold the environment
(credentials, allowed hosts, download limit). Both are arguments of the call, so the same request
plays on any machine. The base is ``--base DIR`` on the command line and ``base=`` in Python. A
request read from a file under a project folder takes that project as its base when none is
given. A request given as a mapping or as text needs a base, and without one it is refused.
Relative paths never read the current folder.

The run writes the request it played as ``request.json`` in its folder, whole and never
redacted, and writes its ``request_id`` in ``outcome.json``. Two requests with the same
``request_id`` ask the same thing, whatever the paths and the names they use. A run identical to a
completed one is given back instead of computed, and the answer names that run.

Submission flow
---------------

1. The frontend builds the document from the form values, keeping the section structure
   (``[flow]``, ``[geographic]``, ...), and puts it under ``config`` of a request.
2. A thin service you write receives the request and writes it into the project folder. It then
   calls ``hmp run request.json --base <project>``, or ``hmp.run(document, base=<project>)`` from
   Python. In a container the command is
   ``docker run <image> run /project/request.json --base /project``, with the project mounted at
   ``/project``.
3. The service returns the run name and its ``request_id`` to the frontend, which polls the
   ``outcome.json`` of the run.

   The server of :doc:`serve-over-http` does steps 2 and 3 for you. The frontend posts the
   request to ``/v1/<org>/<project>/run``, the server plays it in its own process and answers
   with a job, and the job gives the ``RunOutcome`` once the run ends.
4. Results come back through the verbs: ``hmp.status(workspace=project_dir)`` lists the
   outcomes, ``hmp.show(name, what=..., workspace=project_dir, save=path)`` writes a summary, a
   table, a figure or a report, and ``hmp.export`` writes the files. ``hmp.open(project_dir)``
   gives the ``Project`` for a Python caller. Expose the metrics, figures and exports the UI needs.

What HydroModPy does not ship
-----------------------------

- No HTTP server in the wheel. The repository keeps ``hydromodpy_server`` beside it, on the
  Python standard library only, with no authentication of its own.
- No FastAPI, uvicorn or websocket dependency.
- No OpenAPI endpoint: the exported JSON Schemas are the contract.
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

- :doc:`serve-over-http` for the HTTP layer of the repository.
- :doc:`../packages/schema` for the schema package map.
- :doc:`add-a-config-field` for the annotations the frontend reads.
- :doc:`/reference/parameters/explorer` for the interactive browser of the same
  models.
