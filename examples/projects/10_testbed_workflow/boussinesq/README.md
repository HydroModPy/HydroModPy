# Boussinesq Testbed Workflow Experiments

This directory hosts Boussinesq-oriented testbed and comparison experiments that
belong to the `10_testbed_workflow` example family.

Current implementation:

- `synthetic_heterogeneous/`: first synthetic heterogeneous Boussinesq testbed
  and MF6/Boussinesq comparison scaffold. It uses `geographic.source_mode =
  "synthetic"` and regenerates geology-conformal meshes through
  `mesh_catchment`.
- `natural_geology_k/`: natural MF6/Boussinesq regional-lab planning scaffold.
  The regional-lab part defines site selection and stratification; the generic
  `workflow = "testbed"` loop generates one `workflow = "comparison"` case per
  selected site or mesh-sensitivity variant, and each child simulation
  regenerates its catchment mesh through `mesh_catchment`.
