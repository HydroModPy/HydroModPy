# Plan de dépréciation MODFLOW-NWT

Liens : [modflow_contracts.md](modflow_contracts.md),
[glossary.md](glossary.md),
[simulation_catalog_architecture.md](simulation_catalog_architecture.md).

## Contexte

HydroModPy embarque deux variantes MODFLOW :

- **MODFLOW-NWT** : `hydromodpy/solver/modflow_nwt/`, solveur structuré
  DIS, historiquement utilisé pour la plupart des bassins bretons.
- **MODFLOW 6** : `hydromodpy/solver/modflow6/`, solveur non structuré
  DISV, cible stratégique des travaux à venir.

Chaque variante a son propre adaptateur de couplage flow :

- `hydromodpy/solver/modflow_nwt/modflow/flow_to_modflow_adapter.py`
  (environ 1400 lignes)
- `hydromodpy/solver/modflow6/flow_to_modflow_adapter.py`
  (environ 570 lignes)

Le refactoring P06 de la migration `dev-refact_v2` a factorisé la couche
de dispatch partagée (`BoundaryKind -> "RIV" | "DRN" | "GHB" | "CHD"`)
dans `hydromodpy/solver/modflow_common/flow_translator.py`. Les payload
builders eux-mêmes restent volontairement dupliqués.

## Décision

**NWT et MF6 ne seront pas mutualisés au-delà.** MODFLOW-NWT est voué à
la suppression dans une release future, une fois le module LAK (lacs)
intégré côté MF6.

## Raison

- **Support des lacs.** MF6 fournit un package `LAK` de première classe
  avec un chemin d'intégration propre. NWT n'offre qu'une approche
  maison basée sur des astuces DRN/GHB. Les cas d'usage bretons
  (Ploémeur, bassins côtiers, lacs gérés) poussent le projet vers MF6.
- **Coût de factorisation.** Remonter les payload builders RIV, GHB,
  DRN, CHD et WEL dans `modflow_common/boundary_packages.py`
  demanderait un bookkeeping lourd (identifiants de cellules DIS vs
  DISV, mise en forme par stress period, gestion de l'intermittence).
  Ce travail serait jeté lors du retrait de NWT.
- **ROI de suppression.** Retirer NWT supprimera toute la branche
  `hydromodpy/solver/modflow_nwt/` (environ 3500 lignes dont les 1400
  de l'adaptateur), les tests marqués `nwt` et les pipelines CI
  spécifiques NWT. Ce gain l'emporte sur tout bénéfice de déduplication
  intermédiaire.

## Calendrier

| Jalon | État |
|---|---|
| Release v0.4 | NWT supporté, duplication volontaire documentée |
| Intégration LAK dans MF6 | Débloque Ploémeur et les lacs côtiers sous MF6 |
| Release post-LAK | Retrait de la branche NWT et de son adaptateur, des marqueurs tests, et bascule de la doc vers MF6 uniquement |

## Impact utilisateur

- **v0.4 et antérieur** : les workflows NWT continuent de tourner. Le
  marqueur pytest `nwt` reste vert.
- **Après le jalon LAK** : NWT est supprimé d'un seul bloc. Une note de
  migration sera publiée avec la release, expliquant comment porter un
  TOML NWT existant vers MF6 (permutation du solveur plus pivot DIS vers
  DISV, supportés tous les deux aujourd'hui).

## Implications quotidiennes

- **Ne pas** refactorer
  `hydromodpy/solver/modflow_nwt/modflow/flow_to_modflow_adapter.py`
  pour mutualiser les payload builders avec MF6.
- Les nouvelles features de conditions limites sont à prototyper côté
  MF6 d'abord. Le portage NWT n'est requis que si un workflow breton en
  v0.4 le demande explicitement.
- Les bug fixes dans l'adaptateur NWT restent locaux. Aucun sync
  cross-adapter n'est attendu.
