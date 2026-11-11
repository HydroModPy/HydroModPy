# solver/modflow6/extractors

What a MODFLOW 6 run wrote, read into the run store after the solve.

## Modules

1. `flow.py` is `Modflow6OutputAdapter`: heads, the time axis, the mass balance of the listing, the surface elevation, and the lake and stream series.
2. `budget.py` is the per-cell budget of the CBC file. Each stamp closes its stress period, so a flux is the mean of the steps since the previous stamp, weighted by their length.
3. `cbc_reader.py` reads the CBC file in one pass, where the FloPy reader is quadratic on long chronicles.
4. `face_flow.py` reads `FLOW-JA-FACE` from the same CBC file. It keeps one flow per connection, positive from the smaller flat index to the larger, in `face_flow` beside `connection_cells`. A flow that does not write it is refused.
5. `lake.py` and `sfr.py` read the LAK and SFR observation CSVs and their sidecars. `obs_common.py` holds what the two share.
6. `grid_check.py` checks the solved grid against the grid of the store.
7. `transport.py` reads the GWT concentrations and the solute mass balance, `prt.py` and `_prt_tracks.py` the PRT particle tracks.
