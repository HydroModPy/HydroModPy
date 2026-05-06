# Architecture (layer matrix)

HydroModPy is structured by a strict layer matrix. Each top-level package
under `hydromodpy/` is a layer; imports follow the allowed matrix. The layer
contract is the canonical source of truth for v1.0.

- Authoritative spec: this document.
- Machine-readable copy: `tests/unit/architecture/layer_matrix.yaml`.
- CI gate: `tests/unit/architecture/test_layer_matrix.py`.
- AST scanner: `tools/audit/build_graph.py`.

## Layers (low to high)

```
core < schema < physics, data, spatial < simulation < solver
     < results < display, analysis, calibration < workflow < config
     < cli
```

`core` is the kernel leaf. It must not import any sibling layer (not
even under `TYPE_CHECKING`). `cli` is the on-disk CLI top-level package.
`hydromodpy.config` is the canonical application-level configuration package.
There is no `pipeline` package in the current tree; pipeline behavior lives
under `workflow`.

## Allowed targets

A layer can only import from layers in its allowed list. Self-imports
are always allowed.

| src \ tgt    | allowed targets |
|--------------|-----------------|
| core         | core |
| schema       | core, schema, config |
| config       | core, schema, config, physics, data, spatial, simulation, solver, calibration, results, display, analysis, workflow |
| physics      | core, schema, physics |
| data         | core, schema, data, spatial |
| spatial      | core, schema, spatial |
| simulation   | core, schema, physics, spatial, data, simulation |
| solver       | core, schema, physics, spatial, solver, simulation |
| calibration  | core, schema, physics, data, spatial, solver, simulation, calibration, results |
| results      | core, schema, config, results, spatial |
| display      | core, schema, results, display |
| analysis     | core, schema, physics, data, results, display, analysis |
| workflow     | core, schema, config, physics, data, spatial, simulation, solver, calibration, results, display, analysis, workflow |
| cli          | every layer |

## Explicit Structural Choices

The following cross-layer edges are allowed by design and should not be
reported as segmentation problems:

- `data -> spatial`: loaders may materialize spatial products when that keeps
  the user-facing sequence `load -> materialize -> expose in loaded_data`
  coherent.
- `results -> spatial`: `Run` exposes practical helpers for persisted
  hydrographic networks instead of forcing users through raw catalog tables.
- `calibration -> results`: calibration records, promotes, and rereads
  persisted simulation runs through the results catalog.
- `analysis -> display`: analysis workflows may produce visual artifacts while
  rendering implementation remains in `display`.
- `analysis -> physics`: comparison exports reuse the shared transient history
  contract (`t0..tN` snapshots and `dt1..dtN` periods) from `physics.flow`.

## Tolerated cross-edges

A small set of `?` cells is tolerated for v1.0 transitions, each
documented at the call site. Listed in `layer_matrix.yaml` under
`tolerances`:

| src         | tgt     | rationale |
|-------------|---------|-----------|
| cli         | root    | CLI dispatch delegates to public Project facade |

Tolerances tighten over time. Adding a new tolerance requires a
documented rationale and a migration target.

## Cross-cutting rules

- `hydromodpy_annex/` may import `hydromodpy/`. The reverse is forbidden
  and enforced strict by `test_annex_one_way`.
- Each MODFLOW backend (`solver/modflow6/`, `solver/modflow_nwt/`) is
  independent. Cross-imports between backends are forbidden.
- Cross-package imports of `_<name>` modules or sub-packages are
  forbidden. A leading underscore means truly private.

## CI behavior

`test_layer_matrix.py` is the active CI gate. It fails on undocumented
cross-layer imports, stale matrix rows, missing rows for new top-level
packages, and tolerances that reference unknown layers.

Adding a new edge that violates the matrix is a regression even in
stage 1: do not add `# noqa` markers; instead re-shape the call so the
edge points downward (caller materializes, registry dispatch, protocol
import under `TYPE_CHECKING` from an allowed layer, etc.).

## Running the gate

```bash
mamba activate hmp_refact
pytest tests/unit/architecture/test_layer_matrix.py -v
```

For an offline audit with full edge listing:

```bash
python -m tools.audit.build_graph
```
