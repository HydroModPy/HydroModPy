# Contrats MODFLOW-NWT

Ce document décrit les contrats internes qu'HydroModPy respecte avant
d'instancier les packages MODFLOW-NWT. Deux contrats sont couverts :

1. La discrétisation spatiale et temporelle (package DIS).
2. Les conditions limites d'activation et d'initialisation (package BAS,
   tableaux `ibound` et `strt`).

Liens : [glossary.md](glossary.md), [design_patterns.md](design_patterns.md),
[nwt_sunset_plan.md](nwt_sunset_plan.md).

## 1. Contrat de discrétisation

Source : `hydromodpy/solver/modflow_nwt/modflow/discretization.py`.

Deux dataclasses typées portent le contrat :

- `TemporalDiscretizationResult`
- `SpatialDiscretizationResult`

### 1.1. Contrat temporel

Champs de `TemporalDiscretizationResult` :

| Champ | Type | Rôle |
|---|---|---|
| `itmuni` | `int` | Code d'unité de temps MODFLOW transmis à DIS |
| `nper` | `int` | Nombre de stress periods, strict positif |
| `perlen` | `np.ndarray` 1D float | Durée de chaque période en unités `itmuni` |
| `nstp` | `np.ndarray` 1D int | Nombre de pas de temps par période |
| `steady` | `np.ndarray` 1D bool | Drapeau steady ou transient par période |
| `start_datetime` | `object` ou `None` | Métadonnée de date de début optionnelle |

Cohérences requises :

- `nper == perlen.size`
- `nstp.size == nper`
- `steady.size == nper`
- `nper > 0`

La conversion vers les kwargs FloPy se fait via
`TemporalDiscretizationResult.as_dis_kwargs()`, qui expose les clés
`itmuni`, `nper`, `perlen`, `nstp`, `steady`, `start_datetime`.

### 1.2. Contrat spatial

Champs de `SpatialDiscretizationResult` :

| Champ | Type | Rôle |
|---|---|---|
| `sgrid` | objet grille | Retour de `StructuredGridBuilder` |
| `dem` | `np.ndarray` 2D float | Support topographique validé |
| `nlay` | `int` | Nombre de couches |
| `nrow` | `int` | Nombre de lignes |
| `ncol` | `int` | Nombre de colonnes |
| `zbot` | `np.ndarray` 3D float, shape `(nlay, nrow, ncol)` | Élévations de fond |
| `bottom_layer` | `np.ndarray` 2D float | `zbot[-1]`, fond de la couche inférieure |

Cohérences requises :

- `zbot.shape == (nlay, nrow, ncol)`
- `bottom_layer.shape == (nrow, ncol)`
- Le domaine fournit `surface_topo` et `substratum` de type `Surface`,
  cohérents avec la forme du DEM.

### 1.3. Entrées amont

Le constructeur temporel consomme :

- `tgrid_config.to_builder_kwargs()`
- `flow_regime`
- `default_itmuni`

Le constructeur spatial consomme :

- le `domain` avec `surface_topo` et `substratum`
- la forme du DEM actif
- `vertical_config`

### 1.4. Pourquoi ce contrat

- Rendre explicite et testable le payload DIS.
- Empêcher toute dérive de forme ou d'unité entre les objets runtime et
  la configuration du solveur.
- Éviter la dispersion des conventions DIS dans le code d'orchestration.

## 2. Contrat BAS (`ibound`, `strt`)

Ces deux tableaux sont les plus sensibles au démarrage de MODFLOW. Une
incohérence peut déstabiliser la simulation en silence.

### 2.1. Sémantique MODFLOW respectée

HydroModPy applique le contrat BAS standard, basé sur le signe :

- `ibound > 0` : cellule active, la charge est calculée.
- `ibound = 0` : cellule inactive, no-flow.
- `ibound < 0` : cellule à charge imposée (constant head).

`strt` est un tableau 3D `(nlay, nrow, ncol)`. Pour les cellules
`ibound < 0`, `strt` fournit la charge imposée utilisée par BAS.

### 2.2. Où les tableaux sont construits

Source principale :

- `hydromodpy/solver/modflow_nwt/modflow/flow_to_modflow_adapter.py`
  - `FlowToModflowAdapter._build_initial_heads_and_sides`
  - `FlowToModflowAdapter._build_ocean_chd`
  - `FlowToModflowAdapter._validate_ibound_strt_contract`

Point d'assemblage :

- `hydromodpy/solver/modflow_nwt/modflow/nwt_solver.py` appelle
  `flopy.modflow.ModflowBas(..., ibound=..., strt=...)`.

### 2.3. Ordre d'application

La politique d'initialisation de `strt` provient de
`flow.initial_conditions.h.type` :

1. `top` : initialisation depuis le DEM.
2. `bottom` : initialisation depuis l'élévation de la couche inférieure.
3. `custom` : initialisation depuis une valeur scalaire utilisateur.

Puis les conditions de Dirichlet latérales (`west`, `east`, `north`,
`south`) sont appliquées :

1. cellules de face basculées à `ibound = -1`,
2. valeurs `strt` correspondantes écrasées par la charge limite.

Puis le masque no-data :

1. les cellules DEM sous le seuil sentinel passent à `ibound = 0`.

Puis la condition océanique éventuelle :

1. un niveau océan scalaire peut basculer les cellules submergées à
   `ibound < 0` et écraser `strt` ;
2. un forçage océanique transient génère un payload CHD par stress period
   et peut désactiver localement le drainage.

### 2.4. Validations appliquées

Avant la poursuite de l'assemblage, l'adaptateur vérifie :

1. `ibound.shape == (nlay, nrow, ncol)`
2. `strt.shape == (nlay, nrow, ncol)`
3. `drain_array.shape == (nrow, ncol)`
4. toutes les valeurs sont finies
5. `drain_array` est binaire (`0` ou `1`)

La validation contrôle bien la sémantique par signe, pas seulement
`{-1, 0, 1}`.

### 2.5. Debug pratique

1. Vérifier l'ordre d'assignation (conditions initiales, puis limites
   latérales, puis océan).
2. Inspecter les masques de signe de `ibound` (`>0`, `=0`, `<0`) avant
   de lancer le solveur.
3. Tracer les tranches de `strt` pour les faces à charge imposée et les
   zones sous influence océanique.
4. Toute valeur non finie dans `ibound` ou `strt` est une erreur dure.
