Build a Frontend
================

HydroModPy stays a pure Python library: it does not ship an HTTP
server, FastAPI bindings, or websockets. Instead it exposes two
stable contracts that any frontend (Streamlit, Angular, React,
Jupyter widget, electron app) can consume.

Two integration points
----------------------

1. **JSON Schema export** -- ``hmp schema export --output ./schema/``
   writes three JSON files:

   .. code-block:: text

      schema/
      |-- config.json              # full JSON Schema of HydroModPyConfig
      |-- config_meta.json         # ordered TOML sections, UI groups, titles
      `-- field_validators.json    # flat field_path -> validator_type

2. **Partial-field validator** --
   ``hmp schema validate-field <path> <value>`` runs the same
   validator your form should call on each keystroke (under 50 ms per
   call, no I/O).

Both are also available from Python:

.. code-block:: python

   from hydromodpy.schema import export_full_schema, validate_field

   export_full_schema("./schema/")
   result = validate_field("flow.flow_regime", "steady")
   assert result.valid is True

Modules: ``hydromodpy/schema/export.py`` and
``hydromodpy/schema/partial_validator.py``.

Annotations carried by the schema
---------------------------------

Each field in ``config.json`` keeps the ``json_schema_extra``
annotations declared by the Pydantic models:

- ``widget_type`` -- ``slider``, ``text``, ``select``, ``date``,
  ``file``, ``map``, etc.
- ``unit`` -- canonical SI unit (``m``, ``m/s``, ``1/m``, ...).
- ``display_name_fr`` / ``display_name_en`` -- human label.
- ``help_text_fr`` / ``help_text_en`` -- tooltip.
- ``display_min`` / ``display_max`` -- bounds for sliders.
- ``profile`` -- one of ``user`` / ``dev`` / ``expert`` (filterable
  in the UI).

These annotations form the contract between the Pydantic models and
your frontend. Honour them and you avoid a custom mapping layer.

Streamlit (local, Python)
-------------------------

Streamlit is the shortest path because it runs in the same process:

.. code-block:: python

   import json
   from pathlib import Path

   import streamlit as st

   schema = json.loads(Path("schema/config.json").read_text())
   flow = schema["$defs"]["FlowConfig"]["properties"]

   k = st.slider(
       flow["k_aquifer"]["display_name_fr"],
       min_value=flow["k_aquifer"]["display_min"],
       max_value=flow["k_aquifer"]["display_max"],
       help=flow["k_aquifer"]["help_text_fr"],
   )
   st.caption(f"Unite : {flow['k_aquifer']['unit']}")

   if st.button("Run"):
       toml_payload = {"flow": {"k_aquifer": k}}
       hmp.run("project.toml", set=toml_payload)

A worked example lives at
``examples/integrations/streamlit_app.py`` (when shipped).

Angular (external repository)
-----------------------------

Pair JSON Schema with ``ngx-formly`` or ``@rjsf/core``. Two steps:

.. code-block:: bash

   # 1. Export the schema during the HydroModPy CI step.
   hmp schema export --output ./src/app/api/schema/

.. code-block:: ts

   // src/app/api/schema.service.ts
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

A custom widget can switch on the ``widget_type`` annotation to pick
between sliders, dropdowns, and text inputs.

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
           flow: {
             k_aquifer: { 'ui:widget': 'updown' },
           },
         }}
       />
     );
   }

Field-by-field validation on the Python side is reachable through
the CLI (subprocess) or any transport you choose; HydroModPy does
not impose one.

Calling ``validate_field`` from Python
--------------------------------------

.. code-block:: python

   from hydromodpy.schema import validate_field


   def on_change(path: str, value):
       result = validate_field(path, value)
       if not result.valid:
           show_error(path, result.error)

The validator resolves the dotted path on ``HydroModPyConfig``,
picks the matching ``pydantic.TypeAdapter``, and returns a
lightweight ``ValidationResult``. Lookups are memoised so repeated
calls on the same path are free.

Submission flow
---------------

1. The frontend builds a TOML payload from the form values (keep
   the section structure: ``[flow]``, ``[geographic]``, etc.).
2. POST the payload (or a ``HydroModPyConfig`` JSON dump) to a thin
   service that calls ``hmp.run`` or
   ``hmp.Project.from_json(payload).run()``.
3. The service returns a ``sim_id`` that the frontend polls or
   subscribes to.
4. Results come back through the catalog: open the workspace with
   ``hmp.open(workspace)`` and read the ``Run`` rows; expose
   metrics, figures, and exports as the UI needs them.

What HydroModPy intentionally does **not** ship
-----------------------------------------------

- No FastAPI / uvicorn / websockets dependency.
- No OpenAPI endpoint generation: the exported JSON Schema is the
  contract.
- No server-sent events; wire one yourself when a stream is needed.

Any HTTP layer written downstream relies on these hooks without
touching the core package.

Tests to add
------------

- **Unit** for any custom Python service that wraps the schema
  exports.
- **Schema diff CI**: re-run ``hmp schema export`` in CI and fail
  on diffs that the contributor did not commit.
- **Smoke** call against ``validate_field`` for a few known good /
  bad pairs per release.

See also
--------

- :doc:`../overview/frontend-hooks` for the architectural rationale.
- :doc:`../packages/schema` for the schema package map.
- :doc:`add-a-config-field` for the annotations the frontend
  consumes.
- :doc:`/user_guide/config_reference/schema_explorer` for the
  user-facing schema viewer.
