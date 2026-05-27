# Audit preparatoire - deploiement national sur bassins versants de tete

Date: 2026-05-12

Statut: note de reflexion preparatoire. Ce document ne decrit pas une recette
operationnelle stabilisee. Il sert a cadrer le chantier avant d'engager du
developpement ou une campagne de calcul massive.

Document associe: `docs/_dev_notes/legacy/site_selection_tool_implementation_plan.md`
detaille le plan d'implementation specifique pour l'outil independant de
selection de sites en amont des regional labs et testbeds.

## 1. Question posee

L'objectif est d'imaginer comment passer d'un petit banc d'essai regional, deja
present dans `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k`,
a un deploiement massif sur un grand nombre de bassins versants de tete a
l'echelle du territoire francais.

La question n'est pas seulement: "comment lancer beaucoup de simulations ?".
Le vrai chantier est plus large:

- definir proprement ce qu'est un bassin versant de tete exploitable par
  HydroModPy ;
- construire un inventaire national reproductible des sites candidats ;
- telecharger, versionner et qualifier les donnees d'entree ;
- generer des configurations de calcul sans copier-coller fragile ;
- lancer les calculs de maniere idempotente, resumable et auditable ;
- stocker les sorties dans une base exploitable pour analyse, comparaison,
  calibration, cartographie, apprentissage statistique ou diagnostic national.

La reponse courte: la base actuelle est deja assez riche pour un prototype
serieux. Il manque surtout une couche "industrialisation nationale": inventaire
des sites, qualite des donnees, preflight, planification, orchestration,
agregation nationale et taxonomie de diagnostics.

## 2. Positionnement recommande

Le chantier doit etre traite comme une chaine de production scientifique, pas
comme une collection de scripts.

La forme cible la plus robuste serait:

1. Un inventaire national versionne des sites candidats.
2. Un catalogue de donnees source, avec versions, emprises, dates, qualite et
   methode de telechargement.
3. Un plan de campagne declaratif, decrit par TOML/CSV/Parquet.
4. Un generateur generique de cas HydroModPy.
5. Un preflight qui rejette les sites non simulables avant le lancement.
6. Un orchestrateur de lots capable de reprendre, ignorer, relancer et expliquer
   les echecs.
7. Une base de resultats nationale interrogeable, fondee sur DuckDB/Parquet/Zarr.
8. Des rapports de synthese qui ne remplacent pas la base, mais en donnent des
   vues lisibles.

La decision structurante est de ne pas developper un "script France". Le code
doit rester generique:

- les specificites francaises doivent vivre dans des sources de donnees,
  mappings, recettes et catalogues ;
- les algorithmes doivent manipuler des contrats generaux: site, bassin,
  donnees source, recette, plan de run, resultat, diagnostic ;
- les exemples francais doivent etre des cas de configuration, pas des modules
  metier figes dans le code.

## 3. Ce que l'on a deja

### 3.1. Une base de campagne regionale

Le dossier actuel
`examples/projects/10_testbed_workflow/boussinesq/natural_geology_k` contient
deja les elements d'un mini-laboratoire regional:

- `natural_regional_lab_sites.csv`: catalogue de sites pilotes ;
- `natural_regional_lab.toml`: configuration de laboratoire regional ;
- `natural_10km2_mf6_bouss_testbed.toml`: testbed N1 actif ;
- `natural_100km2_mf6_bouss_testbed.toml`: niveau N2, aujourd'hui plutot
  preparatoire ;
- `natural_n3_mesh_sensitivity_mf6_bouss_testbed.toml`: niveau N3 pour la
  sensibilite au maillage ;
- `base_site_01_mf6_bouss_transient.toml`: configuration de base MF6/Boussinesq ;
- `compare_site_01_mf6_bouss.toml`: comparaison type MF6/Boussinesq ;
- `geology_K_dummy_demo.csv`: table demo pour la permeabilite geologique.

Ce dossier montre une intention claire:

- N1: petits bassins, typiquement autour de 10 km2 ;
- N2: bassins plus grands, typiquement autour de 100 km2 ;
- N3: variantes plus couteuses ou plus fines, par exemple sensibilite au
  maillage.

La campagne N1 actuelle a deja produit des sorties exploitables. Le rapport de
testbed indique 8 variantes, 5 reussites et 3 echecs. Les echecs sont
instructifs car ils montrent les futures fragilites a l'echelle nationale:

- collision de catalogue DuckDB sur un identifiant de run ;
- echec du solveur MF6 en regime initial stationnaire ;
- configuration de maillage exigeant une trace riviere absente.

Ces erreurs ne sont pas des details. A l'echelle nationale, elles deviendraient
des familles entieres d'echecs. Il faut donc les transformer en checks de
preflight et en diagnostics classes, pas seulement les corriger au coup par coup.

### 3.2. Une couche data deja bien pensee

Le package `hydromodpy.data` possede deja une architecture utilisable pour une
montee en charge:

- `DataManagersConfig` decrit les sources actives ;
- `DataPlanner` decide quels managers sont necessaires ;
- `DataLoadPlan` formalise le plan de chargement ;
- `DataManagersRuntimeLoader` execute les chargements ;
- `LoadResult`, `PointRecord` et `FieldRecord` donnent un contrat commun pour
  les donnees ponctuelles et mailles ;
- un catalogue DuckDB permet de suivre cache, emprises, metadonnees et
  reutilisation.

Les familles de donnees deja visibles dans l'architecture:

- MNT/DEM ;
- geologie ;
- hydrographie ;
- hydrometrie ;
- piezometrie ;
- intermittence ONDE ;
- qualite de l'eau ;
- variables climatiques/recharge via SIM2/EDR ;
- donnees oceaniques pour les cas littoraux.

Ce point est important: le deploiement national ne doit pas contourner cette
couche. Il doit l'etendre proprement.

### 3.3. Une construction geographique deja disponible

Le package `hydromodpy.spatial.geographic` sait deja construire un domaine a
partir de plusieurs modes:

- point exutoire ;
- polygone shapefile ;
- DEM ;
- entree texte ou mode synthetique.

La chaine geographique sait produire:

- produits de flow direction/accumulation ;
- bassin versant depuis point ou polygone ;
- supports de domaine ;
- clips DEM ;
- surface et metriques ;
- reseau hydrographique genere ;
- ordre de Strahler et liens de cours d'eau selon les options.

La notion de `HydrographicNetwork(role="generated")` est deja une bonne base
conceptuelle. Pour le chantier national, il faudra probablement distinguer:

- reseau de reference, par exemple BD TOPAGE ;
- reseau genere depuis DEM ;
- reseau hybride ou recale ;
- trace riviere utilisee pour contraindre le maillage ;
- trace riviere utilisee seulement pour diagnostic.

### 3.4. Une couche mesh pivot

`hydromodpy.spatial.mesh` contient `HydroMesh`, qui sert de contrat d'echange
entre generateurs, solveurs, sorties et outils tiers.

Points utiles pour le national:

- separation entre contrat de maillage et moteur de generation ;
- adaptateurs vers `meshio`, `flopy`, champs, Gmsh ;
- I/O VTU ;
- conventions utiles pour echanger entre MF6, Boussinesq et analyse.

La bonne direction est de garder `HydroMesh` comme pivot et de ne pas creer un
format parallele pour la campagne nationale.

### 3.5. Une comparaison solver deja industrialisable

`hydromodpy.analysis.comparison` a deja une logique de comparaison:

- materialisation de configurations filles ;
- lancement de simulations enfants via `hmp` ;
- extraction d'observables ;
- audit d'equivalence ;
- metriques ;
- diagnostics numeriques ;
- exports CSV/JSON/figures ;
- rapport web.

Les sorties actuelles sont riches:

- observables ;
- series natives ;
- metriques ;
- differences ;
- budgets ;
- fermeture numerique ;
- diagnostics Boussinesq/PETSc ;
- diagnostics obstacles ;
- execution summary ;
- rapport HTML.

Cela donne deja la bonne forme de sortie pour un site. Le travail national doit
surtout agreger ces sorties et les relier a des attributs de site.

### 3.6. Un testbed generique existe deja

`hydromodpy.analysis.testbed` est une brique tres importante. Elle sait:

- lire un catalogue de variantes CSV/JSONL ;
- filtrer des cas ;
- materialiser des configurations enfants ;
- lancer soit une simulation, soit une comparaison ;
- produire un plan, un CSV de cas, un CSV de metriques, un manifeste et un
  rapport Markdown.

La configuration supporte deja des dimensions utiles:

- `runner`: `simulation` ou `comparison` ;
- `subject`: par exemple `flow`, `mesh`, `transport` ;
- `execute`, `continue_on_error`, `resume`, `skip_existing_outputs` ;
- templates de chemins ;
- champs requis.

Ce testbed devrait rester le point d'entree principal pour la campagne. Il faut
l'enrichir, pas creer un nouveau lanceur specialise.

### 3.7. Un regional lab existe comme esquisse de surcouche

`hydromodpy.analysis.testbed.regional_lab_config` et
`regional_lab_adapter` montrent deja une idee de couche superieure:

- mapping des colonnes de catalogue ;
- filtres de selection ;
- regles de clustering ;
- recettes de lancement ;
- projection vers le provider testbed.

Cette brique semble etre le meilleur endroit pour evoluer vers une logique
"site inventory + recipes". Le nom "regional_lab" est peut-etre trop petit pour
un deploiement national, mais la structure conceptuelle est bonne.

### 3.8. Une base resultats existe deja

`hydromodpy.results.catalog` fournit une facade `SimulationCatalog` basee sur
DuckDB, Parquet et Zarr.

Schema deja utile:

- table `simulations`: identifiant, projet, solveur, statut, mesh, bbox, hash de
  config, chemin Zarr, duree, description, zone d'etude, exutoire ;
- tables `parameters`, `metrics`, `provenance`, `runs_environment` ;
- vues Parquet pour `timeseries`, `budgets`, `mass_balance` ;
- vues larges pour metriques et parametres ;
- chargement de datasets pour pipelines ML/DL avec champs Zarr paresseux.

Conclusion: la base technique pour la future base de donnees nationale existe
deja en partie. Il manque un niveau d'agregation multi-site et des tables
specifiques a l'inventaire national.

### 3.9. Un runner de workflow generique existe

`hydromodpy.workflow.runner.Pipeline` execute des `Step` avec:

- ordre sequentiel ;
- checkpoint ;
- ledger ;
- manifeste resolu ;
- reprise depuis etape ;
- erreurs structurees.

C'est une bonne fondation pour la partie "planifier, verifier, executer,
resumer". Le risque serait de recoder cette orchestration dans des scripts
exemple. Il vaut mieux en faire une sequence de steps generiques.

## 4. Ce qui manque principalement

### 4.1. Un inventaire national des bassins de tete

Il manque une brique qui produit un catalogue national de sites candidats.

Entree possible:

- BD TOPAGE ;
- DEM/RGE ALTI ;
- stations hydrometriques et piezometriques ;
- mailles SIM2 ;
- limites hydrographiques existantes ;
- zones d'exclusion anthropisees ou regulees.

Sortie minimale:

- `site_id` stable ;
- geometrie du bassin ;
- point exutoire ;
- surface ;
- perimetre ;
- altitude min/max/moyenne ;
- pente moyenne ;
- longueur de drain principal ;
- ordre de Strahler ;
- densite de drainage ;
- presence/absence de station hydrometrique proche ;
- presence/absence de piezometre proche ;
- couverture geologique dominante ;
- couverture hydrogeologique dominante si BDLISA utilisee ;
- indicateurs d'anthropisation ;
- statut de qualite ;
- raison d'inclusion/exclusion.

La sortie devrait etre stockee en GeoParquet ou Parquet + geometrie WKB/WKT,
et non uniquement en CSV. Le CSV reste utile pour inspection et pour testbed,
mais GeoParquet preserve mieux les geometries et les types.

### 4.2. Une definition explicite de "bassin de tete"

Le terme "bassin versant de tete" peut etre defini de plusieurs manieres. Avant
d'ecrire du code, il faut figer une definition operatoire.

Definitions possibles:

- par surface: bassin amont inferieur a un seuil, par exemple 1, 5, 10, 50 ou
  100 km2 ;
- par ordre hydrographique: ordre de Strahler 1 ou 2 ;
- par position reseau: absence de troncon amont dans le referentiel ;
- par distance a la source ;
- par absence de station/regulation majeure amont ;
- par typologie hydrogeologique ;
- par objectif numerique: taille compatible avec MF6/Boussinesq.

Recommandation: ne pas choisir une seule definition implicite. Il faut stocker
plusieurs criteres et creer des vues:

- `headwater_strict`: petits bassins, ordre 1, peu anthropises ;
- `headwater_instrumented`: bassins de tete avec station ou piezometre utile ;
- `headwater_modelable`: bassins techniquement simulables ;
- `headwater_reference`: sous-ensemble propre pour validation ;
- `headwater_exploratory`: ensemble large pour cartographie et apprentissage.

Cela evitera de jeter trop tot des sites utiles.

### 4.3. Une qualification des donnees d'entree

Chaque site devrait recevoir des flags de donnees:

- DEM disponible et coherent ;
- exutoire compatible avec accumulation ;
- reseau reference proche du reseau genere ;
- geologie disponible ;
- mapping K/Sy/Ss disponible ;
- recharge disponible sur la periode cible ;
- stations hydrometriques disponibles ;
- piezometres disponibles ;
- donnees ONDE disponibles ;
- donnees de qualite ou temperature disponibles ;
- obstacles/prelevements connus ;
- risque de bassin tres anthropise ;
- risque karstique ou complexe hydrogeologique ;
- risque littoral ou boundary oceanique ;
- risque numerique estime.

Sans cette qualification, une campagne nationale produira beaucoup d'echecs peu
interpretables.

### 4.4. Un preflight avant calcul

Les echecs N1 actuels montrent qu'il faut une etape de preflight stricte.

Checks minimaux:

- config TOML resolue et valide ;
- chemins d'entree existants ;
- `site_id`, `project`, `run_id` et chemins de sortie uniques ;
- absence de collision dans le catalogue resultats ;
- bassin non vide ;
- DEM couvre tout le bassin ;
- rasterisation hydrographique possible ;
- si `mesh_catchment.constraints_mode` exige une riviere, trace disponible ;
- nombre de cellules estime raisonnable ;
- conditions initiales stationnaires plausibles ;
- recharge et pas de temps coherents ;
- limites hydrauliques coherentes avec top/bottom ;
- solver compatible avec dimensions et options ;
- estimation grossiere du temps de calcul.

Le preflight doit pouvoir produire un tableau:

- `site_id` ;
- `recipe_id` ;
- `preflight_status`: pass, warn, fail ;
- `blocking_reason` ;
- `warnings` ;
- `estimated_cost` ;
- `recommended_action`.

### 4.5. Une taxonomie des echecs

A l'echelle nationale, un message Python brut ne suffit pas. Il faut classer les
echecs.

Exemples de classes:

- `DATA_MISSING` ;
- `DATA_EMPTY_AFTER_CLIP` ;
- `DATA_CRS_ERROR` ;
- `DOMAIN_DELINEATION_FAILED` ;
- `RIVER_TRACE_MISSING` ;
- `MESH_FAILED` ;
- `CONFIG_INVALID` ;
- `CATALOG_COLLISION` ;
- `MF6_STEADY_INIT_FAILED` ;
- `MF6_TRANSIENT_FAILED` ;
- `BOUSSINESQ_SOLVER_FAILED` ;
- `NUMERICAL_DIVERGENCE` ;
- `MASS_BALANCE_BAD` ;
- `POSTPROCESS_FAILED` ;
- `REPORT_FAILED`.

Cette taxonomie doit etre stockee dans la base de resultats, pas seulement dans
les logs.

### 4.6. Un moteur de recettes plus explicite

Les recettes actuelles sont portees par templates TOML et champs de catalogue.
C'est une bonne base, mais il faut clarifier le contrat:

- une recette de site ;
- une recette de donnees ;
- une recette de maillage ;
- une recette solver ;
- une recette comparaison ;
- une recette postprocess.

Le but est de pouvoir dire:

- "applique la recette N1_10km2_mf6_bouss a tous les sites headwater_modelable" ;
- "applique la recette N2_100km2_mf6_only aux bassins plus grands" ;
- "applique la recette N3_mesh_sensitivity a un echantillon stratifie" ;
- "applique la recette validation_hydrometry seulement aux bassins instrumentes".

### 4.7. Une base nationale resultats + donnees

Il ne faut pas seulement produire des HTML par site. Il faut produire une base
interrogeable.

Tables recommandees:

- `sites`: identite, geometrie, exutoire, surface, typologie ;
- `site_hydrography`: ordre, longueur, densite, drainage ;
- `site_topography`: altitudes, pentes, hypsometrie ;
- `site_geology`: formations, fractions, mapping hydraulique ;
- `site_hydrogeology`: BDLISA, aquiferes, typologie ;
- `site_climate`: recharge, pluie, ETP, temperature, saisonnalite ;
- `site_observations`: stations et chroniques disponibles ;
- `site_quality_flags`: flags de qualification ;
- `recipes`: versions des recettes appliquees ;
- `run_plan`: cases planifies ;
- `runs`: statuts et liens vers catalogues locaux ;
- `run_failures`: taxonomie d'echecs ;
- `metrics`: metriques scalaires ;
- `time_series_index`: index des series ;
- `field_index`: index des champs Zarr ;
- `provenance`: versions donnees/code/config.

La base peut rester DuckDB/Parquet/Zarr, ce qui est coherent avec ce qui existe
deja.

## 5. Donnees a telecharger ou referencer

Cette section liste les jeux de donnees probablement necessaires. Les liens sont
des points d'entree officiels ou institutionnels identifies le 2026-05-12.

| Theme | Source probable | Role | Etat HydroModPy | Methode d'acquisition possible | Manque principal |
| --- | --- | --- | --- | --- | --- |
| Relief / MNT | IGN RGE ALTI ou BD ALTI, https://geoservices.ign.fr/rgealti | Delimitation, pentes, top/bottom, maillage | Manager DEM avec source `ign_bdalti` et `custom` | Telechargement Geoplateforme/IGN par departement ou tuile, cache local, clipping par bassin | Strategie nationale de tuilage, version freeze, choix 1 m/5 m/25 m selon cout |
| Hydrographie reference | BD TOPAGE, Sandre/OFB/IGN, https://www.sandre.eaufrance.fr/v2/news/diffusion-de-la-1ere-version-de-la-bd-topage-metropole | Reseau reference, sources, troncons, noeuds, bassins | Manager hydrography avec `bdtopage`, `euhydro`, `osm`, `custom` | Telechargement Sandre en Shapefile/GeoJSON/GeoPackage ou WFS/WMS | Pretraitement national: routage, headwaters, matching DEM, attributs Strahler |
| Geologie | BRGM InfoTerre, cartes 1/1 000 000 et 1/50 000 harmonisees, https://infoterre.brgm.fr/page/telechargement-cartes-geologiques | Mapping lithologie -> K/Sy/Ss, typologie | Manager geology avec `brgm_1m`, `brgm_50k`, `custom` | Telechargement direct InfoTerre/BRGM ou data.gouv par departement | Table scientifique de proprietes hydraulique, incertitudes, regroupements lithologiques |
| Hydrogeologie | BDLISA, BRGM/Sandre, https://www.brgm.fr/en/reference-completed-project/bdlisa-french-hydrogeological-database | Systemes aquiferes, limites hydrogeologiques, classification | Pas de manager dedie identifie | Telechargement/flux via Sandre/BRGM, puis usage comme custom vector | Manager BDLISA ou support generic hydrogeology, mapping vers couches modele |
| Recharge / meteo | SIM2/SAFRAN-ISBA via GeoSAS EDR, https://geosas.fr/edr-viewer/ et https://api.geosas.fr/edr/apidocs/ | Recharge, pluie, ETP, temperature, forcing temporel | Source `sim2` via client EDR | API EDR `cube` ou `position`, formats CSV/NetCDF/Parquet selon emprise | Plan national de telechargement par regions/periodes, reprise, cache et controles |
| Hydrometrie | Hub'Eau Hydrometrie, https://hubeau.eaufrance.fr/page/api-hydrometrie | Validation debit, selection bassins instrumentes | Manager hydrometry avec source `hubeau` | API REST JSON/GeoJSON/CSV, filtres station, bbox, periode | Attribution station-bassin, qualite chronique, periode commune |
| Piezometrie | Hub'Eau Piezometrie/ADES, https://hubeau.eaufrance.fr/page/api-piezometrie | Validation nappe, contraintes niveau | Manager piezometry avec source `hubeau` | API REST, stations et chroniques | Selection piezometres representatifs, reference altimetrique, profondeur |
| Intermittence | Hub'Eau Ecoulement des cours d'eau / ONDE, https://hubeau.eaufrance.fr/page/api-ecoulement | Validation assec/intermittence, regimes de tete | Manager intermittency avec source `hubeau` | API REST ONDE | Traduction observations ponctuelles -> metrique modele |
| Qualite eau surface | Hub'Eau Qualite rivieres, https://www.data.gouv.fr/fr/dataservices/hubeau-qualite-des-cours-deau/ | Covariables, validation indirecte, contexte | Manager qualite mentionne | API REST JSON/CSV/GeoJSON | Pas prioritaire pour premier deploiement hydraulique |
| Qualite nappes | Hub'Eau Qualite nappes, https://www.data.gouv.fr/fr/dataservices/hubeau-qualite-des-nappes-deau-souterraine/ | Indices hydrogeologiques, nitrates, contexte | A verifier dans managers qualite | API REST | Usage scientifique a cadrer |
| Occupation du sol | Theia OSO, https://www.theia-land.fr/blog/product/carte-doccupation-des-sols-de-la-france-metropolitaine/ | Recharge, ET, anthropisation, covariables | Pas de manager dedie identifie | Catalogue Theia, raster/vector, souvent compte Theia | Manager landcover generique ou ingestion custom |
| Sols | GIS Sol / RRP / DoneSol, https://www.gissol.fr/donnees/carte-sur-le-geoportail-4789 | Stockage, infiltration, pedotransfert | Pas de manager dedie identifie | Webservices Geoportail/GIS Sol, acces selon couche | Acces donnees detaillees et mapping hydro-pedologique |
| Prelevements | BNPE via Hub'Eau, https://www.data.gouv.fr/dataservices/hubeau-prelevements-en-eau | Exclusion/flag bassins fortement exploites | Pas de manager dedie identifie | API REST Hub'Eau | Attribution spatiale/temporelle, usages, incertitudes |
| Obstacles | ROE/OFB/Sandre, https://ofb.gouv.fr/elements-hydromorphologiques-cours-eau-methodes-surveillance-etat-ecologique | Flag regulation, barrages, seuils | Pas de manager dedie identifie | Sandre/atlas/catalogue, services web selon disponibilite | Manager anthropogenic/obstacles ou ingestion custom |
| Administration / regions | IGN Admin Express, INSEE, data.gouv | Decoupage, reporting, stratification | Hors coeur modele | Telechargement officiel | A garder comme covariable, pas comme dependance forte |

Priorite pour un premier vrai chantier:

1. DEM RGE ALTI/BD ALTI.
2. BD TOPAGE.
3. BRGM geologie 1M ou 50k.
4. SIM2/SAFRAN-ISBA.
5. Hub'Eau hydrometrie, piezometrie, ONDE.
6. BDLISA.
7. Prelevements/obstacles pour exclure ou flagger les sites.
8. Occupation du sol et sols pour enrichir les covariables.

## 6. Forme possible du dispositif

### 6.1. Niveau N0 - inventaire et donnees

N0 ne lance aucune simulation. Il construit la base nationale des sites et des
donnees disponibles.

Sorties:

- `national_sites.geoparquet` ;
- `national_sites.csv` pour inspection rapide ;
- `source_data_manifest.parquet` ;
- `source_data_manifest.md` ;
- `site_quality_flags.parquet` ;
- `headwater_selection_report.md`.

Objectif: savoir combien de sites sont candidats, combien sont simulables, et
pourquoi certains sont rejetes.

### 6.2. Niveau N1 - campagne robuste basse resolution

N1 vise beaucoup de sites a cout raisonnable.

Caracteristiques:

- bassins petits ;
- maillage prudent ;
- geologie simplifiee mais non factice ;
- recharge SIM2 ;
- comparaison MF6/Boussinesq sur un sous-ensemble si le cout est acceptable ;
- simulation simple sur l'ensemble.

Objectif: produire une premiere carte nationale des comportements et des echecs.

### 6.3. Niveau N2 - campagne instrumentee

N2 cible moins de sites, mais mieux observes.

Caracteristiques:

- selection par disponibilite hydrometrie/piezometrie/ONDE ;
- periodes communes ;
- validations plus strictes ;
- eventuellement calibration ou scenarios.

Objectif: evaluer la validite physique et les biais selon regions/geologies.

### 6.4. Niveau N3 - sensibilites et incertitudes

N3 cible un echantillon stratifie:

- sensibilite maillage ;
- sensibilite K/Sy/Ss ;
- sensibilite recharge ;
- sensibilite reseau hydrographique ;
- sensibilite conditions initiales ;
- comparaison solver approfondie.

Objectif: quantifier ce qui controle les resultats, pas couvrir tout le pays.

### 6.5. Niveau N4 - exploitation nationale

N4 exploite la base produite:

- cartes de metriques ;
- clustering de bassins ;
- detection de familles d'echecs ;
- meta-modeles ;
- priorisation de sites pour runs fins ;
- syntheses par hydro-ecoregion, geologie, climat ou agence de l'eau ;
- comparaison de scenarios recharge/climat.

## 7. Analyse des codes existants et manquants

### 7.1. Couche configuration

Existant:

- TOML riche pour simulation et comparaison ;
- testbed declaratif ;
- regional lab avec mapping de colonnes, filtres et recettes ;
- materialisation de configurations filles.

Manquant:

- bibliotheque de recettes versionnees ;
- validation cross-file plus stricte ;
- identifiants de run stables et uniques a grande echelle ;
- overlay TOML generique pour eviter les duplications ;
- schema explicite de catalogue national.

Developpement recommande:

- enrichir `analysis.testbed` plutot que creer un nouveau lanceur ;
- ajouter une couche `recipes` generique ;
- faire des recettes des donnees, pas du code ;
- ajouter une commande dry-run qui produit uniquement le plan resolu.

### 7.2. Couche donnees

Existant:

- managers pour DEM, hydrographie, geologie, hydrometrie, piezometrie,
  intermittence, qualite, recharge/SIM2 ;
- catalogage DuckDB ;
- cache ;
- records normalises.

Manquant:

- manager BDLISA/hydrogeology ;
- manager landcover ;
- manager soil ;
- manager anthropogenic pressures, obstacles, prelevements ;
- manifest national des sources avec versions et checksums ;
- strategie de telechargement multi-emprises, multi-periodes, resumable ;
- tests fake-provider pour eviter de tester contre les APIs en direct.

Developpement recommande:

- ajouter les nouvelles sources comme managers generiques ;
- eviter des fonctions `download_france_*` codees en dur ;
- decrire chaque source par un `DatasetDescriptor` ;
- garder `custom` comme voie de secours pour charger des donnees deja
  telechargees.

### 7.3. Couche inventaire sites

Existant:

- `natural_regional_lab_sites.csv` manuel ;
- regional lab adapter ;
- testbed provider.

Manquant:

- constructeur automatique de sites candidats ;
- definition multi-criteres des bassins de tete ;
- stratification nationale ;
- matching reseau reference / reseau DEM ;
- generation d'exutoires robustes ;
- exports GeoParquet ;
- rapport qualite inventaire.

Developpement recommande:

- creer une brique generique, par exemple `hydromodpy.analysis.site_inventory`
  ou `hydromodpy.analysis.regional_inventory` ;
- lui faire produire un catalogue, pas lancer de simulations ;
- exposer des strategies plug-in: `from_bdtopage`, `from_dem`,
  `from_observation_stations`, `from_custom_polygons` ;
- stocker toutes les decisions de selection dans des colonnes.

### 7.4. Couche domaine et geographie

Existant:

- delimitation depuis exutoire/polygone/DEM ;
- supports de domaine ;
- reseau genere ;
- metriques geographiques.

Manquant:

- reconciliation nationale BD TOPAGE vs DEM ;
- snapping robuste des exutoires ;
- classement des deltas entre bassin reference et bassin genere ;
- cache de produits hydrologiques par tuile/region ;
- checks preflight autour de `river_trace`.

Developpement recommande:

- ajouter des fonctions de reconciliation generiques ;
- exposer les ecarts comme metriques, pas les masquer ;
- rendre l'absence de trace riviere un diagnostic preflight avant le maillage.

### 7.5. Couche proprietes hydrogeologiques

Existant:

- ingestion geologie BRGM ;
- table demo `geology_K_dummy_demo.csv` ;
- rasterisation/champs geologiques.

Manquant:

- mapping scientifique lithologie -> K/Sy/Ss ;
- gestion incertitudes et plages de valeurs ;
- prise en compte BDLISA ;
- epaisseur utile/aquifere ;
- regles karst, socle, sedimentaire, volcanique ;
- provenance des parametres.

Developpement recommande:

- ne pas coder les valeurs dans les scripts ;
- creer des tables de parametrisation versionnees ;
- permettre plusieurs mappings: `conservative`, `literature_median`,
  `calibrated_regional`, `scenario_lowK`, `scenario_highK` ;
- stocker la fraction de bassin par classe geologique et pas seulement une
  valeur raster finale.

### 7.6. Couche maillage

Existant:

- `HydroMesh` ;
- adaptateurs ;
- options de contraintes ;
- comparaison de sensibilite maillage esquissable via N3.

Manquant:

- estimation de cout avant generation ;
- strategie automatique de resolution selon surface/pente/reseau ;
- fallback si contraintes riviere impossibles ;
- metriques de qualite maillage centralisees ;
- choix coherent MF6/Boussinesq.

Developpement recommande:

- declarer des profils de maillage generiques: `coarse`, `standard`,
  `river_refined`, `sensitivity_fine` ;
- faire du profil un parametre de recette ;
- enregistrer les metriques de maillage dans la base.

### 7.7. Couche solveurs

Existant:

- MF6 ;
- Boussinesq/PETSc ;
- comparaisons MF6/Boussinesq ;
- diagnostics numeriques de plus en plus riches.

Manquant:

- heuristiques de conditions initiales robustes pour lots massifs ;
- classification d'echecs solveur ;
- parametres solver adaptatifs par famille de site ;
- relance automatique avec fallback moins ambitieux ;
- estimation pre-run du risque numerique.

Developpement recommande:

- ne pas multiplier les templates solver ;
- definir des profils solver generiques ;
- permettre des fallbacks controles:
  `steady_init_failed -> alternative_initial_head -> transient_warmup` ;
- journaliser chaque fallback.

### 7.8. Couche comparaison et postprocess

Existant:

- output pipeline riche ;
- audit ;
- web report ;
- metriques ;
- budgets ;
- fermeture numerique ;
- diagnostics reseau actif.

Manquant:

- agregateur multi-site ;
- vues nationales ;
- resume par famille geologique/climatique ;
- comparaison distributionnelle ;
- tri automatique des sites a inspecter ;
- API de lecture stable pour downstream notebooks.

Developpement recommande:

- garder les rapports par site ;
- ajouter un collecteur national qui lit manifests et catalogues locaux ;
- produire des tables analytiques, pas seulement des figures.

### 7.9. Couche orchestration

Existant:

- `Pipeline` generique ;
- testbed avec resume/skip/continue ;
- manifests.

Manquant:

- execution parallele controlee ;
- adaptateur scheduler local/HPC/SLURM eventuel ;
- verrouillage de sorties ;
- gestion collisions catalogues ;
- retries par classe d'erreur ;
- tableau d'avancement.

Developpement recommande:

- commencer par orchestration locale robuste ;
- isoler l'interface scheduler dans une abstraction minimale ;
- ne pas dependendre d'un cluster dans le coeur du code ;
- rendre chaque case idempotente.

### 7.10. Couche base de donnees nationale

Existant:

- `SimulationCatalog` ;
- DuckDB/Parquet/Zarr ;
- tables metriques, parametres, provenance, environnement.

Manquant:

- schema multi-sites national ;
- index de sites ;
- index de recettes ;
- lien fort site -> donnees source -> run -> metriques ;
- table de qualite ;
- table d'echecs ;
- ingestion automatique des bundles testbed/comparison.

Developpement recommande:

- etendre la logique de catalogage existante ;
- eviter une nouvelle base parallele ;
- utiliser DuckDB pour requetes analytiques ;
- utiliser Parquet pour tables volumineuses ;
- utiliser Zarr pour champs spatio-temporels.

## 8. Comment minimiser les codes a faire

### 8.1. Regle generale

Chaque nouveau besoin doit d'abord etre formule en configuration ou en donnee.
On n'ecrit du code que si:

- une transformation est reutilisable ;
- une validation est generale ;
- un contrat de donnees est necessaire ;
- une orchestration doit etre fiable ;
- un calcul ne peut pas etre exprime declarativement.

Cela donne l'ordre de preference suivant:

1. Modifier un catalogue CSV/Parquet.
2. Modifier une recette TOML.
3. Ajouter une table de mapping.
4. Ajouter un validateur generique.
5. Ajouter un manager de donnees generique.
6. Ajouter une nouvelle commande ou un nouveau module.
7. Ajouter un script exemple seulement pour demonstrer.

### 8.2. Ce qui peut rester en donnees/configuration

Peuvent rester hors code:

- liste des sites ;
- seuils de selection ;
- profils N1/N2/N3 ;
- chemins des donnees ;
- choix des sources ;
- valeurs K/Sy/Ss ;
- plages d'incertitude ;
- profils de maillage ;
- profils solver ;
- filtres de stations ;
- periodes de simulation ;
- regroupements geologiques ;
- familles climatiques ;
- echantillons de sensibilite.

### 8.3. Ce qui doit devenir du code generique

Devrait etre code:

- generation d'inventaire depuis sources geographiques ;
- snapping exutoire ;
- reconciliation reseau reference/DEM ;
- preflight ;
- manifest de donnees ;
- validation de catalogues ;
- materialisation de recettes ;
- execution idempotente ;
- collecte de resultats ;
- classification d'echecs ;
- agregation nationale ;
- tests.

### 8.4. Contrats de donnees a introduire

Pour eviter les scripts fragiles, il faudrait definir quelques contrats simples:

`SiteCandidate`

- `site_id` ;
- `geometry` ;
- `outlet_x`, `outlet_y`, `crs` ;
- `area_km2` ;
- `selection_flags` ;
- `source_refs`.

`SiteCatalogRecord`

- extension de `SiteCandidate` avec attributs topographiques,
  hydrographiques, geologiques, climatiques et observationnels.

`DatasetDescriptor`

- `dataset_id` ;
- `source` ;
- `version` ;
- `license` ;
- `url` ;
- `coverage` ;
- `format` ;
- `checksum` ;
- `local_path`.

`ModelRecipe`

- `recipe_id` ;
- `domain_profile` ;
- `data_profile` ;
- `mesh_profile` ;
- `solver_profile` ;
- `postprocess_profile`.

`RunPlanCase`

- `case_id` ;
- `site_id` ;
- `recipe_id` ;
- `config_path` ;
- `output_path` ;
- `expected_cost` ;
- `preflight_status`.

`QAFlag`

- `flag_id` ;
- `severity` ;
- `message` ;
- `evidence` ;
- `suggested_action`.

Ces contrats peuvent etre des dataclasses/Pydantic models selon les conventions
du projet. L'important est qu'ils soient serialisables.

### 8.5. Architecture generique proposee

Proposition minimale, a discuter:

```text
hydromodpy/
  analysis/
    site_inventory/
      config.py
      builder.py
      selectors.py
      stratification.py
      quality.py
      exports.py
    testbed/
      preflight.py
      recipes.py
      scheduler.py
      failure_taxonomy.py
      national_collect.py
  data/
    dataset_manifest.py
    variables/
      hydrogeology/
      landcover/
      soil/
      anthropogenic/
```

Le point cle: `site_inventory` ne doit pas etre "France only". Les sources
francaises sont des implementations, pas le concept.

Alternative encore plus prudente:

- commencer dans `analysis/testbed` avec `preflight.py`, `recipes.py` et
  `collect.py` ;
- ne creer `site_inventory` qu'au moment ou l'inventaire devient assez autonome.

### 8.6. Anti-patterns a eviter

- Un script unique `run_france.py` qui telecharge, genere, lance et analyse tout.
- Des chemins absolus codes en dur.
- Des seuils de selection caches dans Python.
- Des identifiants de run comme `run_0001` reutilises dans plusieurs projets.
- Des mappings geologiques dans du code procedural.
- Des notebooks comme seule source de verite.
- Des rapports HTML non relies a une base requetable.
- Des appels API non caches.
- Des tests qui dependent d'APIs externes vivantes.
- Des exceptions libres non classees.

## 9. Base de donnees produite: usages possibles

La base nationale pourrait devenir un actif scientifique central.

### 9.1. Diagnostic national

Questions possibles:

- quels bassins de tete sont modelables avec les donnees actuelles ?
- quelles regions echouent le plus souvent et pourquoi ?
- quels types geologiques produisent les plus fortes differences MF6/Boussinesq ?
- quelle proportion de sites presente une fermeture numerique satisfaisante ?
- quelles familles demandent un maillage plus fin ?

### 9.2. Selection de sites de reference

La base permettrait de choisir:

- sites tres propres pour validation ;
- sites instrumentes ;
- sites representatifs de familles geologiques ;
- sites extremes ;
- sites ou MF6 et Boussinesq divergent ;
- sites ou l'incertitude donnees domine.

### 9.3. Apprentissage statistique

La base pourrait alimenter:

- clustering de bassins ;
- modeles de prediction de cout de calcul ;
- modeles de prediction d'echec solver ;
- meta-modeles de reponse hydrologique ;
- emulation de resultats fins depuis runs grossiers ;
- selection active de nouveaux sites a simuler.

### 9.4. Calibration et validation

En croisant les runs avec Hub'Eau et ONDE:

- validation debit ;
- validation niveau piezometrique ;
- validation presence/absence d'ecoulement ;
- selection de periodes humides/seches ;
- analyse par saison.

### 9.5. Appui aux decisions de developpement

La base aiderait aussi a prioriser le code:

- si beaucoup d'echecs viennent du snapping exutoire, travailler la geographie ;
- si beaucoup d'echecs viennent de MF6 steady init, travailler l'initialisation ;
- si les differences sont liees au maillage, travailler les profils mesh ;
- si les sites sans BDLISA sont mal parametrises, prioriser hydrogeologie.

## 10. Roadmap proposee

### Phase 0 - cadrage scientifique

Objectifs:

- figer les definitions de bassins de tete ;
- choisir les seuils N1/N2/N3 ;
- choisir les sources officielles ;
- definir les criteres d'exclusion ;
- definir les premiers mappings geologie -> proprietes ;
- fixer les periodes temporelles.

Livrable:

- document de specification scientifique court ;
- table de decisions ;
- premier schema de catalogue site.

### Phase 1 - inventaire national sec

Objectifs:

- construire l'inventaire sans simulation ;
- telecharger ou pointer les donnees minimales ;
- produire flags de qualite ;
- produire statistiques nationales.

Livrable:

- GeoParquet national ;
- rapport d'inventaire ;
- manifest sources.

### Phase 2 - preflight et recettes

Objectifs:

- rendre les recettes N1/N2/N3 explicites ;
- ajouter preflight ;
- resoudre les collisions de run/catalogue ;
- tester sur 10 a 20 sites.

Livrable:

- plan de campagne sec ;
- rapport preflight ;
- zero lancement inutile sur sites non simulables.

### Phase 3 - pilote 50-100 sites

Objectifs:

- valider orchestration ;
- mesurer couts ;
- classifier echecs ;
- ajuster recettes ;
- confirmer stockage resultats.

Livrable:

- base pilote ;
- rapport de familles d'echecs ;
- recommandations N1.

### Phase 4 - campagne N1 nationale

Objectifs:

- lancer la recette robuste sur beaucoup de sites ;
- collecter les resultats ;
- produire cartes et distributions ;
- separer echecs donnees, geographie, mesh, solveur, postprocess.

Livrable:

- base nationale N1 ;
- rapport national ;
- liste priorisee de corrections.

### Phase 5 - campagnes N2/N3 ciblees

Objectifs:

- validation sur sites instrumentes ;
- sensibilites ;
- calibration/uncertainty ;
- comparaison solver plus fine.

Livrable:

- base enrichie ;
- jeux de sites de reference ;
- recommandations scientifiques.

## 11. Premier perimetre minimal realiste

Pour eviter de tout ouvrir a la fois, le premier perimetre pourrait etre:

- France metropolitaine seulement ;
- bassins entre 5 et 20 km2 ;
- BD TOPAGE + RGE ALTI/BD ALTI ;
- geologie BRGM 1M ou 50k selon disponibilite ;
- recharge SIM2 quotidienne ;
- pas de calibration ;
- exclusion/flag des sites avec obstacles/prelevements majeurs si donnees
  faciles a croiser ;
- simulation Boussinesq sur tous les sites preflight OK ;
- MF6/Boussinesq seulement sur un echantillon ;
- collecte DuckDB/Parquet/Zarr ;
- rapport national simple.

Ce perimetre donnerait rapidement une base exploitable sans attendre une
parametrisation hydrogeologique parfaite.

## 12. Risques principaux

### Risque scientifique

Le mapping geologie -> proprietes hydrauliques est probablement le plus gros
risque scientifique. Une campagne nationale peut donner une impression de
precision si elle produit de belles cartes, alors que les proprietes sont peu
contraintes.

Mitigation:

- stocker les incertitudes ;
- produire plusieurs scenarios ;
- separer resultats "structurels" et resultats calibres ;
- ne pas presenter une valeur unique comme verite.

### Risque donnees

Les sources ont des resolutions, dates, projections et qualites differentes.

Mitigation:

- manifest versionne ;
- checksums ;
- emprise et date par source ;
- flags de qualite ;
- tests de clipping et CRS.

### Risque numerique

Les solveurs peuvent echouer sur des configurations rares mais nombreuses a
l'echelle nationale.

Mitigation:

- preflight ;
- fallbacks ;
- taxonomie ;
- profils solver ;
- echantillon pilote avant production.

### Risque logiciel

Le chantier peut degenerer en scripts specialises.

Mitigation:

- developper dans les modules generiques ;
- garder les cas France dans des configs ;
- ajouter tests a chaque extension ;
- imposer un contrat de sortie stable.

### Risque cout

Le nombre de sites et le cout MF6 peuvent exploser.

Mitigation:

- commencer par Boussinesq ou par profils grossiers ;
- echantillonner MF6 ;
- estimer cout avant run ;
- stocker temps et ressources ;
- utiliser N3 pour sensibilite, pas pour couverture nationale.

## 13. Definition de fini pour le chantier preparatoire

Le chantier est pret a entrer en developpement quand on a:

- une definition versionnee des bassins de tete ;
- une liste de sources et licences ;
- un schema de catalogue site ;
- une premiere table de mapping geologique ;
- une decision sur DEM et resolution ;
- une decision sur periode SIM2 ;
- une strategie de stockage ;
- une taxonomie d'echecs ;
- un prototype preflight ;
- un pilote manuel sur quelques sites representatifs.

Il ne faut pas attendre que tout soit parfait pour lancer un pilote. En revanche,
il faut eviter de lancer une production nationale avant que les identifiants,
manifestes, preflight et resultats soient stabilises.

## 14. Conclusion operationnelle

HydroModPy dispose deja de plusieurs briques structurantes:

- data managers ;
- construction geographique ;
- maillage pivot ;
- comparaison MF6/Boussinesq ;
- testbed declaratif ;
- regional lab ;
- catalogue resultats ;
- workflow runner.

Le manque n'est pas un solveur supplementaire. Le manque principal est une
couche de production scientifique nationale:

- inventaire ;
- donnees ;
- preflight ;
- recettes ;
- orchestration ;
- taxonomie ;
- agregation ;
- exploitation.

Le meilleur chemin est incremental:

1. produire un inventaire national sans simulation ;
2. rendre les recettes et preflight robustes ;
3. lancer un pilote limite ;
4. collecter dans une base nationale ;
5. seulement ensuite etendre la couverture.

La generique du code doit etre un critere de validation a chaque etape. Si une
fonction ou un module contient "France" dans sa logique interne, il faut se
demander si cette specificite ne devrait pas etre une configuration, une source
de donnees ou une table de mapping.
