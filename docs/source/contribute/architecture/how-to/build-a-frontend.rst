Build a frontend
================

HydroModPy is a Python library. Its wheel ships no HTTP server, no FastAPI binding and no
websocket. A source checkout carries a thin HTTP layer beside the wheel,
``hydromodpy_server``, which :doc:`serve-over-http` describes. Any frontend (Angular,
React, a Jupyter widget, a desktop app) can use three pieces without importing the package.

1. A JSON Schema export of the whole configuration.
2. A check of the document the form holds, which may still be incomplete.
3. The run request, one JSON object that ``hmp run`` reads, that ``hmp.run`` takes as a
   mapping and that a Docker container receives as a file.

The verbs of ``hydromodpy.project.api`` are typed for a service. Each parameter is text, a
number, a boolean, a path, a literal, a mapping or a list of those. Each value a verb returns
has ``to_dict()``, which ``json.dumps`` writes, or is a path, a list of paths or a list of
diagnostics. A verb never looks for a project above the working directory, so a service
passes ``workspace=`` or a path. The verbs are listed in :doc:`/reference/python/index`.

The schema export
-----------------

``hmp config schema --bundle --to ./schema/`` writes three files. ``config.json`` is the
full JSON Schema of ``HydroModPyConfig``. ``config_meta.json`` holds the ordered TOML
sections, the UI groups and the titles, and a section with ``repeated: true`` (``[[export]]``)
is an array of tables. ``field_validators.json`` maps a field path to its validator type.
From Python:

.. code-block:: python

   from hydromodpy import HydroModPyConfig
   from hydromodpy.schema.config_schema import export_full_schema

   export_full_schema("./schema/", root=HydroModPyConfig)


Each field in ``config.json`` keeps what the models declare in ``json_schema_extra``, the
keys of ``FieldMetadata`` in ``hydromodpy/core/config_kit/field_metadata.py``. It also
carries its visibility in ``x-hmp-profile`` (``user``, ``dev`` or ``expert``), so a form can
hide the developer and expert fields. These annotations are the contract between the models
and the UI, and :doc:`add-a-config-field` shows how a field gets them.

The contract is the property paths, their types and their annotations. The names under
``$defs`` are Python class names that a release may rename, so follow a ``$ref`` and never
match on the name it points to. The document holds no package version, so two releases that
leave the models alone export the same bytes. Which changes of a key each version allows is
in :doc:`/about/versions`.

A second file, ``docs/source/_static/hydromodpy-schema.json``, is the editor schema. It
accepts what the loader reads, such as ``base_config``, the ``__append``, ``__delete`` and
``__merge`` directives, quantities written with a unit and files that omit required keys.
``hmp config schema --editor`` writes it, and
``tests/unit/docs/test_docs_config_consistency.py`` keeps it equal to the code. A frontend
that needs the required keys and the strict unions reads the model schema instead.

The check of a document
-----------------------

``check(document, base=folder, partial=True)`` in ``hydromodpy/config/check.py`` is the call
the form makes at each change. It takes the document as a mapping, reads no file, asks no
network and answers in under 10 ms when warm. The ``base`` is the folder the relative paths
are read from. A document in memory has no folder, so the call never reads the current one.

.. code-block:: python

   from hydromodpy.config.check import check, phrase


   def on_change(document: dict):
       for d in check(document, base=project_dir):
           show(d.path, d.severity, phrase(d.code, "fr"), d.detail)

It walks the sections with the validator the loader uses, so it gives every diagnostic at
once. A ``Diagnostic`` is this dataclass. The ``phrase`` of a code is read in English or
French from ``hydromodpy/schema/phrases.toml``, so the form writes the sentence in its own
language.

.. literalinclude:: /../../hydromodpy/core/diagnostic.py
   :pyobject: Diagnostic
   :end-before: @property

The severity is ``error``, ``warning`` or ``to_fill``. A ``to_fill`` is a key the document
must hold and does not hold yet, so the form shows it as a field to fill. A rule that reads
several sections says nothing until every section it reads is complete. ``partial=False``
turns each ``to_fill`` into an ``error``, which is what a run needs. ``inputs=True`` also
reads the header of each input file, so keep it for the submit button.

A frontend that is not written in Python gives the document to the command line:

.. code-block:: bash

   hmp check --partial --format json draft.toml

The output is ``{ok, diagnostics, workspace}``. There is no check of one field on its own.
Send the document, so a rule that crosses two sections is seen.

A form on the schema
--------------------

Export the schema at each HydroModPy release and serve ``config.json`` as a static asset.
Angular applications usually pair it with ``ngx-formly`` or ``@rjsf/core``. With React the
form is ``<Form schema={schema} validator={validator} />`` from ``@rjsf/core`` and
``@rjsf/validator-ajv8``. A custom widget can switch on the ``widget_type`` annotation to
choose between an input, a select and a checkbox.

The run request
---------------

A request is the unit of work of a run, whether it comes from a TOML file, a Python call, a
server or a container. It is a JSON object of the schema ``hydromodpy.request.v1``. The site
publishes it as ``_static/hydromodpy-request-schema.json``, and the fields are the model
below.

.. literalinclude:: /../../hydromodpy/project/request.py
   :pyobject: RunRequest
   :end-before: @field_validator

``schema`` and ``config`` are required. ``config`` holds the whole document with its
``base_config`` chain and its overlays already merged, and a ``base_config`` key in it is
refused. A JSON file without ``schema`` is refused with a sentence that says to put the
document under ``config``.

The request does not hold the base of the relative paths or the environment (credentials,
allowed hosts, download limit). Both are arguments of the call, so the same request plays on
any machine. The base is ``--base DIR`` on the command line and ``base=`` in Python. A
request read from a file under a project folder takes that project as its base. A request
given as a mapping or as text needs a base, and without one it is refused.

The run writes the request it played as ``request.json`` in its folder, whole and never
redacted, and writes its ``request_id`` in ``outcome.json``. Two requests with the same
``request_id`` ask the same thing, whatever the paths and names they use. A run identical to
a completed one is given back instead of computed, and the answer names that run.

Submission flow
---------------

1. The frontend builds the document from the form values, keeps the section structure, and
   puts it under ``config`` of a request.
2. A thin service you write writes the request into the project folder. It calls
   ``hmp run request.json --base <project>``, or ``hmp.run(document, base=<project>)``. In a
   container the command is ``docker run <image> run /project/request.json --base /project``.
3. The service returns the run name and its ``request_id``, and the frontend polls the
   ``outcome.json`` of the run. The server of :doc:`serve-over-http` does steps 2 and 3. The
   frontend posts the request to ``/v1/<org>/<project>/run``, and the job gives the
   ``RunOutcome`` once the run ends.
4. Results come back through the verbs. ``hmp.status`` lists the outcomes,
   ``hmp.show(name, what=..., save=path)`` writes a summary, a table, a figure or a report,
   and ``hmp.export`` writes the files.

What HydroModPy does not ship
-----------------------------

The wheel has no HTTP server. The repository keeps ``hydromodpy_server`` beside it, on the
Python standard library only, with no authentication of its own. There is no FastAPI,
uvicorn or websocket dependency, no OpenAPI endpoint (the JSON Schemas are the contract) and
no server-sent events.

Tests to add
------------

- A schema diff in your CI. Export again and fail on a difference you did not commit.
- A smoke call of ``check`` at each release on a complete document, a document with a key
  left out and a document with a wrong value. The first gives no ``error``, the second a
  ``to_fill`` at that key, the third an ``error``.

See also
--------

- :doc:`serve-over-http` for the HTTP layer of the repository.
- :doc:`../packages/schema` for the schema package map.
- :doc:`/reference/parameters/explorer` for the interactive browser of the same models.
