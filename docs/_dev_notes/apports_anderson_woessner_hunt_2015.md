# Apports d'*Applied Groundwater Modeling* (Anderson, Woessner & Hunt, 2e ed., 2015) pour HydroModPy

Analyse croisee des 12 chapitres du livre de reference contre l'etat reel de HydroModPy
(branche `dev-lakeres_refact`). Objectif : identifier ce que le code embarque deja bien,
les manques que le livre traite comme essentiels, et les changements a fort levier pour
l'approche, la structure et la maniere de developper.

Chaque affirmation sur le code a ete verifiee dans le repo (fichiers cites reels).
Le livre vise surtout les modeles regionaux multi-aquiferes : la section
**Garde-fous** liste ce qu'il ne faut PAS importer tel quel a l'echelle bassin-versant / GW peu profond.

---

## Verdict en une phrase

Le **milieu** du workflow canonique (design, discretisation, solve, calibration) est deja
d'un tres bon niveau ; les manques systematiques sont aux **deux bouts** : a l'entree
(purpose, bilan hydrique conceptuel, conditions initiales) et a la sortie (forecast,
incertitude, rapport defendable). Le fil conducteur qui relie presque tous les bugs Cheze
documentes (fuite SFR, runoff non extrait, domaine inonde, K colle au plancher 1e-5) est
**le bilan hydrique traite comme un objet comptable de premier plan**, que le livre pose
comme controle permanent de routine.

---

## Ce que HydroModPy fait deja bien (a ne pas casser)

| Point | Base livre | Preuve code |
|---|---|---|
| Grille MF6 = **Voronoi/PEBI dual DISV**, orthogonalite CVFD par construction (conductance 2 points exacte, sans XT3D). C'est exactement la bonne facon d'obtenir la liberte geometrique FE avec une conductance FD-simple. | Ch3 3.5.3 / Ch5 5.1.2.2 | `SolverMesh` seam, `SolverSGridConfig.grid_dual` |
| Sources/puits complets et corrects : LAK (bed leakance = terme K'z/b' du livre), SFR limitant la fuite a l'eau captee, MVR (retour DRN in-BV), HFB voile, WEIR. On pilote la nappe par un **flux** de recharge et on resout l'altitude, plutot que d'imposer une charge : traitement recharge-controlled correct qui garde la charge sensible a K/Sy. | Ch4 4.3.3/Box 4.6, Ch6 6.4-6.6 | `builders/lake.py`, `builders/sfr.py` |
| Stack de reproductibilite (`hydromodpy.lock` + catalogue DuckDB avec identite name/if_exists/versioning + Zarr/Parquet/GeoParquet auto-descriptifs) : implemente le contrat de replication de l'archive, plus fort que le journal papier Table 11.1 du livre. | Ch1 step 8, Ch3 3.7.1, Ch11 11.1/11.3 | catalog, lock |
| Calibration reellement first-class : 7 optimiseurs derivative-free (TPE, CMA-ES, GP, DA-MH-GP, random, grid, scipy) derriere un protocole ask/tell ; `Calibrable` porte transforms log/logit, priors, bornes physiques ; harness parallele per-trial-sandbox. | Ch9 9.5.2/Box 9.2, Ch10 10.2 | `calibration/optimizer.py`, `parameters.py`, `adapters/` |
| 4 backends couvrant le spectre de complexite (Boussinesq D-F analytique, GR4J lumped, MF6 CVFD, NWT structure) : on possede deja les modeles simples de screening/verification que le livre exige de garder pour recouper le complexe ; solveurs Newton pour la nappe/marnage. | Ch1 1.2.2, Ch3 3.4, Ch4 4.5.1 | 4 solveurs |
| Un residu global de fermeture du bilan existe deja. | Ch6 6.8 / Ch3 3.6.2 | `analysis/comparison/numerical_closure.py`, `results/derived.py:76 fluxes_from_budget` |
| MF6 **PRT** est DISV-native : le particle tracking tourne deja sur la grille Voronoi par defaut ; porosite effective = champ first-class avec semantique v=q/porosite et warning Sy. | Ch8 8.2.3/8.6/Box 8.1 | `solver/modflow6/prt.py`, `display/figures/particle_tracks.py` |
| Culture des resultats negatifs (revert de `outside_coarsening` qui cassait Newton, revert du reuse non equivalent, interdiction multi-lac/cell) = exactement la retenue que le livre prone contre la complexite non supportee par les donnees/la numerique. | Ch12 12.1 (NRC 1990) | historique projet |

---

## Matrice de priorites

| # | Theme | Prio | Etat actuel | Levier |
|---|---|---|---|---|
| 1 | Bilan hydrique = objet comptable maitre | **P1** | residu global seul ; pas de ledger par package, pas de sub-budget zonal, pas de gate | tres haut |
| 2 | Conditions initiales / spin-up / regime steady-transient | **P1** | `ic=top` + steady 1 jour = spin-down documente (RC-2) | tres haut |
| 3 | Diagnostic de non-unicite (sensibilite, identifiabilite, edge-hit) | **P1** | trials en DuckDB mais aucune CSS/Jacobien/flag borne | haut, peu cher |
| 4 | Forecast + incertitude comme etape de pipeline | **P1** | s'arrete au meilleur jeu unique | haut |
| 5 | Parametrisation distribuee (cause profonde du K-floor) | P2 | tout scalaire domaine-entier | haut |
| 6 | Objectif de calibration bien pose, etage, multi-cible | P2 | KGE/NSE sans ponderation erreur-mesure ni balance de groupes | haut |
| 7 | Conditions limites + maillage comme choix explicites verifies | P2 | boite no-flow implicite hardcodee | moyen |
| 8 | Reproductibilite, provenance, purpose, rapport | P2 | archive forte mais cache code-blind, pas de purpose ni rapport canonique | moyen |
| 9 | Particle tracking comme produit decisionnel (aire d'alimentation) | P3 | PRT forward-only, pas d'agregation capture-zone | moyen |

---

## Top 7 des mouvements a plus fort levier (ranked)

1. **Bilan hydrique : ledger par package + zonal + gate de fermeture.** On lit deja le budget MF6 et on a un residu global : le cout incremental est modeste, mais ce seul mouvement attrape la classe exacte de bug qui a mordu Cheze a repetition (fuite SFR, runoff non extrait, inondation) *a la source* au lieu d'un bisect py-spy. Devient un garde-fou de regression permanent et le substrat pour reconcilier attendu-vs-simule et hydro-vs-GW. Remonte en top reco dans 6 des 12 chapitres.

2. **Etape conditions initiales / spin-up first-class + preflight de constante de temps.** Remplace `ic=top` + steady 1 jour par un mode `steady_solve`/`transient_spinup`, et ajoute le check gratuit `T = S*L^2/(K*b)`. C'est la cause racine (RC-2) du spin-down qui fait que la calibration s'auto-selectionne K au plancher 1e-5. Debloquer ca conditionne le realisme de tout ce qui suit. Le preflight aurait signale le footgun steady-1-jour avant tout solve.

3. **Diagnostic de non-unicite : sensibilite/identifiabilite + garde R/T + flag borne.** Diagnostique *pourquoi* K rail au plancher (correlation K-recharge, sous-determination head-only) au lieu de le laisser silencieux. Le Jacobien est minuscule (poignee de scalaires) donc c'est etonnamment pas cher. `calibration/diagnostics.py:90` a deja `parameter_correlation` : on construit dessus, on n'part pas de zero.

4. **Cache `params_hash` conscient du code de build (fingerprint).** Fold d'un hash git-commit + contenu solver/physics (+ reglages IC/mesh) dans la cle de cache : un hit doit matcher le fingerprint sinon re-solve. S-effort, payoff enorme : ferme un footgun connu qui viole l'invariant de replication, et c'est une precondition dure de tout ensemble UQ (un cache perime empoisonnerait toute l'enveloppe d'incertitude, pas un point).

5. **Etape forecast + UQ (ensemble de scenarios + conditionnement du set behavioral).** C'est le vrai *purpose* metier (le reservoir passera-t-il sous un niveau en secheresse) et le livre qualifie d'inacceptable un livrable a jeu unique. On a deja le moteur d'ensemble (harness parallele) et chaque objectif de trial est stocke en DuckDB, donc le conditionnement behavioral est presque gratuit, et les runs de scenario reutilisent le harness parallele.

6. **Parametrisation distribuee : multiplicateur de recharge maintenant, zonation ensuite.** Le K scalaire unique est la cause profonde derriere l'effondrement calibration-sur-borne. Le multiplicateur de recharge est un petit changement a gros payoff (regle un controle de bilan de 1er ordre sans jeter la structure GR4J) ; la zonation retire la raison pour laquelle une meme molette doit servir deux milieux physiquement distincts (lit du reservoir vs aquifere).

7. **Generateur de rapport de modelisation canonique avec purpose, verdict d'acceptation, limitations.** Verbe `hmp report` assemblant le plan 11.2 depuis config/catalog/session, pilote par un `PurposeConfig` a criteres d'acceptation machine-verifiables. Transforme le tas Zarr/Parquet/HTML en etude defendable et auto-jugeante (purpose -> acceptation -> accept/reject), pour qu'un run converge-mais-vide ne passe pas silencieusement.

---

## Quick wins (S-effort, payoff disproportionne)

- **Multiplicateur de recharge `Calibrable`** (Ch5 Box 5.4) : scale l'array RCHA GR4J entier avec prior log/normal autour de 1.0, preserve la structure spatio-temporelle. Le pont le moins cher du scalaire vers le spatial. Cible : `DataConfig` provider + metadata `Calibrable` + writer RCHA.
- **Preflight constante de temps T + ratio tau** (Ch7) : check ferme en une ligne depuis la config existante, signale une fenetre spin-up << T et le risque K-floor avant tout solve. Cible : diagnostic `physics/analysis` + preflight CLI `run`.
- **Flag parametre-sur-borne / edge-hit dans le rapport** (Ch2/Ch9) : warn quand un optimum est a epsilon d'une borne ou hors des plages litterature, fait remonter le K-au-plancher en warning des le 1er run. Cible : `calibration/diagnostics.py` + rapport + TOLERANCES.
- **Fingerprint code-build dans la cle de cache** (Ch1/7/10/11) : precondition de l'UQ. Cible : cle `params_hash` + `hydromodpy.lock`.
- **Check de completude steady (change-in-storage)** sur le solve IC (Ch7) : assert `|flux storage| / |inflow| < tol` pour prouver que "steady" est vraiment steady. Cible : lecteur budget/CBC + TOLERANCES.
- **Carte QA des flux CL + fraction de mailles inondees** en panneaux de rapport par defaut (Ch4/Ch5) : ou l'eau entre/sort par type de CL (flux net signe), et fraction de mailles avec charge > top DEM. Cible : `analysis` + `display/reporting`.
- **Validateurs au build HDB** (Ch6) : rejeter/warn sur collisions multi-lac/cell, SFR EXT-OUTFLOW hors idomain, stage-init steady != premiere stage observee. 3 bugs latents connus convertis en erreurs bruyantes. Cible : `builders/lake.py`, `builders/sfr.py`.

---

## Garde-fous : ce qu'il ne faut PAS importer du livre (over-engineering)

- **Pas de pilot points / MPS geostatistique / champs K stochastiques** (Ch5/Ch12). Pour un petit bassin peu instrumente avec une ou deux series d'observation, des centaines de pilot points sont massivement sur-parametrees et mal posees. La bonne altitude : une poignee de **zones** (aquifere vs lit reservoir vs buffer). Le livre lui-meme avertit que la complexite sans donnees pour la contraindre ne fait qu'un probleme mal pose plus complexe.
- **Pas de workflow split-sample / holdout de "validation"** (Ch9), et arreter d'appeler un modele calibre "valide". Le livre est explicite : la validation d'un modele de systeme naturel n'est pas defendable, et retenir des donnees nuit plus qu'autre chose, a fortiori sur des chroniques courtes de bassin. Reserver "verification" aux checks solveur-vs-analytique (Boussinesq/LAK/SFR).
- **Pas de XT3D ni tenseur K complet par defaut** (Ch3 Box 3.1). Pour des lits peu profonds quasi-horizontaux, K isotrope aligne axes est correct et le defaut Voronoi sans-XT3D est une *feature*. Garder XT3D en opt-in explicite pour le cas rare d'anisotropie horizontale.
- **Pas de couplage bidirectionnel complet GR4J<->MF6** (Ch12). Le chemin one-way recharge/ET lie est standard et suffisant pour la plupart des purposes bassin. Ajouter au plus une extinction EVT head-dependent et un rejet de recharge la ou la nappe peu profonde atteint demontrablement la zone racinaire ; un solveur couple iteratif complet est une machinerie lourde rarement necessaire ici.
- **Pas de suite transport (GWT) ni Richards/UZF complet en coeur** (Ch12). Extensions regionales/decisionnelles. Heat-as-tracer et UZF = items de roadmap legitimes seulement si le rejet-de-recharge ou les flux d'echange deviennent de 1er ordre pour une etude precise.
- **Ne pas forcer chaque run dans le rapport complet 11.2 ni un ensemble UQ lourd** (Ch1/Ch11). Adapter la ceremonie au purpose : une sonde de screening merite un rapport leger et parfois aucune calibration ; un forecast decisionnel merite le rapport complet + UQ. Le `PurposeConfig` doit brancher le workflow.
- **Ne pas traiter le steady-state comme le livrable** (Ch7/Ch9). Le livre penche steady-first pour le regional, mais toute la valeur de HMP est la dynamique transitoire stage/marnage du lac. Offrir le steady comme dispositif IC/spin-up et baseline de screening, pas comme produit principal.
- **Ne pas porter la pile IES / null-space Monte Carlo de PEST++** (Ch10). Pour ~3 scalaires, un petit Jacobien differences-finies + conditionnement behavioral du catalogue de trials est l'UQ a la bonne taille ; la machinerie de regularisation industrielle est calibree pour des inversions regionales haute-dimension que HMP n'a pas.

---

## Detail des 9 themes (recos + cibles + effort/impact)

### [P1] Theme 1 - Bilan hydrique comme objet comptable maitre et de validation
Base : Ch2 2.3.4 (bilan terrain vs calcule ; reconciliation hydro<->GW, Fig 2.16), Ch3 3.6.2 (seuils Konikow 0.5%/0.1%), Ch4 Box 4.5+P4.6 (budget anomal par conductance HDB ; test swap arete no-flow), Ch6 6.8 (erreurs par terme : mauvais signe/package).
Etat : seul un residu GLOBAL existe (`numerical_closure.py`) ; `fluxes_from_budget` lit le budget mais pas de ledger par package, pas de sub-budget zonal, pas de reconciliation attendu-vs-simule, et le budget ne gate jamais un trial. Tous les echecs Cheze documentes sont des erreurs de budget par package que le residu global ne voit pas.
- (M/high) Ledger in/out par package comme resultat + panneau de rapport (RCHA_IN, EVT_OUT, LAK_GWF, SFR_LEAK, DRN_OUT, MVR, STO, CHD/GHB + % discrepancy). Cible : `analysis/comparison/exports/budget.py`, `results/parquet_schemas.py`, reporting.
- (M/high) **Gate** de fermeture a seuils etages (warn >0.1%, fail >0.5%, hard-fail >1%) qui **rejette** un trial dont le budget echoue, + sub-budgets zonaux (type ZONEBUDGET) par lac/bassin. Cible : lecteur budget + gate d'eval calibration ; seuils dans `tests/TOLERANCES.md`.
- (M/high) `ConceptualBudgetConfig` : bandes min/attendu/max par composante, avec table de residu pass/fail attendu-vs-simule. Cible : nouveau sous-config sur `HydroModPyConfig` ; agregation `derived.py` ; catalog Parquet.
- (M/high) Boucler hydro<->GW<->debit observe : aligner le bilan GR4J (P, AET, recharge, runoff) contre le budget MF6, le debit derive et le debit exutoire observe, residu en % de l'inflow total. Cible : module reconciliation frere de `numerical_closure.py`.
- (M/medium) Audit des flux de frontiere + test automatique de swap arete no-flow (P4.6) pour prouver la conceptualisation de la ligne de partage. Cible : audit `results/analysis` + figure + gate regression/e2e.

### [P1] Theme 2 - Conditions initiales, spin-up, decision de regime steady/transitoire
Base : Ch7 7.2/7.4/7.7/7.8 (Franke : ne jamais imposer des charges terrain en IC transitoire ; `T=S*L^2/(K*b)` ; ratio tau ; change-in-storage->0 au steady ; spin-up>T), Ch4 Box 4.6 (nappe replique-topo = antipattern).
Etat : un pre-step steady existe mais Cheze utilise `ic=top` + steady 1 jour : charge replique-topo imposee en IC transitoire, fenetre bien plus courte que la constante de temps aquifere. C'est le spin-down documente (RC-2), K auto-selectionne au plancher 1e-5.
- (L/high) Etape IC/spin-up first-class : `simulation.initial_conditions` modes `steady_solve` / `transient_spinup` (warm-up jete sous forcage cyclique) / `from_heads`, alimentant le package IC MF6. Cible : config + simulation + writer IC/TDIS.
- (S/high) Preflight `T` et `tau` (Haitjema) : recommande spin-up>T, warn si fenetre << T, conseille steady vs transitoire. Cible : diagnostic physics/analysis + validateur config ; preflight CLI `run` ; header rapport.
- (M/high) Interdire des charges terrain/top imposees comme IC transitoire aquifere (par defaut ICs generees par le modele ; garder `stageinit=observed` pour le LAK, qui initialise l'etat lac pas la nappe). Cible : validateurs `FlowConfig`/`simulation.initial_conditions`.
- (S/medium) Check de completude steady (change-in-storage) sur le solve IC. Cible : lecteur budget/CBC + TOLERANCES.
- (M/medium) Mode `simulation_type = steady|transient` + objectif comparant charges/baseflow steady simules a des cibles moyennees/pseudo-steady. Cible : config + target builder calibration.

### [P1] Theme 3 - Diagnostiquer la non-unicite : sensibilite, identifiabilite, raison des parametres
Base : Ch3 Box 3.2 (`h ~ R/T` : calibration head-only sous-determinee), Ch9 9.5.3 (Jacobien, CSS, flag insensible >2 ordres sous le max, correlation r>0.95, identifiabilite), Ch2 2.3.2/2.5 (valeur calibree sur borne = modele conceptuel inadequat), Ch5 5.6 (plages litterature).
Etat : tous trials/params/objectifs en DuckDB, mais rien ne calcule Jacobien/CSS/matrice de correlation/identifiabilite ni ne flag une borne. `diagnostics.py` a deja `parameter_correlation` et `convergence_rate` : substrat present.
- (L/high) Sous-module `calibration/sensitivity/` (Morris + CSS) reutilisant le runner parallele et les residus par observation ; ranking CSS, flag insensible, matrice correlation r>0.95, identifiabilite ; verbe `hmp sensitivity`. Cible : nouveau sous-module + CLI + catalog.
- (M/high) Garde de non-identifiabilite R/T : si un multiplicateur recharge ET un K aquifere sont Calibrable avec seulement des obs de charge (pas de flux), warn/error + 3 resolutions (fixer un des deux, calibrer le ratio R/T, exiger une obs de debit). Cible : validation objectif/observation.
- (S/medium) Gate de raison / edge-hit post-calibration : flag tout optimum a epsilon d'une borne ou hors plages litterature ("k_aquifer railed to lower bound 1e-5 -> conceptual model may be inadequate"). Cible : `diagnostics.py` + rapport ; plages dans TOLERANCES.
- (M/medium) Gate d'identifiabilite GSA sur les process optionnels (K, bed_leakance, voile HFB, 2e lac, Kv per-cell) avant de les activer. Cible : module sensitivity + reuse ensemble.

### [P1] Theme 4 - Forecast et quantification d'incertitude comme etape de pipeline
Base : Ch10 (chapitre entier : base model -> forecast, UQ scenario + parametres, Occam/MML, 6 regles de cadrage, Monte Carlo contraint par calibration, UQ lineaire/Jacobien, max-min contraint, vocabulaire IPCC), Ch1 steps 6-7 + Doherty (jamais une reponse unique), Ch12 12.5-12.6.
Etat : HMP finit sur un jeu unique. Le harness parallele + sandbox est deja le moteur d'ensemble forward que l'UQ demande, chaque objectif de trial est en DuckDB, DA-MH-GP produit des echantillons posterior, mais l'ensemble est jete.
- (L/high) Etape forecast first-class : `ForecastConfig` (@-selecteur base-model, fenetre forecast distincte de l'history-match, quantite cible, flags de cadrage difference-vs-absolu / moyenne-vs-extreme / changement structurel / horizon-vs-longueur-calib). Verbe `hmp forecast`, run-kind catalog distinct. Cible : config + workflow + `cli/commands/forecast.py` + `project.dispatch`.
- (M/high) Ensemble de scenarios sur forcage futur (`ScenarioConfig` : deltas recharge/ET/pompage) via le harness `parallel=N`, agrege en enveloppe. Cible : config + overrides forcage + fan-out forward.
- (M/high) Monte Carlo contraint calibration (behavioral) par conditionnement du catalogue de trials (set dont l'objectif est dans un seuil du meilleur), enveloppes de quantiles + proba de franchir un seuil d'action, check de convergence 2-sous-echantillons ; exposer aussi le posterior DA-MH-GP. Cible : nouveau module UQ lisant le catalog.
- (M/high) UQ lineaire/Jacobien adaptee aux scalaires (variance d'erreur de forecast Moore-Doherty, contribution par parametre, identifiabilite, data worth d'observations potentielles). Cible : module UQ + sigma de variabilite innee sur Calibrable.
- (M/medium) Forecast max-min contraint (best/worst-case sous penalite quand l'objectif de calibration se degrade). Cible : mode objectif + adapters CMA-ES/optuna.
- (M/medium) Reporting d'incertitude avec vocabulaire de vraisemblance IPCC (enveloppe, box-whisker, proba d'exceedance, barres de variance par parametre). Cible : reporting HTML + display.

### [P2] Theme 5 - Parametrisation distribuee (cause profonde de l'effondrement K-floor)
Base : Ch5 5.5.3 (zonation/interpolation/hybride ; K scalaire homogene = hypothese de screening seulement) + Box 5.4 (calibrer un multiplicateur unique sur l'array recharge), Ch10 10.4.2 (erreur de simplification de parametres = terme UQ dominant pour modeles pauvres), Ch12 12.5.
Etat : chaque Calibrable est un scalaire domaine-entier (k_aquifer, bed_leakance, specific_yield). Une molette ne peut separer un lit de reservoir fuyard d'un aquifere serre, d'ou l'effondrement sur la borne K.
- (S/high) Multiplicateur d'array recharge (au lieu d'un scalaire) : `recharge_multiplier` Calibrable scalant tout l'array RCHA, prior log/normal autour de 1.0 ; generaliser le pattern "multiplicateur sur input distribue" a ETP/tout provider. Cible : `DataConfig` provider + metadata Calibrable + writer RCHA.
- (L/high) Zonation comme Calibrable distribue first-class : `ZonedParameter` mappant un layer de zones (litho/sol ou raster) vers des scalaires par zone expanses sur les mailles au build, le scalaire actuel etant le cas degenere 1-zone ; seam concu pour brancher plus tard un backend interpolation/pilot-point (kriging). Cible : metadata Calibrable + `FlowConfig` ; nouvel expander zone->cell au seam SolverMesh.
- (M/medium) Exposer l'erreur de simplification de parametres a l'etape UQ (feeder C(p) des champs zones/multiplicateur dans l'UQ lineaire et Monte-Carlo). Cible : representation C(p) sur Calibrable + module UQ.

### [P2] Theme 6 - Objectif de calibration bien pose, etage, multi-cible
Base : Ch9 9.5.1/9.7 (les poids expriment d'abord l'erreur de mesure puis equilibrent pour qu'aucun groupe ne domine ; steady-puis-transitoire avec 2e etape storage-only ; cibles en difference temporelle enlevent l'offset IC ; regularisation Tikhonov valeur-preferree ; suite de residus complete), Ch2 2.3.4/Table 2.3 (cibles de flux + erreur par composante), Ch3 Box 3.2 (au moins une cible de flux requise).
Etat : objectifs KGE/NSE/R2 avec echafaudage series/network/composite, mais pas de ponderation erreur-mesure par obs, pas d'equilibrage de groupes (une serie de stage peut ecraser la serie de debit qui casse la correlation K-recharge), pas de steady->transitoire etage avec gel de parametres, pas de cibles en difference, pas de penalite valeur-preferree, et le rapport ne montre que des scores (pas de biais ME, scatter, carte de residus).
- (M/high) Objectif head+flux pondere par erreur-mesure et equilibre par groupe (sigma pour stage/head, CV pour flux/debit ; normalisation par groupe pour qu'une serie stage n'ecrase pas une serie debit ; warn si cible head/stage sans cible flux). Cible : `calibration/objective.py` + schema d'observation config.
- (M/high) Type de cible flux (baseflow, debit GW->stream, composante de budget) avec bande d'erreur. Cible : `objective.py` + `natural_observations.py`.
- (L/high) Calibration etagee steady->transitoire avec gel : tag `stage` par Calibrable ; etape 1 calibre K/recharge/leakance sur cibles steady/moyennees, etape 2 gele ceux-la et calibre seulement specific_yield sur cibles transitoires. Cible : workflow calibration + metadata Calibrable.
- (M/medium) Cibles en difference temporelle (delta-stage/delta-debit) sur l'axe CF /time deja utilise. Cible : `objective.py` series + config observation.
- (M/medium) Penalite Tikhonov valeur-preferree optionnelle (deviations ponderees au carre vs prior, une molette PHIMLIM-like) pour que les parametres insensibles reviennent au prior au lieu de deriver vers une borne ; marche pour les optimiseurs non-Bayesiens. Cible : `objective.py` composite + config.
- (M/medium) Suite de residus complete dans le rapport (ME/MAE/RMSE, NSE transitoire, scatter 1:1, carte spatiale de residus, residus non ponderes). Cible : rapport session + metriques residus.

### [P2] Theme 7 - Conditions limites et maillage physiquement dimensionne comme choix explicites verifies
Base : Ch4 4.2.2/4.3.3-4.3.4 (frontieres physiques vs hydrauliques ; no-flow n'est que le defaut du code ; GHB-vers-lointain Fig 4.19) + Box 4.1/4.6 (validite D-F, Haitjema hD/d), Ch6 6.5-6.6 (HDB far-field vs SFR/LAK near-field ; footguns HDB ; conductance serie Eqn 6.16), Ch5 5.2.6 (longueur de fuite lambda=sqrt(T*c)) + 5.3.3 (mailles inondees), Ch3 Box 3.1 (orthogonalite CVFD / XT3D).
Etat : perimetre = boite no-flow implicite hardcodee au partage topographique (hydraulique) sans config ni provenance ; SFR/LAK + mesh fin partout car `outside_coarsening` casse Newton ; echange inter-bassin = buffer-actif+boite no-flow ad hoc ; raffinement = heuristique lake-field ; pas de check mailles inondees, pas de preflight D-F/Haitjema, pas de validateurs HDB.
- (L/high) Perimetre = decision de config first-class annotee : `PerimeterBoundaryConfig` par segment (type no_flow/specified_head/ghb/river + tag provenance physique/hydraulique) mappe sur l'arete idomain DISV. Defaut no-flow mais declare explicitement partage hydraulique. Cible : nouveau config domain/geographic + spatial tagging + writers CHD/GHB.
- (L/medium) Tiering de representation + perimetre GHB-vers-lointain : selecteur par feature (`FlowLakeConfig.representation` in {lak, fixed_level_ghb} ; stream/drain in {sfr, riv, drn, ghb}) emettant des CL HDB pas cheres (GHB C=K*A/L, lac niveau-fixe, RIV) pour buffer/inter-bassin en gardant LAK/SFR+mesh fin pour le near-field reservoir. Cible : sous-configs FlowLake/stream/drain + writer GHB + scope raffinement.
- (S/medium) Validateurs au build pour les footguns HDB (LAK sans outflow non declare puits ferme ; collision multi-lac/cell ; SFR EXT-OUTFLOW hors idomain ; stage-init steady != premiere stage observee). Cible : `builders/lake.py`, `builders/sfr.py`, check cold-start.
- (M/high) Preflight de modele conceptuel : validite D-F `L/(b*sqrt(Kh/Kv))` et ratio Haitjema `hD/d = R*L^2/(K*8*b*d)`, warnings types. Cible : diagnostic preflight avant solver.
- (M/medium) Dimensionner le raffinement mesh surface-eau par longueur de fuite lambda=sqrt(T*c) (mailles a <3*lambda <= ~0.1*lambda). Cible : config raffinement + seam SolverMesh.
- (S/medium) Diagnostic mailles inondees (fraction charge > top DEM, carte) + carte QA flux CL. Cible : analysis + display/reporting.
- (M/low) Documenter le contrat d'orthogonalite CVFD + opt-in XT3D pour anisotropie K horizontale non representable autrement. Cible : docs `SolverSGridConfig.grid_dual` + champ anisotropy `FlowConfig` + option NPF xt3d.

### [P2] Theme 8 - Reproductibilite, provenance, purpose, rapport de modelisation
Base : Ch11 (rapport + archive + replication ; sim log ; provenance budget/convergence ; provenance obs ; bundle de replication + verify ; assumptions/limitations), Ch1 1.3/1.6 (purpose pilote le workflow ; ethique des hypotheses ; workflow cyclique => cache conscient du build), Ch2 2.1/2.4/2.5 (purpose + criteres d'acceptation ; modeles conceptuels alternatifs), Ch6 Eqn 6.16 (la leakance calibree depend du maillage).
Etat : `hydromodpy.lock` + catalog DuckDB + Zarr/Parquet/GeoParquet = substrat de replication fort. Mais le cache `params_hash` est code-blind (fix de build -> objectifs perimes, 0 re-solve), pas de champ purpose/criteres d'acceptation, pas de decision log par simulation, pas de generateur de rapport canonique, pas d'artefact assumptions/limitations, et le reuse-of-built-model n'est PAS output-equivalent.
- (S/high) `params_hash` conscient du build (fingerprint git-commit + hash contenu solver-build/physics + reglages IC/spin-up + mesh/connlen dont depend la leakance calibree) ; un hit doit matcher le fingerprint. Cible : cle params_hash + lock + lignes objectif catalog.
- (M/high) `PurposeConfig` qui branche le workflow (question libre, enum forecast/hindcast/screening/engineering_calculator/generic, regime, `acceptance_criteria` machine-verifiables type KGE>=0.7 AND budget<10%) ; le dispatch selectionne la sequence d'etapes et pilote le verdict accept/reject du rapport. Cible : nouveau config + workflow/project.dispatch + reporting.
- (M/high) Generateur de rapport canonique (`hmp report`) assemblant le plan 11.2 (purpose, modele conceptuel + bilan, design numerique avec carte grille georef, execution avec erreur budget + convergence, resultats calibration, section assumptions/limitations, references) ; profondeur adaptee au purpose. Cible : nouveau composite reporting + CLI.
- (M/medium) Decision/sim log par simulation (table DuckDB append-only alimentee par evenements workflow : invalidation cache, revert mesh, non-convergence, breach tolerance) + phase de cycle de vie + version MF6 + flag converge + % discrepancy ; refus de presenter des runs non converges/haute-discrepancy. Cible : nouvelle table catalog + migration + hooks + reporting.
- (M/medium) Provenance et poids des observations (source, date, data_type, quality_rank, error_estimate, weight ; poids feede dans l'objectif, partage avec Theme 6). Cible : modeles obs schema/config + objectifs + reporting.
- (L/high) Bundle de replication re-executable + `hmp archive verify` (re-run et assert outputs dans TOLERANCES) ; recadrer "validation" en verification de code pour le tier benchmark analytique dans la doc. Cible : export/gc catalog + CLI verify + docs.
- (M/medium) Modeles conceptuels alternatifs comme groupement catalog first-class (id `conceptual_model` pour que single-lake / forebay+sill / chronicle soient des conceptualisations concurrentes ; comparaison classee par fit ET fermeture de budget). Cible : identite/groupement catalog + comparison web report.

### [P3] Theme 9 - Particle tracking comme produits decisionnels (aire d'alimentation du reservoir)
Base : Ch8 8.5.2 (PT inverse pour capture zones / aires d'alimentation), Box 8.1 (porosite effective = parametre cale sur temps de transit observes), 8.4 (puits faibles ; Ssnk), 8.2.2 (relachement continu ; un relachement unique donne la mauvaise capture zone), 8.6 (PT DISV-native).
Etat : MF6 PRT DISV-native tourne deja sur Voronoi, porosite effective first-class, pathlines/endpoints au catalog. Mais PRT est forward-only (backward seulement sur NWT/MODPATH non-defaut), rien n'agrege les tracks en aire-d'alimentation/capture-zone/age, la porosite est un scalaire fixe sans objectif temps-de-transit, pas de politique puits-faible, et le PT transitoire defaut a un relachement unique.
- (M/high) Tracking inverse pour MF6 PRT (champ GWF a signe inverse, relachement depuis mailles LAK/exutoire) pour que l'aire d'alimentation du reservoir marche sur la grille par defaut. Cible : `solver/modflow6/prt.py` + `track_dir` in `transport_config.py`.
- (M/high) Produits couche-analysis aire-d'alimentation / capture-zone / age (`hydromodpy/analysis/particle_tracking/` lisant endpoints+pathlines : polygone d'aire d'alimentation par puits terminal en GeoParquet, carte capture-zone TOT, table endpoints par puits, CDF de temps de transit/age). Cible : nouveau module analysis + reuse `display/figures/particle_tracks.py`.
- (M/medium) Porosite effective Calibrable (transform logit, bornes ~0.005-0.6) + type d'obs/objectif temps-de-transit/age. Cible : `transport_config.py` + types obs/objectif calibration.
- (S/medium) Politique de capture puits-faible pour LAK/SFR/DRN (always/never/if Ssnk>=seuil). Cible : `Modflow6PrtParametersConfig` + prt.py.
- (S/low) Corriger le defaut de relachement transitoire (flag `release_every_period`) + note doc sur le biais PT des couches distordues par le carving bathy per-cell. Cible : `transport_config.py` + doc PT.

---

## Comment lire cette note

Ordre de valeur suggere : **quick wins d'abord** (gates de bilan + preflight T + fingerprint cache + flag edge-hit), qui transforment des echecs structurels silencieux en warnings au 1er run pour un cout S. Puis les 3 chantiers P1 lourds (conditions initiales, parametrisation distribuee, forecast+UQ) qui debloquent le realisme et le vrai livrable metier. Les garde-fous sont aussi importants que les recos : ils tracent la frontiere entre "adopter la methode du livre a l'echelle bassin" et "importer une machinerie regionale que HMP n'a pas les donnees pour nourrir".

Source : Anderson, Woessner & Hunt, *Applied Groundwater Modeling: Simulation of Flow and Advective Transport*, 2e ed., Academic Press, 2015 (720 p., 12 chapitres). Analyse produite par lecture integrale croisee chapitre par chapitre.
