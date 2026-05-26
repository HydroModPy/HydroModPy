# download_dem_fr

CLI autonome pour explorer et telecharger des archives DEM/MNT IGN par
departement ou region administrative depuis Geoplateforme.

Le workflow HydroModPy normal doit continuer a passer par `[data.dem]`. Cet
outil sert a preparer, tester ou diagnostiquer le cache brut des archives
departementales.

Par defaut, les archives brutes sont rangees hors du depot Git:

```text
HYDROMODPY_WORKSPACE/data/dem/raw_ign/
```

Si `HYDROMODPY_WORKSPACE` n'est pas defini, le fallback est:

```text
~/hydromodpy/data/dem/raw_ign/
```

## Installation minimale

```bash
pip install -r tools/download_dem_fr/requirements.txt
```

## Exemples

Lister les archives RGE ALTI sans telecharger:

```bash
python tools/download_dem_fr/download_dem_fr.py \
  --departements 29 35 \
  --dataset rge-alti \
  --resolution 5 \
  --format ASC \
  --dry-run
```

Lister une region complete en BD ALTI 25 m, avec les checksums quand ils sont
exposes par Geoplateforme:

```bash
python tools/download_dem_fr/download_dem_fr.py \
  --regions Bretagne \
  --dataset bd-alti \
  --resolution 25 \
  --format ASC \
  --dry-run \
  --include-md5
```

Telecharger BD ALTI 25 m pour Paris:

```bash
python tools/download_dem_fr/download_dem_fr.py \
  --departements 75 \
  --dataset bd-alti \
  --resolution 25 \
  --dry-run
```

Telecharger RGE ALTI pour un departement ultramarin:

```bash
python tools/download_dem_fr/download_dem_fr.py \
  --departements 971 \
  --dataset rge-alti \
  --resolution 5
```

Preparer les departements Auvergne-Rhone-Alpes en BD ALTI 25 m:

```bash
python tools/download_dem_fr/download_dem_fr.py \
  --departements 01 03 07 15 26 38 42 43 63 69 73 74 \
  --dataset bd-alti \
  --resolution 25 \
  --format ASC
```

## Cache

Les fichiers sont ranges par dataset, resolution et departement:

```text
~/hydromodpy/data/dem/raw_ign/
  bd-alti/
    25m/
      D035/
        BDALTIV2_...D035....7z
  rge-alti/
    5m/
      D029/
        RGEALTI_...D029....7z
```

Un fichier local non vide est reutilise par defaut. Utiliser `--overwrite` pour
forcer un nouveau telechargement.

`--regions` et `--departements` sont exclusifs. Les regions sont resolues via
le registre administratif HydroModPy, puis converties en departements avant la
decouverte Geoplateforme.

## Limites

Le client tente d'abord la decouverte Geoplateforme. Si l'API est
temporairement indisponible, le cas `bd-alti --resolution 25 --format ASC`
dispose d'un fallback sur la table historique HydroModPy des archives BD ALTI.

RGE ALTI est pris en charge ici comme telechargement brut. L'assemblage raster
automatique dans `DemManager` reste volontairement limite a BD ALTI 25 m ASC
tant que les archives fragmentees et les volumes RGE ALTI 1 m/5 m ne sont pas
bornes par des garde-fous de stockage et de traitement.
