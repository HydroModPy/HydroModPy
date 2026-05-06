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

## What requires a one-line addition: dispatchers

Some TOML grammars are validated dynamically: the parent field is typed
`dict[str, object]` (or `dict[str, dict[str, object]]`) at the Pydantic
level, but the runtime normalizer dispatches each sub-payload to a
specific `BaseModel`. Examples:

- `[flow.bc.dirichlet.<id>]` → `FlowBoundaryConditionConfig`
- `[flow.param.<id>.field_homogeneous]` → `FieldHomogeneousSection`
- `[[data.recharge.sources]]` → `RechargeSourceConfig`

In these cases, `model_fields` alone does not tell the generator which
schema applies to the payload. The pairing is declared in
`dispatchers.py`:

```python
DispatcherEntry(
    section_name="flow",
    pattern="[flow.bc.dirichlet.<id>]",
    model=FlowBoundaryConditionConfig,
    description="Dirichlet boundary condition payload.",
    ids=("ocean", "stream", "north_side", "south_side", "east_side", "west_side"),
)
```

The page for `[flow]` then renders a "Dynamic sub-tables" appendix that
lists the dispatcher patterns and drills into each model.

### Why a separate file rather than an annotation on the Pydantic field?

Putting this metadata on the model itself (e.g. via
`Field(json_schema_extra={"dispatch": "..."})` or a class attribute
`__hmp_dispatch__`) was considered and rejected:

- **Separation of concerns.** Pydantic models are *domain* objects:
  they validate data. Telling them how they are rendered in the
  documentation pushes presentation concerns into the domain layer.
  Dependency direction should be `presentation → domain`, never the
  reverse.
- **String-based coupling.** A dotted import path stored in
  `json_schema_extra` only resolves at runtime, breaks silently on
  rename, and pollutes the public JSON Schema export with
  HydroModPy-specific metadata.
- **Single source of truth for doc structure.** `dispatchers.py` is
  the only file the docs team reads to understand which dynamic
  sub-tables exist; reviewing one short file beats grepping the whole
  codebase.

The cost of this design is one short file to maintain. The next
section adds a guard rail so that cost stays predictable.

## Coverage check (forgotten-dispatcher guard)

`coverage.py` scans `HydroModPyConfig` recursively and flags every
opaque field (`dict[str, object]`, `dict[str, dict[str, object]]`, ...)
that has no matching `DispatcherEntry` in `dispatchers.py`. The result
is printed during `generate_all()` so a forgotten entry shows up as a
clear log line in the Sphinx build:

```
[doc_config] WARNING: uncovered opaque TOML paths detected:
  - flow.something_new  (dict[str, object])
[doc_config] Add a DispatcherEntry for each path in
tools/doc_config/dispatchers.py to surface its sub-schema.
```

Fix it by editing `dispatchers.py` and rebuilding.

### Two automatic exclusions

Some opaque fields are not real dispatchers and would create false
positives:

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
| Added a `dict[str, X]` payload validated by a separate normalizer | `dispatchers.py` (one `DispatcherEntry`) |
| Want a new task-oriented recipe | `docs/source/user_guide/config_reference/recipes.rst` |
| Want to change the page layout or styling | `generate.py` + the CSS/JS under `docs/source/_static/` |

## Running the generator standalone

```bash
mamba activate hmp_refact
python -m tools.doc_config
```

The Sphinx build calls the same entry point automatically, so you
only need this command when iterating on the generator itself.
