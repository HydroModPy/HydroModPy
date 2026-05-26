# Geographic config legacy cleanup report

Date: 2026-05-27

## Lot: centralisation du remapping `[geographic]` plat

Objectif: retirer la duplication de compatibilite entre le loader TOML et le
modele `GeographicConfig`.

Constat:

- Le format plat historique reste tres present dans les exemples et fixtures:
  `catch_def`, `dem_init_path`, `x_outlet`, `y_outlet`, `snap_dist`,
  `buff_area`, `polyg_shp_path`.
- Le supprimer directement casserait de nombreux TOML commits. La suppression
  doit donc passer par une migration mecanique des fichiers avant retrait du
  support modele.

Changements:

- Ajout de `normalize_geographic_catchment_payload()` dans
  `hydromodpy/spatial/geographic/geographic_config.py`.
- `GeographicConfig` utilise ce helper pour le support transitoire du payload
  plat.
- `hydromodpy/config/toml_section_loader.py` ne porte plus sa propre liste de
  cles legacy et delegue la normalisation au helper du modele.
- Ajout de tests pour figer cette frontiere.

Validation:

- `python -m ruff check hydromodpy/config/toml_section_loader.py hydromodpy/spatial/geographic/geographic_config.py tests/unit/config/test_toml_loader.py tests/unit/geographic/test_geographic_config.py`
- `python -m pytest tests/unit/config/test_toml_loader.py tests/unit/geographic/test_geographic_config.py -q`

Resultat: 26 tests passes.

## Proposition du lot suivant

Migrer les TOML commits du format plat:

```toml
[geographic]
catch_def = "from_outlet_coord"
dem_init_path = "dem.tif"
x_outlet = 1.0
y_outlet = 2.0
```

vers le format canonique:

```toml
[geographic]

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "dem.tif"
x_outlet = 1.0
y_outlet = 2.0
```

Ensuite seulement, retirer `normalize_geographic_catchment_payload()` et faire
echouer explicitement les payloads plats.
