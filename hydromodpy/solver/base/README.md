# solver/base

What every backend shares, and nothing that is MODFLOW only.

## Modules

1. `adapter_protocol.py` is the contract a backend meets: the `SolverAdapter` Protocol the runner calls (`validate`, `execute`, `cleanup`, `extract_observables`), `CellLocator`, `MeshReadingAdapter` and `STOP_BEFORE_THE_SOLVE`, which a calibration uses to stop a trial before the solve.
2. `registry.py` pairs a `(process_type, solver_name)` key with an adapter class and an extractor class. The built-in ones are dotted paths imported on first lookup. Out-of-tree backends come from the `hydromodpy.solver` and `hydromodpy.solver.extractor` entry-point groups.
3. `solver_config.py` is the `[solver]` table and its backend union.
4. `protocols.py` holds the structural types the backends annotate with: `DomainLike`, `FlowModelLike`, `TransportLike`.
5. `properties.py` is the one mapping of K, Kv, Sy, Ss and the rest of the K tensor onto the cells (`map_flow_properties`), the runtime overrides a calibration trial writes (`resolve_flow_property_runtime_overrides`), the properties a regime needs (`resolve_required_flow_properties`), and the refusal of a conductivity or a storage that is not positive.
6. `initial_conditions.py` is the head a run starts from: the array of a `flow.ic` kind, and the steady and cyclic spin-up strategies that replace it with the state of an auxiliary solve of the same solver.
7. `drain_conductance.py` is the drain arithmetic every backend uses: the conductance of a free seepage face from K, and the discharge band.
8. `observables.py` turns a solver series or field into an `ObservableResult`, and says in three states whether a backend can serve an observable (`ObservableSupport`).
9. `cell_lookup.py` finds the cell under a point on a solver mesh or a cell mesh.
10. `cleanup.py` removes the scratch files of a run.

`base` imports `core`, `physics` and `spatial`, never a backend.
