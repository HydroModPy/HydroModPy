# Gmsh Zone-Conformal Meshing Plan

Status: design note, no implementation in this document.

## Installation status in this workspace

- The Python package `gmsh` is now available and importable.
- Verified version: `gmsh 4.15.1`.
- The standalone `gmsh.exe` CLI is still not on `PATH`.
- For the integration proposed here, the Python API is sufficient.

## Objective

Add a new meshing path in `gmsh_grid` able to generate a **zone-conformal 2D mesh**
from vector geology zones, so that:

- mesh edges follow geology interfaces;
- each mesh cell belongs to one zone without crossing a zone boundary;
- zone ids are preserved as explicit mesh metadata;
- the mesh can still be consumed through the existing `BaseFieldMesh`-style API;
- the current read-only / projection workflow remains available.

This is a second capability, not a replacement of the current workflow.

## What is true today

Today `gmsh_grid` mainly does:

- read an existing `.msh`;
- expose it as `GmshPlanarMesh2D`;
- project geology / `FieldParam` on that mesh;
- optionally extrude the planar mesh to a 3D prism mesh.

What it does **not** do today:

- build CAD geometry from geology polygons;
- ask Gmsh to mesh that geometry;
- guarantee that mesh edges coincide with geology interfaces.

So the current workflow is:

`zones -> projection on existing mesh`

The new target workflow would be:

`zones -> geometry partition -> Gmsh meshing -> mesh already aligned with zones`

## Core design principle

If we want a mesh to respect geology boundaries, geology polygons must stop being
"only a support field to sample" and become an actual **geometric partition**
given to the mesher.

This changes the role of geology in the meshing path:

- current path: geology is sampled on cells;
- future conformal path: geology defines the surfaces to mesh.

That means the hard problem is not meshing itself. The hard problem is building
a **clean topological partition** from geology polygons.

## Recommendation

My recommendation is to add a **new explicit meshing workflow** instead of
trying to mutate the current read-only reader path.

Concretely:

- keep the current `read existing mesh + project values` path as-is;
- add a parallel `generate mesh from zones` path;
- make both paths converge to the same downstream object:
  `GmshPlanarMesh2D` + metadata.

This keeps the architecture clean:

- generation is one concern;
- reading/exchange is another;
- projection of `Field` / `FieldParam` stays independent.

## Proposed product scope

### In scope

- 2D conformal mesh generation from geology polygons;
- optional clipping by model domain;
- preservation of zone ids and interface ids;
- support for triangles first, quadrilateral recombination later if needed;
- consistent readback into `GmshPlanarMesh2D`;
- use of Gmsh Python API, not shelling out to an external executable.

### Out of scope for first iteration

- full 3D geological conformal meshing;
- volumetric meshing directly in Gmsh;
- full solver coupling on unstructured mesh;
- automatic healing of arbitrarily broken GIS data without tolerances;
- mixed triangle/quad target in the same first release.

## Proposed architecture

Create a new sub-package under:

`hydromodpy/solver/utils/mesh/gmsh_grid/zone_meshing/`

Suggested files:

- `config.py`
  - validate meshing config payloads;
  - define the meshing contract.
- `zone_sources.py`
  - load polygons from shapefile / geopackage / GeoDataFrame-like input;
  - normalize CRS and ids.
- `zone_cleaning.py`
  - validity repair;
  - simplification;
  - sliver filtering;
  - snapping / tolerance handling.
- `zone_partition.py`
  - build a non-overlapping planar partition;
  - clip by domain;
  - produce explicit interfaces between adjacent zones.
- `gmsh_occ_builder.py`
  - convert partition polygons into Gmsh OCC geometry;
  - create points, curves, curve loops, plane surfaces.
- `gmsh_size_fields.py`
  - global size;
  - interface refinement;
  - small-zone refinement;
  - distance / threshold fields.
- `gmsh_generate.py`
  - initialize Gmsh;
  - build geometry;
  - synchronize;
  - generate 2D mesh;
  - write `.msh`.
- `metadata.py`
  - attach zone ids / interface ids / physical groups to outputs;
  - define readback conventions.
- `run_zone_conformal_case.py`
  - reference runner for the new path.

## Proposed config contract

I would not overload the existing `case.mesh.path` config. I would create an
explicit generation section.

Example:

```toml
[case]
output_mesh = "outputs/geology_conformal.msh"
output_summary_json = "outputs/geology_conformal_summary.json"
output_figure = "outputs/geology_conformal_overview.png"

[case.zone_meshing]
kind = "gmsh_generate"
algorithm = "delaunay"
recombine = false
global_size = 250.0
min_size = 50.0
max_size = 500.0
refine_interfaces = true
interface_size = 75.0
refine_small_zones = true
small_zone_area_threshold = 2.0e5
small_zone_size = 40.0
simplify_tolerance = 0.0
heal_tolerance = 1.0
clip_to_domain = true

[case.domain]
source = "polygon"
path = "..."
id_field = "domain_id"
selected_id = "main"

[case.geology]
source = "vector"
path = "..."
code_field = "CODE_LEG"
name_field = "LIBELLE"
priority_field = "priority"
```

Important design choice:

- `case.mesh.path` should remain the "use an existing mesh" contract;
- `case.zone_meshing.*` should become the "generate one mesh from zones" contract.

This avoids ambiguous configs.

## Detailed pipeline

### Step 1: load domain and geology polygons

Inputs:

- geology polygons with a stable zone key;
- optional domain polygon;
- optional priority field for overlaps.

Requirements:

- a single projected CRS in metric units;
- polygon-only input after filtering;
- no null zone key.

Checks:

- CRS present and metric enough for mesh sizing;
- unique / non-empty zone keys;
- input count and bounding boxes logged in summary.

### Step 2: clean geometry

This step is mandatory. Real geology GIS data is often not meshing-ready.

Operations:

- `make_valid` / repair invalid polygons;
- remove empty geometries;
- explode multipart features;
- optional simplify with tolerance;
- optional snap to tolerance;
- optional remove slivers below area threshold;
- optional dissolve by zone key if multiple polygons share one code.

Output of this step:

- clean polygon set per zone;
- domain polygon;
- diagnostics about discarded / repaired geometries.

### Step 3: build a proper planar partition

This is the most important step.

Goal:

- obtain a set of non-overlapping polygon pieces whose union equals the meshed
  domain;
- each piece has exactly one owning zone;
- shared boundaries are explicit and unique.

Recommended approach:

1. clip geology by domain;
2. resolve overlaps using priority rules;
3. compute a planar partition from all boundaries;
4. assign each resulting face to a zone;
5. build adjacency relations between neighboring faces.

At the end of this step we should know:

- all partition faces;
- their owning `zone_key`;
- all interface curves;
- for each interface, the pair of neighboring zones.

Without this step, we do not really have a conformal zone mesh.

### Step 4: convert the partition into Gmsh geometry

Use the Gmsh Python OCC API.

High-level plan:

1. `gmsh.initialize()`
2. `gmsh.model.add(...)`
3. create points and curves for partition boundaries;
4. create one plane surface per partition face;
5. synchronize;
6. optionally fragment / remove duplicates if needed;
7. create physical groups.

Physical groups should be used for:

- surfaces per `zone_key`;
- outer boundaries;
- optionally internal interfaces.

Suggested naming:

- surface physical group: `zone::<zone_key>`
- line physical group: `interface::<zone_a>::<zone_b>`
- line physical group on outer border: `boundary::<name>`

## Mesh sizing strategy

A conformal mesh that follows every interface can explode in size if we are not
careful. So size control is part of the design, not an afterthought.

### First-iteration strategy

Support these controls:

- one global target size;
- one smaller target size near internal interfaces;
- one smaller target size for small / narrow zones;
- optional curvature adaptation off by default.

Gmsh fields to consider:

- `Distance`
- `Threshold`
- `Min`

Typical logic:

- build a distance field to all internal interface curves;
- apply a threshold field to refine near interfaces;
- optionally add a dedicated field for small-zone centroids or boundaries;
- combine with a `Min` field.

### Why this matters

Without refinement near interfaces:

- the mesh may technically conform to boundaries;
- but still underresolve narrow geological corridors.

Without a global cap:

- tiny GIS defects can create absurd local refinement and huge meshes.

## Proposed implementation sketch

This is not production code, but it is the right level of implementation detail
to guide the first PR.

```python
import gmsh


def generate_zone_conformal_mesh(partition, config, output_path):
    gmsh.initialize()
    try:
        gmsh.model.add("zone_conformal")
        occ = gmsh.model.occ

        point_tags = {}
        curve_tags = {}
        surface_tags = {}

        for point in partition.unique_points:
            point_tags[point.id] = occ.addPoint(point.x, point.y, 0.0)

        for edge in partition.edges:
            curve_tags[edge.id] = occ.addLine(
                point_tags[edge.start_id],
                point_tags[edge.end_id],
            )

        for face in partition.faces:
            loop = occ.addCurveLoop([curve_tags[eid] for eid in face.edge_ids])
            surface_tags[face.id] = occ.addPlaneSurface([loop])

        occ.synchronize()

        for zone_key, face_ids in partition.face_ids_by_zone.items():
            tags = [surface_tags[fid] for fid in face_ids]
            pg = gmsh.model.addPhysicalGroup(2, tags)
            gmsh.model.setPhysicalName(2, pg, f"zone::{zone_key}")

        for interface_name, edge_ids in partition.edge_ids_by_interface.items():
            tags = [curve_tags[eid] for eid in edge_ids]
            pg = gmsh.model.addPhysicalGroup(1, tags)
            gmsh.model.setPhysicalName(1, pg, interface_name)

        apply_size_fields(gmsh.model, partition, config)

        gmsh.model.mesh.generate(2)
        gmsh.write(str(output_path))
    finally:
        gmsh.finalize()
```

## Metadata that must survive readback

The existing reader path mostly cares about geometry and connectivity.
For conformal meshing, that is not enough.

We should preserve at least:

- `zone_key` per surface or per cell block;
- physical group name and dimension;
- interface ids if available;
- source CRS and units in the summary JSON;
- meshing options used to generate the mesh.

I would not force all this into `GmshPlanarMesh2D` immediately.
Instead:

- keep `GmshPlanarMesh2D` focused on geometry;
- add a small sidecar metadata object or summary payload.

## Integration with existing HydroModPy contracts

The downstream story should stay simple:

1. generate `.msh` with zone-conformal surfaces;
2. read it back with `GmshPlanarMesh2D.from_file(...)`;
3. if needed, read the sidecar metadata to keep `zone_key` information;
4. reuse `Field.on_mesh(mesh)` and `FieldParam.to_mesh_field(...)`.

Important point:

- a conformal mesh does not remove the need for projection logic;
- but it changes the expected fractions:
  most cells should become pure-zone cells, and mixed cells should collapse
  toward zero except near intended non-zone supports.

## Validation strategy

Validation should happen at three levels.

### 1. Geometry validity

Need assertions on:

- no self-intersections after cleaning;
- no overlaps between partition faces above tolerance;
- domain fully covered above tolerance;
- no duplicate internal edges.

### 2. Mesh conformity

Need assertions on:

- all zone boundaries appear as mesh edges;
- no triangle / quad crosses an interface;
- physical groups exist for all expected zones;
- no zone disappears unexpectedly.

### 3. HydroModPy behavior

Need assertions on:

- `support_field.on_mesh(mesh)` still works;
- `FieldParam.to_mesh_field(...)` still works;
- mixed cell count drops strongly compared with a non-conformal mesh;
- figures and summaries remain readable.

## Proposed test plan

### Synthetic tests first

Do not start on Brittany shapefiles directly.

Start with a tiny analytic case:

- rectangular domain;
- 3 to 5 polygons;
- one diagonal interface;
- one narrow corridor;
- one nested sub-zone.

Why:

- deterministic;
- fast;
- easy to assert exact counts and interfaces.

Suggested tests:

- `test_zone_partition_no_overlap.py`
- `test_zone_partition_adjacency.py`
- `test_gmsh_generate_conformal_mesh.py`
- `test_gmsh_physical_groups.py`
- `test_field_projection_on_conformal_mesh.py`

### Real-data regression second

Then add a small clipped Brittany geology subset:

- not full regional scale first;
- one manageable window with several geology contacts.

Suggested outputs:

- mesh overview PNG;
- zone overlay PNG;
- summary JSON with counts;
- optional golden signature on cell count, zone coverage, mixed-cell count.

## Proposed delivery plan

### Phase 1: minimal working path

- add `gmsh` dependency note and import wrapper;
- create synthetic polygon partition pipeline;
- generate a conformal triangle mesh;
- write `.msh`;
- read it back into `GmshPlanarMesh2D`;
- add one reference case and one figure.

Exit criteria:

- one synthetic case runs end-to-end;
- mesh edges clearly follow zone interfaces.

### Phase 2: real geology input

- load geology polygons from vector source;
- clean and clip by domain;
- assign zone ids;
- build planar partition;
- generate the mesh.

Exit criteria:

- one clipped real-data case succeeds;
- topology diagnostics are explicit.

### Phase 3: meshing controls

- add interface refinement;
- add small-zone protection;
- add summary statistics on mesh size and interface coverage.

Exit criteria:

- mesh is not explosively refined by default;
- narrow zones remain represented.

### Phase 4: QA and user-facing examples

- add a polished runner in `cases/`;
- produce figure(s) showing geology, interfaces, and final mesh;
- add documentation and config examples.

Exit criteria:

- another developer can run the case from TOML without reading internals.

## Risks and mitigation

### Risk 1: dirty GIS data

Symptoms:

- invalid polygons;
- overlaps;
- gaps;
- microscopic slivers.

Mitigation:

- explicit cleaning pipeline;
- tolerance knobs in config;
- diagnostics in summary JSON.

### Risk 2: mesh explosion

Symptoms:

- too many cells around noisy interfaces;
- impractical runtimes.

Mitigation:

- simplify before meshing;
- distance-based local refinement;
- minimum feature size policy;
- sliver removal threshold.

### Risk 3: metadata loss after readback

Symptoms:

- mesh geometry survives, but zone meaning is lost.

Mitigation:

- explicit physical groups;
- sidecar metadata JSON;
- reader extension only if needed.

### Risk 4: too much coupling with current projection code

Symptoms:

- generation logic leaks into `Field` or `FieldParam`.

Mitigation:

- keep generation fully in `zone_meshing/`;
- downstream still only sees mesh + metadata.

## Open design decisions

These should be decided before implementation starts:

1. Should the first conformal mesher support only triangles?
   - My recommendation: yes.

2. Should overlaps be solved by priority or by hard failure?
   - My recommendation: support both, default to hard failure unless a
     `priority_field` is provided.

3. Should interface ids be first-class metadata?
   - My recommendation: yes, at least in summary JSON and physical groups.

4. Should the first real-data case be full Brittany?
   - My recommendation: no, start with a clipped subset.

5. Should the existing reference case be rewritten to generate the mesh?
   - My recommendation: no, add a new case alongside the current read-only case.

## Final recommendation

The best next step is **not** to rewrite the current `reference_2d_geology_base`
runner. The best next step is:

1. add a new synthetic conformal meshing case;
2. prove that we can build a clean partition from zones;
3. generate one Gmsh mesh whose edges follow those interfaces;
4. only then connect this new path to real geology vector data.

This gives the project a real Gmsh meshing capability while preserving the
current clean separation between:

- mesh generation;
- mesh I/O;
- field projection;
- solver-specific logic.
