# solver/modflow6/adapters

The two transport adapters of MODFLOW 6. Each one validates its context, adds its model to the flow simulation of an earlier run, solves, and cleans the scratch folder. Each class also carries the twelve attributes of the port (`solver/base/README.md`), and the registry returns the class by them (`transport_modflow6` for GWT, `transport_modflow6_prt` for PRT). The flow adapter is `../adapter.py`.

1. `transport.py` adds a GWT model to the flow simulation of an earlier run.
2. `prt.py` adds a PRT particle tracking model the same way.

The `SolverRun` of the flow arrives in `ctx.upstream`. The two adapters read `ctx.state` for their setup until the transport port takes the `Model`.
