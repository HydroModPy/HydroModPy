# hydromodpy_annex

This folder hosts annex toolsets that are related to HydroModPy workflows but are
not part of the reusable core package (`hydromodpy/`).

Rules:

- Annex code can import from `hydromodpy`.
- Core code in `hydromodpy` must stay independent from annex folders.
- Put case-specific launchers, exploratory preprocessing/postprocessing pipelines,
  and external-collaboration scripts here.

Current annex toolset:

- `HCDM/`
