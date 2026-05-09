# Boussinesq Testbed Workflow Experiments

This directory hosts Boussinesq-oriented testbed and comparison experiments that
belong to the `10_testbed_workflow` example family.

Current implementation:

- `natural_geology_k/`: first natural MF6/Boussinesq comparison smoke case. It
  uses the standard `workflow = "comparison"` path and regenerates the
  catchment mesh through `mesh_catchment`.
- `synthetic_heterogeneous/`: first synthetic heterogeneous Boussinesq testbed
  and MF6/Boussinesq comparison scaffold. It uses `geographic.source_mode =
  "synthetic"` and regenerates geology-conformal meshes through
  `mesh_catchment`.

Planned:

- larger natural catalogues driven by generated site lists and regional-lab or
  testbed summaries.
