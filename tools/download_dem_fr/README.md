# download_dem_fr

A standalone command to list and download IGN DEM archives by French department or region from Geoplateforme.

The normal HydroModPy workflow goes through `[data.dem]`. This tool prepares, tests or checks the raw cache of
departmental archives. It needs no package beyond HydroModPy itself.

Raw archives are stored outside the Git repository, in `$HYDROMODPY_WORKSPACE/data/dem/raw_ign/`. Without
`HYDROMODPY_WORKSPACE` the folder is `~/hydromodpy/data/dem/raw_ign/`.

## Examples

List the RGE ALTI archives without downloading:

```bash
python tools/download_dem_fr/download_dem_fr.py \
  --departements 29 35 \
  --dataset rge-alti \
  --resolution 5 \
  --format ASC \
  --dry-run
```

List a whole region in BD ALTI 25 m, with the checksums when Geoplateforme gives them:

```bash
python tools/download_dem_fr/download_dem_fr.py \
  --regions Bretagne \
  --dataset bd-alti \
  --resolution 25 \
  --format ASC \
  --dry-run \
  --include-md5
```

Download BD ALTI 25 m for several departments:

```bash
python tools/download_dem_fr/download_dem_fr.py \
  --departements 01 03 07 15 \
  --dataset bd-alti \
  --resolution 25 \
  --format ASC
```

Download RGE ALTI for an overseas department:

```bash
python tools/download_dem_fr/download_dem_fr.py \
  --departements 971 \
  --dataset rge-alti \
  --resolution 5
```

## Cache

Files are stored by dataset, resolution and department:

```text
~/hydromodpy/data/dem/raw_ign/
  bd-alti/25m/D035/BDALTIV2_...D035....7z
  rge-alti/5m/D029/RGEALTI_...D029....7z
```

A non-empty local file is reused. Pass `--overwrite` to download it again.

`--regions` and `--departements` exclude each other. Regions are resolved with the HydroModPy administrative
registry and turned into departments before the Geoplateforme lookup.

## Limits

The client tries the Geoplateforme lookup first. If the API is down, the case `bd-alti --resolution 25 --format ASC`
falls back on the HydroModPy internal index of BD ALTI archives.

RGE ALTI is only supported here as a raw download. The raster assembly in `DemManager` stays limited to BD ALTI 25 m
ASC, until the fragmented archives and the RGE ALTI 1 m and 5 m volumes have storage and processing limits.
