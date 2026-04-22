# Frontend hooks

HydroModPy stays a pure-Python library: it ships **no HTTP server, no
FastAPI, no WebSocket**. Instead, it publishes two stable integration
points that any frontend — Streamlit, Angular, React, a Jupyter widget —
can consume without importing the Python package:

1. `hmp schema export --output ./schema/` produces three JSON files that
   describe the configuration surface.
2. `hmp schema validate-field <path> <value>` runs the partial validator
   used for field-by-field form feedback (< 50 ms per call).

Both entry points are also reachable programmatically:

```python
from hydromodpy.schema import export_full_schema, validate_field

export_full_schema("./schema/")
result = validate_field("flow.flow_regime", "steady")
assert result.valid is True
```

## Files produced by `hmp schema export`

| File                      | Purpose                                                      |
|---------------------------|--------------------------------------------------------------|
| `config.json`             | Full Pydantic JSON Schema of `HydroModPyConfig`.            |
| `config_meta.json`        | Ordered list of TOML sections + UI groups.                   |
| `field_validators.json`   | Flat `field_path -> validator_type` mapping.                 |

Each field in `config.json` preserves the `json_schema_extra` annotations
that the Pydantic models carry (`widget_type`, `unit`, `display_name_fr`,
`help_text_fr`, `display_min`, `display_max`). Those annotations are the
contract between the Python models and the UI.

## Streamlit (local, Python)

A minimal Streamlit app can auto-generate a form from the schema:

```python
import json
from pathlib import Path
import streamlit as st

schema = json.loads(Path("schema/config.json").read_text())
flow = schema["$defs"]["FlowPhysicalProperties"]["properties"]

k = st.slider(
    flow["k_aquifer"]["display_name_fr"],
    min_value=flow["k_aquifer"]["display_min"],
    max_value=flow["k_aquifer"]["display_max"],
    help=flow["k_aquifer"]["help_text_fr"],
)
st.caption(f"Unit: {flow['k_aquifer']['unit']}")
```

See [`docs/examples/streamlit_app.py`](../examples/streamlit_app.py) for
an end-to-end example that discovers sections dynamically.

## Angular (external repo)

Angular apps typically pair a JSON Schema with
[`ngx-formly`](https://formly.dev/) or
[`@rjsf/core`](https://rjsf-team.github.io/react-jsonschema-form/) (via a
wrapper). Two steps:

```bash
# 1. Produce the schema once per HydroModPy release.
hmp schema export --output ./src/app/api/schema/

# 2. Load it in the Angular service.
```

```ts
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
```

`ngx-formly` then consumes the schema to render the form; custom widgets
can key on the `widget_type` annotation to pick sliders vs. text inputs.

## React (external repo)

```tsx
// react: SchemaForm.tsx
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
```

Field-level validation from the Python side is available through the CLI
(subprocess) or any transport the integrator chooses to build; HydroModPy
does not prescribe one.

## Calling `validate_field` from Python

```python
from hydromodpy.schema import validate_field

def on_change(path, value):
    result = validate_field(path, value)
    if not result.valid:
        show_error(result.error)
```

The validator resolves the leaf field on the root `HydroModPyConfig`
model, picks the matching `pydantic.TypeAdapter`, and returns a small
`ValidationResult` dataclass. Look-ups are memoised, so repeated calls on
the same path are free.

## What HydroModPy deliberately does NOT ship

- No FastAPI / uvicorn / websockets dependency.
- No OpenAPI endpoint generation; the exported JSON Schema is the
  contract.
- No live server-sent events; wire your own if you need streaming.

Any HTTP layer a downstream project writes can build on top of these
hooks without touching the core package.
