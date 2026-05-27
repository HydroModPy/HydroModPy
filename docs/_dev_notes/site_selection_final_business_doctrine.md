# Doctrine metier finale - `site_selection`

Date: 2026-05-26

Statut: doctrine court terme finale pour les profils stabilises.

Ce document fixe la doctrine metier finale du chantier court terme
`site_selection`. Il complete le contrat court terme et l'etat
d'implementation: il dit ce que le workflow promet au metier, ce qu'il ne
promet pas, et comment interpreter les decisions produites.

## Decision centrale

`site_selection` est un workflow amont de choix de bassins candidats.

Il sert a preparer une campagne de modelisation en produisant:

- des bassins candidats delimites;
- une decision finale par candidat;
- des preuves et composants de criteres auditables;
- un catalogue de sites selectionnes pour les workflows aval;
- un manifest officiel de transfert.

Il ne valide pas un modele hydrologique, ne lance pas de simulation, ne calibre
pas de parametres et ne remplace pas `regional_lab`, `testbed`, `comparison` ou
`calibration`.

La separation metier finale est:

```text
site_selection choisit et explique les bassins
regional_lab croise des sites selectionnes avec des recettes
testbed execute les variantes numeriques
comparison compare les resultats
calibration ajuste les parametres
```

## Vocabulaire normatif

- Un `candidat` est un exutoire ou un bassin propose avant decision finale.
- Un `bassin delimite` est un candidat pour lequel la delimitation amont a
  produit une surface et, quand disponible, une geometrie de bassin.
- Un `site selectionne` est un bassin delimite qui passe les criteres actifs et
  la selection spatiale finale.
- Un `site rejete` est un candidat bloque par la delimitation, un critere
  metier ou une regle de selection spatiale.
- Une `preuve` est une observation ou un croisement spatial source, par exemple
  station de debit, piezometre, influence anthropique ou geologie.
- Un `composant de critere` est l'evaluation auditable d'une regle sur un site.
- Une `decision finale` est le resume stable consomme par les outils aval.
- Le `site_selection_manifest.json` est le contrat officiel de transfert.

La decision finale ne doit jamais etre consideree comme un score opaque. Elle
est la consequence explicable des composants de criteres et des preuves
disponibles.

## Profils metier stabilises

Deux profils sont stabilises pour le court terme.

### `area_only`

Objectif metier: selectionner des bassins selon une plage ou une cible de
surface.

La surface est l'axe actif. Les observations, la geologie, la piezometrie et les
influences peuvent etre exportees comme information, mais elles ne pilotent pas
ce profil sauf evolution explicite et separee.

Modes d'entree stabilises:

- `site_selection.input.mode = "dem_area_light"` pour generer un nombre borne
  de candidats depuis le DEM autour d'une surface cible;
- `site_selection.input.mode = "delineated_catchments"` pour rejouer un
  catalogue ou une fixture de bassins deja delimites.

Regles metier:

- un echec de delimitation rejette le candidat;
- une surface hors plage rejette le candidat quand `area.mode = "hard_reject"`;
- une cible de surface peut contribuer au classement quand la configuration le
  demande;
- les bassins redondants peuvent etre ecartes par recouvrement, distance entre
  exutoires, plafond global ou quota spatial;
- les couches absentes de contexte ou d'observation ne rejettent pas un bassin.

### `gauged_downstream_station`

Objectif metier: selectionner des bassins jauges dont l'exutoire candidat est
porte par une station de debit aval.

La station de debit est l'objet metier principal. Elle fournit le point de
depart, permet de delimiter le bassin et sert a verifier que l'exutoire final
reste coherent avec l'observation.

Mode d'entree stabilise:

- `site_selection.input.mode = "hydrometry"` avec
  `candidate_mode = "station_outlets"`.

`delineated_catchments` reste accepte pour les catalogues figes et les tests,
mais ce n'est pas le chemin metier cible.

Regles metier:

- un echec de delimitation rejette le candidat;
- la distance station-exutoire est evaluee sur l'exutoire final affiche, y
  compris apres snap DEM;
- la longueur de chronique peut etre bloquante si configuree;
- la coherence station dans le bassin ou a l'exutoire peut etre bloquante si
  configuree;
- une surface peut etre bloquante ou seulement informative selon la campagne;
- une influence majeure ne rejette que si une preuve explicite est fournie et
  si la configuration la rend bloquante.

BD Topage ou un reseau custom peuvent contraindre le placement de l'exutoire
avant le snap local DEM. Ce reseau est une aide de localisation, pas une preuve
que le bassin contient ce reseau et pas un substitut a la delimitation DEM.

## Doctrine de selection finale

La selection finale intervient apres delimitation et evaluation des criteres.
Elle sert a eviter une liste finale redondante ou concentree.

Ordre logique:

```text
candidats delimites
-> rejet des echecs structurels
-> evaluation des criteres metier
-> classement deterministe
-> plafond global optionnel
-> controle de recouvrement
-> distance minimale entre exutoires
-> quota spatial optionnel
-> decision finale auditee
```

Les regles de selection spatiale sont des criteres auditables. Elles produisent
des composants comme:

- `target_count` quand le nombre maximal de sites selectionnes est atteint;
- `basin_overlap` quand un bassin recouvre trop un bassin deja retenu;
- `outlet_spacing` quand deux exutoires sont trop proches;
- `spatial_quota` quand une cellule de quota spatial est deja pleine.

Le classement doit rester deterministe. A score comparable, les avertissements
et l'identifiant stable servent a rendre le resultat reproductible.

Le quota spatial est une regle de repartition simple. Ce n'est pas une
optimisation hydrologique globale, ni une garantie de representativite
statistique.

## Doctrine des preuves

Une absence de donnee n'est pas une preuve negative.

Par defaut:

- absence de couche d'influence: pas de rejet pour influence;
- absence de couche piezometrique: pas de rejet piezometrique;
- absence de geologie: pas de rejet geologique;
- influence inconnue dans les metadonnees station: neutre, sauf politique
  explicite d'avertissement.

Un rejet metier exige toujours:

- une preuve ou une valeur mesurable;
- un critere configure comme bloquant;
- une raison exportee dans les decisions.

Cas particulier Hub'Eau hydrometrie:

- `station_influence` exploite les metadonnees du referentiel station;
- les seuls champs pouvant justifier un rejet dur sont
  `influence_generale_site` et `influence_locale_station`, quand ils indiquent
  explicitement une influence;
- `unknown_policy = "neutral"` signifie que l'absence de champ, le champ vide
  ou le statut inconnu ne rejette pas la station;
- les commentaires et les mots-cles detectes dans ces commentaires sont des
  alertes de revue. Ils ne sont pas une preuve suffisante pour rejeter;
- ce controle qualifie la station, pas le bassin entier. Une preuve spatiale
  d'ouvrage en amont devra venir d'une couche `influence` ou d'un futur
  provider ROE.

Les preuves normalisees sont ecrites comme `EvidenceRecord` dans
`site_selection_evidence.jsonl` quand elles existent. Les composants de criteres
sont ecrits dans `criteria_components.jsonl`. Les decisions normalisees sont
ecrites dans `site_selection_decisions.jsonl` et
`site_selection_decisions.csv`.

## Doctrine des sorties

Le manifest est la source de verite.

Les workflows aval doivent recevoir le chemin du manifest et y resoudre la
sortie voulue, en particulier `regional_lab_sites_csv`. Ils ne doivent pas
dependre d'un chemin CSV recopie a la main.

Sorties minimales d'un run de selection:

- `site_selection_manifest.json`;
- `criteria_components.jsonl`;
- `site_selection_decisions.csv`;
- `site_selection_decisions.jsonl`;
- `site_selection_evidence.jsonl` quand des preuves existent;
- `selected_sites.csv`;
- `rejected_sites.csv`;
- `regional_lab_sites.csv`;
- `selected_outlets.geojson`;
- `rejected_outlets.geojson`;
- `selected_basins.geojson`;
- `rejected_basins.geojson`.

Le rapport HTML est une vue de controle derivee du manifest. Il ne doit pas
devenir une deuxieme source de verite ni porter de logique metier non presente
dans les sorties d'audit.

## Doctrine de configuration

Une campagne stabilisee doit declarer clairement:

- le profil metier explicite pour les campagnes hydrometriques;
- le territoire;
- les donnees d'entree;
- les criteres actifs;
- les options de selection spatiale finale;
- les sorties attendues.

Pour `area_only`, les observations et la geologie restent en `report_only` ou
equivalent non bloquant. Pour `gauged_downstream_station`, la configuration doit
porter `principle = "observation_led"`,
`profile = "gauged_downstream_station"`,
`primary_observation_type = "flow_station"` et
`candidate_mode = "station_outlets"`.

Les TOML sans profil explicite ne font plus partie de la doctrine stabilisee.

## Hors doctrine finale

Les sujets suivants ne font pas partie de la doctrine metier finale court terme:

- generation hydrographique avancee par confluences, sous-bassins ou ordre de
  Strahler;
- selection automatique nationale comme produit metier stabilise;
- optimisation multi-objectif globale;
- carte interactive;
- provider ROE pour obstacles;
- provider BNPE pour prelevements;
- chargement ADES complet;
- qualite eau et intermittence comme criteres fournisseurs;
- execution de simulations depuis `site_selection`.

Ces sujets peuvent etre ouverts comme evolutions separees. Ils ne doivent pas
changer l'interpretation des deux profils stabilises.

## Regle d'arbitrage

En cas de doute, appliquer cette hierarchie:

1. Le manifest et les fichiers d'audit sont la verite operationnelle.
2. Une decision doit etre explicable par des composants de criteres.
3. Une preuve absente ne rejette pas un site.
4. Le profil metier decide quels criteres pilotent la selection.
5. `site_selection` prepare les sites; les workflows aval jugent les modeles.

La cible finale du chantier court terme est donc:

```text
site_selection sait produire ou relire des candidats,
delimiter les bassins,
selectionner proprement les meilleurs selon des regles explicites,
et expliquer chaque decision dans des sorties auditables.
```
