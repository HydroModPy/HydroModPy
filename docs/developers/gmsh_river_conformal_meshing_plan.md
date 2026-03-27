# Plan de Maillage Gmsh Conforme au Reseau de Riviere

Statut: note de design.

Etat d'avancement (2026-03-15):
- `DomainGeographicContext` expose deja `river_mesh_trace` en memoire.
- `generate_zone_conformal_mesh_from_dataframe(...)` accepte deja `river_trace`.
- Le case runner conformal (`run_case_zone_conformal.py`) peut deja consommer
  `domain_geographic.river_mesh_trace` sans relecture fichier.
- Un launcher dedie existe: `launchers/mesh_catchment/launcher.py`
  (`MeshCatchmentLauncher`), sans branchement a `process_simulation`.

## Objectif

Definir un workflow pour generer un maillage 2D Gmsh de domaine qui soit:

- conforme au reseau de riviere (les rivieres suivent des aretes du maillage),
- raffine pres des rivieres et plus grossier ailleurs,
- compatible avec plusieurs origines de reseau de riviere:
  - fichier externe,
  - donnees hydrography chargees,
  - extraction DEM via le pipeline geographic.

Extension visee: mode optionnel ou le maillage est aussi conforme a la lithologie.

## Alignement avec l'existant

Elements deja presents:

- extraction reseau de riviere DEM dans geographic:
  - `hydromodpy/geographic/core/river_network.py`
  - `hydromodpy/geographic/core/domain_geographic_pipeline.py`
- sorties canoniques geographic deja presentes (utile audit/repro):
  - `results_stable/geographic/river_network.shp`
  - `results_stable/geographic/river_network_summary.json`
- workflow Gmsh conformal sur polygons de zones (lithologie):
  - `hydromodpy/solver/utils/mesh/gmsh_grid/zone_meshing/conformal.py`
- separation actuelle `domain.supports` vs logique maillage:
  - `hydromodpy/domain/spatial_support.py`
  - `hydromodpy/domain/spatial_support_config.py`
- objet runtime deja porte dans setup:
  - `setup.domain_geographic` (`DomainGeographicContext`)

## Decision de structuration

### Ce qui va dans Domain

- Les supports spatiaux utilises par la discretisation de parametres (`FieldParam`),
- la logique de zones/surfaces metier.

### Ce qui ne va pas dans Domain

- La generation du maillage Gmsh,
- les contraintes geometriques de meshing (riviere/lithologie/interfaces),
- la politique de refinement.

Conclusion:

- ne pas stocker le reseau de riviere comme "zone domain",
- garder la logique de maillage dans `gmsh_grid/zone_meshing`.

### Position retenue pour l'acces runtime

Decision:

- exposer un sous-objet riviere dedie dans `DomainGeographicContext`,
- ne pas stocker le reseau dans `Domain.zones`.

Extension proposee de `DomainGeographicContext`:

- `river_mesh_trace: RiverMeshTrace | None`

## Contrat `RiverMeshTrace` (v1)

Objectif v1:

- conserver en memoire uniquement le trace riviere utile au maillage conforme,
- eviter toute relecture disque au moment du maillage.

Proposition de champs:

- `source_kind: str` (`geographic_generated`, `hydrography_loaded`, `file`)
- `crs_wkt: str`
- `lines: tuple[LineString, ...]`
- `segment_count: int`
- `total_length_m: float`

Regles:

- `lines` est deja reprojete dans le CRS du domaine,
- `lines` est deja clippe au catchment/domaine,
- pas de raster dans ce sous-objet (volontaire),
- les fichiers restent optionnels pour audit, pas necessaires au mesher.

## Origine multiple du reseau de riviere

Proposer un contrat explicite:

- `origin = "geographic_generated"`:
  - source de reference `results_stable/geographic/river_network.shp`
- `origin = "hydrography_loaded"`:
  - source data-manager hydrography charge dans le run
- `origin = "file"`:
  - chemin explicite configure

Regle:

- pas d'auto-detection implicite en v1,
- resolution explicite de la source vers un objet `RiverMeshTrace`.

## Stockage recommande

Conserver les produits geographic dans leur emplacement actuel (audit/reproductibilite).

Ajouter un espace mesh dedie:

- `results_stable/mesh/inputs/river_network_for_mesh.*`
- `results_stable/mesh/inputs/lithology_for_mesh.*` (si mode lithologie)
- `results_stable/mesh/gmsh/domain_river_conformal.msh`
- `results_stable/mesh/gmsh/domain_river_conformal_summary.json`
- `results_stable/mesh/figures/domain_river_conformal_overview.png`

Important:

- `mesh/inputs` est optionnel (debug/audit),
- la phase maillage lit prioritairement `setup.domain_geographic.river_mesh_trace`.

## Etape de generation dans le pipeline

### Cas riviere generee depuis DEM

Ordre recommande:

1. preprocessing geographic (catchment, DEM, flow products),
2. extraction riviere (`geographic.river_network.enabled=true`),
3. conversion en `RiverMeshTrace` (normalisation, reprojection, clip),
4. hydratation `DomainGeographicContext.river_mesh_trace`,
5. generation maillage Gmsh conforme depuis `setup.domain_geographic`,
6. phases flow/transport.

Point d'attention:

- l'etape 3 doit etre faite dans la pipeline geographic (pas dans le mesher),
- le mesher consomme un objet deja pret, sans IO riviere.

### Cas riviere chargee

Ordre recommande:

1. setup geographic/domain,
2. data loading (hydrography ou fichier),
3. normalisation + reprojection + clip catchment,
4. construction `RiverMeshTrace`,
5. hydratation `DomainGeographicContext.river_mesh_trace`,
6. generation maillage Gmsh depuis `setup.domain_geographic`,
7. phases flow/transport.

## Option lithologie + riviere

Deux modes:

- `compliance_mode = "river_only"`:
  - conformite riviere,
  - refinement distance-a-riviere,
  - pas de conformite imposee lithologique.
- `compliance_mode = "river_plus_lithology"`:
  - conformite interfaces lithologiques + rivieres,
  - refinement prioritaire pres des rivieres,
  - refinement optionnel sur interfaces lithologiques.

## Proposition de contrat TOML (v1)

```toml
[mesh]
enabled = true
backend = "gmsh"
mode = "river_conformal" # "river_conformal" | "river_lithology_conformal"

[mesh.domain]
kind = "vector"
path = "..."
id_field = "domain_id"
selected_id = "main"

[mesh.river.source]
origin = "geographic_generated" # "geographic_generated" | "hydrography_loaded" | "file"
path = null                      # requis si origin="file"

[mesh.gmsh]
algorithm = "delaunay"
global_size = 250.0
min_size = 80.0
max_size = 500.0

[mesh.gmsh.river_refinement]
enabled = true
river_size = 60.0
river_distance = 400.0
river_sampling = 96

[mesh.runtime]
use_in_memory_river_trace = true
persist_mesh_inputs = false

[mesh.lithology]
enabled = false
source_mode = "geology_data_manager" # ou "file"
```

## Integration launcher

Recommandation en deux temps:

1. court terme:
   - ajouter un launcher dedie maillage (`MeshGenerationLauncher`) pour iteration rapide.
2. moyen terme:
   - integrer une phase optionnelle `mesh` dans `ProcessSimulationLauncher` entre `data` et `flow`.

Point de raccord:

- la phase mesh lit `setup.domain_geographic.river_mesh_trace`,
- pas de lecture directe de fichiers dans le mesher.

## Criteres QA (Quality Assurance)

Definition:

- un critere QA est un indicateur mesurable, stable et verifiable qui confirme que le maillage genere est conforme aux exigences.

Criteres QA minimaux proposes:

1. conformite riviere/aretes:
   - proportion de longueur de riviere qui coincide avec des aretes de maillage >= seuil cible.
2. gradient de raffinement:
   - taille mediane des cellules dans un buffer proche riviere < taille mediane hors buffer.
3. couverture domaine:
   - ecart `|aire_maillage - aire_domaine|` <= tolerance.
4. stabilite numerique structurelle:
   - nombre total de cellules dans une plage attendue pour une config donnee.
5. conformite lithologie (si activee):
   - baisse nette du nombre de cellules mixtes lithologiques.
6. reproductibilite:
   - `summary.json` stable (ou variations dans tolerance definie) entre runs identiques.
7. contrat pipeline memoire:
   - si source riviere resolue et `mesh.enabled=true`, `river_mesh_trace` est non-null.

Sortie QA recommandee:

- un fichier `domain_river_conformal_summary.json` avec ces metriques.

## Plan de validation minimal

1. cas synthetique:
   - geometrie simple, riviere unique, verification robuste des metriques.
2. cas reel clippe:
   - subset geologique/reseau existant, verification des sorties mesh + QA.
3. non regression:
   - test golden sur la signature QA (avec tolerances explicites).

## Conclusion

La direction la plus coherente avec l'architecture actuelle est:

- geographic produit (ou reference) le reseau de riviere,
- `DomainGeographicContext` expose un `RiverMeshTrace` memoire (trace uniquement),
- zone_meshing genere le maillage conforme et le refinement,
- domain conserve son role de support metier,
- launcher evolue vers une phase mesh optionnelle, avec un mode mesh-only pour l'iteration.
