# Audit critique — Packages `spatial/` et `solver/utils/mesh/`

**Date :** 2026-04-17
**Périmètre :** `hydromodpy/spatial/` (geographic, domain, field, mesh, surface) + `hydromodpy/solver/utils/mesh/` (cartesian_grid, gmsh_grid, zone_meshing)
**Posture :** Audit d'expert senior (maillage numérique, hydrogéologie, géomatique). Aucune modification du code, rapport critique uniquement.

---

## 0. Synthèse exécutive

Le socle géométrique de HydroModPy est **fonctionnellement solide** (conformité MODFLOW DIS irréprochable, abstraction `HydroMesh` pivot correcte, extrusion prismatique propre, usage intelligent de Whitebox/Gmsh/meshio), mais il souffre de **trois pathologies structurelles** :

1. **Sur-fragmentation logicielle** (notamment `zone_meshing/` : 27 fichiers, ~6 000 lignes, dont ~7 façades stériles) → 2×-3× le code nécessaire.
2. **Duplications massives** de helpers (clipping raster ×8, `_get_nested_section` ×3, `make_valid_geometry` ×2, `_optional_text` ×3, interpolation cell-centers ×2).
3. **Lacunes physiques** : la discrétisation des propriétés hydrodynamiques (conductivité hydraulique K) utilise **systématiquement une moyenne arithmétique pondérée par fractions zonales**, alors que la théorie exige une moyenne **harmonique** pour les flux horizontaux dans des milieux stratifiés. Erreur silencieuse potentiellement sévère (facteur ≥ 10 pour K₁/K₂ ≥ 100).

S'ajoutent des **validations manquantes** (ordre CCW des cellules DISV, convexité, pinch-outs non supportés) et une **API publique / privée déséquilibrée** (ratio ~3:1 de fichiers privés dans `gmsh_grid/` et `zone_meshing/`).

**Verdict global : ACCEPTABLE mais À CONSOLIDER**. Le module est production-ready pour le cas d'usage Brittany/catchment typique (DEM 25-30 m, K homogènes ou peu contrastés) mais fragile sur les cas limites (K contrastés, pinch-outs géologiques, DEM très basse résolution, maillages non-standards).

---

## 1. Grilles régulières vs irrégulières — DIS / DISV / DISU

### 1.1 Abstraction `HydroMesh` (hydromodpy/spatial/mesh/hydro_mesh.py)

| Composant | Verdict | Justification | Recommandation |
|---|---|---|---|
| `HydroMesh` pivot | **Conforme** | `@dataclass(frozen=True)`, validation `__post_init__`, property `.is_structured`, `cell_blocks` polymorphes (hydro_mesh.py:55-216). La structure capture proprement DIS (structured_shape), DISV (cell_blocks), DISU (cells hétérogènes). | Documenter explicitement la couverture DIS/DISV/DISU dans la docstring. |
| `CellType` enum | **Conforme** | `cell_types.py` (79 lignes) : enum complet (TRIANGLE, QUADRILATERAL, WEDGE, HEXAHEDRON), aliases robustes, utilisé dans 5 modules réels. Pas de dead code. | Maintenir tel quel. |
| Dispatch plotting | **Conforme** | `plotting.py:54-62` choisit pcolormesh (DIS) / tripcolor (triangles) / PolyCollection (polygons) selon `is_structured` + `single_cell_type`. Aucun code ne présuppose implicitement une grille régulière. | Paralléliser sur gros maillages batch (optimisation mineure). |
| Indexing MODFLOW | **Acceptable mais non documenté** | Code 0-based uniformément (convention NumPy). Adapter FloPy gère conversion `cell2d` (MF6 est aussi 0-based depuis flopy ≥3.3). Pas d'ambiguïté décelée, mais **aucune docstring n'énonce cette convention explicitement**. | Ajouter bloc docstring « HydroMesh uses 0-based indexing. Converted by FloPy adapter to MF6 DISV format. ». |
| IDOMAIN / IBOUND | **À améliorer** | Le mapping des cellules inactives n'est pas uniforme. `idomain` apparaît dans `sgrid_generation.py` mais le traitement des `nodata` du DEM → IDOMAIN=0 n'est pas centralisé. Chaque adapter refait le mapping. | Extraire `build_idomain_from_dem(surface, nodata)` dans `hydromodpy/spatial/mesh/`. Imposer une convention unique (IDOMAIN=0 inactive, 1 active, -1 passthrough MF6). |

### 1.2 Transition DIS → DISV → DISU

**Vérification** : aucun code audité n'assume implicitement un stride `(nrow, ncol)` alors que l'entrée est DISV. Les helpers `hydro_mesh.is_structured`, `adapters/flopy_adapter.to_flopy_disv_args()` (flopy_adapter.py:118-126) basculent proprement selon la structure.

**Point faible** : la **validation CCW** des cellules DISV n'est **pas effectuée**. Un maillage Gmsh inversé passerait silencieusement jusqu'au solveur, qui pourrait produire des résidus divergents sans message clair.

→ **Recommandation P0** : ajouter à `GmshPlanarMesh2D.__post_init__` un contrôle `_check_ccw_orientation()` (signe de l'aire via la formule du lacet). Quelques lignes de code, impact critique.

### 1.3 Adapters FloPy / meshio / field

| Adapter | Verdict | Justification |
|---|---|---|
| `flopy_adapter.py` | **Conforme** | `to_flopy_disv_args()` respecte le contrat FloPy MF6 (vertices, cell2d avec `[icell2d, xc, yc, ncvert, *icvert]`). Orientation CW appliquée en sortie (29-36) — conforme au format MF6. |
| `meshio_adapter.py` | **Conforme** | Conversion bidirectionnelle ; duck-typing sur `cells_dict`. |
| `field_mesh_adapter.py` | **Conforme** | Pont `FieldMesh` ↔ `HydroMesh` propre. |
| `vtu_io.py` | **Conforme, minimaliste** | 50 lignes, wrapper sur meshio. |

---

## 2. Délinéation de bassin — DEM → Catchment

### 2.1 Pipeline `spatial/geographic/`

| Composant | Verdict | Justification | Recommandation |
|---|---|---|---|
| Pipeline D8 (fill/breach) | **Acceptable** | `flow_products.py:109-116` utilise whitebox-workflows (fill puis D8 pointer puis D8 flow accumulation, `log=True`, `esri_pntr=False`). Conforme à la pratique standard. Gestion des flats déléguée à Whitebox (robuste). | Documenter le fait que fill+breach précèdent systématiquement l'accumulation. |
| Absence D-infinity | **À améliorer** | Pysheds et whitebox exposent aussi D-inf (Tarboton 1997), plus précis sur pentes fortes et hétérogènes. HydroModPy ne l'expose pas. | Ajouter option `flow_algorithm: Literal["d8", "dinf"]` dans `GeographicConfig`, dispatch via `whitebox.d_inf_flow_accumulation()`. |
| Seuil d'extraction rivière | **Non documenté** | `geographic_config.py:25-53` expose `threshold_area_km2` / `threshold_cells` mais **sans tableau de référence ni guide empirique** (à 30 m, 1 km² = 1 111 cellules ; à 10 m, = 10 000). | Ajouter un tableau de recommandations dans la docstring ou un module `stream_threshold_recommendations.py`. |
| Strahler / Shreve | **Acceptable** | Codes via Whitebox (`compute_strahler_order`, `compute_stream_links`). Pas activés par défaut (probable raison coût). | Exposer flags au niveau TOML avec défaut documenté. |
| Synthétique (`spatial/geographic/synthetic/`) | **Problématique** | Module `synthetic_geographic.py` + `topography.py` (200+ lignes) crée un DEM analytique mais **n'est référencé dans aucun cas de régression** (`cases/reference_*` = DEMs réels). Fonctionnalité non testée en prod. | **Supprimer** OU publier un cas `reference_synthetic_flat_case.py` sous `tests/regression/`. En l'état, c'est du code mort entretenu. |
| Trois pipelines en parallèle | **Problématique** | `pipeline.py` (521 L, wrapper legacy), `geographic.py` (232 L, façade compat), `core/domain_geographic_pipeline.py` (288 L, pipeline « moderne »). Deux chemins d'accès au même résultat. | Fusionner `pipeline.py` + `geographic.py` en **une seule** façade compat, ou supprimer `pipeline.py` s'il est intégralement redondant avec `domain_geographic_pipeline`. |
| Nommage `Geographic` | **Non-standard** | Très vague. Pysheds utilise `Grid`, `FlowAccumulation` ; whitebox-tools `WatershedDelineation`. `Geographic` ne décrit pas ce qu'il fait. | Renommer `CatchmentDelineation` (ou `CatchmentGeometry`) pour la classe principale. `Geographic` = faux ami avec geopandas. |
| Gestion CRS / NoData | **Conforme** | `ensure_crs()` systématique, NoData uniforme (-9999 DEM, -32768 direction). `GeographicPaths` centralise les noms de fichiers. | Robuste, rien à changer. |

### 2.2 Duplications critiques de clipping raster

**Code identique répété 8 fois** :

- `domain_rasters.py:45-47` (boucle)
- `domain_dem.py:69-75`
- `river_network.py:343-346, 360-362, 378-380, 394-396` (4 occurrences)

```python
backend.clip_raster_to_polygon(str(src), str(polygon), str(dst), maintain_dimensions=maintain_dimensions)
ensure_crs(dst, crs_project)
if nodata is not None:
    backend.modify_no_data_value(dst_path, new_value=float(nodata))
```

→ **Recommandation P0** : extraire `clip_raster_to_polygon_normalized(src, polygon, dst, *, crs_project=None, nodata=None, maintain_dimensions=False, backend=None)` dans `geographic_io.py`. Gain : ~40 lignes, cohérence garantie.

### 2.3 Comparaison aux standards du domaine

| Standard | Conformité | Détail |
|---|---|---|
| GRASS `r.watershed` | Partielle | D8 OK ; pas de MFD (multi-flow direction). |
| PySheds | Basique | D8 seulement, pas D-inf ni multi-algo. |
| whitebox-tools | **Conforme** | Utilisation cohérente et idiomatique. |
| QGIS processing / TauDEM | Compatible | Shapefiles et GeoTIFF standards en sortie. |

---

## 3. Conventions MODFLOW — Indexation et IDOMAIN

### 3.1 Indexation 0-based

**Vérifié partout** : `range(nlay)`, `range(nrow)`, `range(ncol)`, `cell2d` indexes 0-based. Aucun « +1 » ou « -1 » suspect dans les adapters. Conforme PyFloPy ≥ 3.3.

### 3.2 Mapping `(layer, row, col)` vs `(layer, cell2d)`

| Adapter | Mapping | Conforme ? |
|---|---|---|
| `flopy_adapter.to_flopy_disv_args()` | `(layer, cell2d)` pour MF6 DISV | ✓ |
| `sgrid_mesh_adapter` (cartesian) | `(layer, row, col)` pour DIS | ✓ |
| `extruded_prism_mesh` | Stocke `layer_index`, `source_cell_index_2d` | ✓ (DISV 3D cohérent) |

**Observation** : la convention est correcte partout, **mais il manque une assertion explicite** que `cell2d_id ∈ [0, ncpl)` avant l'appel FloPy. Un bug de construction pourrait produire un crash obscur côté solveur.

### 3.3 Cellules inactives

| Convention | Dans le code | Verdict |
|---|---|---|
| MODFLOW-NWT (IBOUND) | Géré dans `modflow_nwt/` | Hors périmètre |
| MODFLOW-6 (IDOMAIN) | Transmis via `idomain` dans DIS/DISV payload | **Correct** |
| Dans `HydroMesh` | Absent | **Limite** : la mesh pivot ne porte pas de notion d'« actif ». Chaque adapter reconstruit IDOMAIN depuis le domaine. | À améliorer : champ `active: np.ndarray[bool]` sur `HydroMesh`. |

---

## 4. Intégration Gmsh

### 4.1 API Gmsh (hydromodpy/solver/utils/mesh/gmsh_grid/zone_meshing/)

| Aspect | Verdict | Détail |
|---|---|---|
| API Python native | **Conforme** | `gmsh.model.occ.*` + `gmsh.model.mesh.*` partout ; **aucun fichier .geo intermédiaire**. C'est la bonne pratique (versioning, debugging). |
| `synchronize()` | **Conforme** | Appelé systématiquement après création OCC, avant meshing. |
| Physical groups | **Conforme** | `conformal.py:374-388` : une zone géologique → un `physicalGroup` distinct, nommé `zone::<key>`. |
| `BooleanFragments` | **Acceptable** | Stratégie alternative : Shapely → `occ.addPlaneSurface()` par zone. Évite les fragilités de `occ.fragment()` mais **risque de slivers** si `heal_tolerance` mal réglé. | Documenter le choix et imposer `heal_tolerance ≥ 1e-6`. |
| Refinement adaptatif | **Conforme, complexe** | 5 fichiers `_refinement_*` + 1 façade `_refinement_policy.py`. Algorithme sophistiqué (grille, hotspots, policy, resolution, candidates). |

### 4.2 Qualité de maillage (aspect ratio, skewness, angle minimum)

**CRITIQUE** : **aucune métrique de qualité n'est calculée** sur les maillages produits.

| Métrique | Implémentée ? |
|---|---|
| Angle minimum | ❌ |
| Aspect ratio | ❌ |
| Skewness | ❌ |
| Convexité des cellules | ❌ |
| CCW check | ❌ |
| Monotonie z_interfaces | ✓ (extruded_prism_mesh.py:74-82) |

→ **Recommandation P0** : ajouter `mesh_quality.py` avec fonctions (vectorisées numpy, < 100 lignes) :

```python
def min_interior_angle(points_xy, connectivity): ...
def max_aspect_ratio(points_xy, connectivity): ...
def is_ccw(points_xy, connectivity): ...
```

Appel optionnel via `hydro_mesh.quality_report()` avec logging des cellules suspectes (angle < 15°, aspect_ratio > 20).

### 4.3 Conformal meshing — Préservation des frontières

**Correct** : `_partition_builder.py:161-238` polygonise puis assigne un propriétaire unique par face (via `geometry.covers(point)`). Chaque arête de contour géologique est préservée (pas d'arête coupée arbitrairement).

→ **Point fort du module**.

### 4.4 Sur-fragmentation `zone_meshing/` — OVER-ENGINEERING SÉVÈRE

**27 fichiers, 5 951 lignes pour ~2 500 lignes de logique réelle** (ratio 2.4×).

| Fichier | Lignes | Verdict |
|---|---|---|
| `_gmsh_driver.py` | 35 | **Façade stérile** : 8 imports + ré-export, 0 logique. |
| `_geometry_cleaning.py` | 68 | **Façade stérile** : ré-export de 17 symboles depuis 5 modules. |
| `_refinement_policy.py` | 40 | **Façade stérile** : pur wrapper d'orchestration. |
| `_domain_contracts.py` (108) + `_domain_schema.py` (198) + `domain.py` | — | Fragmentation à fusionner (contrats + schemas + logique domaine). |
| `_geometry_contracts.py` + `_polygon_cleaning.py` + `_geometry_utils.py` | — | Trois modules pour un nettoyage polygonal. |
| 5 modules `_refinement_*` | — | Fragmentation excessive ; `_refinement_resolution.py` compte 10 helpers privés de < 30 lignes chacun. |

**Duplication Shapely confirmée** :
- `_geometry_utils.py:39-52` (`make_valid_geometry`) = **copier-collé** de `_domain_geometry.py:16-29`.
- Idem pour `iter_polygon_parts()`.

**Recommandation P0** :
1. Supprimer `_gmsh_driver.py`, `_geometry_cleaning.py`, `_refinement_policy.py` (façades pures).
2. Fusionner `_domain_geometry.py` → `_geometry_utils.py` (déduplication).
3. Fusionner `_refinement_policy.py` dans `_refinement_resolution.py`.
4. Objectif : 27 → 20 fichiers, 5 951 → ~4 500 lignes (−25 %) **sans perte fonctionnelle**.

---

## 5. Discrétisation des champs (K, Sy, Ss)

### 5.1 Pathologie centrale — Moyenne arithmétique systématique

**Code incriminé** (`hydromodpy/spatial/field/core/field_param.py:745-749`) :

```python
contribution = frac * value
weighted = weighted + contribution
```

**Problème physique** : pour un aquifère stratifié avec deux zones (f₁, K₁) et (f₂, K₂) :
- **Flux parallèle à la stratification** : K_eff = f₁·K₁ + f₂·K₂ (arithmétique) ✓
- **Flux perpendiculaire** : 1/K_eff = f₁/K₁ + f₂/K₂ (**harmonique**)

Dans un aquifère hydrogéologique réel, K = conductivité équivalente ≠ concentration chimique moyenne. Pour des contrastes K₁/K₂ > 100 (granite vs alluvium), l'erreur de moyenne arithmétique peut dépasser **un ordre de grandeur**.

→ **Recommandation P0** : ajouter paramètre `aggregation: Literal["arithmetic", "harmonic", "geometric"]` dans `WeightedAverageFieldDiscretization`. Documenter conventions par propriété :

| Propriété | Agrégation recommandée |
|---|---|
| K horizontal (flux horizontal, strates //) | arithmétique pondérée volume |
| K vertical (flux vertical, strates //) | harmonique |
| Sy (porosité utile) | arithmétique |
| Ss (emmagasinement spécifique) | arithmétique |
| Transmissivité T | arithmétique |
| Résistance 1/K | arithmétique |

### 5.2 Interpolation spatiale

| Aspect | Verdict |
|---|---|
| Nearest-neighbor géologique | **Conforme** (cellules qualitatives) |
| Bilinéaire sur raster continu | **Conforme** (via rasterio.warp.reproject) |
| Conservatif (volume-preserving) | **Absent** — pertinent pour recharge/ETP grossier → fine | À ajouter : option `Resampling.average` en down-sampling, `Resampling.cubic` en up-sampling, déjà partiellement fait dans `planar_discretizer.py`. |

### 5.3 Validation des fractions par cellule

**Risque** : `GeologyField.on_mesh()` (`geology_field.py:339-340, 372-374`) accumule fractions par comptage `zone_counts / valid_codes.size`. Si une cellule est partiellement hors couverture géologique, la somme des fractions < 1.0 silencieusement.

→ **Recommandation** : ajouter dans `__post_init__` de `WeightedAverageFieldDiscretization` :

```python
assert np.allclose(np.sum(list(self.fractions_by_zone.values()), axis=0), 1.0, atol=1e-3), \
    "Cell fractions must sum to 1.0 (found {min} / {max})"
```

### 5.4 Duplication `StructuredFieldMesh` vs `GeologyStructuredMesh`

**80 % du code en commun** :
- `structured_field_mesh.py:10-89`
- `geology/geometry_mesh.py` (structures quasi identiques)

Même `iter_cells()`, même `to_cell_values()`, même `plot_cell_values()`. Seule différence : constructeur alternatif (`from_bounds()`).

→ **Recommandation** : classe unique `StructuredFieldMesh` avec deux constructeurs alternatifs (`from_edges`, `from_bounds`). Gain : ~150 lignes.

---

## 6. Formats d'export

| Format | Supporté | Conformité | Notes |
|---|---|---|---|
| VTU (VTK XML) | ✓ (`mesh/io/vtu_io.py` via meshio) | **Conforme** | 50 lignes, délégation propre. |
| Gmsh `.msh` v2/v4 | ✓ (gmsh_reader.py + meshio) | **Conforme** | Fallback ASCII custom + meshio. |
| Shapefile (rivers, catchments) | ✓ (via geopandas) | **Conforme** | Standard OGC Simple Features. |
| GeoTIFF (rasters) | ✓ (via rasterio) | **Conforme** | CRS + nodata + transform respectés. |
| UGRID (CF-conventions) | ❌ | **Non-standard** | Le `catchment_mesh_bundle` (CSV + JSON + .msh) est un **format maison**. |
| NetCDF CF-Conventions | ❌ (pour les maillages) | — | Les sorties spatiales multi-layer ne respectent pas les CF pour `mesh_topology` / `ugrid`. |

**Critique** : le `catchment_mesh_bundle` (`gmsh_grid/catchment_mesh_bundle.py`) est un format **propriétaire** (nodes.csv + cells.csv + edges.csv + metadata.json + mesh_2d.msh). Il est **inspectable** (bon point) mais **non interopérable** avec les outils standards (Ferret, Panoply, Paraview pour UGRID, QGIS Mesh Layer).

→ **Recommandation** : fournir un export UGRID (CF 1.8) via `xarray.Dataset` → `to_netcdf()` en option. L'implémentation est légère (< 100 lignes) avec les attributs `mesh_topology`, `face_node_connectivity`, `node_coordinates`.

---

## 7. Surface / Topographie

### 7.1 DEM → z_interfaces

| Aspect | Verdict | Détail |
|---|---|---|
| Extraction surface_topo | **Conforme** | `Surface` (`spatial/surface.py`) stocke valeurs + `RasterSupport`. `Domain.surface_topo` clairement défini. |
| Construction substratum | **Conforme** | `Domain` utilise `depth_model` (ConstantThickness, FlatSubstratum) pour dériver le toit du bedrock. |
| z_interfaces monotonie | **Conforme** | `extruded_prism_mesh.py:74-82` valide `np.all(deltas > 0)` ou `< 0`. |
| Couches inclinées | **Acceptable** | `ConstantThickness` + `FlatSubstratum` couvrent les cas usuels. Pas de support de couches inclinées arbitraires (dip, strike). |
| **Pinch-outs** | **Non supporté** | `z_interfaces` constant par couche (dim : `(n_layers+1, n_cells_2d)`). Si une couche géologique s'amincit et disparaît, il faudrait `z_interfaces(cell, layer)` variable. **Workaround actuel : dédoubler les couches** (coûteux). |

→ **Recommandation P1** : documenter explicitement la limitation dans la docstring de `ExtrudedPrismMesh3D`, et proposer un issue GitHub pour le support natif des pinch-outs (via IDOMAIN=-1 en MF6 ou couches d'épaisseur quasi-nulle).

### 7.2 Nommage / Sémantique

| Classe | Rôle | Conflit ? |
|---|---|---|
| `Surface` | Valeurs (DEM) + RasterSupport | ✓ |
| `RasterSupport` | Métadonnées géospatiales | ✓ |
| `SpatialSupport` | Raster fields sur mesh | ⚠ **Confusion** avec RasterSupport |
| `Domain` | Aggregator (surface + substratum + zones) | ✓ |

→ **Recommandation** : renommer `SpatialSupport` → `GriddedFieldSupport` ou `MeshFieldRaster` pour lever l'ambiguïté avec `RasterSupport`.

---

## 8. Nommage et organisation

### 8.1 Comparaison aux standards

| HydroModPy | FloPy équivalent | meshio équivalent | Verdict |
|---|---|---|---|
| `HydroMesh` | `flopy.discretization.Grid` (`StructuredGrid`, `VertexGrid`, `UnstructuredGrid`) | `meshio.Mesh` | **Acceptable** (différent mais cohérent). Nom plus parlant que `Grid`. |
| `SGrid` (`sgrid_*.py`) | `flopy.discretization.StructuredGrid` | — | **Acceptable** — préfixe cohérent, mais 9 modules `sgrid_*.py` = verbeux. |
| `GmshPlanarMesh2D` / `ExtrudedPrismMesh3D` | — | `meshio.Mesh` | **Conforme** — noms descriptifs. |
| `Geographic` | — | — | **Non-standard** — trop vague. Pysheds : `Grid`, `FlowAccumulation`. whitebox : `WatershedDelineation`. → Renommer `CatchmentDelineation` ou `CatchmentGeographicPipeline`. |
| `CatchmentDomain` / `CatchmentFromPoint` / `CatchmentFromPolygon` | — | — | **Acceptable** — descriptifs. |
| `FieldParam` vs `FieldSpatial` | — | — | **Acceptable** — distinction sémantique claire (paramètres vs support spatial). |
| `HydroMesh` vs `SpatialSupport` vs `Mesh` | — | — | **Ambigu** — 3 abstractions pour le même espace conceptuel. |

### 8.2 API publique / privée

| Package | Fichiers publics | Fichiers privés `_*` | Ratio |
|---|---|---|---|
| `spatial/mesh/` | 8 | 0 | 0.0 |
| `spatial/geographic/` | 22 | 0 | 0.0 |
| `spatial/field/` | 12 | 0 | 0.0 |
| `cartesian_grid/` | 8 + utils | 0 | 0.0 |
| `gmsh_grid/` (racine) | 12 | 7 | **0.58** |
| `zone_meshing/` | 4 | 24 | **6.0** |

→ **Ratio `zone_meshing` 6:1 = excessif**. Normal en Python ≈ 0.3-1.0.

---

## 9. Tableau récapitulatif par composant

| Composant | Verdict | Points critiques |
|---|---|---|
| `spatial/mesh/hydro_mesh.py` | **Conforme** | Abstraction pivot DIS/DISV/DISU solide. |
| `spatial/mesh/cell_types.py` | **Conforme** | Enum propre, pas de dead code. |
| `spatial/mesh/adapters/*` | **Conforme** | FloPy MF6 DISV correct, meshio bidirectionnel. |
| `spatial/mesh/io/vtu_io.py` | **Conforme** | Thin wrapper meshio. |
| `spatial/mesh/batch*.py` | **Acceptable** | `_optional_text` / `_require_text` dupliqués ×3. |
| `spatial/mesh/runtime*.py` | **Conforme** | Séparation API publique / impl interne intentionnelle. |
| `spatial/mesh/config.py` | **Acceptable** | 893 L verbeux mais cohérent Pydantic ; schemas twin `MeshCatchmentBatchOutputsSchema` à consolider. |
| `spatial/domain/*` | **Conforme** | `Domain`, `SpatialSupport` séparation nette. |
| `spatial/surface.py` / `surface_sampling.py` | **Conforme** | Séparation valeurs / métadonnées propre. |
| `spatial/raster_support.py` | **Conforme** | Wrapper rasterio bien isolé. |
| `spatial/geographic/geographic.py` | **Legacy** | Façade compat ; fusionner avec `pipeline.py`. |
| `spatial/geographic/pipeline.py` | **Dead/Legacy** | 521 L, wrapper legacy redondant avec `core/domain_geographic_pipeline.py`. |
| `spatial/geographic/core/*` | **Conforme** | Pipeline moderne, mais clipping raster dupliqué ×8. |
| `spatial/geographic/synthetic/*` | **Dead code potentiel** | Non référencé dans tests de régression. |
| `spatial/field/core/field_param.py` | **Problématique** | Moyenne arithmétique systématique pour K (voir §5.1). |
| `spatial/field/core/field_spatial*.py` | **Conforme** | Duck typing propre. |
| `spatial/field/core/field_mesh.py` | **Conforme** | Abstraction BaseFieldMesh correcte. |
| `spatial/field/core/field_spatial_weighted_discretization.py` | **À améliorer** | Pas de validation `sum(fractions) ≈ 1` ; pas de `aggregation` paramétrable. |
| `spatial/field/meshes/structured_field_mesh.py` | **Duplication** | 80 % de code commun avec `geology/geometry_mesh.py`. |
| `spatial/field/meshes/triangular_field_mesh.py` | **Conforme** | Support triangles + quadrilatères. |
| `spatial/field/geology/geology_field.py` | **Acceptable** | `_sample_points_in_cell` dupliqué avec `field_spatial_square.py`. |
| `spatial/field/geology/geology_mesh.py` | **Duplication** | Voir ci-dessus. |
| `solver/utils/mesh/cartesian_grid/sgrid_generation.py` | **Conforme** | Conforme FloPy DIS ; formules verticales (decay/constant/list) correctes. |
| `solver/utils/mesh/cartesian_grid/sgrid_config.py` | **Acceptable** | 417 L ; validators `lay_proportions` dupliqués (SGridConfig + VerticalGridConfig). |
| `solver/utils/mesh/cartesian_grid/sgrid_field_discretization.py` vs `sgrid_fieldparam_discretization.py` | **Duplication** | 676 L + 286 L ; `_cell_centers_from_sgrid`, `_interp_2d` dupliqués. |
| `solver/utils/mesh/cartesian_grid/sgrid_mesh_adapter.py` | **Conforme** | 81 L, propre. |
| `solver/utils/mesh/cartesian_grid/spatial_interpolation.py` | **Conforme** | Vectorisé scipy ; fallback brute-force explicite. |
| `solver/utils/mesh/cartesian_grid/examples/*` | **Dead code** | ~2 700 L, aucun import production. Déplacer vers `docs/` ou supprimer. |
| `solver/utils/mesh/gmsh_grid/gmsh_reader.py` | **Acceptable** | Pas de validation CCW. |
| `solver/utils/mesh/gmsh_grid/gmsh_planar_mesh.py` | **À améliorer** | Pas de diagnostic qualité maillage. |
| `solver/utils/mesh/gmsh_grid/extruded_prism_mesh.py` | **Conforme (avec limites)** | Pinch-outs non supportés. |
| `solver/utils/mesh/gmsh_grid/extruded_fieldparam_discretization.py` | **À améliorer** | K anisotrope horizontal ignoré. |
| `solver/utils/mesh/gmsh_grid/catchment_mesh_bundle*.py` | **Non-standard** | Format maison ; manque export UGRID. |
| `solver/utils/mesh/gmsh_grid/exchange_api.py` | **Conforme** | Façade I/O propre. |
| `solver/utils/mesh/gmsh_grid/_bundle_export_contracts.py` | **Verbeux** | 200 L de dataclasses imbriquées. |
| `solver/utils/mesh/gmsh_grid/_constants.py` | **Acceptable** | À exporter en public. |
| `solver/utils/mesh/gmsh_grid/runtime_support.py` | **Dead code partiel** | `_infer_boundary_labels_by_edge_id` (L 88-130) semble non appelée. |
| `solver/utils/mesh/gmsh_grid/zone_meshing/conformal.py` | **Conforme, dense** | 683 L, orchestration centrale propre. |
| `solver/utils/mesh/gmsh_grid/zone_meshing/_gmsh_driver.py` | **Dead (façade)** | 35 L de ré-export. **À supprimer**. |
| `solver/utils/mesh/gmsh_grid/zone_meshing/_geometry_cleaning.py` | **Dead (façade)** | 68 L de ré-export. **À supprimer**. |
| `solver/utils/mesh/gmsh_grid/zone_meshing/_refinement_policy.py` | **Dead (façade)** | 40 L de ré-export. **À fusionner dans `_refinement_resolution.py`**. |
| `solver/utils/mesh/gmsh_grid/zone_meshing/_domain_geometry.py` | **Duplication** | `make_valid_geometry` identique à `_geometry_utils.py:39-52`. |
| `solver/utils/mesh/gmsh_grid/zone_meshing/_refinement_*.py` | **Over-engineered** | 5 modules pour le raffinement, `_refinement_resolution.py` a 10 helpers privés. |

---

## 10. Duplications — Inventaire exhaustif

| # | Fonction / Logique | Emplacements | Ligne(s) | Action |
|---|---|---|---|---|
| 1 | `clip_raster_to_polygon` normalisé | `domain_rasters.py:45-47`, `domain_dem.py:69-75`, `river_network.py:343-346, 360-362, 378-380, 394-396` | 8 occurrences | Factoriser dans `geographic_io.py`. |
| 2 | `_optional_text` / `_require_text` | `batch_io.py:243-254`, `batch.py:515-528`, `runtime.py:41-46` | ~30 L | Extraire dans `core/utils/text_helpers.py`. |
| 3 | `_get_nested_section` | `field_mesh.py:59-70`, `field_param.py:94-112`, `field_spatial.py:29-40` | ~35 L | Extraire dans `core/utils/toml_helpers.py`. |
| 4 | `make_valid_geometry` | `_geometry_utils.py:39-52` ≡ `_domain_geometry.py:16-29` | Copié-collé | Supprimer `_domain_geometry.py`, importer. |
| 5 | `iter_polygon_parts` | Idem ↑ | — | Idem. |
| 6 | `_cell_centers_from_sgrid` / `_interp_2d` | `sgrid_field_discretization.py:230-264, 363-390`, `sgrid_fieldparam_discretization.py` | ~150 L | Extraire dans `spatial_interpolation.py`. |
| 7 | `_sample_points_in_cell` | `field_spatial_square.py:127-166`, `geology_field.py:160-223` | ~100 L | Factoriser dans `field/core/sampling.py`. |
| 8 | `StructuredFieldMesh` ≡ `GeologyStructuredMesh` | `structured_field_mesh.py:10-89`, `geology/geometry_mesh.py:18-151` | ~150 L | Fusionner en 1 classe, 2 constructeurs. |
| 9 | `validator lay_proportions` | `sgrid_config.py:302-314` ≡ `VerticalGridConfig:83-95` | ~25 L | Unifier. |
| 10 | `_normalize_optional_float` | `catchment_mesh_bundle.py:84`, `catchment_mesh_bundle_reader.py:17` | 2 occurrences | Centraliser. |
| 11 | Bundle contracts | `_bundle_export_contracts.py` ↔ `catchment_mesh_bundle_reader.py` | Doublons structurels | Source unique. |

**Total : ~500 lignes dupliquées éliminables** sans perte fonctionnelle.

---

## 11. Dead code — Inventaire

| Fichier / Fonction | Lignes | Statut | Action |
|---|---|---|---|
| `spatial/geographic/pipeline.py` | 521 | Wrapper legacy non appelé via la nouvelle API | Archiver ou fusionner. |
| `spatial/geographic/synthetic/*` | ~300 | Aucun test ne l'utilise | Publier un cas régression ou supprimer. |
| `cartesian_grid/examples/*` | ~2 700 | Aucun import production (6 fichiers) | Déplacer vers `docs/examples/`. |
| `gmsh_grid/zone_meshing/_gmsh_driver.py` | 35 | Façade pure | Supprimer. |
| `gmsh_grid/zone_meshing/_geometry_cleaning.py` | 68 | Façade pure | Supprimer. |
| `gmsh_grid/zone_meshing/_refinement_policy.py` | 40 | Façade pure | Fusionner. |
| `gmsh_grid/runtime_support.py:88-130` | ~40 | `_infer_boundary_labels_by_edge_id` suspicieusement non appelée | Vérifier puis supprimer. |

**Total dead code : ~3 700 lignes** (dont 2 700 dans `examples/`).

---

## 12. Optimisations manquantes

| Item | Bénéfice | Effort | Priorité |
|---|---|---|---|
| IDW paramétrable (k voisins, cache cKDTree) | Perf + flexibilité | Bas | P2 |
| Numba JIT sur `_point_in_polygon` | ~50× speedup grands maillages | Bas | P3 |
| Cache centroïdes `extruded_prism_mesh` | 5-10 % perf replot | Très bas | P3 |
| Vectorisation D8 (optionnel, petits bassins) | 10-100× speedup | Moyen | P2 |
| Export UGRID CF 1.8 | Interopérabilité | Moyen | P2 |
| `mesh_quality.py` (angles, aspect, CCW) | Diagnostic critique | Bas | P0 |

---

## 13. Recommandations prioritaires

### P0 — Bloquant ou correctif critique

1. **Ajouter agrégation harmonique** pour la conductivité hydraulique K dans `WeightedAverageFieldDiscretization`. Fichier : `spatial/field/core/field_param.py`. Impact : correction physique majeure.
2. **Ajouter `mesh_quality.py`** : `min_interior_angle`, `max_aspect_ratio`, `is_ccw`, appelé en `__post_init__` de `GmshPlanarMesh2D`. Évite erreurs silencieuses MODFLOW 6.
3. **Factoriser `clip_raster_to_polygon_normalized`** dans `geographic_io.py`. Remplace 8 duplications.
4. **Supprimer les 3 façades stériles** dans `zone_meshing/` (`_gmsh_driver.py`, `_geometry_cleaning.py`, `_refinement_policy.py`).
5. **Centraliser les helpers texte et TOML** (`_optional_text`, `_get_nested_section`).

### P1 — Amélioration structurelle

6. **Fusionner `pipeline.py` + `geographic.py`** en une seule façade compat (−521 L).
7. **Fusionner `_domain_geometry.py` → `_geometry_utils.py`** dans `zone_meshing/`.
8. **Supprimer ou tester `synthetic/`** — actuellement code mort entretenu.
9. **Déplacer `cartesian_grid/examples/`** vers `docs/` ou supprimer (−2 700 L).
10. **Factoriser `_cell_centers_from_sgrid`, `_interp_2d`** dans `spatial_interpolation.py`.
11. **Unifier `StructuredFieldMesh` et `GeologyStructuredMesh`** (−150 L).
12. **Ajouter validation `sum(fractions) ≈ 1.0`** dans `WeightedAverageFieldDiscretization`.
13. **Documenter la convention CCW et 0-based indexing** dans `HydroMesh`.
14. **Documenter la limitation pinch-outs** dans `ExtrudedPrismMesh3D`.

### P2 — Enrichissement fonctionnel

15. **Export UGRID CF 1.8** via xarray (< 100 lignes).
16. **Option D-infinity** pour flow accumulation.
17. **Tableau de référence seuils rivière** dans `GeographicConfig`.
18. **Renommer `Geographic` → `CatchmentDelineation`** (ou équivalent).
19. **Renommer `SpatialSupport` → `GriddedFieldSupport`** pour lever l'ambiguïté avec `RasterSupport`.

### P3 — Optimisations ciblées

20. Numba JIT sélectif (`_point_in_polygon`).
21. Cache `cKDTree` pour IDW répétées.
22. Paramétrage `k` voisins IDW.

---

## 14. Verdict final

| Axe | Verdict | Score qualitatif |
|---|---|---|
| Conformité MODFLOW DIS/DISV/DISU | **Conforme** (DISU partiel) | 8/10 |
| Algorithmes de délinéation | **Acceptable** (D8 OK, manque D-inf) | 7/10 |
| Intégration Gmsh | **Conforme** (API native, physical groups) | 8/10 |
| Qualité maillage (diagnostics) | **Problématique** (absente) | 3/10 |
| Discrétisation des champs | **Problématique** (moyenne K arithmétique) | 4/10 |
| Surface / topographie | **Acceptable** (pinch-outs non supportés) | 6/10 |
| Formats d'export | **Acceptable** (manque UGRID) | 6/10 |
| Nommage / organisation | **À améliorer** (`Geographic`, `SpatialSupport`) | 6/10 |
| Duplications | **Problématique** (~500 L) | 4/10 |
| Dead code | **Problématique** (~3 700 L) | 3/10 |
| Over-engineering (`zone_meshing/`) | **Problématique** (7 façades, 27 fichiers pour 2 500 L utiles) | 3/10 |

**Synthèse : ACCEPTABLE avec consolidation requise.** Le module est **fonctionnellement correct pour les cas usuels** (catchment breton 10-100 km², DEM 25 m, 2-3 zones géologiques peu contrastées) mais **fragile sur les cas limites** (contrastes K > 100×, pinch-outs, DEMs haute-résolution, maillages non-triviaux). L'effort de consolidation est **mesuré** (~15-20 jours de refactoring ciblé) pour un gain structurel substantiel : **−500 L de duplications, −3 700 L de dead code, 7 fichiers en moins, +1 correction physique majeure (K harmonique), +1 diagnostic qualité maillage**.
