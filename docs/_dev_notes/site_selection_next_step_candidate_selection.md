# Prochaine etape proposee - selection robuste parmi candidats delimites

Date: 2026-05-26

Statut: implemente dans la phase commune `select_delineated_catchments()`.

Ce rapport propose une suite bornee pour `site_selection` avant cloture du
chantier court terme. L'objectif n'est pas de construire un nouveau moteur
hydrographique complet, mais d'ameliorer la selection finale parmi des candidats
deja produits et delimites.

## Constat

`site_selection` dispose maintenant d'un socle exploitable:

- configurations dediees;
- profils courts termes `area_only` et `gauged_downstream_station`;
- chargement des donnees via les gestionnaires existants;
- construction d'exutoires candidats depuis stations, CSV ou DEM par surface cible;
- delimitation des bassins;
- criteres auditables;
- decisions normalisees;
- exports CSV, JSONL, GeoJSON, GPKG/GeoParquet optionnels;
- manifest et rapport HTML.

Le point a ne pas rouvrir maintenant est la generation hydrographique autonome
avancee depuis le DEM. C'est un sujet plus large: sous-bassins, confluences,
ordre de Strahler, graphe de reseau, quotas par axe hydrologique. Ce chantier
peut vite augmenter la complexite et repousser la stabilisation.

Le point utile et realiste est different: mieux choisir dans une liste de
bassins deja delimites.

## Proposition

Ajouter une etape explicite de selection robuste apres delimitation:

```text
candidats delimites
-> rejet des echecs structurels
-> score ou filtre de surface
-> controle de recouvrement/emboitement
-> quota spatial simple
-> tri deterministe
-> selection finale auditee
```

Cette approche reste compatible avec l'architecture actuelle. Elle reutilise
les bassins, criteres, decisions et exports deja presents. Elle evite de
melanger deux problemes:

- produire de bons candidats hydrographiques depuis le DEM;
- choisir proprement parmi des candidats deja disponibles.

La premiere action doit traiter le second probleme seulement.

## Regles proposees

Les regles minimales sont:

1. Rejeter les candidats non exploitables: bassin absent, surface absente,
   geometrie invalide, exutoire hors territoire ou echec de delimitation.
2. Evaluer la surface selon le profil:
   - filtre dur pour `area_only` quand une plage est declaree;
   - avertissement ou score lorsque la surface n'est pas bloquante.
3. Rejeter les bassins trop redondants:
   - recouvrement trop fort;
   - emboitement trop fort;
   - distance minimale entre exutoires si configuree.
4. Ajouter un quota spatial simple:
   - par departement ou region administrative quand disponible;
   - sinon par grille spatiale simple dans le CRS projet;
   - garder au plus `n` bassins par secteur.
5. Trier de facon deterministe:
   - candidats sans rejet;
   - moins d'avertissements;
   - surface la plus proche de la cible quand une cible existe;
   - meilleur score station ou snap quand pertinent;
   - identifiant stable en dernier recours.

Chaque regle doit produire une raison lisible dans les sorties de decision. Il
ne faut pas cacher le choix dans un score unique opaque.

## Pourquoi cette etape

Cette etape donne un bon ratio utilite/complexite:

- elle ameliore directement les resultats des profils existants;
- elle aide aussi les modes DEM sans rendre leur generation plus ambitieuse;
- elle limite les bassins emboites ou repetitifs;
- elle produit des selections plus lisibles dans le rapport HTML;
- elle reste testable avec des fixtures synthetiques.

Elle permet de clore le chantier court terme avec une selection finale plus
propre, sans ouvrir un refactoring hydrographique lourd.

## Perimetre recommande

### Inclus

- logique de classement et filtrage apres delimitation;
- quota spatial simple;
- traces de decision pour les rejets par quota, recouvrement ou classement;
- tests unitaires sur bassins synthetiques;
- validation sur les deux exemples courts termes:
  - `calvados_non_jauge_dem_10bassins_100km2.toml`;
  - `bretagne_jauge_7stations.toml`.

### Exclu

- generation par confluences;
- ordre de Strahler comme critere de generation;
- graphe hydrographique complet;
- decoupage automatique en sous-bassins;
- optimisation globale multi-objectif;
- carte interactive.

Ces sujets doivent rester des evolutions separees apres cloture du chantier
court terme.

## Implementation suggeree

L'implementation est restee localisee dans la nouvelle structure:

- `hydromodpy/spatial/site_selection/evaluation/selection.py` pour la selection
  finale et les raisons de rejet;
- `hydromodpy/spatial/site_selection/evaluation/spatial_filters.py` pour les
  helpers de recouvrement ou de distance;
- `hydromodpy/spatial/site_selection/config/models.py` pour les options de
  quota;
- `tests/unit/site_selection/` pour les cas synthetiques.

Il faut eviter d'ajouter un nouveau sous-systeme. Une fonction ou classe de
selection supplementaire, appelee depuis le flux existant, suffit si elle reste
lisible et auditable.

## Configuration minimale envisagee

La configuration ajoutee reste dans `[site_selection.spatial_selection]`:

```toml
[site_selection.spatial_selection]
max_selected_sites = 10
overlap_mode = "hard_reject"
max_pairwise_basin_overlap_fraction = 0.20
min_outlet_distance_km = 2.0
spatial_quota_mode = "grid"
spatial_quota_cell_size_km = 25.0
spatial_quota_max_sites_per_cell = 1
```

Les champs existants `max_pairwise_basin_overlap_fraction`, `overlap_reference`
et `overlap_mode` restent utilises pour le recouvrement. Les nouveaux champs
sont limites au plafonnement global et au quota spatial grille.

## Mise en oeuvre

La mise en oeuvre est volontairement localisee:

- `SpatialSelectionConfig` porte les options `max_selected_sites`,
  `spatial_quota_mode`, `spatial_quota_cell_size_km` et
  `spatial_quota_max_sites_per_cell`;
- `select_delineated_catchments()` applique maintenant, apres les criteres
  metier, le plafonnement global, le recouvrement, la distance minimale entre
  exutoires et le quota spatial;
- `dem_area_target` utilise `max_selected_sites = n_basins` dans cette phase
  commune, au lieu d'un post-traitement separe;
- chaque rejet produit un composant auditable: `target_count`,
  `basin_overlap`, `outlet_spacing` ou `spatial_quota`.

Tests ajoutes:

- limite globale de sites selectionnes;
- rejet par distance minimale entre exutoires;
- quota spatial grille;
- validation de la configuration du quota grille.

## Critere de fin

Cette etape peut etre consideree terminee quand:

1. les bassins non exploitables sont rejetes avec une raison explicite;
2. les bassins trop recouvrants ou emboites sont geres de maniere
   deterministe;
3. un quota spatial simple peut eviter une selection concentree dans une seule
   zone;
4. les decisions finales expliquent les rejets et les avertissements;
5. les tests unitaires couvrent tri, recouvrement, quota et egalites de score;
6. les deux exemples courts termes continuent de produire un manifest valide et
   un HTML de controle.

## Recommandation

Faire cette etape, mais la garder courte. Elle doit consolider la selection
finale, pas transformer `site_selection` en moteur complet de conception
hydrographique.

La bonne cible pour cloturer le chantier est:

```text
site_selection sait produire ou relire des candidats,
delimiter les bassins,
choisir proprement les meilleurs selon des regles explicites,
et expliquer chaque decision dans ses sorties.
```

Cloture verifiee le 2026-05-26:

- `calvados_non_jauge_dem_10bassins_100km2.toml` tourne et produit
  `outputs/calvados_non_jauge_dem_100km2_v1/review/index.html`;
- `bretagne_jauge_7stations.toml` tourne et produit
  `outputs/bretagne_jauge_7stations_v1/review/index.html`;
- les tests unitaires `tests/unit/site_selection` et les tests de bridge
  exemples passent;
- l'index API local pointe maintenant vers les sous-packages
  `candidates`, `evaluation`, `evidence`, `hydrology`, `outputs`,
  `pipelines` et `reports`.
