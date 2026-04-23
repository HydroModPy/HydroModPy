# Documentation développeur

Cette documentation couvre l'architecture interne, les conventions de
code et les points d'extension de HydroModPy. Public visé : contributeurs
au code, mainteneurs, intégrateurs frontaux. Pour l'usage utilisateur voir
`docs/readthedocs/`.

## Par où commencer

1. [glossary.md](glossary.md) : vocabulaire canonique (Workspace, Project,
   Run, Catalog...). Sert d'arbitre en cas de conflit de nommage.
2. [design_patterns.md](design_patterns.md) : dix patterns récurrents à
   connaître avant de lire le code.
3. [CLI.md](CLI.md) : commandes `hmp` et workflows disponibles.

## Architecture et stockage

- [databases_and_workflows.md](databases_and_workflows.md) : vue
  d'ensemble des deux bases (catalogue sortie, cache entrée) et de leurs
  interactions avec chaque workflow.
- [simulation_catalog_architecture.md](simulation_catalog_architecture.md) :
  catalogue central (DuckDB + Zarr + Parquet), API Python, exports.
- [parquet_lakehouse_architecture.md](parquet_lakehouse_architecture.md) :
  disposition disque des séries temporelles, budgets, bilans de masse.
- [parquet_lakehouse_concurrency.md](parquet_lakehouse_concurrency.md) :
  verrous DuckDB, écriture atomique, retries.
- [parquet_lakehouse_migration_guide.md](parquet_lakehouse_migration_guide.md) :
  migration d'un workspace v0.5 vers le lakehouse v0.6.
- [schema_evolution.md](schema_evolution.md) : règles d'évolution des
  schémas DuckDB et Zarr.

## Solveurs

- [boussinesq_solver_architecture.md](boussinesq_solver_architecture.md) :
  architecture du solveur Boussinesq (PETSc, scipy).
- [boussinesq_petsc_vs_marcais_2017.md](boussinesq_petsc_vs_marcais_2017.md) :
  comparaison numérique avec Marcais 2017.
- [boussinesq_petsc_headwater_100km2_diagnostic.md](boussinesq_petsc_headwater_100km2_diagnostic.md) :
  cas de diagnostic sur bassin amont.
- [boussinesq_linux_ci.md](boussinesq_linux_ci.md) : intégration continue
  Linux pour Boussinesq.
- [modflow_contracts.md](modflow_contracts.md) : contrats de
  discrétisation et BAS (`ibound`, `strt`) pour MODFLOW-NWT.
- [modflow6_gmsh_disv_development_perspective.md](modflow6_gmsh_disv_development_perspective.md) :
  perspective DISV non structurée pour MODFLOW 6.
- [nwt_sunset_plan.md](nwt_sunset_plan.md) : plan de dépréciation de
  MODFLOW-NWT.

## Maillage et spatial

- [unified_mesh_pivot_architecture.md](unified_mesh_pivot_architecture.md) :
  hiérarchie de maillage et pivot `HydroMesh`.
- [gmsh_mesh_integration_note.md](gmsh_mesh_integration_note.md) : note
  d'intégration de gmsh dans la pipeline.
- [gmsh_conformal_meshing.md](gmsh_conformal_meshing.md) : plans de
  maillage conforme (zones, rivières, réseau hydrographique).

## Calibration

- [calibration_guide.md](calibration_guide.md) : guide de calibration
  (moteur, objectifs, paramètres, persistance).

## Frontend et schémas

- [frontend_hooks.md](frontend_hooks.md) : exposition JSON Schema pour
  Streamlit, Angular, React.

## Cas d'étude

- [ploemeur_3d_development_perspective.md](ploemeur_3d_development_perspective.md) :
  perspective 3D pour le site de Ploémeur.

## Packaging

- [conda_pkg.md](conda_pkg.md) : empaquetage conda-forge.

## Références numériques

- [numerical_methods_references/](numerical_methods_references/) : PDF de
  référence (Marcais 2017...).

## Annexe

Le PDF `Recapitulatif perlen HMP.pdf` archive une synthèse historique
sur la discrétisation temporelle de MODFLOW.

## Conventions rédactionnelles

- Français, phrases courtes.
- Pas de tiret long `-` ni `-` (remplacer par `:` ou `,`).
- Pas d'emoji.
- Chemins absolus dans `hydromodpy/`, liens relatifs entre docs.
- Vérifier que chaque classe ou fonction citée existe dans le code avant
  de la mentionner.
