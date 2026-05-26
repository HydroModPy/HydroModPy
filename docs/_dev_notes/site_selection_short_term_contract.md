# Contrat court terme - `site_selection`

Date: 2026-05-26

Ce document fixe le contrat court terme de `site_selection`. Il ne remplace pas
le plan long `site_selection_tool_implementation_plan.md`: il borne ce qui doit
etre considere comme utilisable et maintenu maintenant.

La doctrine metier finale associee est documentee dans
`docs/_dev_notes/site_selection_final_business_doctrine.md`.

## Objectif

`site_selection` doit fournir une plateforme claire pour preparer une campagne
de modelisation a partir de bassins candidats. A court terme, deux usages sont
supportes:

1. selection de bassins par critere de surface;
2. selection de bassins jauges depuis une station hydrometrique situee a
   l'aval.

Le code doit rester extensible, mais les evolutions plus larges ne doivent pas
empecher de stabiliser ces deux usages.

## Limites d'architecture

Les responsabilites restent separees:

- `hydromodpy.data` charge, met en cache et normalise les sources fournisseur;
- `hydromodpy.spatial.site_selection` construit les candidats, delimite les
  bassins, calcule les croisements spatiaux, evalue les criteres et ecrit les
  preuves;
- `hydromodpy.workflow.site_selection` assemble le run depuis le TOML, resout
  les donnees via les data managers et lance les phases spatiales;
- le rapport HTML est une vue de controle issue du manifest et des artefacts,
  pas une deuxieme source de verite.

La sequence attendue d'un run complet est:

```text
configuration -> donnees -> candidats -> produits DEM -> delimitation
-> annotations -> selection -> sorties -> manifest/rapport
```

## Profil `area_only`

### Intention

Selectionner des bassins selon une plage ou une cible de surface. Les autres
familles de criteres peuvent etre reportees, mais elles ne doivent pas piloter
la decision court terme.

### Modes d'entree acceptes

- `site_selection.input.mode = "dem_area_light"` pour generer des candidats
  depuis le DEM autour d'une surface cible;
- `site_selection.input.mode = "delineated_catchments"` pour rejouer un
  inventaire de bassins deja delimites, par exemple une fixture ou un catalogue
  fige.

### Configuration attendue

Pour un CSV de bassins deja delimites:

```toml
[site_selection.strategy]
principle = "criteria_crossing"
profile = "area_only"
primary_axes = ["area"]
observation_role = "report_only"
geology_role = "report_only"

[site_selection.criteria.area]
mode = "hard_reject"

[[site_selection.criteria.area.ranges]]
range_id = "target_area"
min_area_km2 = 75.0
max_area_km2 = 125.0
```

Pour le mode DEM leger:

```toml
[site_selection.input]
mode = "dem_area_light"

[site_selection.dem_area_light]
target_area_km2 = 100.0
min_area_km2 = 75.0
max_area_km2 = 125.0
n_basins = 10
max_candidates_before_delineation = 30
```

`dem_area_light` est classe en `effective_profile = "area_only"` meme si le TOML
ne declare pas explicitement `strategy.profile`.

### Criteres actifs

- critere de surface;
- filtrage spatial des bassins emboites ou trop recouvrants;
- echec de delimitation.

Les observations, la geologie, la piezometrie et les influences restent
optionnelles et non obligatoires dans ce profil.

### Exemples maintenus

- `examples/projects/17_site_selection_workflow/configs/calvados_dem_area_light_100km2_fast.toml`
- `examples/projects/17_site_selection_workflow/configs/manche_dem_area_light_100km2_fast.toml`
- `examples/projects/17_site_selection_workflow/configs/auvergne_rhone_alpes_area_only.toml`

`normandie_dem_area_light_100km2.toml` reste un cas theorique plus lourd. Il ne
doit pas etre utilise comme test rapide de non-regression.

## Profil `gauged_downstream_station`

### Intention

Selectionner des bassins jauges ou une station de debit fournit l'exutoire aval
candidat. La station est l'objet metier principal: elle permet de construire le
point candidat, de delimiter le bassin, puis de verifier que l'exutoire et la
station restent coherents.

### Mode d'entree accepte

- `site_selection.input.mode = "hydrometry"` pour charger les stations via les
  data managers, typiquement Hub'Eau;
- `site_selection.input.mode = "delineated_catchments"` reste accepte pour des
  catalogues figes ou des fixtures deja normalisees, mais ce n'est pas le
  chemin cible.

### Configuration attendue

```toml
[site_selection.input]
mode = "hydrometry"

[site_selection.strategy]
principle = "observation_led"
profile = "gauged_downstream_station"
primary_observation_type = "flow_station"
observation_source = "hubeau_hydrometrie"
candidate_mode = "station_outlets"

[site_selection.outlets]
candidate_mode = "station_outlets"
snap_strategy = "dem_accumulation"
snap_dist_m = 150
```

Le profil accepte aussi:

```toml
[site_selection.outlets]
snap_strategy = "bdtopage_then_dem"
reference_network_source = "bdtopage"
reference_network_max_distance_m = 100.0
```

BD Topage est alors un support technique de localisation de l'exutoire avant le
snap DEM local. Il ne devient pas une preuve que le bassin contient ce reseau.

### Criteres actifs

- distance station-exutoire;
- longueur de chronique si configuree;
- station dans le bassin ou a l'exutoire si configure;
- echec de delimitation;
- surface en rejet ou avertissement selon campagne;
- influence majeure si une couche d'influence est fournie et si le rejet est
  explicitement configure.

Exemple de blocage par barrage ou influence majeure:

```toml
[site_selection.criteria.influence]
mode = "hard_reject"
reject_major_dam_upstream = true

[[site_selection.criteria.influence.layers]]
name = "Barrages majeurs"
path = "data/influence/barrages.gpkg"
influence_type = "major_dam_upstream"
id_field = "id"
label_field = "name"
severity_field = "severity"
major_values = ["major"]
```

L'absence de couche d'influence ne doit pas rejeter un site par defaut. Le rejet
ne vient que d'une preuve explicite croisee avec le bassin.

### Doctrine `station_influence`

`station_influence` est le controle disponible a court terme pour exploiter les
metadonnees Hub'Eau hydrometriques. Sa doctrine est volontairement stricte:

- rejet dur seulement si `influence_generale_site` ou
  `influence_locale_station` indique explicitement une influence et si le mode
  du critere est `hard_reject`;
- absence de champ, champ vide ou statut inconnu: pas de rejet avec
  `unknown_policy = "neutral"`;
- commentaire contenant un mot-cle comme `barrage`, `retenue` ou `canal`:
  avertissement de revue seulement, jamais rejet dur;
- le controle ne remplace pas un inventaire spatial d'ouvrages. Quand un
  provider ROE ou une couche locale sera branche, ce sera un critere
  `influence` distinct.

### Exemples maintenus

- `examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_small_bdtopage.toml`
- `examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_small.toml`
- `examples/projects/17_site_selection_workflow/configs/auvergne_rhone_alpes_hydrometry_preview.toml`

Les variantes Corse et AURA completes sont utiles, mais elles ne doivent pas
etre les tests rapides de stabilisation car elles peuvent etre plus longues ou
dependre davantage des donnees disponibles.

## Sorties minimales attendues

Un run execute doit produire:

- `site_selection_manifest.json`;
- `selection_decisions.jsonl`;
- `criteria_components.jsonl`;
- `site_selection_decisions.csv`;
- `site_selection_decisions.jsonl`;
- `site_selection_evidence.jsonl` quand au moins une preuve normalisee existe;
- `selected_sites.csv`;
- `rejected_sites.csv`;
- `regional_lab_sites.csv`;
- `selected_outlets.geojson`;
- `rejected_outlets.geojson`;
- `selected_basins.geojson`;
- `rejected_basins.geojson`;
- `review/index.html` et `review/site_selection_map.png` quand
  `write_report_html = true`.

Les sorties GPKG et GeoParquet sont des sorties de production optionnelles. Les
tests unitaires doivent continuer a verifier qu'elles s'ecrivent quand les
dependances sont disponibles, mais elles ne sont pas obligatoires dans les
exemples rapides.

## Preuves et decisions

Le contrat d'audit court terme est:

- chaque critere produit des composants auditables dans
  `criteria_components.jsonl`;
- les composants et decisions finales sont convertis en
  `DecisionRecord` dans `site_selection_decisions.jsonl`;
- les preuves station, piezometrie, influence et geologie sont converties en
  `EvidenceRecord` dans `site_selection_evidence.jsonl`;
- les decisions peuvent porter un `evidence_ref` quand une preuve concrete
  existe;
- le manifest expose `strategy.effective_profile` pour classer le run meme si
  le TOML historique n'a pas encore un `strategy.profile` explicite.

## Hors perimetre immediat

Les points suivants sont importants, mais ne font pas partie de la stabilisation
court terme:

- provider ROE pour les obstacles;
- provider BNPE ou prelevements;
- classification BRGM fine et table lithologique generique;
- chargement ADES complet des piezometres;
- qualite eau Hub'Eau;
- intermittence ONDE;
- carte interactive;
- generation automatique hydrologiquement avancee par confluences, ordre de
  Strahler ou sous-bassins.

Ces sujets doivent etre ouverts comme chantiers separes apres stabilisation des
deux profils ci-dessus.

## Validation de fin de chantier

La stabilisation court terme est terminee quand:

1. les tests unitaires `tests/unit/site_selection` passent;
2. le lint cible `hydromodpy/spatial/site_selection` et
   `hydromodpy/workflow/site_selection.py` passe;
3. un petit exemple `area_only` tourne et produit un HTML de controle;
4. un petit exemple `gauged_downstream_station` tourne et produit un HTML de
   controle;
5. le manifest de ces deux exemples contient `strategy.effective_profile`;
6. les sorties de decisions et de preuves sont lisibles sans relancer le calcul.

Apres ces validations, la refonte structurelle `site_selection` doit etre
consideree comme arretee pour le court terme. Les travaux suivants doivent etre
planifies comme evolutions fonctionnelles separees.
