# solver/modflow6/builders

The arguments of each MODFLOW 6 package, built from the `Model` and the solver mesh. `build.py` calls them. A builder does not import another package's builder: SFR and LAK couple only through the mover records of `mvr.py`.

## Modules

1. `solver_options.py`: IMS, Newton, XT3D, ATS and output control.
2. `initial_conditions.py`: the start heads of the five start states of `Model.initial` and the REWET options of NPF.
3. `boundary_conditions.py`: the ocean, stream and side constant heads, and the drains.
4. `recharge.py`: RCH, the routed negative recharge and the soil ETP on EVT.
5. `wells.py`: WEL, with the flow reduction under Newton.
6. `period_forcing.py`: the period values of a lake or stream forcing, in the units the package reads.
7. The lakes. `lake_cells.py` puts a lake on the mesh (its cells, its carved bed, its inactive footprint), `lake.py` builds LAK (connections, table, period data), `lake_outflow.py` its outlets, movers and spillway seeds, `lake_obs.py` its observations, `lake_column_regrade.py` regrades a mesh column around a carved bed so it stays a valid prism. The `_lake_*` modules hold their geometry, definitions, connection rows and outlet rows.
8. The streams. `sfr.py` builds SFR, `sfr_rectify.py` rebuilds the reach cells as one single-flow-direction channel along the descent D, and the `_sfr_*` modules hold the network, the bed, the period data and the drains under a reach.
9. `mvr.py`: the mover records and the MVR package.
10. `flow_barrier.py`: HFB on the cutoff walls and the flow barriers.
