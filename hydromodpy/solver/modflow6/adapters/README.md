# solver/modflow6/adapters

The three adapters of MODFLOW 6. Each one validates its context, builds and solves its model, and cleans the scratch folder. Each class also carries the twelve attributes of the port (`solver/base/README.md`), and `solvers.get("flow", "modflow6")` returns the class by them.

1. `flow.py` is the flow adapter. It also serves the observables of a calibration trial straight from the scratch files, and says which observables the resolved configuration can serve.
2. `transport.py` adds a GWT model to the flow simulation of an earlier run.
3. `prt.py` adds a PRT particle tracking model the same way.
