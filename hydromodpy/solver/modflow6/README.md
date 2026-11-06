# solver/modflow6

MODFLOW 6 through FloPy: a GWF flow model, and GWT or PRT transport on the same simulation.

## Parts

1. `modflow6.py` is `Modflow6`, the model object a run builds, writes and solves. `modflow6_config.py` is the `[modflow6]` table.
2. `build.py` assembles the flow model. `run_pre_processing` runs its steps in the order MODFLOW 6 needs: inputs, time, grid, properties, simulation, lakes, constant heads, streams, grid packages, recharge and EVT, drains, CHD and wells, LAK, HFB, SFR, MVR and OC.
3. `builders/` holds one module per package or subject, see its README.
4. `run.py` writes the files and solves, with the `mf6` executable or in process through `libmf6` (`api/`), after a steady initialization or a cyclic spin-up when the `flow.ic` asks for one.
5. `transport.py` and `prt.py` add a GWT or a PRT model to the flow simulation.
6. `adapters/` are the registry adapters: flow, GWT transport and PRT.
7. `extractors/` read the binary files and the observation CSVs into the store, see its README.
8. `support/` holds what the build and the run share: names, the computational top, the property mapping on the solver mesh, time series files, the steady initialization, two FloPy patches.

`modflow6` imports `base`, `modflow_common` and `modflow_grid`, never `modflow_nwt` or `boussinesq`.
