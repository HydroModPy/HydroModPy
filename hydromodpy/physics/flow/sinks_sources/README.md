# physics/flow/sinks_sources

The payloads of `[flow.sinks_sources]`, one module per kind of sink or source.

## Modules

1. `container.py` is `FlowSinksSourcesConfig`, the whole table: wells, recharge, ETP, lakes, SFR networks and flow barriers.
2. `recharge.py` and `etp.py` are the recharge and ETP payloads, with their steady first period (`first_clim`, normalized by `physics/forcing/steady_periods.py`).
3. `wells.py` is a well and its location, and the report of a well whose pumping MODFLOW 6 cut.
4. `lake.py` is a lake, its outlets and its forcings, with the sign each forcing must have.
5. `sfr.py` is an SFR reach network and its forcings.
6. `flow_barrier.py` is a flow barrier (HFB), and `CutoffWallConfig`, the barrier of a lake dam laid on the shore.

`__init__.py` gives the main payload names.
