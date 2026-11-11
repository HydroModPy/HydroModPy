"""Finite-volume assembly helpers shared by all current Boussinesq runtimes.

Public facade. Implementation is split across:

- `inputs.py` for runtime input normalization and constraint handling,
- `fluxes.py` for transmissivity and flux operators,
- `surface.py` for surface-interaction closures,
- `residuals.py` for steady/transient residual assembly.
"""
