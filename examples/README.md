# HydroModPy - exemples

Suite d'exemples alignée sur l'API publique **v1** (CLI `hmp` + API
Python `import hydromodpy as hmp`). Le dossier `examples/` est lui-même
un **workspace HydroModPy** : les projets vivent sous
[`projects/`](projects/) et partagent les [données d'entrée](data/) via
la résolution de chemins du workspace.

## Prérequis

```bash
mamba activate hmp_refact
pip install -e .
hmp install-binaries     # MF6 + MFNWT + MP6 + MP7 + MT3D-USGS dans ~/.cache/hydromodpy/bin/
hmp doctor               # diagnostic env (Python, deps, solveurs, workspace)
```

## Stockage V1 - trois DuckDB

| Fichier | Emplacement | Rôle |
|---|---|---|
| `catalog.duckdb` | `<workspace>/` | simulations + têtes / budget MODFLOW par projet |
| `cache.duckdb` | `<workspace>/data/` | cache d'inputs (DEM, hydrographie, BRGM, SIM2, ...) |
| `index.duckdb` | `<state>/` (machine-wide) | registre des workspaces (`hmp index register`) |

Les champs gridded vivent en **Zarr v2** (sortie split
`schema/writer/reader/finalizer`) et respectent les conventions
**CF-1.11 + ACDD-1.3 + UGRID-1.0**. Les exports portables vont sur
COG GeoTIFF (zstd, overviews 2/4/8/16/32x) et STAC
(`Collection`/`Catalog` writers). La provenance s'écrit en **PROV-O**.

## Catalog facade Python

| Appel | Retour | Namespaces |
|---|---|---|
| `hmp.open(workspace)` | `SimulationCatalog` | API simulations historique (legacy, mais stable). |
| `hmp.open_catalog(workspace)` | `CatalogFacade` | `.simulations`, `.inputs`, `.projects`. |

`hmp.open_catalog(...)` est le point d'entrée recommandé dès qu'on
touche au cache d'inputs ou au registre projets.

## CLI - verbs clés

Liste à jour via `hmp --help`. Les nouveautés à connaître :

- `hmp export-package <sim_ref> -o sim.hmp` : archive portable
  (tar.zst + manifeste RO-Crate).
- `hmp add sim.hmp` / `hmp import sim.hmp` : roundtrip d'import.
- `hmp index register|search|forget|prune` : registre machine-wide
  des workspaces.
- `hmp install-binaries` : MF6 / MFNWT / MP6 / MP7 / MT3D-USGS.
- `hmp gc` : caches orphelins + tmp parquet + runs zombies.
- `hmp vacuum` : compaction DuckDB (CHECKPOINT) + consolidation Zarr.
- `hmp privacy` : purge auditée d'une simulation.
- `hmp manage [--workspace ...]` : UI navigateur locale pour inspecter
  les DuckDB.
- `hmp run --resume <RUN_ID>` / `--from <STEP>` : reprise cascade-aware
  via le journal append-only `workflow_steps` (HeartbeatPulse détecte
  les zombies).

## Index des projets

| # | Dossier | Titre | Solveur | Durée | Réseau |
|---|---|---|---|---|---|
| 00 | [`projects/00_getting_started/`](projects/00_getting_started/) | Aquifère Dupuit synthétique | MODFLOW-NWT | ~20 s | non |
| 01 | [`projects/01_calibration/`](projects/01_calibration/) | Calibration Optuna sur K | MODFLOW-NWT | ~1 min | non |
| 02 | [`projects/02_nancon_watershed/`](projects/02_nancon_watershed/) | Bassin du Nançon (v1 flagship) | MODFLOW-NWT | ~5 min | possible |
| 03a | [`projects/03_canut_watershed/`](projects/03_canut_watershed/) | Bassin du Canut (config expert) | MODFLOW-NWT | ~5 min | possible |
| 03b | [`projects/03_groundwater_1d/`](projects/03_groundwater_1d/) | Dupuit-Forchheimer 1D analytique | aucun | < 1 s | non |
| 04 | [`projects/04_data_overview/`](projects/04_data_overview/) | Carte d'identité d'un bassin | aucun | ~1 min | oui |
| 05 | [`projects/05_nancon_data_overview/`](projects/05_nancon_data_overview/) | Overview complet Nançon | aucun | ~2 min | oui |
| 06 | [`projects/06_vire_selune/`](projects/06_vire_selune/) | Vire & Sélune (MF6 + NWT) | MF6 / NWT | ~10 min | possible |
| 07 | [`projects/07_mesh_gallery/`](projects/07_mesh_gallery/) | Galerie de maillages (bundles) | aucun | instantané | non |
| 08 | [`projects/08_mesh_viewer/`](projects/08_mesh_viewer/) | Inspection de bundles de maillage | aucun | instantané | non |
| 09a | [`projects/09_capability_gallery/`](projects/09_capability_gallery/) | Figures publiées (gallery statique) | aucun | aucun | non |
| 09b | [`projects/09_comparison_workflow/`](projects/09_comparison_workflow/) | Workflows de comparaison + testbed stability | mixte | variable | possible |
| 10 | [`projects/10_testbed_workflow/`](projects/10_testbed_workflow/) | Testbed Boussinesq + reporting | Boussinesq | ~2 min | non |
| 11a | [`projects/11_nancon_network_physical_benchmark/`](projects/11_nancon_network_physical_benchmark/) | Benchmark réseau physique Nançon | MODFLOW-NWT | ~20 min | oui |
| 11b | [`projects/11_nancon_watershed/`](projects/11_nancon_watershed/) | Nançon - showcase complet v2 | MF6 / NWT | ~5 min | possible |
| 12 | [`projects/12_calibration_network_transient_b0/`](projects/12_calibration_network_transient_b0/) | Calibration réseau + transient (testbed) | MODFLOW-NWT | long | oui |
| 13 | [`projects/13_transport_mf6_gwt_disv_visual_guard/`](projects/13_transport_mf6_gwt_disv_visual_guard/) | Transport MF6 GWT DISV (visual guard) | MF6-GWT | ~3 min | non |
| 14 | [`projects/14_transport_nancon_gwt_visual_guard/`](projects/14_transport_nancon_gwt_visual_guard/) | Transport GWT sur Nançon (visual guard) | MF6-GWT | ~5 min | non |
| 15 | [`projects/15_nancon_gauged_context/`](projects/15_nancon_gauged_context/) | Contexte jaugé Nançon | aucun | ~1 min | oui |

## Ordre de lecture recommandé

1. **00_getting_started** : structure minimale d'un `project.toml`,
   premier run, découverte du catalogue.
2. **01_calibration** : `[workflow].mode = "calibration"` via `hmp run`
   et API `hmp.calibrate`.
3. **04_data_overview** : workflow « données seulement », sans
   simulation.
4. **02_nancon_watershed** : premier bassin réel, Nançon (~110 km²).
5. **11_nancon_watershed** : showcase v2 du Nançon (tous les workflows,
   overlays, API Python complète).
6. **06_vire_selune** : permanent / transitoire, MF6 vs NWT, maillage
   régulier vs irrégulier.
7. **07_mesh_gallery** + **08_mesh_viewer** : cas « maillage seul ».
8. **09_capability_gallery** : figures de référence publiées.

Parcours data-scientist : `00` → `01` → explorer
`hmp.open_catalog("examples/")` (table `simulations`, namespace
`inputs`, namespace `projects`) puis `SimulationGroup` pour les
exports ML-ready.

## État courant après migration

- Tous les TOML des projets `00` à `09` et `11` ont été migrés vers la
  schema v1 (`modflownwt` -> `modflow_nwt`, restructuration de
  `[overview]`, `[geographic]`, `[flow.param.X.field]`).
- Les artefacts (`catalog.duckdb`, dossier `simulations/<sim_id>.zarr`,
  `figures/<run_name>/`) sont créés au niveau du workspace
  `examples/` et ignorés par `.gitignore`.
- Trois fichiers ont été mis en quarantaine avec suffixe `.draft`
  parce qu'ils ne migrent pas proprement vers v1 :
  - `projects/03_groundwater_1d/project.toml.draft` : cas analytique
    pas dispatché par `hmp run` (à driver via
    `hydromodpy.calibration.cases`).
  - `projects/02_nancon_watershed/run_transient_prototype.py.draft` :
    prototype Python en attente de réécriture.
  - Vérifier régulièrement : `find examples -name "*.draft"`.

## Limitations connues

- **`hmp run` complet bloqué par un bug Zarr v2 schema**
  (`ZarrSchemaVersionError: expected '2', found None`). Le scénario
  end-to-end correspondant est skippé dans
  `tests/e2e/test_workflow_from_scratch.py:287`. En attendant le fix,
  valider les TOML avec `hmp config check` puis vérifier la
  résolution avec `hmp run --dry-run`.
- `02_nancon_watershed/run_sweep_sy.toml` est un **draft de design**
  documenté : le workflow `sweep` n'est pas (encore) câblé dans le
  dispatcher.
- Les **overlays** `11_nancon_watershed/overlays/*.toml` sont des
  fragments minimaux et ne valident **pas** en standalone. Usage :
  `hmp run base.toml --overlay overlays/X.toml`.
- Les **TOMLs spécialisés** (schéma propre, pas `HydroModPyConfig`)
  ne passent pas `hmp config check`. Ils sont consommés par leur
  propre runner :
  - `08_mesh_viewer/config_*.toml` -> `tools/mesh_bundle_viewer/`.
  - `09_comparison_workflow/stability_targets.toml` ->
    `validate_stability_targets` (testbed).
  - `12_calibration_network_transient_b0/configs/*.toml` ->
    `run_real_parameter_grid.py`.
  - `13_transport_mf6_gwt_disv_visual_guard/cases/*.toml` ->
    `run_visual_guard.py`.

## Conventions

Chaque projet runnable est un sous-dossier auto-contenu sous
`projects/` :

```
examples/projects/<NN_nom>/
├── README.md         # description FR détaillée
├── project.toml      # configuration valide quand le dossier est runnable
└── run*.py / *.toml  # entrées CLI ou API additionnelles
```

Les brouillons de conception (`*.draft`) sont conservés dans leur
dossier source avec une mention explicite en en-tête. Ils ne doivent
pas être lancés avec `hmp run` tant que le workflow correspondant
n'est pas exposé par le dispatcher `hmp run`.

## Archive

Les exemples qui ne s'alignent plus sur l'API actuelle ne font plus
partie du parcours public. Les projets versionnés sous `projects/`
restent la référence.
