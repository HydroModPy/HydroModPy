# Audit critique — packages `spatial/` et `solver/utils/mesh/`

**Auditeur** : expert maillage numérique & géomatique hydrogéologique
**Cible** : `hydromodpy/spatial/**` et `hydromodpy/solver/utils/mesh/**`
**Date** : 2026-04-17
**Méthode** : lecture exhaustive des modules (hors `examples/` et `cases/`), comparaison systématique avec FloPy, meshio, pysheds, whitebox-tools, conventions CF-UGRID et règles MODFLOW.

---

## 0. Synthèse exécutive

Le périmètre spatial est le plus volumineux du dépôt (~130 modules). Il est **fonctionnellement riche** (trois backends de maillage : SGrid cartésien, Gmsh planaire conformal, prismes extrudés 3D) mais souffre de **quatre pathologies structurelles** :

1. **Duplication architecturale** : deux pipelines géographiques concurrents (`pipeline.py` vs `core/domain_geographic_pipeline.py`), deux discrétiseurs `fieldparam` quasi-identiques (cartesian_grid vs gmsh_grid), deux maillages structurés presque jumeaux (`StructuredFieldMesh` vs `GeologyStructuredMesh`).
2. **Upscaling hydraulique non-physique** : la conductivité K est discrétisée par **nearest/linear/IDW** sans jamais recourir à la moyenne harmonique — contraire à Wen & Gómez-Hernández (1996), Renard & de Marsily (1997), et aux recommandations FloPy.
3. **Explosion en micro-fichiers** : `zone_meshing/` compte 25 modules dont 15 < 100 lignes, plusieurs sont de simples stubs.
4. **Absence de IDOMAIN/IBOUND et de gestion pinch-out** : l'abstraction `HydroMesh` ne porte ni masque d'activité, ni épaisseurs dégénérées, ce qui bloque tout modèle 3D sérieux à substratum incliné.

L'architecture de base (adapters FloPy/meshio, kernel OCC de Gmsh, conformal meshing edges-enforced) est **saine**. C'est principalement une dette de refactorisation et un manque de rigueur hydrogéologique qui plombent la note finale.

---

## 1. Grilles régulières (DIS) vs irrégulières (DISV/DISU)

### 1.1 État du support

| Type MODFLOW | Support actuel | Où | Verdict |
|---|---|---|---|
| **DIS** (structured 3D) | Partiel | `sgrid_generation.py` via FloPy `StructuredGrid` | Acceptable |
| **DISV** (vertex) | Partiel | `flopy_adapter.py::to_flopy_disv_args` (2D planar uniquement) | À améliorer |
| **DISU** (unstructured) | **Absent** | — | Problématique |

### 1.2 Analyse critique

- **DIS propre** : `sgrid_generation.py` construit une FloPy `StructuredGrid` avec `delr`/`delc` uniformes, `botm` via broadcast vectorisé (`botm = top[None,:,:] - (top-bot)[None,:,:] * alpha[:,None,None]`) — code O(nlay·nrow·ncol) sans boucle. Conforme aux conventions FloPy (row 0 = Y max, 0-based).
- **DISV incomplet** : `flopy_adapter.py:104` lève explicitement `ValueError` si `ndim != 2`. Aucune extrusion verticale (pas de `top[nrow,ncol]` + `botm[nlay,nrow,ncol]` gérés dans l'adapter). Le pivot `HydroMesh` reste donc **2D planar uniquement**, alors que le package annonce un outil de modélisation 3D.
- **DISU absent** : aucun code ne produit la connectivité topologique (cell2d, faces, areas) nécessaire à DISU.
- **Hypothèses implicites de régularité** : `sgrid_mesh_adapter.py:57-62` reconstruit `x_edges = xoff + np.cumsum(delr)` sans assertion `len(delr) == ncol` ; un utilisateur passant un `StructuredGrid` avec `delr` hétérogène ne sera pas averti.

### 1.3 Verdict

**À améliorer — DISV partiel, DISU absent.** Le code n'est pas prêt pour de vraies grilles irrégulières 3D.

### 1.4 Recommandations

1. Ajouter une énumération `MeshOrigin` (`DIS`, `DISV`, `DISU`, `UNSTRUCTURED`) dans `HydroMesh`.
2. Étendre `flopy_adapter.to_flopy_disv_args` pour supporter `top`/`botm` 3D.
3. Documenter explicitement la convention d'origine (coin SW géographique, indexing `xy`) dans `sgrid_generation.py`.
4. Ajouter assertions de cohérence `len(delr) == ncol`, `len(delc) == nrow` dans `sgrid_mesh_adapter.py`.

---

## 2. Délinéation de bassin (DEM → catchment)

### 2.1 Stack utilisée

| Étape | Algorithme | Bibliothèque | Verdict |
|---|---|---|---|
| Pit-filling / breaching | `fill_depressions` **ou** `breach_depressions` (choix TOML) | whitebox-tools | Conforme |
| Flow direction | D8 | whitebox (`d8_pointer`, `esri_pntr=False`) | Conforme (D8 seul) |
| Flow accumulation | D8 log-scaled | whitebox (`d8_flow_accumulation(log=True)`) | Conforme |
| Delineation amont (point) | `extract_catchment_from_point()` | `geographic/core/catchment_from_point.py` | OK |
| Delineation polygone | `extract_catchment_from_polygon()` | `catchment_from_polygon.py` | OK |

### 2.2 Critiques

- **D8 seul** : aucun choix D-infinity (Tarboton 1997) ou MFD (Seibert & McGlynn 2007). Pour DEM à résolution grossière (>50 m) ou terrains plats, D8 produit des artefacts en « escalier » et concentre l'écoulement dans des lignes de drainage unicellulaires. Ce n'est pas un défaut absolu (D8 reste le standard industriel), mais la limitation n'est pas documentée.
- **Fallback breach → fill** (`domain_geographic_pipeline.py:198-219`) : tentative de rattrapage si `breach_depressions` produit un polygone vide. Pragmatique, mais aucun log clair ni avertissement utilisateur.
- **Pas de garde-fou sur la résolution DEM** : `pipeline_steps.py:76` lit `transform.a` et continue sans prévenir si la résolution est absurde (ex. 1000 m pour un petit bassin).
- **Pas de validation post-délinéation** : aucune vérification d'aire minimale, de validité topologique (polygone non auto-intersectant), ni de cohérence `exutoire ∈ bassin`.

### 2.3 Verdict

**Acceptable pour le cas d'usage D8 / Brittany**. Problématique si l'outil est appliqué à des DEMs hétérogènes sans garde-fous.

### 2.4 Recommandations

1. Ajouter paramètre `dem_resolution_min_m` en config avec validation bloquante.
2. Post-vérification : `polygon.area > min_area`, `polygon.is_valid`, `outlet.within(polygon)`.
3. Documenter explicitement le choix D8 et ses limites.
4. Exposer optionnellement D-inf ou MFD pour les bassins à terrain plat (whitebox supporte les deux).

---

## 3. Conventions MODFLOW (indices, nodata, IDOMAIN)

### 3.1 Indices 0-based / 1-based

| Adapter | Statut | Preuve |
|---|---|---|
| `flopy_adapter.py:110-112` | **0-based** ✓ | `cell2d = np.arange(n_cells, dtype=int)` |
| `meshio_adapter.py` | 0-based ✓ | concaténation numpy standard |
| `sgrid_mesh_adapter.py:57-62` | 0-based ✓ | construction `x_edges` via `cumsum` |
| `extruded_prism_mesh.py:156-188` | 0-based ✓ | `layer_indices >= 0` |

Conforme dans toute la chaîne. **Aucun cas observé de 1-based qui fuirait.**

### 3.2 Mapping (layer, row, col) vs (layer, cell2d)

- **Mapping DIS** : trivialement géré par FloPy.
- **Mapping DISV** : `flopy_adapter.py:29` implémente `_orient_nodes_for_disv` pour forcer l'ordre horaire attendu par MF6 — **bonne pratique**.
- **Mapping DIS → DISV (traçabilité)** : `HydroMesh` ne porte pas de champ `layer_mapping` ou `cell_provenance` permettant de retrouver la cellule (row, col) source d'une cellule DISV. Cela bloque toute comparaison inter-formats.

### 3.3 Nodata / IDOMAIN / IBOUND

- **Nodata fuyant** : `direct_dem_domain.py:84-90` lit `src.nodata` mais ne le propage qu'au masque interne. Les exports utilisent `-9999.0` hardcodé (`domain_rasters.py:62,132,160,167`) au lieu de l'héritage source. **C'est un bug caché** : un DEM source avec `nodata = -32768` produira des pixels non-masqués avec valeur `-32768` dans les exports.
- **IDOMAIN/IBOUND** : **totalement absents de `HydroMesh`**. Aucun champ `idomain: np.ndarray` ni masque d'activité. Impossible de gérer proprement :
  - les cellules désactivées (shale impénétrable, aquitard continu),
  - les pinch-outs (couches qui disparaissent),
  - les frontières internes complexes.

### 3.4 Verdict

| Aspect | Verdict |
|---|---|
| Indices 0-based | Conforme |
| DISV orientation | Conforme |
| Traçabilité (layer, row, col) → cell2d | À améliorer |
| Propagation nodata | **Problématique (bug)** |
| IDOMAIN/IBOUND | **Problématique (absent)** |

### 3.5 Recommandations

1. **Corriger le bug nodata** : tracer `src.nodata` dans `FlowProducts` et `DirectDemDomainProducts`, remplacer les hardcodes par la valeur héritée.
2. **Ajouter `idomain`** à `HydroMesh` et l'implémenter dans les adapters.
3. Ajouter `layer_mapping: Optional[np.ndarray]` pour traçabilité DIS↔DISV.

---

## 4. Intégration Gmsh et qualité du maillage

### 4.1 API et kernel

| Choix | État | Verdict |
|---|---|---|
| API Python native | ✓ (`gmsh.model.*` partout) | Conforme (bon choix) |
| Pas de fichiers `.geo` | ✓ | Conforme |
| Kernel OCC (moderne) | ✓ (aucun appel `gmsh.model.geo`) | Conforme |
| Gestion import optionnel | ✓ (`_deps.py::require_gmsh`) | Conforme |

C'est **la partie la mieux faite du package**. Le choix OCC est correct, l'import optionnel est propre, les erreurs sont explicites.

### 4.2 Conformal meshing

- **Edges enforced** : `conformal.py:271-310` crée une surface OCC distincte par zone puis les courbes partagées deviennent des frontières naturelles — bonne pratique.
- **Contraintes rivières** : `_curve_groups.py:84-97` utilise `gmsh.model.mesh.embed(1, [curve_tag], 2, surface_tag)` pour forcer le maillage à passer sur les rivières — correct.

### 4.3 Qualité du maillage

**Problématique** : aucune vérification de qualité n'est faite après `gmsh.model.mesh.generate(2)`.

- Pas d'appel à `gmsh.model.mesh.getElementQualities()`.
- Aucun seuil sur aspect ratio, skewness, angle minimum.
- Aucune option `Mesh.Quality*` définie.

Pour du MODFLOW 6 DISV, un triangle d'angle < 20° ou d'aspect ratio > 100 peut dégrader sévèrement la solution numérique (mauvaise matrice de raideur, oscillations). C'est **un manque critique**.

### 4.4 Extrusion 2D → 3D et pinch-outs

`extruded_prism_mesh.py:210-275` : extrusion naïve — la grille 2D est répétée pour chaque `z_interface`. Triangles → wedges (6 nœuds) ; quads → hexaèdres (8 nœuds). C'est formellement correct, mais :

- **Aucune détection de pinch-out** : si `top - botm[k] < tol`, des prismes dégénérés sont créés (volume ~0), ce qui fait diverger MODFLOW.
- **Aucun collapse de nœuds** : impossible de représenter une couche qui s'évanouit latéralement.

### 4.5 Micro-fichiers explosés (`zone_meshing/`)

**Répartition effective** (d'après l'inventaire des tailles) :

| Fichiers < 100 lignes | Nombre |
|---|---|
| `_gmsh_driver.py` (35 L) | stub façade |
| `_refinement_policy.py` (40 L) | 1 fonction |
| `__init__.py` (55 L) | re-exports |
| `_geometry_cleaning.py` (68 L) | 2 helpers |
| `_domain_geometry.py` (73 L) | 2 helpers |
| `_build_context.py` (85 L) | dataclass |
| Total < 100 L | **6 modules** |

Plus une dizaine d'autres < 250 L qui pourraient fusionner. Le découpage en contrats (`_geometry_contracts.py`, `_domain_contracts.py`, `_refinement_contracts.py`) est **trois fois le même motif** — un seul `contracts.py` suffirait.

### 4.6 Verdict

| Sous-aspect | Verdict |
|---|---|
| API Gmsh Python / OCC | Conforme |
| Conformal meshing edges-enforced | Conforme |
| Vérification qualité (aspect, skewness, angle) | **Problématique (absent)** |
| Pinch-outs / couches dégénérées | **Problématique** |
| Explosion micro-fichiers | À améliorer (over-engineering) |

### 4.7 Recommandations

1. Ajouter post-validation qualité : extraire les éléments, calculer aspect ratio et angle min, warner/rejeter si `aspect > 100` ou `angle < 20°`.
2. Détecter et supprimer les couches pinch-out (épaisseur < `tol`), ou marquer les prismes correspondants `idomain = -1`.
3. Fusionner `_geometry_contracts.py` + `_domain_contracts.py` + `_refinement_contracts.py` → `contracts.py`.
4. Fusionner `_geometry_cleaning.py` + `_polygon_cleaning.py` + `_geometry_utils.py` → `geometry.py`.
5. Supprimer `_gmsh_driver.py` (stub de 35 L sans valeur ajoutée) ou l'intégrer à `_gmsh_occ.py`.

---

## 5. Discrétisation des champs (K, Sy, Ss, recharge)

### 5.1 État actuel

Trois chemins de discrétisation existent :

| Backend | Module | Méthode par défaut | Moyenne harmonique ? |
|---|---|---|---|
| 2D cartésien | `cartesian_grid/sgrid_field_discretization.py` | `nearest` / `linear` / `idw` | **Non** |
| 3D cartésien | `cartesian_grid/sgrid_fieldparam_discretization.py` | idem (boucle layer) | **Non** |
| 3D Gmsh extrudé | `gmsh_grid/extruded_fieldparam_discretization.py` | point-wise `to_mesh_field()` | **Non** |
| 2D zones (fractions) | `spatial/field/core/field_param.py:745-749` | moyenne **arithmétique** pondérée par fraction | **Non** |

### 5.2 Critique hydrogéologique

**C'est le problème le plus grave du package.**

En hydrogéologie, l'upscaling de la conductivité K dépend de la direction du flux :

- **Flux perpendiculaire aux hétérogénéités** → moyenne **harmonique** (résistances en série).
- **Flux parallèle aux hétérogénéités** → moyenne **arithmétique**.
- **Cas isotrope / flux diagonal** → moyenne **géométrique** (borne de Wiener, Cardwell-Parsons).

Références : Wen & Gómez-Hernández (1996), Renard & de Marsily (1997), FloPy recommendations. Dans MODFLOW, la conductivité inter-cellule est d'ailleurs calculée en moyenne harmonique par défaut (`flow package`).

**Dans HydroModPy, K est traité comme n'importe quel champ scalaire**, avec nearest ou IDW. Cela produit :

- un biais positif systématique sur K (surestimation par moyenne arithmétique implicite),
- une sensibilité artificielle au raffinement du maillage,
- une invalidité des résultats dès que l'hétérogénéité K est significative (> 1 ordre de grandeur).

De plus, le chemin « zone fractions » (`field_param.py:745-749`) fait `weighted += frac * value` — une moyenne arithmétique pure, sans différenciation par type de paramètre.

### 5.3 Traitement des variables extensives (recharge, flux)

`planar_discretizer.py:89-103` utilise `rasterio.warp.reproject` avec sélection automatique `bilinear` (upsampling) / `average` (downsampling). `average` est une moyenne arithmétique — correct pour K en flux parallèle, **faux pour la recharge** qui doit être conservée en masse (somme × surface). Aucun paramètre `conserve_mass` n'existe.

### 5.4 Performance

`sgrid_fieldparam_discretization.py:259-279` boucle sur les couches en Python pur (`for ilay in range(nlay)`), appelant `field_param.to_mesh_field` une fois par couche. Pour `nlay=50`, `nrow=ncol=100`, cela fait 50 évaluations successives alors qu'une seule opération broadcast suffirait. **Sub-optimal**.

### 5.5 Verdict

| Aspect | Verdict |
|---|---|
| Interpolation générique (nearest/linear/IDW) | Acceptable |
| Moyenne harmonique pour K | **Problématique (absent)** |
| Conservativité pour recharge/flux | **Problématique (absent)** |
| Performance discrétisation 3D | À améliorer (boucle Python) |

### 5.6 Recommandations

1. **Urgent** : implémenter `harmonic_mean`, `geometric_mean` dans `spatial_interpolation.py`, ajouter un paramètre `upscaling_rule: {nearest, arithmetic, harmonic, geometric}` dans toutes les fonctions `discretize_*`. Faire de `harmonic` le défaut pour K.
2. Ajouter un paramètre `conserve_mass: bool` dans `planar_discretizer.py` pour les variables extensives.
3. Vectoriser la boucle layer si `field_param.to_mesh_field` accepte une entrée 3D, sinon documenter la limitation.

---

## 6. Formats d'export et interopérabilité

### 6.1 État

| Format | Support | Module | Conformité |
|---|---|---|---|
| **VTU** (VTK XML) | Oui | `mesh/io/vtu_io.py` via meshio | Conforme VTK |
| **PVD** (VTU temporel) | **Non** | — | Absent |
| **UGRID** (CF-conventions) | Théorique (via meshio) | Jamais testé | **Non-standard** |
| **Shapefile** | **Non** | — | Absent |
| **GeoTIFF** (rasters) | Oui (rasterio) | `geographic/geographic_io.py` | Conforme |
| **MSH** (Gmsh) | Oui | `_gmsh_export.py` (MSH2 ASCII) | Conforme |

### 6.2 Critiques

- **Pas de série temporelle VTU (PVD)** : impossible d'exporter proprement une simulation transitoire pour ParaView. `HydroMesh` ne porte que `cell_data`/`point_data` statiques.
- **CF-conventions zéro** : aucun attribut `standard_name`, `long_name`, `units` n'est attaché aux champs. Les exports sont incompréhensibles pour des outils génériques (xarray, QGIS, GDAL) sans documentation externe.
- **Pas de shapefile** : pour de la visualisation simple en SIG, aucun export 2D polygone direct. L'utilisateur doit passer par VTU → conversion manuelle.
- **MSH2 ASCII** au lieu de MSH4 binaire : format legacy, fichiers volumineux et lents à parser pour grands maillages.

### 6.3 Verdict

**Non-standard pour l'interopérabilité**. Le couplage fort à meshio/VTK limite la diffusion des résultats. L'absence de CF-UGRID exclut le package de l'écosystème xarray/scientific Python moderne.

### 6.4 Recommandations

1. Implémenter `write_pvd_timeseries(times, meshes, path)` pour les runs transitoires.
2. Ajouter un export UGRID-NetCDF (`ugrid_conventions=1.0`) via xarray ou meshio.
3. Exposer un export shapefile 2D basique via `geopandas`.
4. Attacher systématiquement `units` et `long_name` dans `cell_data`.

---

## 7. Surface topographique (DEM → z_interfaces)

### 7.1 Pipeline actuel

- `surface.py` : abstraction raster-support (DEM top unique).
- `surface_sampling.py::PreparedSurfaceSampler` : sampling bilinéaire vectorisé numpy avec clamping de bords et re-pondération NaN.
- `surface.shifted_down_by(offset)` (`surface.py:149-168`) : applique un offset **constant** au DEM pour dériver le substratum.

### 7.2 Critiques

- **Couches inclinées non gérées** : `shifted_down_by` ne prend qu'un scalaire. Un substratum incliné (pendage géologique) n'est représentable que par construction externe.
- **Pinch-outs absents** : aucune détection de cellule où top ≈ botm. Aucune méthode `extrude_layers(top, interfaces, pinch_tol)` qui générerait un IDOMAIN cohérent.
- **Sampler bilinéaire solide** : `PreparedSurfaceSampler.sample` (`surface_sampling.py:92-161`) est bien écrit — vectorisé numpy complet, clamping aux bornes (lignes 131-134), re-pondération correcte des NaN (lignes 150-159). Limité au bilinéaire (pas de bicubique ni spline), mais c'est acceptable pour la plupart des cas.
- **Nodata propagé correctement** dans le sampler (ligne 50).

### 7.3 Verdict

| Aspect | Verdict |
|---|---|
| Sampling bilinéaire | Conforme |
| Gestion nodata sampler | Conforme |
| Couches inclinées | **À améliorer (non supporté)** |
| Pinch-outs | **Problématique (absent)** |

### 7.4 Recommandations

1. Ajouter `extrude_layers(top: ndarray, interfaces: list[ndarray], pinch_tol: float) -> (top3d, botm3d, idomain)` dans `surface.py`.
2. Supporter un pendage : `shifted_down_by(offset: ndarray | float)` où `offset` peut être un array 2D (pendage spatialement variable).
3. Optionnellement : ajouter bicubique via `scipy.interpolate.RectBivariateSpline`.

---

## 8. Nommage et organisation

### 8.1 Pathologies nommage

| Problème | Fichier(s) | Comment ça **devrait** s'appeler |
|---|---|---|
| `CatchmentDomain` est une **fonction**, pas une classe | `geographic/core/catchment_domain.py:93-191` | `derive_catchment_domain_products()` ou vraie classe `CatchmentDomain` |
| `field_param` vs `field_spatial` vs `field_mesh` : trois concepts voisins, frontières floues | `spatial/field/core/*` | `parameter_field.py` / `spatial_zonation.py` / `mesh_support.py` |
| Préfixe `sgrid_` dans un dossier `cartesian_grid/` | `solver/utils/mesh/cartesian_grid/sgrid_*.py` | `generation.py`, `config.py`, `field_discretization.py` |
| `LegacyGeographicContext` et `DomainGeographicContext` coexistent | `geographic/pipeline.py` vs `geographic/core/domain_geographic_pipeline.py` | Une seule classe `GeographicContext` |

### 8.2 Organisation

- **Package `spatial/`** : niveau racine trop peuplé (11 fichiers hétérogènes : `pipeline.py`, `geographic.py`, `geographic_config.py`, `geographic_io.py`, `geographic_paths.py`, `domain_rasters.py`, `subbasin.py`, `store_ingestion.py`, `dem_metadata.py`, `structure_binders.py`, `raster_support.py`, `surface*.py`, `catchment_zones_field.py`). Pas de regroupement clair.
- **Package `gmsh_grid/zone_meshing/`** : 25 fichiers, 6 modules < 100 lignes, granularité excessive.
- **Package `cartesian_grid/`** : structure honnête mais préfixe `sgrid_` redondant.

### 8.3 Comparaison avec les standards

| Référence | Ce qu'ils font | HydroModPy |
|---|---|---|
| FloPy | `ModflowDis`, `ModflowDisv`, `StructuredGrid`, `VertexGrid`, `UnstructuredGrid` — noms courts, discriminants nets | Noms longs, ambigus (`sgrid_fieldparam_discretization`) |
| meshio | `Mesh(points, cells)` — pivot minimal | `HydroMesh` trop riche, sans discriminant de type |
| pysheds | `Grid.view()`, `Grid.catchment()` — API flat | Pipeline hiérarchique à 3 niveaux |
| xarray | `DataArray` avec dims/coords/attrs — métadonnées CF intégrées | Arrays numpy bruts, pas de métadonnées |

### 8.4 Verdict

**À améliorer sévèrement.** Le nommage actuel impose une courbe d'apprentissage inutile à un hydrogéologue expérimenté. Un ingénieur FloPy doit réapprendre le vocabulaire.

### 8.5 Recommandations

1. Renommer `derive_catchment_domain()` explicitement (`*_products`) ou en faire une vraie classe.
2. Fusionner les deux contextes géographiques en un seul avec deux constructeurs (`from_legacy`, `from_new`).
3. Supprimer le préfixe `sgrid_` dans `cartesian_grid/`.
4. Consolider `spatial/` en sous-packages thématiques : `spatial/raster/`, `spatial/geography/`, `spatial/mesh/`, `spatial/surface/`.
5. Faire converger le vocabulaire vers FloPy (`StructuredGrid`, `VertexGrid`) quand c'est pertinent.

---

## 9. Duplications, code mort, over-engineering

### 9.1 Duplications majeures

| Duplication | Fichier A | Fichier B | Recommandation |
|---|---|---|---|
| Orchestrateurs géographiques | `spatial/geographic/pipeline.py:385-521` | `spatial/geographic/core/domain_geographic_pipeline.py:108-288` | Fusionner, un point d'entrée unique |
| Discrétiseur fieldparam 3D | `cartesian_grid/sgrid_fieldparam_discretization.py:48-80` | `gmsh_grid/extruded_fieldparam_discretization.py:41-74` | Extraire `discretize_fieldparam_on_layered_mesh()` générique |
| Mesh structuré | `field/meshes/structured_field_mesh.py:10-89` | `field/geology/geology_mesh.py:18-151` | Fusionner en `StructuredFieldMesh` + classmethod `from_bounds()` |
| `_sample_points_in_cell` | `field/core/field_spatial.py:23-52` | `field/geology/geology_field.py:159-176`, `domain/spatial_support.py:23-52` | Extraire module `field/core/sampling.py` |
| `_optional_text()` | `mesh/runtime.py:41` | `mesh/batch.py:515` | Helper partagé |
| Contrats zone_meshing | `_geometry_contracts.py` / `_domain_contracts.py` / `_refinement_contracts.py` | — | Fusionner en `contracts.py` |

### 9.2 Code mort probable / wrappers inutiles

- `build_standard_catchment()` (`geographic/core/pipeline_steps.py:90-142`) : wrapper de 52 lignes qui dispatch deux fonctions simples par `if/elif`. Pattern factory injustifié.
- `GeographicDerivedFeatures.to_domain_geographic_context()` ↔ `from_domain_geographic_context()` (`derived_features.py:48-111`) : conversion round-trip entre deux designs concurrents. Signe d'une migration inachevée.
- `_gmsh_driver.py` (35 lignes, stub façade) : valeur ajoutée nulle.
- 9 dataclasses pures sans méthode (`CatchmentDomainProducts`, `DirectDemDomainProducts`, `FlowProducts`, `RiverNetworkProducts`, `LegacyDomainRasterProducts`, etc.) : `NamedTuple` suffirait dans la moitié des cas.
- `Geographic` (`geographic.py:83-232`) : classe-façade legacy qui appelle `build_legacy_geographic_context()` et `setattr()` dynamiquement 20+ attributs. Non typée, source d'erreurs silencieuses.

### 9.3 Over-engineering

- **zone_meshing/** : 25 fichiers. 6 < 100 lignes. Trois modules `_*_contracts.py` redondants. Fusion possible en 8-10 modules cohérents.
- **Conversion bidirectionnelle de contextes** : indique un refactor abandonné à mi-chemin.
- **Deux « Context » classes parallèles** : `LegacyGeographicContext` vs `DomainGeographicContext` avec 95% des champs identiques.

### 9.4 Performance

- `sgrid_fieldparam_discretization.py:259-279` — boucle Python sur les couches au lieu de broadcast vectorisé.
- `StructuredGridBuilder.build_from_surfaces` — déjà vectorisé ✓.
- `PreparedSurfaceSampler.sample` — déjà vectorisé ✓.

---

## 10. Tableau récapitulatif par composant

| Composant | Verdict | Sévérité | Justification principale |
|---|---|---|---|
| `spatial/geographic/core/flow_products.py` (D8) | Conforme | — | Whitebox D8 standard |
| `spatial/geographic/pipeline.py` (legacy) | Problématique | Haute | Duplication avec `domain_geographic_pipeline.py` |
| `spatial/geographic/core/domain_geographic_pipeline.py` | À améliorer | Moyenne | Nomenclature (classe vs fonction), mais contenu bon |
| `spatial/geographic/geographic.py::Geographic` | À améliorer | Moyenne | Façade legacy fat, attributs non typés |
| `spatial/geographic/domain_rasters.py` (nodata) | **Problématique** | **Haute** | Nodata hardcodé `-9999`, pas d'héritage source |
| `spatial/domain/domain.py` | Acceptable | Faible | Responsabilités nettes |
| `spatial/field/core/field_param.py` (moyenne K) | **Problématique** | **Critique** | Moyenne arithmétique pondérée, pas harmonique |
| `spatial/field/core/field_spatial_weighted_discretization.py` | Acceptable | Faible | Contenu simple, mais nom trompeur |
| `spatial/field/meshes/structured_field_mesh.py` | À améliorer | Moyenne | Duplication avec `geology_mesh.py` |
| `spatial/field/geology/geology_mesh.py` | À améliorer | Moyenne | Doublon de `StructuredFieldMesh` |
| `spatial/mesh/hydro_mesh.py::HydroMesh` | À améliorer | Haute | Pas de IDOMAIN, pas d'énum `MeshOrigin`, 2D-biaisé |
| `spatial/mesh/cell_types.py` | À améliorer | Faible | Pas de VTK type IDs, pas de tet/pyramid |
| `spatial/mesh/adapters/flopy_adapter.py` | À améliorer | Haute | 2D planar uniquement, lève ValueError pour 3D |
| `spatial/mesh/adapters/meshio_adapter.py` | Acceptable | Faible | Round-trip correct, perte métadonnées temporelles |
| `spatial/mesh/io/vtu_io.py` | À améliorer | Moyenne | Pas de PVD temporel |
| `spatial/mesh/runtime.py` / `runtime_single_run.py` | À améliorer | Faible | Séparation justifiée mais helpers dupliqués |
| `spatial/mesh/batch*.py` | Acceptable | Faible | Architecture honnête |
| `spatial/surface.py` | À améliorer | Moyenne | Pas de support pendage, pas de pinch-out |
| `spatial/surface_sampling.py` | Conforme | — | Bilinéaire vectorisé numpy, propre |
| `spatial/raster_support.py` | Acceptable | Faible | Metadata basique |
| `solver/utils/mesh/cartesian_grid/sgrid_generation.py` | Conforme | — | Broadcast vectorisé, FloPy standard |
| `solver/utils/mesh/cartesian_grid/sgrid_*_discretization.py` | **Problématique** | **Critique** | Pas de moyenne harmonique pour K |
| `solver/utils/mesh/cartesian_grid/spatial_interpolation.py` | À améliorer | Haute | Manque `harmonic`, `geometric`, `conservative` |
| `solver/utils/mesh/cartesian_grid/utils/planar_discretizer.py` | À améliorer | Moyenne | Pas conservatif pour variables extensives |
| `solver/utils/mesh/cartesian_grid/utils/raster_grid_reader.py` | À améliorer | Moyenne | Pas de validation CRS top vs bottom |
| `solver/utils/mesh/cartesian_grid/sgrid_mesh_adapter.py` | Acceptable | Faible | Conversion OK, assertions manquantes |
| `solver/utils/mesh/gmsh_grid/gmsh_planar_mesh.py` | Conforme | — | API OCC, bien fait |
| `solver/utils/mesh/gmsh_grid/zone_meshing/conformal.py` | Conforme | — | Edges enforced correctement |
| `solver/utils/mesh/gmsh_grid/zone_meshing/_gmsh_driver.py` | À améliorer | Faible | Stub 35 L sans valeur |
| `solver/utils/mesh/gmsh_grid/zone_meshing/_*_contracts.py` (×3) | À améliorer | Moyenne | Fusion possible en un seul |
| `solver/utils/mesh/gmsh_grid/extruded_prism_mesh.py` | À améliorer | Haute | Pas de pinch-out, prismes dégénérés possibles |
| `solver/utils/mesh/gmsh_grid/extruded_fieldparam_discretization.py` | **Problématique** | **Critique** | Pas de moyenne harmonique, duplication sgrid |
| `solver/utils/mesh/gmsh_grid/exchange_api.py` | À améliorer | Haute | Conversion DISV/DISU finale peu claire |
| `solver/utils/mesh/gmsh_grid/_deps.py` | Conforme | — | Import optionnel propre |
| **Qualité maillage (post-generate)** | **Problématique** | **Haute** | Aucune vérification aspect/skewness/angle |

---

## 11. Priorisation des actions

### P0 — Critique hydrogéologique (à corriger avant toute mise en production)

1. **Moyenne harmonique pour K** : implémenter dans `spatial_interpolation.py`, router selon `param_name in {"k", "K", "conductivity"}`, faire de `harmonic` le défaut pour K.
2. **Bug nodata** : propager `src.nodata` source dans les exports au lieu de `-9999` hardcodé.
3. **IDOMAIN dans HydroMesh** : ajouter le champ et l'exposer dans les adapters.
4. **Pinch-out detection** dans l'extrusion 3D (cartesian + gmsh).

### P1 — Qualité et robustesse

5. **Post-validation qualité Gmsh** : aspect ratio, angle min.
6. **Extension DISV 3D** dans `flopy_adapter.to_flopy_disv_args`.
7. **Validation CRS** top vs bottom dans `raster_grid_reader.py`.
8. **Post-validation délinéation** : aire > seuil, polygone valide, outlet dans bassin.

### P2 — Dette technique

9. Fusionner `pipeline.py` + `domain_geographic_pipeline.py`.
10. Fusionner `StructuredFieldMesh` + `GeologyStructuredMesh`.
11. Extraire `discretize_fieldparam_on_layered_mesh()` générique (gmsh + sgrid).
12. Fusionner les 3 `_*_contracts.py` de `zone_meshing/`.
13. Renommer le préfixe `sgrid_` en `cartesian_grid/`.

### P3 — Interopérabilité

14. Export UGRID-NetCDF (CF-conventions).
15. Export PVD temporel.
16. Export shapefile 2D.

---

## 12. Conclusion

Le périmètre spatial de HydroModPy offre une stack **fonctionnelle** et **ambitieuse** (SGrid + Gmsh OCC + conformal meshing + extrusion 3D + batch multi-exutoires). L'architecture de pivot (`HydroMesh` + adapters) est saine, les choix Gmsh (API Python, kernel OCC, `embed()` pour les contraintes) sont **conformes aux meilleures pratiques**.

Mais trois dettes pèsent lourd :

1. **Une dette hydrogéologique critique** : l'upscaling K par nearest/arithmétique invalide la physique dès qu'on quitte l'homogène.
2. **Une dette de refactorisation** : deux pipelines géographiques concurrents, deux discrétiseurs `fieldparam` jumeaux, deux meshs structurés jumeaux, contextes bidirectionnels, préfixes redondants.
3. **Une dette de rigueur MODFLOW** : pas de IDOMAIN, pas de pinch-out, pas de qualité maillage, pas de traçabilité DIS→DISV.

Un sprint ciblé (~2 semaines) sur les items P0 et P1 élèverait drastiquement la qualité scientifique et la robustesse de production du package. Le reste (P2, P3) relève d'une hygiène continue.
