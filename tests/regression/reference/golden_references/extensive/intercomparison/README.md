# Extensive Intercomparison Goldens

Golden files in this directory belong to
`tests/regression/extensive/intercomparison/`.

Keep these references compact and deterministic:

- store selected scalar metrics and statistical signatures as JSON,
- do not store generated figures or complete solver outputs,
- update them only through pytest's `--update-goldens` workflow,
- document the scientific or code-level reason for any signature change in the
  commit message.
