# Architecture (layer matrix)

HydroModPy is structured as a strict layered DAG. Each top-level package
under `hydromodpy/` is a layer; imports flow downward only. The layer
contract is the canonical source of truth for v1.0.

- Authoritative spec: this document.
- Machine-readable copy: `tests/unit/architecture/layer_matrix.yaml`.
- CI gate: `tests/unit/architecture/test_layer_matrix.py`.
- AST scanner: `tools/audit/build_graph.py`.

## Layers (low to high)

```
core < schema < physics, data, spatial < simulation < solver
     < results < display, analysis, calibration < workflow < master_config < cli
```

`core` is the kernel leaf. It must not import any sibling layer (not
even under `TYPE_CHECKING`). `cli` is the on-disk CLI top-level package.
There is no `pipeline` package in the current tree; pipeline behavior lives
under `workflow`.

## Allowed targets

A layer can only import from layers in its allowed list. Self-imports
are always allowed.

| src \ tgt    | allowed targets |
|--------------|-----------------|
| core         | core |
| schema       | core, schema |
| physics      | core, schema, physics |
| data         | core, schema, data |
| spatial      | core, schema, spatial |
| simulation   | core, schema, physics, spatial, data, simulation |
| solver       | core, schema, physics, spatial, solver, simulation |
| calibration  | core, schema, physics, data, spatial, solver, simulation, calibration |
| results      | core, schema, results |
| display      | core, schema, results, display |
| analysis     | core, schema, data, results, analysis |
| workflow     | core, schema, physics, data, spatial, simulation, solver, calibration, results, display, analysis, workflow, master_config |
| master_config | core, schema, physics, data, spatial, simulation, solver, calibration, results, display, analysis, workflow, master_config |
| cli          | every layer |

## Tolerated cross-edges

A small set of `?` cells is tolerated for v1.0 transitions, each
documented at the call site. Listed in `layer_matrix.yaml` under
`tolerances`:

| src         | tgt     | rationale |
|-------------|---------|-----------|
| data        | spatial | geology field bridging |
| calibration | results | catalog read at planning time |
| simulation  | solver  | dispatch through solver registry |
| results     | spatial | results stores spatial indices |
| analysis    | root    | simulation comparison launches public Project facade |
| calibration | root    | trial promotion launches public Project facade |
| cli         | root    | CLI dispatch delegates to public Project facade |
| master_config | root | module entrypoint delegates to `hydromodpy.__main__` |
| results     | root    | `Run.rerun` launches public Project facade |
| workflow    | root    | sweep helper accepts Project facade instances |

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
