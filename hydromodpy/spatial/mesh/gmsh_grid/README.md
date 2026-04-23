# gmsh_grid Package

This package contains the reusable Gmsh-based mesh tooling used by HydroModPy.

The main idea is to keep the stack layered:

- `gmsh_reader.py` and `gmsh_planar_mesh.py`
  read, normalize and expose 2D planar meshes;
- `extruded_prism_mesh.py`, `extruded_mesh_values.py`,
  `extruded_fieldparam_discretization.py`, and the viewer/plotting helpers
  build and inspect 3D meshes obtained by vertical extrusion;
- `catchment_mesh_bundle.py` and `catchment_mesh_bundle_reader.py`
  export a self-contained exchange bundle that can be reused outside the full
  HydroModPy codebase;
- `zone_meshing/`
  contains the conformal meshing workflow that drives Gmsh from polygonal
  geology zones, river lines and optional internal constraints;
- `cases/`
  contains runnable reference and comparison scripts used for manual review and
  non-regression validation.

## Mental Model

There are really two families of tools here.

### 1. Mesh I/O and mesh data structures

These modules answer questions such as:

- How do we read a `.msh` file into a stable internal object?
- How do we expose a planar or extruded mesh through the HydroModPy mesh APIs?
- How do we attach values, summaries and plotting helpers to these meshes?

This part is mostly about normalization, bookkeeping and exchange formats.

### 2. Zone-conformal mesh generation

The `zone_meshing` subpackage answers a different question:

- Starting from polygons and line constraints, how do we generate a mesh whose
  edges follow the relevant geological or hydrological interfaces?

This part is mostly about geometry cleaning, domain loading, partition building
and controlled interaction with the Gmsh Python API.

## Public Typed API

The public `zone_meshing` entry points are now intentionally typed.

For new code, prefer:

- `parse_zone_meshing_settings(...)` to validate meshing settings;
- `parse_zone_meshing_domain_config(...)` to validate the support-domain block;
- `load_zone_meshing_domain_payload(...)` to load the resolved domain geometry
  from one `ZoneMeshingDomainConfig`;
- `generate_zone_conformal_mesh_from_dataframe(...)` or
  `generate_zone_conformal_mesh_from_geology_config(...)` to run Gmsh.

The older mapping-only wrappers were removed so the public API now matches the
typed contracts used internally by the launcher and the reference case.

## Recommended Reading Order

For the reusable core, the fastest reading order is:

1. `README.md`
2. `__init__.py`
3. `gmsh_reader.py`
4. `gmsh_planar_mesh.py`
5. `exchange_api.py`
6. `catchment_mesh_bundle_reader.py`
7. `catchment_mesh_bundle.py`
8. `zone_meshing/domain.py`
9. `zone_meshing/config.py`
10. `zone_meshing/_geometry_cleaning.py`
11. `zone_meshing/_gmsh_driver.py`
12. `zone_meshing/conformal.py`

That order goes from the simplest mesh payloads to the most advanced meshing
workflow.

## Scope

The package is intentionally pragmatic. It focuses on:

- simple and auditable geometry handling,
- stable exchange formats,
- clear separation between geometry preparation and direct Gmsh calls,
- small public entry points that can be reused by launchers and validation
  scripts.

It is not meant to hide every implementation detail. Many modules expose rich
intermediate objects on purpose so developers can inspect what happened during
meshing, extrusion or bundle export.
