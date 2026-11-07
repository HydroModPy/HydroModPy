# model/sinks_sources

The payloads of `[flow.sinks_sources]`, one module per kind of sink or source. `container.py` is the
whole table, and `Flow.set_sinks_sources` reads it.

## Modules

| module | answers |
|---|---|
| `container.py` | `FlowSinksSourcesConfig`, the whole table: wells, recharge, ETP, lakes, SFR networks and flow barriers |
| `etp.py` | Diffuse evapotranspiration payload for the flow process |
| `flow_barrier.py` | Horizontal flow barrier (HFB) payload for the flow process |
| `lake.py` | Lake / reservoir boundary-condition payload for the flow process |
| `recharge.py` | Diffuse recharge payload for the flow process |
| `sfr.py` | Streamflow-routing (SFR) boundary-condition payload for the flow process |
| `wells.py` | Pumping/injection well payloads for the flow process |

`recharge.py` and `etp.py` carry a steady first period (`first_clim`), normalized by
`model/forcing/steady_periods.py`. `wells.py` also holds the report of a well whose pumping MODFLOW 6 cut.
`lake.py` holds a lake, its outlets and its forcings, with the sign each forcing must have.
`flow_barrier.py` holds a flow barrier and `CutoffWallConfig`, the barrier of a lake dam laid on the shore.
The soil reservoir that can feed `recharge.py` is in `model/soil/`. `__init__.py` gives the main payload
names.
