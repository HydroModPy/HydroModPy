# `tools/doc_config`

Generator for the HydroModPy configuration reference under
`docs/source/user_guide/config_reference/`.

## What it does

At every Sphinx build (`make -C docs html`), the `builder-inited` hook
calls `generate_all()`. The generator walks `HydroModPyConfig.model_fields`
and writes:

| File | Role |
|---|---|
| `index.rst` | Cards-based overview of every TOML section |
| `<section>.rst` | One page per top-level section (`[workspace]`, `[flow]`, ...) |
| `complete_toml.rst` | Annotated copy-pasteable TOML reference |
| `config_index.rst` | Flat global index of every TOML path |
| `schema_explorer.rst` | Stoplight Elements viewer over the JSON Schema |
| `validate.rst` | In-browser TOML structural pre-flight |
| `_static/hydromodpy-schema.json` | Canonical JSON Schema export |
| `_static/hmp-config-search.json` | Search index used by the index page |

`recipes.rst` is **not** auto-generated and lives next to the others.

## What is automatic

If you add or change a Pydantic field anywhere in the model tree, the
documentation updates on its own at the next build. No manual editing is
needed for:

- new fields in an existing model,
- new top-level sections in `HydroModPyConfig`,
- description / default / type changes,
- `Annotated[T, Profile.USER | DEV | EXPERT]` tags,
- `Field(json_schema_extra={"stability": "experimental"})` markers,
- nested `BaseModel` payloads (rendered as collapsible dropdowns up to
  `MAX_NESTED_DEPTH = 3`).

## Coverage check

The generator has no side table for dynamic payloads. Every documented
payload must be reachable from `HydroModPyConfig.model_fields` as a typed
Pydantic model. Discriminated unions, `dict[str, BaseModel]`, and
`list[BaseModel]` are rendered from annotations directly.

`coverage.py` scans `HydroModPyConfig` recursively and flags every
opaque field (`dict[str, object]`, `dict[str, dict[str, object]]`, ...)
that is not explicitly free-form. The result is printed during
`generate_all()` so a hidden schema shows up as a clear log line in the
Sphinx build:

```
[doc_config] WARNING: uncovered opaque TOML paths detected:
  - flow.something_new  (dict[str, object])
[doc_config] Replace each opaque payload with a typed BaseModel or add a
free-form mapping to INTENTIONALLY_OPAQUE_PATHS.
```

Fix it by replacing the payload with a typed `BaseModel`. If the mapping
is truly free-form key/value data, add its TOML path to
`coverage.INTENTIONALLY_OPAQUE_PATHS`.

### Two automatic exclusions

Some opaque fields are intentional and would create false positives:

- **`exclude=True` fields**: inherited generic containers that the
  parent model marks `exclude=True` are not part of the published
  schema. The check skips them automatically. Example: the
  `param`/`bc`/`sinks_sources` fields inherited by `TransportConfig`
  from `ProcessSpatialConfig`.
- **Free-form key/value mappings**: some `dict[str, scalar]` fields
  exist on purpose without a sub-model (geology zone -> conductivity
  scalar, station id -> coordinate, ...). Such paths are listed
  explicitly in `coverage.INTENTIONALLY_OPAQUE_PATHS`. Add an entry
  there for any new free-form mapping you introduce.

## When you should edit which file

| Change you made | File to edit |
|---|---|
| Added a regular field or sub-model in Pydantic | nothing (auto) |
| Added a new top-level section in `HydroModPyConfig` | nothing (auto) |
| Added a `dict[str, X]` payload | type `X` as a `BaseModel` |
| Added a free-form key/value mapping | `coverage.INTENTIONALLY_OPAQUE_PATHS` |
| Want a new task-oriented recipe | `docs/source/user_guide/config_reference/recipes.rst` |
| Want to change the page layout or styling | `generate.py` + the CSS/JS under `docs/source/_static/` |

## Running the generator standalone

```bash
mamba activate hmp_refact
python -m tools.doc_config
```

The Sphinx build calls the same entry point automatically, so you
only need this command when iterating on the generator itself.
