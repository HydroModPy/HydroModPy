![logo](https://github.com/HydroModPy/HydroModPy/blob/61d654ca738c488480fd22aa01c2b1002984eac9/docs/readthedocs/source/images/logoHydroModPy_long.png)

**HydroModPy** is a Python toolbox for deploying catchment-scale shallow
groundwater models. One TOML config drives MODFLOW 6, MODFLOW-NWT, Boussinesq
and GR4J on the same hydrology, with reproducible inputs and ML-friendly
outputs.

[![PyPI](https://img.shields.io/pypi/v/hydromodpy.svg)](https://pypi.org/project/hydromodpy/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: EPL-2.0](https://img.shields.io/badge/license-EPL--2.0-green.svg)](https://opensource.org/licenses/EPL-2.0)
[![CI Fast](https://github.com/HydroModPy/HydroModPy/actions/workflows/ci-fast.yml/badge.svg?branch=dev)](https://github.com/HydroModPy/HydroModPy/actions/workflows/ci-fast.yml?query=branch%3Adev)
[![Documentation](https://readthedocs.org/projects/hydromodpy-docs/badge/?version=dev)](https://hydromodpy-docs.readthedocs.io/en/dev/)
[![Codecov](https://codecov.io/gh/HydroModPy/HydroModPy/branch/dev/graph/badge.svg)](https://codecov.io/gh/HydroModPy/HydroModPy/tree/dev)

## What you get

- **One config, four solvers.** A single `HydroModPyConfig` (Pydantic v2)
  drives MODFLOW 6, MODFLOW-NWT, Boussinesq and GR4J on the same catchment.
- **Bit-exact reproducibility.** A frozen `hydromodpy.lock` and the
  `runs_environment` provenance table (Python, packages, git commit, host,
  timestamp) pin every run.
- **ML-friendly storage.** A DuckDB catalog, per-simulation Parquet tables
  and per-simulation Zarr stores plug straight into sklearn, PyTorch, JAX,
  xarray and xugrid pipelines.
- **End-to-end provenance.** Every solver run, calibration iteration and
  derived metric is traceable back to its config, inputs and binaries.

## Install

```bash
pip install hydromodpy
```

Optional extras: `[ide]`, `[test]`, `[viewer3d]`, `[docs]`. Solver binaries
(MODFLOW 6, MODFLOW-NWT, MODPATH, MT3D-USGS) are downloaded on demand into
`~/.cache/hydromodpy/bin/` on first solver run, or eagerly with
`hmp install-binaries`.

For developer install, conda recipes, Windows + WSL setup and the PETSc
backend, see the [installation guide](https://hydromodpy-docs.readthedocs.io/en/dev/install.html).

## Quickstart

Scaffold a workspace, create a project from a template, run it.

```bash
hmp init .
hmp new getting_started --workspace .
hmp run projects/getting_started/run_demo.toml
```

Outputs land next to the config:

- `hydromodpy.duckdb` - unified simulation catalog.
- `simulations/<basename>.zarr.zip` - finalized spatial fields per run.
- `simulations/<basename>.parquet/` - tabular views (timeseries, budgets, mass balance).

Open the results from Python:

```python
import hydromodpy as hmp

catalog = hmp.open(".")
sim = catalog.best("getting_started")
sim.plot("watertable_map", save=".")
```

For SQL queries, Parquet batch loading and Zarr DataLoaders, see the
[ML access guide](https://hydromodpy-docs.readthedocs.io/en/dev/user_guide/index.html).

## Documentation

Full documentation lives at
**[hydromodpy-docs.readthedocs.io](https://hydromodpy-docs.readthedocs.io/en/dev/)**.

| Section | What it covers |
|---------|----------------|
| [Get started](https://hydromodpy-docs.readthedocs.io/en/dev/getting_started/index.html) | Install, scaffold, first run end to end. |
| [User Guide](https://hydromodpy-docs.readthedocs.io/en/dev/user_guide/index.html) | Workflows, configuration, theory, cookbook. |
| [Configuration](https://hydromodpy-docs.readthedocs.io/en/dev/user_guide/config_reference/index.html) | Every TOML section validated by `HydroModPyConfig`. |
| [Gallery](https://hydromodpy-docs.readthedocs.io/en/dev/capability_gallery/index.html) | Validation figures, mesh illustrations, watershed diagnostics. |
| [API Reference](https://hydromodpy-docs.readthedocs.io/en/dev/api/index.html) | Auto-generated reference for every public class and module. |
| [Architecture](https://hydromodpy-docs.readthedocs.io/en/dev/architecture/index.html) | Layer matrix, module diagrams, contributor maps. |

## Contributing

Bug reports, feature requests and pull requests are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the short version and the
[contributor guide](https://hydromodpy-docs.readthedocs.io/en/dev/contribute.html)
for the full reference.

Security issues: please follow [SECURITY.md](SECURITY.md) and use a private
advisory rather than a public issue.

## How to cite

If HydroModPy supports your work, please cite the software and the companion
paper. Full BibTeX, RIS and plain-text entries are on the
[citation page](https://hydromodpy-docs.readthedocs.io/en/dev/how_to_cite.html);
GitHub renders the "Cite this repository" button from
[`CITATION.cff`](CITATION.cff).

> Gauvain, A., Abhervé, R., Boivin, B., Roques, C., Le Mesnil, M., Coche, A.,
> Babey, T., Marçais, J., Bouchez, C., Leray, S., Marti, E., Bresciani, E.,
> Figueroa, R., Pélissier, M., Guillaumot, L., Touzeau, T., Issolah, I.,
> Maugan, E., Bagagnan, R. S., Vautier, C., Sallou, J., Bourcier, J.,
> Combemale, B., Brunner, P., Longuevergne, L., Aquilina, L., & de Dreuzy, J.-R.
> (2026). Technical note: HydroModPy – a Python toolbox for deploying
> catchment-scale shallow groundwater models. *EGUsphere* [preprint], 1–31.
> <https://doi.org/10.5194/egusphere-2026-868>

## Authors and contact

HydroModPy is developed by Geosciences Rennes (Université de Rennes, CNRS)
together with collaborators at CHYN Neuchâtel, INRAE, Pontificia Universidad
Católica de Chile, Universidad de O'Higgins, WUR, Inria/IRISA and CNRS-LMD.
The complete author list with affiliations is maintained in
[`CITATION.cff`](CITATION.cff).

For questions or collaboration: <alexandre.gauvain.ag@gmail.com> or
<ronan.abherve@gmail.com>.

## License

HydroModPy is released under the [Eclipse Public License 2.0](https://opensource.org/licenses/EPL-2.0).
See [LICENSE](LICENSE).
