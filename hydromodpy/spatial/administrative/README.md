# spatial/administrative

This package knows the French departments. It holds one small file with their outlines, and it
answers questions about a place in France: which departments a rectangle touches, which
departments make a region, and what area and rectangle they cover. The data managers use it to
download only the tiles that a study area needs. It makes no network call.

The package does not find the department of a point. Its search works on a rectangle (a bounding
box). A rectangle that shrinks to one point would return the department under that point, but no
function takes a point.

## How a question is answered

1. A caller gives a rectangle in EPSG:2154 (Lambert-93), a list of departments or a list of
   regions.
2. `france.py` reads `departement.gpkg`. If the file is in another CRS, it is reprojected to
   EPSG:2154.
3. For a rectangle, it keeps the departments whose outline touches it. For a region, it keeps the
   departments of that region. For departments, it keeps the ones asked for.
4. It returns sorted codes, a bounding box (with an optional margin in meters) or the union of
   the outlines. The bounding box is always in EPSG:2154, the union in the CRS asked for (EPSG:2154 by default).

A department code is always written with three characters: `35` becomes `035`, `2A` becomes
`02A`, and `971` stays `971`. A region is given by its name, with or without accents and capitals,
or by its code. The names and codes come from `hydromodpy/spatial/administrative/regions.py`, which
the data config also reads. An unknown region is refused with a clear message. A list of departments is refused only when none of its codes is known, and an unknown code beside known ones is skipped.

The file holds 101 departments, metropolitan and overseas. The outlines come from IGN
ADMIN EXPRESS and are simplified, with a tolerance of 500 m, so a border is only accurate to a few hundred meters. The
package is for choosing which departments to download, not for measuring.

## The folder map

```text
administrative/
├── regions.py          the names and codes of the French regions, and their spelling rules
├── france.py           the questions: codes in a rectangle or a region, bounding box, union outline
└── departement.gpkg    outlines of the departments in EPSG:2154, with their code and region code
```

## Where to start

| To change | Open first |
|-----------|------------|
| which departments a rectangle touches | `france.py`, `find_departments_in_bbox` |
| the departments of a region | `france.py`, `find_departments_in_regions` |
| the rectangle or the outline of some departments or regions | `france.py`, `bbox_for_departments`, `geometry_for_departments` |
| the spelling of a department code | `france.py`, `department_code_to_padded` |
| the accepted region names | `hydromodpy/spatial/administrative/regions.py` |
| another country | a new module beside `france.py` |

## Rules between the folders

- `france.py` imports the region helpers of `hydromodpy/spatial/administrative/regions.py` and nothing
  else from HydroModPy. Its other imports are geopandas and shapely.
- No import is deferred inside this package.
- The callers import it inside their functions: `hydromodpy/data/variables/dem/manager.py`,
  `hydromodpy/data/variables/dem/apis/ign_dem_fr.py` and
  `hydromodpy/data/variables/geology/apis/brgm_50k.py`.

The rules between HydroModPy layers are checked by `tests/unit/architecture/`.

## Changing the code

The tests are in `tests/unit/administrative/test_france.py`. The data source contract
`tests/contract/test_data_source_contract.py` also calls `find_departments_in_bbox`. The CI job
`mesh-coverage` in `.github/workflows/main-ci.yml` fails when the coverage of
`hydromodpy/spatial/administrative/*` is under 100.0, so every line of `france.py` needs a test.

```bash
pytest tests/unit/administrative -q
```

When the `.gpkg` file is replaced, keep a code column named `code_insee` and a region column named
`code_insee_de_la_region`, because `france.py` reads them by name.

## Documentation

No page of `docs/source/` describes this package. The parameter page that exposes the regions it
serves is `docs/source/reference/parameters/data/dem.md`.
