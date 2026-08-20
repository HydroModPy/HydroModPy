Frontend Hooks
==============

HydroModPy stays a pure Python library: no HTTP server, no FastAPI, no
WebSocket. Two stable integration points are exposed for any frontend
(Angular, React, Jupyter widget) that does not need to
import the Python package.

For complementary reading, see :doc:`design-patterns` (item 10) and
:doc:`../../user_guide/cli-reference`.

Entry points
------------

1. ``hmp dev schema export --output ./schema/`` writes three JSON files
   that describe the configuration surface.
2. ``hmp dev schema validate-field <path> <value>`` runs the partial
   validator used for field-by-field feedback in forms (under 50 ms
   per call).

Both are also accessible from Python:

.. code-block:: python

   from hydromodpy.schema import export_full_schema, validate_field

   export_full_schema("./schema/")
   result = validate_field("flow.flow_regime", "steady")
   assert result.valid is True

Modules: ``hydromodpy/schema/export.py`` and
``hydromodpy/schema/partial_validator.py``.

Files emitted by ``hmp dev schema export``
------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - File
     - Role
   * - ``config.json``
     - Full JSON Schema of ``HydroModPyConfig``
   * - ``config_meta.json``
     - Ordered TOML sections, UI groups, titles
   * - ``field_validators.json``
     - Flat mapping ``field_path -> validator_type``

Each field in ``config.json`` keeps the ``json_schema_extra``
annotations carried by the Pydantic models: ``widget_type``, ``unit``,
``display_name_fr``, ``help_text_fr``, ``display_min``,
``display_max``. These annotations form the contract between the
Python models and the UI.

Doc-side schema artifacts
-------------------------

The Sphinx build emits two additional schema artifacts under
``docs/source/_static/`` via ``tools/doc_config/generate.py``:

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - File
     - Role
   * - ``hydromodpy-schema.json``
     - Raw JSON Schema 2020-12 export of ``HydroModPyConfig``. Use
       this file for Ajv / ajv-cli, IDE schema stores, and any
       external validator that consumes JSON Schema directly.
   * - ``hydromodpy-openapi.json``
     - OpenAPI 3.1 wrapper produced by ``export_openapi_wrapper`` in
       the same module. The Pydantic ``$defs`` are promoted to
       ``components.schemas`` and every internal ``$ref`` is
       rewritten from ``#/$defs/...`` to ``#/components/schemas/...``.
       Consumed by the Stoplight Elements viewer on
       :doc:`/user_guide/config_reference/schema_explorer`.

The OpenAPI wrapper exists because Stoplight Elements rejects a raw
JSON Schema with "failed to parse openapi file". The wrapper keeps the
``hmp dev schema export`` route untouched (it remains the canonical export
for frontends) and only adds a second artifact for the doc viewer.

.. seealso::
   :doc:`/user_guide/config_reference/schema_explorer` for the
   user-facing schema browser that consumes the OpenAPI wrapper.

Angular (external repository)
-----------------------------

Angular applications usually pair JSON Schema with ``ngx-formly`` or
``@rjsf/core``. Two steps:

.. code-block:: bash

   # 1. Produce the schema on every HydroModPy release.
   hmp dev schema export --output ./src/app/api/schema/

.. code-block:: ts

   // angular: src/app/api/schema.service.ts
   import { HttpClient } from '@angular/common/http';
   import { Injectable } from '@angular/core';
   import { Observable, shareReplay } from 'rxjs';

   @Injectable({ providedIn: 'root' })
   export class SchemaService {
     private schema$ = this.http
       .get<object>('/assets/schema/config.json')
       .pipe(shareReplay(1));

     constructor(private http: HttpClient) {}

     get schema(): Observable<object> {
       return this.schema$;
     }
   }

``ngx-formly`` then consumes the schema to render the form. A custom
widget can use the ``widget_type`` annotation to switch between
sliders and text inputs.

React (external repository)
---------------------------

.. code-block:: tsx

   import Form from '@rjsf/core';
   import validator from '@rjsf/validator-ajv8';
   import schema from './schema/config.json';

   export function SchemaForm() {
     return (
       <Form
         schema={schema}
         validator={validator}
         uiSchema={{
           'flow': {
             'properties': {
               'k_aquifer': { 'ui:widget': 'updown' },
             },
           },
         }}
       />
     );
   }

Field-by-field validation on the Python side is reachable through the
CLI (subprocess) or any transport the integrator picks. HydroModPy does
not impose one.

Calling ``validate_field`` from Python
--------------------------------------

.. code-block:: python

   from hydromodpy.schema import validate_field

   def on_change(path, value):
       result = validate_field(path, value)
       if not result.valid:
           show_error(result.error)

The validator resolves the field on the root model
``HydroModPyConfig``, picks the matching ``pydantic.TypeAdapter``, and
returns a lightweight ``ValidationResult``. Lookups are memoised:
repeated calls on the same path are free.

What HydroModPy intentionally does not ship
-------------------------------------------

- No FastAPI, uvicorn, or websockets dependency.
- No OpenAPI endpoint generation: the exported JSON Schema is the
  contract.
- No server-sent events; wire one yourself if a stream is needed.

Any HTTP layer written downstream can rely on these hooks without
touching the core package.

See also
--------

- :doc:`design-patterns` (item 10) for the pattern behind the
  frontend hook contract.
- :doc:`../../user_guide/config_reference/schema_explorer` for the
  interactive viewer of the same schema.
