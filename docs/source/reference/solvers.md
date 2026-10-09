# Solvers

Every process a run can plan and the solver that carries it out, read from the solver
registry of the code: what each pair provides, the lines of the TOML file that select it, the
executable it runs, the run it needs before it, and whether its results are read back into the
catalog. What they solve is in {doc}`../theory/solvers`.

The executables are downloaded by `hmp install-binaries` (see {doc}`cli/install-binaries`), or
the first time a solver needs one.

```{hmp-solvers}
```
