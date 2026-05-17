# Rapport methodologique Boussinesq / MODFLOW 6 sur les cas naturels

Date: 2026-05-13

Statut: rapport de synthese technique fonde sur les configurations, notes de developpement et sorties de testbed presentes dans le depot. Il est redige pour etre lisible hors contexte, en distinguant les constats probants, les indices non probants et les hypotheses a verifier.

## 1. Resume executif

Les comparaisons naturelles disponibles ne montrent pas un simple probleme de convergence generalise du solveur Boussinesq. Les cas naturels executes a ce stade montrent plutot trois familles de resultats:

1. Des comparaisons terminees ou les deux solveurs produisent des champs de charge et des flux, avec bilans numeriques acceptables, mais avec des ecarts hydrauliques importants: RMSE de charge de quelques metres a environ 8 m dans la campagne N1 terminee, et jusqu'a environ 17 m dans des artefacts de regression PETSc VI sur bassins plus grands.
2. Des comparaisons plus recentes, partielles, ou l'alignement de methode et de maillage reduit parfois fortement l'ecart: RMSE de charge en fin de simulation autour de 0.5 a 0.9 m sur plusieurs candidats reseau et variantes drainage/K a maillage triangulaire identique, mais avec des contre-exemples forts comme `site_02_low_k` a 19.84 m.
3. Des echecs de chaine qui ne qualifient pas directement la methode physique: collision d'identifiant dans le catalogue DuckDB, verrou DuckDB concurrent, absence de trace riviere pour une contrainte de maillage, campagnes declarees "execute=false" ou variantes encore "pending".
4. Des echecs numeriques clairs: un echec MODFLOW 6 pour une initialisation stationnaire auxiliaire sur un site naturel, et plusieurs echecs Boussinesq recents, notamment `SolverDivergedError` sur des variantes naturelles site_02 ou K/drainage.

La conclusion principale est que les ecarts observes sont suffisamment grands pour ne pas etre traites comme du bruit numerique. Ils doivent etre analyses comme des ecarts de formulation, de discretisation, de conditions de surface, d'initialisation et de parametrisation. En particulier, la campagne naturelle N1 compare souvent:

- MODFLOW 6 avec drainage de surface explicite de conductance elevee (`0.1 m2/s`);
- Boussinesq PETSc TS VI avec obstacle superieur `h <= z_top` et drainage configure a `0.0 m2/s`.

Cette difference de fermeture de surface est voulue dans la configuration, mais elle signifie que les ecarts ne peuvent pas etre interpretes comme une erreur purement numerique entre deux implementations identiques. Les experiences recentes avec drainage partage et/ou meme maillage montrent que l'ecart peut devenir beaucoup plus faible, ce qui renforce l'hypothese d'un role majeur de la fermeture de surface, du maillage et du parametrage. Elles introduisent aussi une nouvelle nuance: Boussinesq ne diverge pas partout, mais certaines variantes naturelles echouent maintenant explicitement cote Boussinesq.

Point central pour la lecture des derniers tests: lorsque Boussinesq et MODFLOW 6 utilisent le meme maillage triangulaire contraint, les ecarts de charge peuvent tomber sous 1 m de RMSE sur plusieurs sites. Lorsque l'on change de support de discretisation, par exemple vers un maillage triangulaire quasi uniforme seulement contraint par les rivieres, les ecarts peuvent monter a 16-24 m de RMSE, y compris entre deux variantes MODFLOW 6. L'effet "maillage/support spatial" est donc du meme ordre, voire plus grand, que l'effet "solveur" dans plusieurs comparaisons.

Sur la question specifique de la non-convergence, les diagnostics disponibles pointent d'abord vers un blocage d'initialisation stationnaire Boussinesq, pas vers un pas mensuel transitoire trop long. Plusieurs variantes echouees portent `flow_regime = "steady"`, `runtime_problem_kind = "steady_head_balance"`, `SNES_DIVERGED_LINE_SEARCH`, `total_periods = 0` et aucun sous-pas transitoire execute. L'hypothese "pas de temps trop long" reste plausible comme facteur aggravant dans des configurations futures, mais elle n'est pas la cause principale observable dans les artefacts d'echec actuels.

Le terme "divergence" doit donc etre lu ici comme une non-convergence du solveur non lineaire, pas comme la preuve que la charge part physiquement a l'infini. Le mecanisme le plus plausible combine un etat stationnaire initial difficile, beaucoup de cellules proches des seuils `z_bottom` et `z_top`, un active set surface/fond instable, une raideur accrue lorsque `K` augmente, et une interaction numeriquement dure entre obstacle VI et drainage de surface.

## 2. Sources utilisees

Les constats ci-dessous proviennent principalement de:

- `docs/_dev_notes/calibration_network_transient_audit.md`;
- `docs/_dev_notes/national_headwater_deployment_audit.md`;
- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/*.toml`;
- `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/`;
- `examples/projects/10_testbed_workflow/outputs/boussinesq_petsc_vi_regression_testbed/`;
- `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_*_testbed/`;
- `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_network_site_candidates_testbed/`;
- `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/`;
- `examples/projects/10_testbed_workflow/outputs/boussinesq_petsc_vi_regression_testbed/sensitivity_runs/`;
- modules `hydromodpy/solver/boussinesq/`, `hydromodpy/solver/modflow6/` et tests sous `tests/validation/`.

La premiere version du rapport synthetisait l'etat observable dans les artefacts existants. La presente mise a jour ajoute l'execution locale de la matrice `natural_drainage_k_mesh_matrix` et ses metriques consolidees.

## 3. Objet exact de la comparaison

### 3.1 Donnees hydrogeologiques communes

Les configurations naturelles utilisent un meme cadre general:

- domaine issu d'un exutoire et d'un MNT regional, notamment `examples/data/dem/DEM_armorican_massif.tif`;
- hydrographie regionale `regional_stream_network.shp`;
- geologie `GEO1M.shp` et table de permeabilite demonstrative `geology_K_dummy_demo.csv`;
- epaisseur aquifere constante de 30 m;
- conductivite hydraulique heterogene par geologie;
- `Ss = 1e-5 m-1`;
- `Sy = 0.05`;
- recharge transitoire synthetique mensuelle;
- periode transitoire du 2000-09-01 au 2002-08-31;
- pas de temps de forcage mensuel;
- ruissellement direct configure a zero dans les cas examines.

La recharge mensuelle synthetique est:

| Mois relatif | Recharge mm/j |
|---:|---:|
| 1 | 0.05 |
| 2 | 0.12 |
| 3 | 0.45 |
| 4 | 1.10 |
| 5 | 1.90 |
| 6 | 2.40 |
| 7 | 1.50 |
| 8 | 0.65 |
| 9 | 0.20 |
| 10 | 0.04 |
| 11 | 0.00 |
| 12 | 0.02 |
| 13 | 0.03 |
| 14 | 0.08 |
| 15 | 0.30 |
| 16 | 0.90 |
| 17 | 1.70 |
| 18 | 2.80 |
| 19 | 1.20 |
| 20 | 0.35 |
| 21 | 0.08 |
| 22 | 0.01 |
| 23 | 0.00 |
| 24 | 0.03 |

Ces donnees ne constituent pas une calibration hydrologique reelle. La table de conductivite est demonstrative, la recharge est synthetique, et les metriques reseau comparent une reponse simulee a une hydrographie de reference sans ajustement de parametres. Les ecarts avec le reseau naturel ne doivent donc pas etre lus comme une erreur de solveur seule.

### 3.2 Maillage naturel

Les cas naturels utilisent un maillage de bassin avec contraintes geologie/rivieres:

- mode `constraints_mode = "geology_rivers"`;
- lissage du bassin;
- contraintes d'interface geologique et de reseau;
- taille cible globale typique autour de 130 m;
- taille minimale typique autour de 45 m;
- taille d'interface typique autour de 70 m.

Les comparaisons utilisent les memes domaines et cherchent a comparer les sorties sur une grille commune, avec raster fin active, taille de raster typique 80 m, intersection spatiale et interpolation lineaire.

Un point important: le maillage non structure est traite differemment par les deux solveurs. Boussinesq utilise un volume fini centre cellule avec flux a deux points sur triangles. MODFLOW 6 utilise un modele GWF DISV, avec les choix NPF/STO/DRN propres a MODFLOW et XT3D active automatiquement sur maillage non structure sauf configuration contraire.

### 3.3 Familles de maillages effectivement comparees

Les derniers tests ne comparent pas seulement deux solveurs. Ils comparent aussi plusieurs supports de discretisation. Il faut donc distinguer quatre familles.

| Famille | Exemples de simulations | Caracteristiques | Role dans l'analyse |
|---|---|---|---|
| Triangulaire contraint identique | `mf6_unstructured_reference` vs `bouss_unstructured_same_mesh`; `mf6_tri_irregular_drain_01` vs `bouss_tri_irregular_*` | Meme support `mesh_catchment`; contraintes `geology_rivers`; taille globale typique 130 m; taille minimale 45 m; raffinement d'interfaces actif; taille d'interface 70 m | Isole au mieux l'effet solveur/formulation, car les deux simulations voient les memes cellules ou un support quasi identique |
| Triangulaire contraint grossier | `mf6_unstructured_350m` | Meme logique `geology_rivers`, mais taille globale 350 m, taille minimale 150 m, interface 180 m | Teste l'effet de coarsening sur un maillage non structure qui garde les contraintes geologie/rivieres |
| Triangulaire quasi uniforme rivieres | `mf6_tri_uniform_rivers_drain_01`, `bouss_tri_uniform_rivers_drain_01` | `constraints_mode = "rivers_only"`; taille globale 180 m; taille minimale 180 m; `refine_interfaces = false`; pas de raffinement geologique local | Teste un support triangulaire beaucoup plus lisse et moins conforme a la geologie; les ecarts peuvent devenir tres grands meme a solveur identique |
| Grille structuree reguliere | `mf6_regular_120`, `mf6_regular_180`, `mf6_structured_120_drain_01`, `mf6_structured_180_drain_01` | MODFLOW 6 resample le domaine vers une grille reguliere `120 x 120` ou `180 x 180`; resampling `nearest`; XT3D desactive en mode structure | Teste l'effet d'un support cartesien/resample par rapport au maillage triangulaire natif |

Le resultat a retenir est net: les comparaisons a meme maillage triangulaire contraint peuvent donner des ecarts faibles, tandis que les comparaisons entre supports differents melangent effet solveur, effet de projection/resampling, effet de contraintes geologiques/rivieres et effet de resolution. Les grandes RMSE observees sur certains cas ne doivent donc pas etre attribuees automatiquement au solveur Boussinesq.

## 4. Methode Boussinesq dans HydroModPy

### 4.1 Inconnue principale et equation resolue

La formulation Boussinesq locale est une formulation de nappe libre. L'inconnue principale des solveurs head-only est la charge hydraulique `h` au centre de chaque cellule triangulaire.

La geometrie verticale est definie par:

- `z_bottom`: fond de l'aquifere;
- `z_top`: toit ou topographie aquifere;
- `h`: charge inconnue;
- epaisseur saturee effective `b(h) = clip(h - z_bottom, 0, z_top - z_bottom)`;
- transmissivite `T(h) = K * b(h)`.

Dans les assemblages, les flux internes entre cellules utilisent:

- une moyenne harmonique de `K` entre cellules voisines;
- une moyenne arithmetique de l'epaisseur saturee;
- un facteur geometrique `longueur_arete / distance_centres`;
- une loi de flux du type `q = -tau * (h_b - h_a)`.

Cette approche est simple, robuste et coherente avec un volume fini centre cellule. Elle est toutefois de type flux a deux points. Sur triangles non orthogonaux ou geometries naturelles complexes, elle peut produire des erreurs de discretisation differentes de celles d'un schema MODFLOW 6 DISV avec XT3D.

### 4.2 Terme de stockage

En transitoire, la methode Boussinesq utilise un schema implicite de type Backward Euler. Le volume stocke est calcule a partir de:

`volume_stocke = aire_cellule * storage_coefficient * max(h - z_bottom, 0)`.

Le terme de stockage est donc borne inferieurement par le fond, mais il n'est pas plafonne par `z_top` de la meme facon que la transmissivite. La transmissivite reste plafonnee par l'epaisseur aquifere. Cette dissociation peut contribuer a des differences avec MODFLOW 6 dans les zones proches de la surface ou lorsque `h` tend a depasser `z_top`.

### 4.3 Fermeture de surface

Les assemblages Boussinesq contiennent plusieurs manieres de gerer l'exces de saturation ou la contrainte de surface.

#### Partition regularisee

La methode `regularized_partition` est l'approche historique. Elle reste une formulation head-only et applique une partition regularisee de l'exces de saturation. La regularisation de type Marcais repose sur un facteur exponentiel fonction du ratio de saturation. Elle repartit progressivement la recharge excedentaire en flux de surface lorsque la cellule approche de la saturation complete.

Cette methode peut produire de faibles flux de surface diffus meme lorsque le seuil physique n'est pas strictement atteint. Elle est utile numeriquement, mais elle peut differer d'une formulation complementaire stricte.

#### Complementarite mixte

La methode `complementarity` introduit une formulation mixte avec charge, taux d'exces de saturation et deficit sec. Elle utilise une relation de complementarite, notamment une forme Fischer-Burmeister dans le backend PETSc.

Cette formulation est plus explicite sur les contraintes:

- non-negativite des flux de surface;
- activation du flux lorsque la contrainte de saturation est atteinte;
- separation plus nette entre regime libre et regime contraint.

Elle est plus proche d'une formulation mathematique de type obstacle/complementarite, mais elle implique un systeme plus large et des conditions numeriques plus exigeantes.

#### Obstacle variationnel SNESVI

La methode `vi_obstacle` utilise PETSc SNESVI. Elle reste head-only: l'inconnue resolue est `h`. Les contraintes sont imposees directement sous forme de bornes variationnelles.

Cas sans drainage de surface positif:

- borne inferieure: `h >= z_bottom`;
- borne superieure: `h <= z_top`;
- l'exces de surface est reconstruit apres convergence comme reaction de contrainte.

Cas avec drainage de surface positif:

- la borne superieure est relachee vers une grande valeur;
- le flux de drainage de type Cauchy porte l'echange de surface;
- cela rapproche la fermeture de surface du fonctionnement du package DRN de MODFLOW 6.

Cette distinction est essentielle. Deux simulations Boussinesq toutes deux appelees "VI obstacle" peuvent ne pas representer la meme fermeture de surface si la conductance de drainage est nulle dans un cas et positive dans l'autre.

#### TS VI obstacle

La methode `ts_vi_obstacle` utilise PETSc TS avec SNESVI et des pas Backward Euler internes dans chaque periode de forcage. Elle est egalement head-only. Les reactions de surface et de fond sont reconstruites apres convergence.

Dans les comparaisons naturelles N1 executees, la configuration Boussinesq utilise:

- `runtime_backend = "petsc"`;
- `surface_interaction_model = "ts_vi_obstacle"`;
- `ts_vi_steps_per_period = 4`;
- `ts_vi_type = "beuler"`;
- `ts_vi_snes_type = "vinewtonrsls"`;
- drainage Boussinesq configure a `0.0 m2/s`;
- obstacle superieur actif `h <= z_top`.

Les resultats termines montrent une convergence numerique de ces solveurs TS VI sur les sites reussis, sans violation de bornes VI detectee.

### 4.4 Drainage dans Boussinesq

Le flux de drainage assemble cote Boussinesq est de la forme:

`q_drain = conductance_effective * max(h - z_top, 0)`.

Si une conductance positive est fournie, elle est utilisee. Si la conductance est nulle ou negative dans certaines branches, un fallback peut utiliser `K * aire_cellule` comme conductance effective, mais les configurations comparees doivent etre interpretees au cas par cas selon le modele de surface actif.

Dans les configurations N1 `ts_vi_obstacle`, l'obstacle superieur est l'element dominant: le solveur empeche la charge de depasser le toit et reconstruit une reaction de surface. Dans les configurations PETSc VI avec drainage positif, la borne superieure est relachee et le drainage explicite devient dominant.

### 4.5 Backend PETSc

Les backends PETSc sont prevus pour Linux avec `petsc4py`. Les solveurs VI utilisent:

- SNES type `vinewtonrsls`;
- KSP souvent `preonly`;
- PC `lu`;
- decalage de factorisation non nul typique `1e-10`;
- critere de convergence fonde sur le residu projete VI.

Les validations PETSc sont donc dependantes de l'environnement. Sur Windows, les tests PETSc sont generalement sautes.

### 4.6 Limite connue: conditions de Dirichlet Boussinesq

La condition de charge imposee cote Boussinesq est appliquee comme charge prescrite au centre cellule (`prescribed_head_m_by_cell`) et non comme condition d'arete exacte. Une note de contrat signale un biais systematique possible sur cas analytique Dupuit, avec erreur de l'ordre du centimetre a quelques centimetres dans les tests connus.

Cet effet doit etre documente, mais il est tres inferieur aux ecarts naturels observes, qui sont de l'ordre du metre a plusieurs dizaines de metres localement.

## 5. Methode MODFLOW 6 dans HydroModPy

### 5.1 Structure generale

Le solveur MODFLOW 6 est construit via FloPy avec un modele GWF. Dans les cas naturels non structures, il utilise une discretisation DISV.

Les packages principaux sont:

- DISV pour le maillage;
- NPF pour les proprietes d'ecoulement;
- STO pour le stockage transitoire;
- IC pour les conditions initiales;
- RCHA pour la recharge;
- DRN pour le drainage de surface lorsque le drainage est actif;
- CHD pour certaines conditions de charge imposee, notamment ocean, cours d'eau ou bords selon configuration;
- OC pour sorties;
- IMS pour la resolution numerique.

Dans les configurations naturelles examinees:

- le modele est a une couche;
- `icelltype = 1`, donc cellule convertible;
- `sy = 0.05`;
- `ss = 1e-5 m-1`;
- `save_specific_discharge` et `save_saturation` sont actifs;
- rewetting desactive;
- Newton principal desactive dans les cas transitoires examines;
- under-relaxation configuree mais seulement effective si Newton est actif;
- complexite IMS `COMPLEX`;
- tolerances de fermeture typiques `outer_dvclose = inner_dvclose = 1e-4`;
- maxima iterations souvent pousses a 1000 dans les overlays naturels.

### 5.2 XT3D

Sur maillage non structure, HydroModPy active automatiquement XT3D sauf configuration contraire. Si XT3D est actif, la complexite IMS peut etre promue a `COMPLEX`.

Cela rend la comparaison avec Boussinesq non triviale:

- MODFLOW 6 peut utiliser une correction de tenseur / discretisation plus adaptee aux geometries non orthogonales;
- Boussinesq utilise un flux a deux points centre cellule;
- les deux solveurs voient le meme domaine mais pas exactement le meme operateur discret.

### 5.3 Drainage MODFLOW 6

Le drainage de surface MODFLOW 6 est porte par le package DRN. Les entrees DRN placent typiquement le drain a `z_top` pour chaque cellule active non ocean / non cours d'eau, avec conductance configuree.

Dans la comparaison naturelle N1, l'enfant MODFLOW de reference utilise:

- solveur `modflow6`;
- drainage top actif;
- conductance typique `0.1 m2/s`.

Un tel drainage autorise `h` a depasser legerement le niveau de drain selon la resistance de drainage et retire le debit correspondant. Ce n'est pas strictement identique a une contrainte dure `h <= z_top`.

### 5.4 Initialisation stationnaire auxiliaire

Pour certaines configurations d'initialisation, HydroModPy lance un calcul stationnaire auxiliaire MODFLOW 6 avec forcage moyen afin de produire une condition initiale.

Ce calcul auxiliaire:

- force Newton actif;
- active l'under-relaxation;
- relaxe certaines tolerances au moins a `1e-3`;
- pousse les maxima d'iterations au moins a 1000;
- verifie le succes MODFLOW et un budget acceptable.

Si ce calcul echoue, la chaine leve:

`RuntimeError: MODFLOW 6 steady-state initial-condition solve failed`.

C'est l'echec numerique le plus net observe dans les campagnes naturelles executees.

## 6. Configurations de comparaison naturelles

### 6.1 Comparaison N1 terminee

La campagne `boussinesq_natural_n1_10km2_testbed` est la source la plus probante actuellement disponible.

Elle annonce:

- execution active;
- 8 variantes;
- 5 succes;
- 3 echecs.

Les variantes reussies sont:

- `site_03`;
- `site_05`;
- `site_06`;
- `site_07`;
- `site_08`.

Les variantes echouees sont:

- `site_01`;
- `site_02`;
- `site_04`.

La campagne est probante pour constater que des cas naturels reussissent numeriquement et que les ecarts de charge/reseau persistent malgre la convergence. Elle est aussi probante pour classer certains types d'echec de chaine.

### 6.2 Comparaison N1: difference de fermeture de surface

La configuration N1 ne compare pas deux methodes strictement identiques.

Reference MODFLOW 6:

- drainage explicite de surface;
- conductance `0.1 m2/s`;
- package DRN.

Candidat Boussinesq:

- PETSc TS VI obstacle;
- obstacle superieur actif;
- drainage configure a `0.0 m2/s`;
- reaction de contrainte reconstruite.

Le rapport d'audit ignore explicitement certains ecarts `flow.bc` attendus comme differences de methode solveur. Ce choix est legitime pour comparer des formulations candidates, mais il interdit d'interpreter les ecarts comme une simple erreur d'implementation d'une meme equation.

### 6.3 Regression PETSc VI avec drainage partage

La configuration `compare_natural_mf6_bouss_petsc_vi_base.toml` est plus proche d'une comparaison methodologique directe:

- MODFLOW 6 et Boussinesq utilisent tous deux une conductance top-drain `0.1 m2/s`;
- Boussinesq utilise `vi_obstacle`;
- la borne superieure VI est relachee lorsque la conductance positive est presente;
- l'echange de surface est donc porte par le flux de drainage.

Des artefacts de comparaison existent sous `boussinesq_petsc_vi_regression_testbed/comparisons/`, mais le rapport de testbed lui-meme indique une campagne non executee / pending. Ces artefacts sont utiles comme diagnostic local, mais ne doivent pas etre presentes comme une campagne validee complete tant que leur provenance n'est pas figee.

## 7. Resultats probants: campagne N1

### 7.1 Statut par site

| Site | Statut | Duree observee | Nature du resultat |
|---|---:|---:|---|
| site_01 | echec | 112.69 s | collision d'identifiant catalogue DuckDB |
| site_02 | echec | 234.97 s | echec numerique MODFLOW 6 stationnaire auxiliaire |
| site_03 | succes | 498.74 s | comparaison complete |
| site_04 | echec | 1534.43 s | precondition maillage / trace riviere absente |
| site_05 | succes | 407.50 s | comparaison complete |
| site_06 | succes | 492.95 s | comparaison complete |
| site_07 | succes | 462.67 s | comparaison complete |
| site_08 | succes | 2113.03 s | comparaison complete, domaine beaucoup plus grand que 10 km2 |

Remarque importante: `site_08` porte une aire d'environ 221.60 km2 dans les sorties de bilan, malgre le nom de campagne N1 10 km2. Il faut donc le considerer comme un cas naturel disponible, mais verifier son profil/catalogue avant de l'utiliser comme representant 10 km2.

### 7.2 Classification des echecs N1

#### site_01

Message principal:

`Constraint Error: Duplicate key "project: mf6_ref, name: run_0001" violates unique constraint`

Interpretation:

- echec de preparation / catalogue;
- collision de run id dans DuckDB;
- ne qualifie pas la convergence Boussinesq ni MODFLOW 6;
- necessite idempotence, nettoyage ou isolation des catalogues par variante.

#### site_02

Message principal:

`RuntimeError: MODFLOW 6 steady-state initial-condition solve failed`

Interpretation:

- echec numerique MODFLOW 6 pendant l'initialisation stationnaire auxiliaire;
- pas un echec du transitoire Boussinesq;
- indique qu'un etat stationnaire moyen peut etre difficile ou incompatible avec les parametres naturels du site;
- a investiguer via logs MODFLOW, budget, cellules seches, top drain et conditions aux limites.

#### site_04

Message principal:

`mesh_catchment.constraints_mode requires river_trace, but no in-memory river trace was generated. Ensure [geographic.river_network] is enabled with valid threshold parameters.`

Interpretation:

- echec de precondition de maillage / donnees hydrographiques;
- pas un echec de solveur;
- signale que les contraintes `geology_rivers` ne doivent pas etre activees sans trace riviere disponible.

### 7.3 Convergence Boussinesq TS VI sur sites reussis

Sur les 5 sites N1 termines, les syntheses runtime Boussinesq PETSc TS VI indiquent:

| Site | Periodes | Pas TS total | Iterations SNES totales | Iterations SNES max | Top actif max | Top actif final | Convergence |
|---|---:|---:|---:|---:|---:|---:|---|
| site_03 | 24 | 96 | 261 | 7 | 1270 | 1099 | oui |
| site_05 | 24 | 96 | 168 | 4 | 699 | 685 | oui |
| site_06 | 24 | 96 | 246 | 5 | 1048 | 939 | oui |
| site_07 | 24 | 96 | 260 | 5 | 999 | 850 | oui |
| site_08 | 24 | 96 | 369 | 8 | 9166 | 5887 | oui |

Les violations superieures et inferieures de bornes VI sont nulles dans les syntheses disponibles. Cela signifie que les cas reussis ne sont pas des cas de non-convergence Boussinesq. Au contraire, ils convergent vers une solution contrainte, avec un grand nombre de cellules actives a la contrainte de surface.

### 7.4 Fermeture de bilan

Les bilans numeriques des sites reussis sont petits en valeur absolue:

| Site | Solveur | Aire km2 | Max abs closure m3/s | Moyenne abs closure m3/s |
|---|---|---:|---:|---:|
| site_03 | Boussinesq | 15.39 | 4.76e-7 | 7.23e-8 |
| site_03 | MODFLOW 6 | 15.39 | 7.96e-8 | 4.07e-8 |
| site_05 | Boussinesq | 9.92 | 7.25e-7 | 8.14e-8 |
| site_05 | MODFLOW 6 | 9.92 | 1.19e-7 | 5.02e-8 |
| site_06 | Boussinesq | 14.58 | 2.81e-7 | 5.16e-8 |
| site_06 | MODFLOW 6 | 14.58 | 1.61e-7 | 9.25e-8 |
| site_07 | Boussinesq | 13.37 | 1.66e-6 | 1.02e-7 |
| site_07 | MODFLOW 6 | 13.37 | 2.11e-7 | 1.02e-7 |
| site_08 | Boussinesq | 221.60 | 7.60e-7 | 1.12e-7 |
| site_08 | MODFLOW 6 | 221.60 | 3.14e-8 | 9.62e-9 |

Conclusion: les ecarts de charge ne proviennent pas d'un bilan numerique manifestement divergent. Les deux familles de solveurs ferment leurs bilans a des niveaux faibles dans ces sorties.

### 7.5 Ecarts de charge en fin de simulation

Metrique `head_map_last` sur les sites N1 reussis:

| Site | Paires comparees | Biais m | MAE m | RMSE m | Max abs m | RMSE normalisee |
|---|---:|---:|---:|---:|---:|---:|
| site_03 | 1989 | 5.24 | 5.34 | 8.39 | 29.66 | 7.8% |
| site_05 | 1106 | 6.19 | 6.19 | 8.22 | 29.83 | 12.1% |
| site_06 | 1804 | 2.49 | 2.57 | 4.35 | 17.13 | 14.2% |
| site_07 | 1614 | 3.78 | 3.78 | 5.69 | 19.67 | 13.6% |
| site_08 | 33676 | 0.75 | 0.91 | 3.02 | 28.62 | 2.8% |

Ces ecarts sont materiels. Les biais sont majoritairement positifs, ce qui suggere que le champ Boussinesq est souvent plus haut que le champ MODFLOW 6 sur ces comparaisons, sauf cas plus modere `site_08`.

### 7.6 Ecarts de charge selon les dates observees

Les quatre observables de carte disponibles donnent les plages suivantes sur les 5 sites reussis:

| Observable | RMSE min m | RMSE max m | MAE min m | MAE max m | Max abs max m |
|---|---:|---:|---:|---:|---:|
| `head_map_first_computed` | 2.90 | 8.30 | 0.88 | 5.95 | 29.69 |
| `head_map_wet_year1` | 2.59 | 7.52 | 0.74 | 5.23 | 28.78 |
| `head_map_dry_late` | 2.94 | 8.20 | 0.88 | 6.03 | 29.71 |
| `head_map_last` | 3.02 | 8.39 | 0.91 | 6.19 | 29.83 |

L'ecart est persistant dans le temps. Il n'apparait pas seulement a une date isolee ou a la fin de la simulation.

### 7.7 Relation au reseau hydrographique

Les metriques de recouvrement reseau indiquent que les deux solveurs produisent des reseaux actifs imparfaitement alignes avec l'hydrographie de reference, et que Boussinesq active souvent beaucoup plus de cellules.

| Site | Solveur | Cellules actives | Cellules reseau | Coverage | Precision | F1 | Jaccard |
|---|---|---:|---:|---:|---:|---:|---:|
| site_03 | Boussinesq | 1139 | 76 | 0.59 | 0.04 | 0.07 | 0.04 |
| site_03 | MODFLOW 6 | 281 | 76 | 0.57 | 0.15 | 0.24 | 0.14 |
| site_05 | Boussinesq | 691 | 56 | 0.14 | 0.01 | 0.02 | 0.01 |
| site_05 | MODFLOW 6 | 73 | 56 | 0.09 | 0.07 | 0.08 | 0.04 |
| site_06 | Boussinesq | 965 | 60 | 0.40 | 0.02 | 0.05 | 0.02 |
| site_06 | MODFLOW 6 | 182 | 60 | 0.40 | 0.13 | 0.20 | 0.11 |
| site_07 | Boussinesq | 881 | 70 | 0.19 | 0.01 | 0.03 | 0.01 |
| site_07 | MODFLOW 6 | 119 | 70 | 0.13 | 0.08 | 0.10 | 0.05 |
| site_08 | Boussinesq | 6559 | 1053 | 0.27 | 0.04 | 0.07 | 0.04 |
| site_08 | MODFLOW 6 | 3176 | 1053 | 0.27 | 0.09 | 0.14 | 0.07 |

Interpretation:

- la couverture peut etre similaire, car un reseau actif diffus finit par croiser une partie du reseau reference;
- la precision est faible, surtout cote Boussinesq;
- Boussinesq tend a produire une activation spatiale plus diffuse;
- les deux solveurs restent faibles si l'on exige un recouvrement strict sans buffer spatial.

### 7.8 Distances au reseau

| Site | Solveur | Actives | Moyenne sim vers reseau m | Moyenne reseau vers sim m | Moyenne bidirectionnelle m | Ratio |
|---|---|---:|---:|---:|---:|---:|
| site_03 | Boussinesq | 1139 | 1099 | 7 | 553 | 160.2 |
| site_03 | MODFLOW 6 | 281 | 523 | 25 | 274 | 21.1 |
| site_05 | Boussinesq | 691 | 939 | 110 | 524 | 8.6 |
| site_05 | MODFLOW 6 | 73 | 825 | 156 | 490 | 5.3 |
| site_06 | Boussinesq | 965 | 1340 | 11 | 676 | 116.8 |
| site_06 | MODFLOW 6 | 182 | 941 | 11 | 476 | 82.9 |
| site_07 | Boussinesq | 881 | 1212 | 50 | 631 | 24.0 |
| site_07 | MODFLOW 6 | 119 | 942 | 135 | 539 | 7.0 |
| site_08 | Boussinesq | 6559 | 5161 | 71 | 2616 | 73.0 |
| site_08 | MODFLOW 6 | 3176 | 3982 | 70 | 2026 | 57.3 |

Les distances `reseau vers sim` peuvent etre faibles parce que le reseau simule est large/diffus. Les distances `sim vers reseau` montrent en revanche une forte dispersion des cellules actives hors reseau reference, surtout cote Boussinesq.

## 8. Resultats utiles mais non pleinement probants: regression PETSc VI

Des comparaisons completes existent sous le repertoire de regression PETSc VI. Elles utilisent une configuration plus proche entre solveurs, avec drainage positif partage.

Cependant, le rapport de testbed indique:

- `execute = false`;
- 6 variantes pending.

Ces artefacts doivent donc etre etiquetes comme diagnostics locaux, pas comme campagne officiellement validee.

### 8.1 Ecarts de charge en fin de simulation

| Cas | Paires | RMSE last m | Max abs last m | Convergence Boussinesq | Max substeps |
|---|---:|---:|---:|---|---:|
| headwater_100km2_outlet_2 | 4216 | 17.32 | 77.75 | oui | 4 |
| headwater_100km2_outlet_4 | 3864 | 7.67 | 52.11 | oui | 4 |
| s3_100km2_outlet_25 | 3736 | 10.59 | 93.45 | oui | 4 |
| site_01 | 1250 | 10.50 | 29.59 | oui | 4 |
| site_03 | 2033 | 9.46 | 29.66 | oui | 4 |
| site_08 | 33676 | 3.02 | 28.62 | oui | 4 |

Meme avec drainage positif partage, les ecarts de charge restent importants dans ces artefacts: RMSE de 3 m a plus de 17 m, maxima locaux de 29 m a plus de 93 m.

### 8.2 Iterations PETSc VI

| Cas | Iterations SNES totales | Iterations SNES max | Top actif max | Cellules libres finales |
|---|---:|---:|---:|---:|
| headwater_100km2_outlet_2 | 96 | 1 | 0 | 4216 |
| headwater_100km2_outlet_4 | 102 | 2 | 0 | 3864 |
| s3_100km2_outlet_25 | 111 | 2 | 0 | 3736 |
| site_01 | 212 | 18 | 0 | 1250 |
| site_03 | 449 | 22 | 0 | 2034 |
| site_08 | 632 | 24 | 0 | 33654 |

Le `Top actif max = 0` est coherent avec le relachement de l'obstacle superieur lorsque la conductance de drainage positive est active. Les ecarts residuels ne s'expliquent donc pas par une contrainte dure `h <= z_top` dans ces artefacts.

## 9. Campagnes non probantes ou planifiees

### 9.1 `boussinesq_natural_10km2_testbed`

Le rapport indique:

- `execute = false`;
- 8 variantes pending;
- 0 succes;
- 0 echec.

Il existe des repertoires de comparaison anciens ou partiels, mais ils ne doivent pas etre comptabilises comme resultats de cette campagne.

### 9.2 `boussinesq_natural_n2_100km2_testbed`

Le rapport indique:

- `execute = false`;
- 9 variantes pending.

Cette campagne est utile comme plan d'evaluation 100 km2, mais elle ne fournit pas encore de resultats probants.

### 9.3 `boussinesq_natural_n3_mesh_sensitivity_testbed`

Le rapport indique:

- `execute = false`;
- 9 variantes pending;
- variantes coarse/reference/refined prevues sur plusieurs sites.

Elle est centrale pour separer effet de methode et effet de maillage, mais elle n'a pas encore produit de resultats a retenir.

### 9.4 `boussinesq_natural_drainage_k_mesh_matrix_testbed`

Le rapport indique:

- `execute = false`;
- 6 variantes pending;
- matrice prevue sur K faible/base/fort et sites `site_01`, `site_02`.

Depuis les derniers tests, les 6 variantes ont maintenant un repertoire de comparaison avec `comparison_metrics.csv` et une page HTML de synthese locale. Le `testbed_report.md` reste toutefois en mode `execute=false` et `testbed_metrics.csv` est vide. Ces resultats doivent donc etre traites comme une execution locale de matrice, pas comme une campagne testbed officiellement cloturee. Les constats chiffres sont synthetises en section 16.

### 9.5 `boussinesq_natural_network_site_candidates_testbed`

Le rapport indique une execution active. Dans l'etat relu le 2026-05-13 soir, le `testbed_report.md` annonce 3 succes et 7 variantes pending, alors que `testbed_metrics.csv` contient 4 lignes `ok`, incluant `site_05`. Cette incoherence de statut doit etre conservee dans l'analyse.

Les repertoires de comparaison montrent plus d'information que le rapport de synthese:

- 5 comparaisons avec Boussinesq terminees ou partiellement terminees sur petits/moyens sites;
- 1 echec Boussinesq explicite sur `site_02`;
- 2 comparaisons 100 km2 avec variantes MODFLOW 6 seulement, sans Boussinesq configure;
- 1 repertoire `site_01_low_k` cree mais sans rapport ni metriques.

Ces resultats sont maintenant utiles pour qualifier les ecarts, avec les reserves de statut ci-dessus. Les chiffres sont syntheses en section 16.

## 10. Validation analytique et numerique existante

Les tests sous `tests/validation/` indiquent que le projet separe:

- validations analytiques;
- validations numeriques;
- regressions de workflow.

Les tests PETSc Boussinesq comprennent notamment:

- Dupuit stationnaire a charge imposee;
- cas numerique headwater 100 km2 stationnaire;
- cas transitoire headwater 100 km2;
- hillslope avec pulse de recharge et overflow.

Les tolerances documentees incluent:

- fermeture globale de bilan d'eau typiquement 1%;
- erreurs de pente de recession Boussinesq / Marcais inferieures a 5%;
- RMSE Dupuit fixe de l'ordre de quelques centimetres selon solveur;
- tolerances specifiques pour diffusion transitoire sur maillage triangulaire irregulier.

Ces tests sont importants: ils montrent que les formulations Boussinesq PETSc peuvent converger et verifier des proprietes controlees. En revanche, ils ne prouvent pas l'equivalence Boussinesq / MODFLOW 6 sur cas naturels heterogenes, drainage de surface, topographie complexe et maillage contraint geologie/rivieres.

## 11. Qualification des ecarts observes

### 11.1 Les ecarts ne sont pas de simples non-convergences

Sur les sites N1 reussis:

- Boussinesq TS VI converge;
- les bornes VI sont respectees;
- les bilans sont faibles;
- MODFLOW 6 termine;
- les ecarts de charge restent de plusieurs metres.

Cela oriente l'analyse vers des differences de formulation et de parametrisation plutot que vers une divergence numerique brute.

### 11.2 Les ecarts de charge sont grands

Les RMSE de charge en fin de simulation sont:

- environ 3.0 m au mieux dans N1;
- environ 8.4 m au pire dans N1 terminee;
- jusqu'a environ 17.3 m dans les artefacts PETSc VI 100 km2;
- maxima locaux de 17 m a 30 m dans N1;
- maxima locaux jusqu'a 93 m dans les artefacts 100 km2.

Ce niveau d'ecart est incompatible avec une simple tolerance solveur `1e-4` ou avec les biais centimetriques connus sur certains cas analytiques.

### 11.3 Les ecarts reseau indiquent une activation trop diffuse

Boussinesq active souvent beaucoup plus de cellules de sortie/release que MODFLOW 6:

- site_03: 1139 vs 281;
- site_05: 691 vs 73;
- site_06: 965 vs 182;
- site_07: 881 vs 119;
- site_08: 6559 vs 3176.

La precision reseau Boussinesq est faible. Le modele semble couvrir une partie du reseau naturel mais avec beaucoup de faux positifs spatiaux. Cette signature est compatible avec:

- fermeture de surface par obstacle/reaction trop diffuse;
- seuil de detection de flux trop permissif;
- parametrisation K/Sy/recharge non calibree;
- effet de maillage et topographie;
- differences entre flux de drainage DRN et reaction VI.

### 11.4 Les ecarts persistent dans le temps

Les metriques aux dates `first_computed`, `wet_year1`, `dry_late` et `last` restent du meme ordre. Cela suggere une difference structurelle de dynamique et/ou d'etat, pas seulement un transitoire initial mal amorti.

## 12. Hypotheses principales sur l'origine des differences

### 12.1 Fermeture de surface non equivalente

C'est l'hypothese la plus importante pour la campagne N1.

MODFLOW 6:

- drain explicite a `z_top`;
- conductance `0.1 m2/s`;
- charge pouvant depasser le drain avec flux proportionnel.

Boussinesq TS VI N1:

- contrainte dure ou quasi dure `h <= z_top`;
- drainage configure a zero;
- reaction de surface reconstruite apres resolution.

Ces deux modeles peuvent produire des nappes et des flux de surface tres differents, meme avec memes K, recharge et maillage.

### 12.2 Schema spatial different

Boussinesq:

- volume fini centre cellule;
- flux a deux points;
- transmissivite calculee par epaisseur saturee moyenne;
- sensibilite possible aux triangles non orthogonaux.

MODFLOW 6:

- DISV;
- NPF;
- XT3D probablement actif;
- formulation de cellule convertible propre a MODFLOW.

La difference TPFA / XT3D peut devenir significative sur topographie naturelle, heterogeneite geologique et maillage contraint.

### 12.3 Stockage et saturation differents

Boussinesq:

- stockage proportionnel a `max(h - z_bottom, 0)`;
- transmissivite plafonnee par `z_top`;
- reactions de surface selon methode choisie.

MODFLOW 6:

- STO convertible;
- saturation et transmissivite gerees par les options MODFLOW;
- drainage explicite par DRN.

Les equations discretes ne sont pas strictement identiques dans les zones proches du toit ou du fond.

### 12.4 Initialisation differente

MODFLOW 6 peut utiliser une initialisation stationnaire auxiliaire. Au moins un site naturel echoue a cette etape. Si l'etat initial differe entre solveurs, les cartes aux premieres dates et meme les dynamiques ulterieures peuvent diverger.

La persistence des ecarts suggere toutefois que l'initialisation n'est pas la seule cause.

### 12.5 Parametrisation non calibree

La comparaison utilise:

- K par table geologique demonstrative;
- Sy uniforme;
- Ss uniforme;
- recharge synthetique;
- pas de calibration conjointe K/Sy/recharge/drainage.

Il est donc normal que les reseaux actifs ne correspondent pas finement a l'hydrographie naturelle. Cette limite affecte les deux solveurs, mais peut amplifier differemment leurs ecarts.

### 12.6 Metriques reseau severes

Les metriques actuelles semblent utiliser une logique de recouvrement stricte. En milieu naturel, un decalage lateral d'une ou deux tailles de maille peut faire chuter la precision et le Jaccard. Les distances bidirectionnelles compensent partiellement, mais une analyse avec buffers multi-echelles serait necessaire.

### 12.7 Robustesse de workflow

Plusieurs echecs ne sont pas numeriques:

- collision de catalogue;
- absence de trace riviere;
- campagnes pending;
- sorties anciennes dans des repertoires non executes.

Ces points peuvent brouiller l'analyse si les resultats sont agreges sans controle du statut de campagne.

## 13. Ce qui est prouve, probable ou non prouve

### 13.1 Prouve par les artefacts actuels

- La campagne N1 a 5 comparaisons completes et 3 echecs.
- Les 5 comparaisons N1 terminees montrent une convergence Boussinesq TS VI.
- Les bilans des cas termines sont faibles.
- Les ecarts de charge entre Boussinesq et MODFLOW 6 sont de l'ordre du metre a plusieurs metres en RMSE.
- Les maxima locaux sont de l'ordre de plusieurs dizaines de metres.
- Boussinesq active plus de cellules de release que MODFLOW 6 dans les cas N1 reussis.
- Au moins un echec naturel vient de l'initialisation stationnaire MODFLOW 6.
- Au moins deux echecs naturels viennent du workflow et non de la physique solveur.
- Les derniers artefacts candidats reseau montrent aussi des cas a ecart faible lorsque Boussinesq et MODFLOW 6 sont compares a meme maillage: RMSE `head_map_last` de 0.47 a 0.87 m sur `site_03_low_k`, `site_01` et `site_05`.
- Des echecs Boussinesq naturels sont maintenant documentes, notamment `SolverDivergedError` sur `site_02_natural_network_site_candidates` et sur plusieurs variantes de la matrice K/drainage.
- Les echecs Boussinesq inspectes sur `site_02` et dans la matrice K/drainage surviennent pendant un calcul stationnaire auxiliaire (`steady_head_balance`) avant execution des periodes transitoires; les diagnostics de plusieurs variantes echouees indiquent `total_periods = 0` et aucun sous-pas transitoire execute.
- La matrice K/drainage montre que le changement de maillage peut produire des RMSE de 16 a 24 m meme entre deux variantes MODFLOW 6 ou entre une variante Boussinesq et la reference, ce qui isole un effet maillage/support tres important.
- L'effet maillage peut dominer l'effet solveur: sur `site_01_k_base`, Boussinesq vs MODFLOW 6 a meme maillage est autour de 0.54-0.60 m de RMSE, alors que le changement vers un maillage triangulaire quasi uniforme donne environ 16 m de RMSE pour Boussinesq comme pour MODFLOW 6.

### 13.2 Probable mais a confirmer

- La fermeture de surface explique une part importante des ecarts N1.
- Les differences de discretisation TPFA / DISV+XT3D contribuent aux ecarts spatiaux.
- Les differences de support de maillage, surtout conformite geologie/rivieres contre maillage quasi uniforme ou structure, expliquent probablement une part majeure des grands ecarts de carte.
- La non-convergence Boussinesq documentee semble probablement liee en premier lieu a l'initialisation stationnaire, a l'active set VI, au drainage de surface et au conditionnement du probleme, plus qu'au pas de temps transitoire seul.
- La calibration absente et la K geologique demonstrative amplifient les differences de reseau.
- Les artefacts PETSc VI indiquent que les ecarts persistent meme avec drainage partage, mais cette conclusion doit etre confirmee par une campagne executee proprement.
- La variante drainage 0.01 semble parfois plus robuste que drainage 0 ou 0.1 dans la matrice K/drainage, mais ce n'est pas universel.
- A K10 sur `site_01`, les formulations Boussinesq qui convergent donnent des ecarts tres proches; cela suggere que le choix de formulation n'est pas le facteur dominant dans ce scenario precis.

### 13.3 Non prouve actuellement

- Il n'est pas prouve que Boussinesq diverge generalement sur les cas naturels; il est seulement prouve qu'il diverge sur certains couples site/K/drainage/methode.
- Il n'est pas prouve que MODFLOW 6 soit toujours la reference numerique correcte dans ces configurations.
- Il n'est pas prouve que les ecarts viennent d'une seule cause.
- Il n'est pas prouve que le raffinement de maillage reduise ou augmente les ecarts, car la campagne N3 est pending.
- Il n'est pas prouve qu'un pas de temps transitoire trop long soit la cause principale des echecs Boussinesq actuels; il faut un balayage de sous-pas a condition initiale controlee pour le demontrer.
- Il n'est pas prouve que la matrice K/drainage resolve les ecarts au sens campagne officielle, car le `testbed_report.md` correspondant reste pending, meme si des artefacts locaux existent.

## 14. Programme d'investigation recommande

### 14.1 Separer convergence et equivalence

Les prochains rapports devraient toujours distinguer:

- echec de preparation;
- echec maillage/geographie;
- echec initialisation MODFLOW 6;
- echec solveur transitoire MODFLOW 6;
- echec solveur Boussinesq;
- convergence avec ecart de methode;
- convergence avec ecart faible.

Un site qui converge avec RMSE 8 m n'est pas un echec de convergence. C'est un echec d'equivalence ou de calibration.

### 14.2 Rejouer la comparaison a drainage partage

Priorite elevee:

- utiliser la configuration PETSc VI avec drainage positif cote Boussinesq et MODFLOW 6;
- figer un catalogue propre;
- executer officiellement les 6 variantes PETSc VI;
- produire un `testbed_report.md` avec succes/echecs;
- comparer aux resultats N1 obstacle dur.

Objectif: isoler l'effet "obstacle superieur sans drainage" vs "drainage top explicite".

### 14.3 Consolider la matrice drainage / K / maillage

La matrice `natural_drainage_k_mesh_matrix` a ete executee localement et produit des metriques exploitables. Elle doit maintenant etre consolidee en campagne propre pour tester sans artefacts residuels:

- K faible/base/forte;
- drainage faible/base/fort;
- effet sur RMSE de charge;
- effet sur reseau actif;
- effet sur convergence MODFLOW 6 stationnaire.

Les resultats actuels sont deja informatifs, mais ils melangent des sorties fraiches, des repertoires reutilises et des statuts testbed encore `execute=false`. Une relance propre devra supprimer les enfants retires de la matrice, refaire les catalogues et produire un `testbed_report.md` coherent.

### 14.4 Executer la sensibilite maillage N3

La campagne N3 coarse/reference/refined est indispensable pour qualifier:

- erreur de discretisation Boussinesq TPFA;
- effet de XT3D cote MODFLOW 6;
- stabilite des reseaux actifs;
- convergence des ecarts de charge avec raffinement.

### 14.5 Ajouter des empreintes methodologiques dans chaque rapport

Chaque comparaison devrait imprimer explicitement:

- methode Boussinesq (`regularized_partition`, `complementarity`, `vi_obstacle`, `ts_vi_obstacle`);
- backend (`local`, `scipy`, `petsc`);
- bornes VI effectives;
- conductance top-drain effective;
- nombre de substeps;
- type SNES/KSP/PC;
- MODFLOW Newton on/off;
- XT3D on/off;
- rewet on/off;
- tolerances IMS;
- methode d'initialisation.

Sans cette empreinte, les comparaisons naturelles sont difficiles a auditer a posteriori.

### 14.6 Renforcer les preflights

Avant execution lourde:

- verifier unicite catalogue/run id;
- verifier presence de `river_trace` si `constraints_mode = geology_rivers`;
- verifier hydrographie exploitable;
- tester initialisation stationnaire MODFLOW 6 seule;
- detecter domaines dont l'aire ne correspond pas a la famille de campagne;
- refuser ou etiqueter les sorties anciennes si `execute=false`.

### 14.7 Ajouter une calibration Boussinesq exploitable

La note de calibration indique que l'extraction Boussinesq pour calibration n'est pas implementee. Tant que cette extraction manque, la calibration reseau/transitoire privilegie MODFLOW 6.

Pour analyser les differences, il faudrait pouvoir calibrer ou au moins extraire de maniere comparable:

- cartes de charge;
- flux de drainage;
- release/saturation excess;
- hydrogrammes;
- metriques reseau natives.

### 14.8 Tester l'hypothese pas de temps sans la confondre avec l'initialisation

Les echecs Boussinesq actuellement inspectes se produisent avant le transitoire. Le test du pas de temps doit donc isoler l'initialisation de la dynamique.

Plan recommande:

- rejouer les variantes echouees avec une condition initiale imposee simple (`top`, `top_offset` ou champ issu d'une variante convergee) pour savoir si le transitoire VI echoue encore;
- rejouer l'initialisation stationnaire seule, avec recharge moyenne rampee et diagnostics PETSc conserves meme en cas d'echec;
- balayer `vi_substeps_per_period = 4, 8, 16, 32` sur une meme condition initiale;
- activer ou verifier le chemin `vi_substep_on_failure = true`, `vi_max_adaptive_substeps = 32` et enregistrer la premiere periode/sous-periode echouee;
- tester une rampe de recharge sur 2 a 4 periodes de warm-up avant la serie mensuelle;
- comparer les raisons PETSc, les residus projetes VI, les cellules actives top/fond et les violations de bornes.

Si un cas echoue a 4 sous-pas puis converge a 16 ou 32 sous-pas avec la meme condition initiale, l'hypothese "pas de temps trop grand" deviendra probante. Si l'echec reste dans le solveur stationnaire ou persiste avec 32 sous-pas, il faudra privilegier l'initialisation, la fermeture de surface, le drainage, le maillage ou le conditionnement.

### 14.9 Tester une continuation K / drainage / recharge

Les echecs actuels ressemblent davantage a une perte de robustesse du chemin non lineaire qu'a une absence demontree de solution. Un test de continuation permettrait de le verifier.

Plan recommande:

- partir d'un cas convergent proche, par exemple `site_01_k_base` ou `site_02_k_low` avec conductance intermediaire;
- augmenter progressivement `K` vers la valeur cible en reutilisant chaque solution convergee comme condition initiale de l'etape suivante;
- balayer ensuite la conductance de drainage de la meme maniere, de la valeur intermediaire vers `0` ou `0.1 m2/s`;
- tester aussi une rampe de recharge moyenne avant la recharge mensuelle complete;
- enregistrer a chaque etape le residu PETSc, les cellules actives top/fond, les cellules sous le fond, les depassements de `z_top` et les flux de drainage.

Si la continuation converge alors que le lancement direct diverge, le probleme principal est l'initialisation et le chemin de Newton/VI. Si elle diverge au meme seuil de `K`, drainage ou recharge, il faudra chercher une limite plus structurelle du modele discret, du maillage ou de la fermeture de surface.

## 15. Questions de recherche a approfondir ailleurs

1. Quelle est la relation theorique exacte entre une contrainte obstacle `h <= z_top` avec reaction reconstruite et un drainage Cauchy type DRN a conductance finie?
2. Pour quelles conductances DRN la solution MODFLOW 6 tend-elle vers la solution obstacle dure?
3. Quel est l'impact quantitatif de XT3D par rapport a un flux a deux points sur triangles naturels non orthogonaux?
4. Comment MODFLOW 6 STO convertible traite-t-il exactement la saturation et le stockage pres du toit par rapport a la formulation Boussinesq `Sy * max(h - z_bottom, 0)`?
5. Les ecarts de charge se concentrent-ils sur les zones de surface active, les limites, les interfaces geologiques ou les fonds de vallee?
6. Les maxima locaux de 30 a 90 m correspondent-ils a des artefacts de topographie, des cellules seches, des bords, ou des zones de K contraste?
7. Quelle metrique reseau est robuste a un decalage lateral de 1 a 3 mailles?
8. Le raffinement de maillage reduit-il l'ecart Boussinesq / MODFLOW 6 ou revele-t-il une difference structurelle?
9. Une calibration conjointe K/Sy/drainage peut-elle rapprocher les deux solveurs, ou les ecarts persistent-ils a parametres ajustes?
10. L'echec MODFLOW 6 stationnaire auxiliaire de `site_02` disparait-il avec Newton principal, rewetting, drainage different, charge initiale differente ou forcage moyen modifie?

## 16. Mise a jour des derniers tests

Cette section ajoute les sorties presentes dans le depot le 2026-05-13 soir apres la premiere redaction du rapport. Elles doivent etre lues avec une nuance importante: plusieurs repertoires de comparaison contiennent des metriques exploitables alors que les `testbed_report.md` de niveau campagne restent parfois `execute=false`, `pending`, ou incoherents avec les CSV de metriques.

### 16.1 Candidats reseau naturel

Repertoire:

`examples/projects/10_testbed_workflow/outputs/boussinesq_natural_network_site_candidates_testbed/`

Etat de synthese:

- `testbed_report.md`: `execute=true`, 10 variantes, 3 succes, 0 echec, 7 pending;
- `testbed_metrics.csv`: 4 lignes `ok` (`site_01`, `site_02`, `site_03`, `site_05`);
- incoherence: `site_05` est `planned` dans le rapport mais `ok` dans le CSV de metriques;
- plusieurs repertoires de comparaison additionnels existent, y compris des low-K et des 100 km2.

Statut observe dans les rapports de comparaison:

| Cas | Simulations completees | Statut Boussinesq meme maillage | Commentaire |
|---|---:|---|---|
| `site_01` | 5 / 5 | completed | comparaison complete |
| `site_02` | 4 / 5 | failed | echec Boussinesq |
| `site_03` | 4 / 5 | completed | Boussinesq ok, une variante MF6 reguliere echoue |
| `site_05` | 5 / 5 | completed | comparaison complete, statut testbed incoherent |
| `site_02_low_k` | 5 / 5 | completed | comparaison complete low-K |
| `site_03_low_k` | 5 / 5 | completed | comparaison complete low-K |
| `headwater_100km2_outlet_2` | 3 / 3 | non configure | variantes MODFLOW 6 seulement |
| `s3_100km2_outlet_25` | 3 / 3 | non configure | variantes MODFLOW 6 seulement |
| `site_01_low_k` | n/a | n/a | repertoire cree sans rapport/metriques |

Ces comparaisons ont une structure differente de N1. La reference est `mf6_unstructured_reference`, et les candidats peuvent inclure:

- `bouss_unstructured_same_mesh`;
- `mf6_regular_120`;
- `mf6_regular_180`;
- `mf6_unstructured_350m`.

Elles testent donc a la fois l'effet solveur Boussinesq/MODFLOW 6 et l'effet discretisation/maillage.

#### 16.1.1 Ecarts de charge Boussinesq meme maillage

Metrique `head_map_last`, `bouss_unstructured_same_mesh` versus `mf6_unstructured_reference`:

| Cas | Paires | Biais m | MAE m | RMSE m | Max abs m | RMSE normalisee |
|---|---:|---:|---:|---:|---:|---:|
| `site_01` | 1221 | 0.02 | 0.36 | 0.54 | 6.22 | 1.14% |
| `site_03_low_k` | 2032 | -0.05 | 0.22 | 0.47 | 6.35 | 0.47% |
| `site_05` | 1040 | 0.27 | 0.43 | 0.87 | 10.87 | 1.57% |
| `site_03` | 1805 | -0.59 | 1.33 | 3.03 | 30.01 | 3.36% |
| `site_02_low_k` | 13212 | -0.12 | 13.85 | 19.84 | 87.59 | 18.95% |

Lecture:

- l'ecart peut etre tres inferieur a N1 lorsque la comparaison est faite a meme maillage et avec une configuration plus alignee;
- `site_01`, `site_03_low_k` et `site_05` donnent des RMSE inferieurs a 1 m;
- `site_03` reste a environ 3 m, avec un maximum local de 30 m;
- `site_02_low_k` est un contre-exemple majeur: RMSE 19.84 m malgre convergence Boussinesq.

Ce resultat change la conclusion pratique: les ecarts metres a dizaines de metres ne sont pas inevitables, mais ils dependent fortement du site, du K, du maillage et de la fermeture de surface.

Dans cette table, les lignes `site_01`, `site_03_low_k` et `site_05` sont les plus importantes pour qualifier l'effet maillage: elles montrent que, a support triangulaire contraint identique, l'ecart Boussinesq/MODFLOW 6 peut etre inferieur a 1 m de RMSE. Ce niveau est tres different des 8-17 m cites dans les comparaisons N1/PETSc VI moins alignees, et des 16-24 m observes lors des changements de support de maillage. Le cas `site_02_low_k` rappelle toutefois que le meme maillage ne garantit pas l'equivalence: le site et les parametres peuvent encore produire un ecart fort.

#### 16.1.2 Convergence Boussinesq TS VI sur candidats reseau

Synthese des diagnostics `bouss_unstructured_same_mesh__ts_vi_obstacle_runtime_summary.json`:

| Cas | Periodes | Pas TS | Iterations SNES totales | Iterations SNES max | Top actif max | Top actif final | Convergence |
|---|---:|---:|---:|---:|---:|---:|---|
| `site_01` | 24 | 96 | 280 | 8 | 81 | 32 | oui |
| `site_02_low_k` | 24 | 96 | 340 | 8 | 2631 | 1113 | oui |
| `site_03_low_k` | 24 | 96 | 279 | 6 | 301 | 151 | oui |
| `site_03` | 24 | 96 | 311 | 6 | 84 | 47 | oui |
| `site_05` | 24 | 96 | 255 | 6 | 27 | 20 | oui |

Les violations superieures et inferieures sont nulles dans ces diagnostics. Le cas `site_02_low_k` est notable: il converge numeriquement, mais avec beaucoup de cellules actives a la contrainte de surface et un ecart de charge tres eleve.

#### 16.1.3 Echec Boussinesq sur `site_02`

Le cas nominal `site_02_natural_network_site_candidates` contient un echec Boussinesq explicite:

- simulation `bouss_unstructured_same_mesh`: failed;
- exception: `SolverDivergedError`;
- etape: `run_solver`;
- solveur signale dans le resume Boussinesq: `petsc_partition_snes`;
- formulation: `regularized_partition`;
- regime du solveur echoue: `steady`;
- residu infini final: environ `8.0e-5`;
- tolerance demandee: `1e-6`;
- raison PETSc: `SNES_DIVERGED_LINE_SEARCH`;
- cellules sous le fond dans le diagnostic: 114;
- cellules actives au seuil de surface: 5811, soit environ 43.9% des cellules.

Ce point est nouveau par rapport a la premiere synthese: il existe maintenant un echec numerique Boussinesq naturel documente. Il se produit dans un solveur stationnaire regularise, probablement lie a une initialisation ou a une phase de preparation du transitoire, et non dans un diagnostic TS VI abouti.

#### 16.1.4 Metriques reseau sur candidats reseau

Metriques `release_flux_network_overlap_metrics.csv` pour les cas avec Boussinesq et MF6 reference:

| Cas | Solveur | Actives | Reseau | Coverage | Precision | F1 | Jaccard |
|---|---|---:|---:|---:|---:|---:|---:|
| `site_01` | MF6 ref | 39 | 42 | 0.00 | 0.00 | 0.00 | 0.00 |
| `site_01` | Bouss | 58 | 42 | 0.00 | 0.00 | 0.00 | 0.00 |
| `site_02_low_k` | MF6 ref | 1449 | 1102 | 0.30 | 0.23 | 0.26 | 0.15 |
| `site_02_low_k` | Bouss | 1412 | 1100 | 0.29 | 0.22 | 0.25 | 0.14 |
| `site_02` | MF6 ref | 490 | 1105 | 0.10 | 0.23 | 0.14 | 0.08 |
| `site_03_low_k` | MF6 ref | 178 | 76 | 0.39 | 0.17 | 0.24 | 0.13 |
| `site_03_low_k` | Bouss | 186 | 76 | 0.37 | 0.15 | 0.21 | 0.12 |
| `site_03` | MF6 ref | 49 | 76 | 0.05 | 0.08 | 0.06 | 0.03 |
| `site_03` | Bouss | 52 | 76 | 0.01 | 0.02 | 0.02 | 0.01 |
| `site_05` | MF6 ref | 22 | 56 | 0.00 | 0.00 | 0.00 | 0.00 |
| `site_05` | Bouss | 22 | 56 | 0.00 | 0.00 | 0.00 | 0.00 |

Lecture:

- contrairement a N1, Boussinesq n'active pas systematiquement beaucoup plus de cellules que MODFLOW 6 dans ces candidats reseau;
- sur `site_02_low_k` et `site_03_low_k`, les scores Boussinesq sont proches de MF6 reference;
- les scores absolus restent faibles, ce qui confirme que la comparaison au reseau hydrographique naturel reste tres sensible au seuil, au buffer spatial et a l'absence de calibration.

### 16.2 Matrice drainage / K / maillage

Repertoire:

`examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/`

Etat de synthese:

- execution locale terminee par `run_natural_drainage_k_mesh_matrix_chain.py`;
- 6 variantes de site/K traitees: `site_01_k_low`, `site_01_k_base`, `site_01_k_high`, `site_02_k_low`, `site_02_k_base`, `site_02_k_high`;
- page de synthese locale: `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/web_synthesis/index.html`;
- les 6 repertoires de comparaison contiennent `comparison_metrics.csv`;
- tous les audits sont en statut `warn`, principalement a cause des changements de maillage, d'ecarts de recharge persistee et de depassements locaux du toit;
- `testbed_report.md` reste toutefois `execute=false` et `testbed_metrics.csv` reste vide: ces resultats sont donc des metriques locales consolidees, pas encore une campagne testbed officiellement cloturee.

Statut par comparaison:

| Cas | Datasets de charge exploitables | Statut notable |
|---|---:|---|
| `site_01_k_base` | 6 / 6 | toutes les variantes presentes |
| `site_01_k_low` | 5 / 6 | `bouss_tri_irregular_drain_00` absent des metriques exploitables; origine workflow/catalogue dans les traces anterieures |
| `site_01_k_high` | 3 / 6 | seuls `mf6_tri_irregular_drain_01`, `bouss_tri_irregular_drain_001` et `mf6_tri_uniform_rivers_drain_01` sont exploitables |
| `site_02_k_low` | 4 / 6 | `bouss_tri_irregular_drain_00` et `bouss_tri_irregular_drain_01` non exploitables |
| `site_02_k_base` | 3 / 6 | seules les variantes MF6 et `bouss_tri_uniform_rivers_drain_01` sont exploitables |
| `site_02_k_high` | 2 / 6 | seules les deux variantes MF6 sont exploitables; toutes les variantes Boussinesq sont non exploitables |

#### 16.2.1 Ecarts de charge dans la matrice

Metrique `head_map_last`, reference `mf6_tri_irregular_drain_01`. Ici `bouss_tri_irregular_drain_001` signifie drainage Boussinesq `0.01 m2/s`.

| Cas | Simulation | Paires | Biais m | MAE m | RMSE m | Max abs m |
|---|---|---:|---:|---:|---:|---:|
| `site_01_k_base` | `bouss_tri_irregular_drain_00` | 1221 | 0.02 | 0.36 | 0.54 | 6.22 |
| `site_01_k_base` | `bouss_tri_irregular_drain_001` | 1221 | 0.14 | 0.40 | 0.60 | 6.22 |
| `site_01_k_base` | `bouss_tri_irregular_drain_01` | 1221 | 0.04 | 0.36 | 0.55 | 6.22 |
| `site_01_k_low` | `bouss_tri_irregular_drain_001` | 1250 | 0.18 | 0.40 | 0.68 | 3.70 |
| `site_01_k_low` | `bouss_tri_irregular_drain_01` | 1250 | 0.13 | 0.39 | 0.66 | 3.61 |
| `site_01_k_high` | `bouss_tri_irregular_drain_001` | 912 | 1.41 | 2.40 | 3.43 | 13.62 |
| `site_02_k_low` | `bouss_tri_irregular_drain_001` | 13210 | -0.06 | 0.93 | 2.45 | 28.51 |

Lecture:

- lorsque le maillage triangulaire contraint est conserve et que la variante Boussinesq converge, l'ecart peut etre faible, surtout sur `site_01`;
- la conductance 0, 0.01 et 0.1 donne des resultats proches sur `site_01_k_base` lorsque les trois variantes convergent;
- `site_01_k_high` degrade nettement l'accord, meme pour la variante qui converge;
- `site_02_k_low` converge avec RMSE 2.45 m, bien inferieur au `site_02_low_k` des candidats reseau, mais avec un maximum local encore eleve.

#### 16.2.2 Effet du maillage uniforme/rivieres

Les variantes `bouss_tri_uniform_rivers_drain_01` et `mf6_tri_uniform_rivers_drain_01`, comparees a la reference `mf6_tri_irregular_drain_01`, donnent des RMSE beaucoup plus elevees lorsque les sorties sont exploitables:

| Cas | Simulation | RMSE m | Max abs m |
|---|---|---:|---:|
| `site_01_k_base` | Bouss uniforme/rivieres | 16.04 | 47.52 |
| `site_01_k_base` | MF6 uniforme/rivieres | 16.01 | 47.80 |
| `site_01_k_low` | Bouss uniforme/rivieres | 19.73 | 55.71 |
| `site_01_k_low` | MF6 uniforme/rivieres | 19.68 | 56.18 |
| `site_01_k_high` | MF6 uniforme/rivieres | 16.19 | 48.32 |
| `site_02_k_base` | Bouss uniforme/rivieres | 20.33 | 74.60 |
| `site_02_k_base` | MF6 uniforme/rivieres | 20.33 | 79.08 |
| `site_02_k_high` | MF6 uniforme/rivieres | 19.30 | 75.91 |
| `site_02_k_low` | Bouss uniforme/rivieres | 24.07 | 87.84 |
| `site_02_k_low` | MF6 uniforme/rivieres | 24.14 | 90.19 |

Cette table est importante: le changement de maillage peut produire des ecarts du meme ordre pour Boussinesq et pour MODFLOW 6. Il ne faut donc pas attribuer automatiquement tout RMSE eleve au solveur Boussinesq. Une partie peut venir du support spatial, des contraintes geologie/rivieres et de l'alignement des cellules.

Caracterisation de la difference de maillage dans cette matrice:

- reference `tri_irregular_geology_rivers`: maillage triangulaire contraint par geologie et rivieres, taille globale 130 m, taille minimale 45 m, raffinement d'interfaces actif, taille locale d'interface 70 m;
- variante `tri_quasi_uniform_rivers_180m`: maillage triangulaire seulement contraint par les rivieres, taille globale 180 m, taille minimale 180 m, raffinement d'interfaces desactive, donc pas de conformite fine aux contacts geologiques;
- dans cette version consolidee, les variantes structurees `120 x 120` et `180 x 180` ont ete retirees de la matrice par defaut, car elles melangeaient trop fortement effet support cartesien, resampling et cout de calcul.

Le changement de support reduit fortement le nombre de cellules communes:

| Site | Reference triangulaire contrainte | Quasi-uniforme rivieres |
|---|---:|---:|
| `site_01` | 1250 cellules | 534 cellules |
| `site_02` | environ 13214-13236 cellules | environ 5708-5722 cellules |

Le contraste quantitatif est fort. Sur `site_01_k_base`, les variantes Boussinesq a meme maillage triangulaire contraint donnent environ 0.54-0.60 m de RMSE, alors que le passage au maillage triangulaire quasi uniforme donne environ 16.0 m, pour Boussinesq comme pour MODFLOW 6. Le facteur d'augmentation est d'environ 25 a 30. Sur `site_02_k_low`, la variante Boussinesq triangulaire contrainte qui converge donne 2.45 m de RMSE, tandis que le maillage quasi uniforme donne environ 24.1 m, soit un facteur proche de 10.

#### 16.2.3 Flux, audits et limites de lecture

Les metriques de flux confirment le meme diagnostic mais avec une amplitude plus faible que les charges. Sur `release_flux_map_last`, les variantes Boussinesq a meme maillage ont des RMSE normalisees typiquement de l'ordre de 1.7 a 4.8% dans les cas exploitables (`site_01_k_base`, `site_01_k_low`, `site_01_k_high`, `site_02_k_low`). Le passage au maillage quasi uniforme augmente ces ecarts, souvent vers 5.5 a 20% selon site et solveur.

Les audits `warn` ne doivent pas etre ignores:

- les ecarts de recharge persistee sont modestes dans plusieurs cas (`site_01_k_base` environ 1.4-2.0%, `site_02_k_high` environ 1.9% pour MF6 uniforme), mais peuvent monter a 26.3% sur `site_01_k_high` pour `bouss_tri_irregular_drain_001`;
- les comparaisons de maillage declenchent logiquement des alertes `mesh_hash` et `n_cells`;
- plusieurs sorties Boussinesq ont des cellules ou la charge depasse localement `z_top`, surtout en periode humide: environ 5 a 23% des cellules selon cas, avec des maxima typiques de 0.1 a 1.6 m.

Ces alertes n'expliquent pas a elles seules les RMSE de charge de 16-24 m des variantes quasi uniformes. Elles reduisent en revanche la confiance dans les cas K fort et confirment que la fermeture de surface reste un levier a auditer finement.

#### 16.2.4 Echecs Boussinesq, initialisation et hypothese du pas de temps

Echecs identifies:

| Cas | Simulation | Type / indice |
|---|---|---|
| `site_01_k_low` | `bouss_tri_irregular_drain_00` | absent des metriques exploitables; verrou DuckDB concurrent observe dans les traces anterieures |
| `site_01_k_high` | `bouss_tri_irregular_drain_00` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~1.1e-3 |
| `site_01_k_high` | `bouss_tri_irregular_drain_01` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~1.7e-4 |
| `site_01_k_high` | `bouss_tri_uniform_rivers_drain_01` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~3.0e-4 |
| `site_02_k_low` | `bouss_tri_irregular_drain_00` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~1.9 |
| `site_02_k_low` | `bouss_tri_irregular_drain_01` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~1.4 |
| `site_02_k_base` | `bouss_tri_irregular_drain_00` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~9.3 |
| `site_02_k_base` | `bouss_tri_irregular_drain_001` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~1.4e-1 |
| `site_02_k_base` | `bouss_tri_irregular_drain_01` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~1.4 |
| `site_02_k_high` | `bouss_tri_irregular_drain_00` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~34 |
| `site_02_k_high` | `bouss_tri_irregular_drain_001` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~1.4e-1 |
| `site_02_k_high` | `bouss_tri_irregular_drain_01` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~1.4 |
| `site_02_k_high` | `bouss_tri_uniform_rivers_drain_01` | Boussinesq stationnaire PETSc: `SNES_DIVERGED_LINE_SEARCH`, residu ~1.3 |

La matrice etablit donc une vraie limite de robustesse Boussinesq sur certains couples site/K/drainage. Elle montre aussi que la variante drain 0.01 peut etre plus robuste dans plusieurs cas, mais pas universellement (`site_02_k_base` et `site_02_k_high` echouent aussi a 0.01). Les echecs documentes se produisent sur l'etat stationnaire auxiliaire Boussinesq/PETSc, avant de pouvoir interpreter un transitoire complet.

Ce point est important pour l'hypothese "pas de temps trop long". Dans les variantes echouees inspectees, les fichiers de diagnostic VI indiquent `total_periods = 0`, `failed_periods = [0]`, `max_substeps_used = 0` et `substep_diagnostic_count = 0`. Le solveur ne s'est donc pas encore engage dans une periode mensuelle ni dans les sous-pas Backward Euler du transitoire. Le blocage observe est un probleme stationnaire de condition initiale, pas un echec demontre d'un sous-pas transitoire.

Les variantes convergentes utilisent pourtant la meme structure temporelle transitoire: 24 periodes mensuelles et `vi_substeps_per_period = 4`, soit des sous-pas internes d'environ 7 a 8 jours. Dans les cas `vi_obstacle`, `vi_substep_on_failure = true` et `vi_max_adaptive_substeps = 32` sont configures, mais les variantes convergentes comme `site_02_k_low / bouss_tri_irregular_drain_001` n'ont pas eu besoin d'utiliser le sous-pas adaptatif. Le contraste entre conductances 0, 0.01 et 0.1, a discretisation temporelle comparable, pointe donc davantage vers l'initialisation stationnaire, l'active set VI, le drainage de surface et le conditionnement du systeme que vers le pas de temps seul.

Le pas de temps reste un facteur aggravant possible apres initialisation. Les sauts mensuels de recharge peuvent deplacer rapidement les cellules actives, surtout a faible K. Mais il manque encore un test probant montrant qu'un cas echoue en transitoire a 4 sous-pas puis converge a 8, 16 ou 32 sous-pas avec la meme condition initiale.

#### 16.2.5 Lecture mecanique des divergences Boussinesq

Les diagnostics disponibles pointent vers une divergence de solveur non lineaire, pas vers une explosion physique directe des charges. La raison PETSc dominante est `SNES_DIVERGED_LINE_SEARCH`: Newton propose une correction, mais la recherche de pas ne trouve pas de deplacement qui reduise suffisamment le residu projete. Le calcul est alors arrete avant d'obtenir un etat initial stationnaire acceptable.

Le mecanisme probable est le suivant:

- la formulation Boussinesq head-only rend la transmissivite dependante de la charge par l'epaisseur saturee;
- pres de `z_bottom`, l'epaisseur saturee tend vers zero et l'operateur devient mal conditionne;
- pres de `z_top`, l'obstacle VI, le drainage de type `max(h - z_top, 0)` et les reactions de surface introduisent des changements brusques de regime;
- sur les sites naturels, beaucoup de cellules peuvent basculer simultanement entre regime libre, contraint en surface, draine ou presque sec;
- lorsque `K` augmente, les flux internes et les reactions de drainage deviennent plus forts, donc le systeme stationnaire devient plus raide;
- sur les maillages contraints par geologie et rivieres, les petits elements, les voisinages irreguliers, les contrastes de K et les fortes pentes locales amplifient ce conditionnement.

Cette lecture explique plusieurs observations:

- `site_01` converge a K faible/base mais devient fragile a K fort;
- `site_02` est plus difficile que `site_01`, avec des echecs meme a K faible/base selon drainage et maillage;
- le maillage quasi uniforme peut aider `site_02` a K faible/base, ce qui incrimine une partie du maillage contraint naturel;
- a K fort, meme les maillages plus simples peuvent echouer, ce qui incrimine aussi la raideur hydraulique et pas seulement le maillage;
- la conductance intermediaire peut etre plus robuste que `0` ou `0.1 m2/s`, ce qui suggere une transition numeriquement delicate entre obstacle dur et drainage fort.

La consequence pratique est importante: relancer seulement avec plus de sous-pas transitoires ne traitera probablement pas ces echecs si l'etat stationnaire auxiliaire echoue avant la premiere periode. Les leviers prioritaires sont plutot l'initialisation, la continuation progressive de `K`/drainage/recharge, la regularisation des transitions sec/sature/surface, et la cartographie des cellules responsables du residu au dernier Newton.

### 16.3 Sensibilites PETSc VI sur `site_01`

Repertoire:

`examples/projects/10_testbed_workflow/outputs/boussinesq_petsc_vi_regression_testbed/sensitivity_runs/`

Ces sorties sont hors `testbed_report.md` principal, qui reste `execute=false`, mais elles documentent des tests methodologiques utiles sur `site_01`.

Statut:

| Cas | Audit | Simulations completees | Statut Boussinesq |
|---|---|---:|---|
| `site_01_bouss_constraint` | pass | 2 / 2 | completed |
| `site_01_k3` | pass | 2 / 2 | completed |
| `site_01_k10_natural` | pass | 1 / 2 | failed |
| `site_01_k10_regularized_petsc` | pass | 1 / 2 | failed |
| `site_01_k10_regularized_scipy_sparse` | warn | 2 / 2 | completed |
| `site_01_k10_complementarity_petsc` | warn | 2 / 2 | completed |
| `site_01_k10_ts_vi_petsc` | warn | 2 / 2 | completed |

Metrique `head_map_last`, `bouss_candidate` versus `mf6_ref`:

| Cas | Paires | Biais m | MAE m | RMSE m | Max abs m |
|---|---:|---:|---:|---:|---:|
| `site_01_bouss_constraint` | 1250 | 7.38 | 7.48 | 10.50 | 29.59 |
| `site_01_k3` | 1241 | 10.20 | 10.28 | 13.65 | 29.77 |
| `site_01_k10_regularized_scipy_sparse` | 1124 | 10.21 | 10.71 | 14.69 | 29.90 |
| `site_01_k10_complementarity_petsc` | 1124 | 10.28 | 10.73 | 14.70 | 29.90 |
| `site_01_k10_ts_vi_petsc` | 1124 | 10.29 | 10.74 | 14.70 | 29.90 |

Lecture:

- augmenter K dans ces variantes ne reduit pas l'ecart avec MODFLOW 6; l'ecart augmente plutot de 10.50 m a 13.65-14.70 m de RMSE;
- a K10, trois formulations tres differentes qui convergent donnent quasiment le meme RMSE et le meme maximum local;
- deux variantes Boussinesq echouent (`site_01_k10_natural`, `site_01_k10_regularized_petsc`);
- la proximite des RMSE entre regularise scipy sparse, complementarite PETSc et TS VI PETSc suggere que, dans ce scenario K10, le choix de formulation Boussinesq n'est pas le facteur dominant de l'ecart de charge.

### 16.4 Effet sur la qualification generale

Les derniers tests renforcent six points:

1. La non-convergence Boussinesq existe bien sur certains cas naturels, mais elle n'est pas generale. Plusieurs simulations Boussinesq TS VI ou VI convergent avec diagnostics propres.
2. Quand maillage, drainage et support spatial sont bien alignes, l'accord Boussinesq/MODFLOW 6 peut etre bien meilleur que dans N1: RMSE inferieur a 1 m sur plusieurs cas.
3. Les grands ecarts ne sont pas uniquement un probleme de solveur: le changement de maillage peut produire des RMSE de 16 a 24 m aussi bien pour Boussinesq que pour MODFLOW 6 par rapport a une reference triangulaire contrainte.
4. La difference majeure entre les maillages n'est pas seulement la taille moyenne des cellules: c'est aussi la conformite aux interfaces geologiques, la conformite au reseau riviere, le raffinement local, le graphe de voisinage et la maniere dont K/topographie/recharge sont projetes sur les cellules.
5. Les divergences Boussinesq inspectees s'expliquent le mieux par un probleme non lineaire raide et non lisse: cellules proches de `z_bottom`/`z_top`, active set surface/fond instable, interaction obstacle-drainage, K eleve et maillage naturel contraint.
6. Les echecs Boussinesq inspectes sont pour l'instant des echecs stationnaires d'initialisation, pas des echecs transitoires attribuables directement a un pas de temps mensuel trop grand.

La conclusion operationnelle change donc legerement: il ne faut plus dire seulement "les cas naturels ne convergent pas" ou "Boussinesq diverge". Il faut dire que la convergence et l'accord dependent fortement du triplet site / K-drainage / maillage, avec des zones de robustesse et des zones d'echec clairement identifiees.

## 17. Conclusion

L'etat actuel montre une chaine capable de produire des comparaisons naturelles completes, mais pas encore une equivalence fiable Boussinesq / MODFLOW 6 sur cas naturels.

Les cas termines ne soutiennent pas l'idee d'une non-convergence Boussinesq generale. Les derniers tests montrent une situation plus nuancee: certaines configurations Boussinesq convergent avec des ecarts faibles a meme maillage, certaines convergent avec des ecarts tres forts, et certaines echouent explicitement par `SolverDivergedError`. Une partie des ecarts N1 reste probablement attendue car les fermetures de surface comparees ne sont pas identiques.

Pour les echecs inspectes, l'explication la plus directe n'est pas encore un pas de temps transitoire trop long. Les diagnostics pointent vers l'etat stationnaire auxiliaire Boussinesq/PETSc, avec divergence de ligne de recherche avant execution des periodes transitoires. Il faut donc d'abord tester l'initialisation et les active sets stationnaires, puis seulement isoler l'effet des sous-pas transitoires.

Le mecanisme probable est une perte de robustesse du Newton/VI dans un probleme tres contraint: nombreuses cellules proches du fond ou du toit, changement brutal d'active set, drainage non lisse au seuil de surface, forte transmissivite lorsque `K` augmente, et conditionnement degrade par certains maillages naturels. La verification la plus directe consiste a utiliser une continuation progressive de `K`, du drainage et de la recharge, avec reutilisation des solutions convergentes comme conditions initiales.

Le point le plus explicite des derniers tests est l'effet du support de maillage. A maillage triangulaire contraint identique, plusieurs comparaisons Boussinesq/MODFLOW 6 descendent sous 1 m de RMSE. En changeant le support vers un maillage quasi uniforme seulement contraint par les rivieres, ou vers des supports cartesien/structures dans les essais precedents, les ecarts peuvent devenir un ordre de grandeur plus grands. Les differences futures doivent donc etre presentees au minimum selon deux axes separes: effet solveur a maillage fixe et effet maillage a solveur fixe.

Le point le plus critique pour la suite est de rejouer des campagnes propres ou la fermeture de surface est alignee:

- drainage top positif des deux cotes;
- obstacle Boussinesq relache comme prevu;
- catalogue propre;
- preflight maillage;
- rapport de statut sans artefacts anciens.

Ensuite seulement, les ecarts residuels pourront etre attribues plus solidement a la discretisation, au stockage, aux conditions aux limites, a la calibration ou a des choix propres a MODFLOW 6. La matrice locale consolidee montre en particulier qu'il faudra isoler l'effet maillage avant de conclure sur l'effet solveur.
