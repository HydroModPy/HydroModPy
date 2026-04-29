# Architecture (layer matrix)

HydroModPy is structured as a strict layered DAG. Each top-level package
under `hydromodpy/` is a layer; imports flow downward only. The 14x14
contract is the canonical source of truth for v1.0.

- Authoritative spec: `unified_architecture/20_ENCAPSULATION_AND_COUPLING.md` §2.
- Machine-readable copy: `tests/unit/architecture/layer_matrix.yaml`.
- CI gate: `tests/unit/architecture/test_layer_matrix.py`.
- AST scanner: `tools/audit/build_graph.py`.

## Layers (low to high)

```
core < schema < physics, data, spatial < simulation < solver
     < results < display, analysis, calibration < pipeline < workflow < _cli
```

`core` is the kernel leaf. It must not import any sibling layer (not
even under `TYPE_CHECKING`). `_cli` is the on-disk name of the CLI
top-level package (the spec table writes `cli` for readability).

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
| pipeline     | core, schema, physics, data, spatial, solver, simulation, calibration, results, pipeline |
| workflow     | every layer except `_cli` |
| `_cli`       | every layer |

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

`test_layer_matrix.py` is currently marked `xfail`. It reports the
count of remaining forbidden imports without breaking CI. The roadmap
follows `unified_architecture/20_ENCAPSULATION_AND_COUPLING.md` §7.7:

1. **Stage 1 (active)** — xfail; count and report only.
2. **Stage 2** — quota; fail if count exceeds a decreasing budget.
3. **Stage 3** — strict zero P0; only `tolerances` allowed.

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
