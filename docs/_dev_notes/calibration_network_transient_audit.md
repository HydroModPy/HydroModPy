# Audit prospectif - calibration conjointe reseau permanent et debit transitoire

Date: 2026-05-12

Statut: note de cadrage preparatoire. Ce document ne decrit pas encore une
recette operationnelle stabilisee. Il sert a expliciter ce qui est deja
possible dans le code, ce qui est proche, et ce qui demanderait une extension
avant de lancer des campagnes naturelles.

## 1. Question posee

L'objectif est d'evaluer la possibilite de calibrer un modele HydroModPy avec
deux familles d'information en meme temps:

- un reseau hydrographique en regime permanent, typiquement un reseau actif ou
  une emprise de drainage simulee a comparer a une reference hydrographique;
- une chronique de debit en regime transitoire, typiquement `Q(t)` a
  l'exutoire ou a une station hydrometrique.

La question n'est pas seulement de savoir si un optimiseur peut minimiser deux
metriques. La vraie difficulte est de definir un objectif composite qui melange:

- une information spatiale, souvent binaire ou quasi-binaire: la riviere est
  active ici, absente ailleurs, trop courte, trop longue, decalee, mal
  connectee;
- une information temporelle continue: debit, decrue, amplitude saisonniere,
  phase, volume;
- potentiellement deux simulations par candidat: une simulation permanente
  pour le reseau, puis une simulation transitoire pour le debit.

La strategie recommandee est de commencer par des cas synthetiques generes par
nous-memes, dans l'esprit testbed/twin experiment, avant de passer aux bassins
naturels.

Choix de cadrage retenu pour la suite: viser la version ambitieuse du
probleme inverse. Un meme vecteur de parametres `theta = {K, Sy}` doit etre
evalue sur deux scenarios numeriques distincts:

```text
theta = {K, Sy}
  -> scenario A: regime permanent, score de reseau hydrographique actif
  -> scenario B: regime transitoire, score de chronique de debit Q(t)
  -> objectif composite unique
```

Pour le premier testbed, `S` est donc fixe explicitement a `Sy`: le stockage
drainable/rendement specifique d'une nappe libre. `Ss` ou un coefficient
d'emmagasinement equivalent restent des extensions possibles, mais pas la
cible initiale.

## 2. Conclusion courte

Le principe est scientifiquement coherent et l'architecture actuelle de
calibration est proche de ce qu'il faut, mais la version ambitieuse retenue
(`K` et `Sy` calibres conjointement sur deux scenarios) n'est pas encore
complete en "pure TOML, sans code specifique":

```text
theta = {K, Sy}
  -> une simulation permanente notee par une metrique de reseau
  -> une simulation transitoire notee par une metrique de debit
  -> un objectif composite unique
```

Ce qui existe deja:

- un moteur de calibration `prepare-once-evaluate-many`;
- des optimiseurs (`grid`, `random_search`, `optuna`, `cma_es`,
  `scipy_nelder_mead`, `scipy_de`, `gp_mapping`, `da_mh_gp` selon
  disponibilite);
- un schema `CalibrationConfig` avec `parameters`, `outputs` et
  `objective_blocks`;
- des objectifs composites ponderes avec normalisation par bloc;
- des extracteurs legers pour MODFLOW-NWT et MODFLOW 6 sur charge/debit;
- des sorties Boussinesq deja riches dans les runtimes et rapports:
  historiques d'etat, flux de drainage, diagnostics PETSc/VI;
- des cas de validation synthetiques "twin" deja orientes tete/flux et
  permanent/transitoire.

Ce qui manque ou reste incomplet:

- un type d'observable calibration pour carte/reseau (`support = "map"` ou
  `support = "network"`);
- une metrique native de similarite de reseau hydrographique;
- un scenario de calibration multi-run, ou un candidat declenche a la fois une
  simulation permanente et une simulation transitoire;
- un extracteur standard pour le solveur `boussinesq`;
- un filtrage propre par identifiant de boundary dans les extracteurs
  legers MODFLOW, au-dela du debit global DRAIN deja disponible.

Donc:

- a tres court terme, le choix retenu est de partir en Boussinesq seul, pour
  profiter de runs rapides et evaluer directement la robustesse du solveur
  cible;
- cela impose de brancher en priorite un extracteur Boussinesq leger pour les
  flux, les charges et les cartes de drainage;
- avec ce developpement cible, on peut ajouter une metrique reseau sur une
  seule simulation candidate;
- avec un developpement plus structurant, on peut faire la calibration
  conjointe stricte "permanent reseau + transitoire debit".

## 3. Etat actuel dans le code

### 3.1. Calibration generale

La calibration standard passe par:

- `hydromodpy/calibration/config.py`;
- `hydromodpy/calibration/runner.py`;
- `hydromodpy/calibration/runners/trial.py`;
- `hydromodpy/calibration/objective.py`;
- `hydromodpy/calibration/metrics.py`.

Le fonctionnement est deja le bon pour une campagne inverse:

1. la configuration complete est chargee;
2. les etapes couteuses sont preparees une fois;
3. chaque essai fork le contexte prepare;
4. les valeurs de parametres sont injectees par chemin TOML;
5. le solveur est lance en mode leger;
6. l'objectif est extrait en RAM;
7. les iterations sont persistantes dans DuckDB;
8. les meilleurs essais peuvent etre promus en simulations completes.

Cette organisation est favorable a une calibration sur plusieurs observables,
car on ne veut pas reconstruire MNT, maillage, hydrographie et donnees a chaque
iteration.

### 3.2. Objectifs composites

Le schema enrichi permet deja ceci:

```toml
[calibration.outputs.head_mid]
variable = "head"
support = "point"
x = "200 m"
y = "25 m"
time = "all"
observed_values = [1.0, 1.1, 1.2]

[calibration.outputs.q_outlet]
variable = "outlet_discharge"
support = "boundary"
boundary_id = "east_side"
time = "all"
observed_values = [0.02, 0.03, 0.025]

[[calibration.objective_blocks]]
name = "heads"
metric = "rmse"
weight = 1.0
uses_outputs = ["head_mid"]
normalize_cost = true

[[calibration.objective_blocks]]
name = "flux"
metric = "rmse"
weight = 1.0
uses_outputs = ["q_outlet"]
normalize_cost = true
```

Le mecanisme conceptuel est donc deja present: chaque bloc produit un cout,
les poids sont normalises, et le total est minimise.

Limite importante: ce schema sait declarer `point`, `cell`, `boundary`, mais
pas encore `map` ou `network`. Or le reseau hydrographique permanent est plutot
une observable spatiale.

### 3.3. Debit transitoire

Le chemin historique de calibration sur `variable = "discharge"` existe. Il lit
les observations depuis `hydrometry`, lit le debit simule depuis les budgets
DRAIN MODFLOW, aligne observation/simulation, puis calcule `rmse`, `mae`,
`nse` ou `kge`.

Le code ajoute aussi le ruissellement charge depuis la couche data quand il est
disponible. C'est important car le DRAIN MODFLOW represente plutot une
composante de drainage/baseflow; une station hydrometrique mesure souvent un
debit total.

Points d'attention:

- le debit extrait en calibration legere est aujourd'hui un total DRAIN, pas
  un debit par troncon hydrographique;
- le support `boundary` du schema composite demande un `boundary_id`, mais les
  adaptateurs MODFLOW legers actuels ne filtrent pas encore proprement par
  `boundary_id`;
- la chronique de debit est donc mieux couverte par le chemin legacy
  `variable = "discharge"` que par le chemin composite `outputs.boundary`,
  sauf metric function specifique.

Pour le plan Boussinesq seul, il ne faut pas dependre de ce chemin legacy
MODFLOW. La premiere implementation peut passer par une `metric_fn` dediee qui
lit directement les historiques Boussinesq, calcule `Q_sim(t)` et retourne
`C_debit_phys`. Une fois ce prototype stabilise, on pourra le faire rentrer
dans le contrat standard d'extraction calibration.

### 3.4. Reseau hydrographique permanent

HydroModPy sait deja produire et comparer des sorties liees au reseau:

- reseau hydrographique issu du MNT;
- hydrographie de reference chargee depuis la couche data;
- champs `outflow_drain` et `accumulation_flux`;
- figures de reseau actif simule;
- rapports de comparaison MF6/Boussinesq ou MF6/NWT.

Mais ces objets ne sont pas encore exposes comme observable de calibration
standard. Aujourd'hui ils servent plutot a la simulation, a la comparaison, au
diagnostic et aux rapports.

Pour calibrer sur le reseau, il faudrait transformer ces produits en un cout
scalaire utilisable dans la boucle inverse.

### 3.5. Boussinesq

Le solveur `boussinesq` produit des grandeurs utiles, notamment charge et flux
de drainage. En revanche, le contrat calibration standard ne sait pas encore
extraire ces series depuis le scratch Boussinesq:

```text
Boussinesq calibration extraction is not implemented
```

Cela ne veut pas dire que la calibration Boussinesq est impossible en theorie.
Cela veut dire qu'il manque l'adaptateur qui lirait, par exemple:

- `drainage_flux_history_m3_s`;
- `head` ou `watertable_elevation`;
- les etats transitoires sauvegardes;
- les flux agreges sur un support de reseau.

Le choix de planification retenu ici est maintenant different: commencer avec
Boussinesq seul. Cela demande un petit developpement d'extraction, mais c'est
coherent avec l'objectif de robustesse:

- les evaluations seront plus rapides qu'une campagne MF6 equivalente;
- on teste directement le solveur que l'on veut rendre operationnel;
- on evite de confondre le premier test inverse avec une comparaison de modele
  MF6/Boussinesq;
- les echecs eventuels seront informatifs sur la stabilite numerique, les
  sorties disponibles et l'identifiabilite `K/Sy` dans la formulation cible.

La limite est claire: un twin Boussinesq -> Boussinesq ne teste pas l'erreur de
modele. Il teste d'abord la robustesse de l'objectif, de l'extraction et de
l'inversion dans le moteur cible. Les comparaisons MF6 restent utiles ensuite,
mais comme validation externe, pas comme premiere verite synthetique.

## 4. Definition possible des deux observables

### 4.1. Observable reseau en permanent

Il faut choisir ce que l'on appelle "reseau hydrographique calibre".
Possibilites, de la plus simple a la plus exigeante:

| Niveau | Observable | Metrique possible | Interet | Risque |
| --- | --- | --- | --- | --- |
| R0 | Longueur active totale | erreur relative | Tres robuste | Peu informatif spatialement |
| R1 | Masque actif/inactif sur cellules ou aretes | Jaccard, F1, precision/rappel | Simple et lisible | Sensible aux petits decalages |
| R2 | Distance au reseau reference | distance moyenne, distance quantile | Tolere les decalages modestes | Demande raster/vector robuste |
| R3 | Flux accumule par cellule/troncon | RMSE log, Spearman, KGE spatial | Utilise l'intensite du drainage | Depend de l'agregation |
| R4 | Topologie | nombre de sources, connexite, longueur par ordre | Physiquement riche | Plus fragile a optimiser |

Pour un testbed synthetique, le meilleur premier choix est R1 + R2:

- R1 donne une metrique binaire claire;
- R2 evite de punir excessivement un reseau legerement decale;
- les deux peuvent etre calculees sur une grille ou sur les aretes d'un maillage.

Un cout reseau minimal pourrait etre:

```text
cost_network =
  w_mask * (1 - jaccard(active_sim, active_ref))
  + w_dist * mean_distance_to_reference(active_sim, active_ref) / L_ref
```

Pour une version flux:

```text
cost_network_flux = rmse(log1p(accumulation_flux_sim), log1p(accumulation_flux_ref))
```

### 4.2. Observable debit en transitoire

Le debit transitoire peut etre score de plusieurs facons:

| Niveau | Observable | Metrique possible | Role |
| --- | --- | --- | --- |
| Q0 | Debit total `Q(t)` | KGE, NSE, RMSE normalise | Ajustement global |
| Q1 | Debit log `log(Q)` | RMSE log, KGE log | Recessions et basses eaux |
| Q2 | Volume cumule | erreur relative volume | Bilan hydrologique |
| Q3 | Pente de recession | diagnostic ou contrainte separee | Exclusion physique eventuelle |
| Q4 | Pics ou saisonnalite | erreur sur date/amplitude | Timing, recharge/runoff |

Pour commencer, il faut rester simple:

```text
cost_Q = 1 - KGE(Q_sim, Q_ref)
```

ou, pour un cas synthetique bruite:

```text
cost_Q = RMSE(Q_sim, Q_ref) / std(Q_ref)
```

Le code sait deja faire cette transformation de score en cout pour `nse` et
`kge`.

### 4.3. Normalisation physique et ponderation

La ponderation `w_reseau` / `w_debit` ne doit pas servir a corriger les
unites. Les unites doivent etre eliminees avant, par une normalisation
physique. Ensuite seulement les poids expriment une priorite scientifique ou
une confiance relative dans les deux references synthetiques.

La forme cible est:

```text
J(theta) =
  w_reseau * C_reseau_phys(theta)
  + w_debit  * C_debit_phys(theta)

avec theta = {K, Sy}
et w_reseau + w_debit = 1
```

ou `C_reseau_phys` et `C_debit_phys` sont deja des couts sans dimension
normalises par des erreurs physiquement acceptables. Une valeur proche de 1
doit signifier: "le candidat atteint la limite d'erreur acceptable pour ce
bloc".

#### Principe progressif de construction des couts

La normalisation doit etre construite avant la calibration. Sinon les facteurs
de normalisation deviennent eux-memes des parametres caches et l'objectif perd
son sens physique. La sequence a retenir est:

```text
observable physique
  -> erreur physique E_k
  -> seuil acceptable eta_k
  -> cout elementaire c_k = E_k / eta_k
  -> cout de bloc C = sum_k a_k * c_k
```

Un cout elementaire `c_k = 1` signifie que l'erreur atteint exactement le
seuil accepte pour cette composante. Un cout elementaire `c_k = 0.2` signifie
que l'erreur ne vaut que 20 % de cette tolerance. Un cout elementaire `c_k = 3`
signifie que le candidat depasse trois fois l'erreur physique jugee acceptable.

Les poids internes `a_k` ou `b_k` ne remplacent donc pas les `eta_k`. Les
`eta_k` definissent l'echelle physique d'acceptabilite. Les poids internes
expriment seulement l'importance relative des composantes une fois qu'elles
sont toutes exprimees en nombre de tolerances. Avec `sum a_k = 1`, un bloc
`C = 1` se lit comme une erreur moyenne egale au seuil physique du bloc.

Cette lecture reste vraie seulement si les diagnostics elementaires sont aussi
conserves. Un `C` moyen peut masquer une composante tres mauvaise compensee par
une autre tres bonne. Le rapport de calibration devrait donc toujours afficher:

```text
c_flux, c_dist, c_len, C_reseau_phys
c_Q_forme, c_Q_lame, c_Q_bilan, C_debit_phys
```

et pas seulement `J`.

#### Normalisation figee pendant l'inversion

Oui: la normalisation ne doit pas changer en cours de simulation, ni d'un
candidat a l'autre pendant la calibration. Elle est definie une fois pour le
testbed, a partir de la reference synthetique, de la fenetre temporelle choisie
et des tolerances physiques retenues.

Concretement, les grandeurs suivantes sont fixees avant de lancer l'inversion:

```text
reseau permanent:
  q_ref_i, R_ref, Q_ref_steady, L_ref, d_tol
  eta_flux, eta_dist, eta_len
  a_flux, a_dist, a_len

debit transitoire:
  Q_ref(t), V_ref, Qbar_ref, T, pas de temps / poids temporels
  eta_Q_forme, eta_Q_lame, eta_Q_bilan
  b_forme, b_lame, b_bilan

objectif conjoint:
  w_reseau = 0.5
  w_debit  = 0.5
```

Ensuite, pour chaque candidat `theta = {K, Sy}`, seules les sorties simulees
changent: `q_sim_i`, `R_sim`, `L_sim`, `Q_sim(t)`. Les denominateurs et les
seuils de normalisation restent ceux de la reference. C'est indispensable pour
que deux candidats soient compares sur la meme echelle.

Si l'on change la fenetre temporelle, la chronique de recharge, la maille, le
seuil de detection du reseau, ou le bassin, alors il faut recalculer les
normalisations une fois pour ce nouveau cas. Mais a l'interieur d'un meme
probleme inverse, elles restent figees.

#### Normalisation du reseau

Le reseau ne doit pas etre score seulement par un Jaccard de pixels. Il faut
donner plus de poids aux erreurs qui deplacent ou perdent du drainage
significatif. Pour un premier testbed, on peut partir des flux de drainage du
run permanent:

```text
q_ref_i = drainage permanent de reference sur la cellule/arete i
q_sim_i = drainage permanent simule sur la cellule/arete i
Q_ref_steady = sum_i q_ref_i
```

Trois erreurs physiques sont utiles:

```text
E_flux =
  sum_i abs(q_sim_i - q_ref_i) / Q_ref_steady

E_dist =
  [sum_i q_sim_i * d(i, R_ref) + sum_i q_ref_i * d(i, R_sim)]
  / [2 * d_tol * Q_ref_steady]

E_len =
  abs(L_sim - L_ref) / L_ref
```

- `E_flux` mesure une fraction du drainage permanent mal reproduite.
- `E_dist` mesure une distance moyenne de mauvais placement, ponderee par le
  flux de drainage. `d_tol` est la largeur de corridor acceptable: une largeur
  de vallee synthetique, une incertitude cartographique, ou 1 a 2 tailles de
  maille dans le premier cas. Le denominateur utilise `Q_ref_steady`, pas le
  flux total du candidat, afin que la normalisation reste fixe pendant
  l'inversion.
- `E_len` mesure l'erreur de longueur active.

On transforme ensuite ces erreurs en couts normalises par seuils
d'acceptabilite:

```text
C_reseau_phys =
  a_flux * E_flux / eta_flux
  + a_dist * E_dist / eta_dist
  + a_len  * E_len  / eta_len

a_flux + a_dist + a_len = 1
```

Valeurs de depart raisonnables pour un cas synthetique:

```text
eta_flux = 0.05 a 0.10    # 5-10 % du drainage permanent
eta_dist = 1.0            # deplacement moyen egal a d_tol
eta_len  = 0.10           # 10 % d'erreur de longueur active

a_flux = 0.4
a_dist = 0.4
a_len  = 0.2
```

Lecture progressive des facteurs de normalisation du reseau:

1. `eta_flux` fixe la tolerance sur la repartition spatiale du drainage
   permanent. Il ne s'agit pas d'une tolerance sur le debit total seulement:
   `sum_i abs(q_sim_i - q_ref_i)` penalise aussi un flux deplace d'une branche
   a une autre. Pour un twin experiment sans bruit, on pourrait descendre vers
   1-2 %, mais ce serait surtout tester la reproductibilite numerique. Pour un
   testbed robuste aux effets de maille, de seuil de drainage et de solveur,
   5-10 % est plus defendable. Si la recharge synthetique elle-meme est
   perturbee, `eta_flux` doit etre au moins de l'ordre de cette incertitude de
   bilan.

2. `d_tol` fixe l'echelle physique d'un mauvais placement acceptable. Ce n'est
   pas un poids: c'est une longueur. En synthetique, `d_tol` peut valoir 1 a 2
   tailles de maille, ou la largeur imposee du corridor de vallee. En naturel,
   il devrait plutot etre relie a la largeur effective du fond de vallee, a
   l'incertitude de position du talweg, ou a l'echelle a laquelle une erreur de
   position change vraiment l'interpretation hydrologique. Ensuite
   `eta_dist = 1` signifie: "un decalage moyen d'un corridor acceptable". Si on
   veut etre deux fois plus strict, on garde `d_tol` physique et on met
   `eta_dist = 0.5`, plutot que de melanger les deux notions.

3. `eta_len` fixe la tolerance sur l'extension active du reseau. Cette
   composante est sensible au seuil qui transforme un flux de drainage en
   troncon actif. Il faut donc la garder moins dominante que les flux et les
   distances au debut. Une valeur de 10 % est raisonnable pour commencer; elle
   peut etre abaissee dans un cas synthetique propre si le seuil de detection
   du reseau est stable, ou augmentee si l'activation de petits affluents est
   tres discontinue.

4. Les poids `a_flux`, `a_dist`, `a_len` decrivent ce que le reseau doit
   contraindre. `a_flux` porte la conservation et la repartition des sorties
   d'eau. `a_dist` porte la geometrie du drainage. `a_len` porte l'extension
   active et la tendance a creer ou supprimer des branches. Le choix
   `0.4 / 0.4 / 0.2` dit donc: le flux et la localisation sont les deux
   criteres physiques principaux; la longueur active est un controle
   secondaire, utile mais plus fragile.

Avec ces definitions, une valeur `C_reseau_phys = 1` ne veut pas dire "le
reseau est parfait". Elle veut dire que, en moyenne ponderee, le candidat est
au seuil physique acceptable pour le reseau permanent. Pour un diagnostic plus
strict, on peut aussi conserver une regle de passage par composante:

```text
E_flux / eta_flux <= 1
E_dist / eta_dist <= 1
E_len  / eta_len  <= 1
```

Ces nombres ne sont pas universels. Ils rendent explicite ce qu'on accepte:
une erreur de reseau devient comparable a une erreur de debit parce qu'elle est
exprimee comme nombre de tolerances physiques, pas comme nombre de pixels.

#### Normalisation du debit

Le debit doit aussi etre normalise par des grandeurs hydrologiques, pas
seulement par l'ecart-type statistique. Avec une reference synthetique:

```text
V_ref = integral(Q_ref(t) dt)
A     = surface du bassin
D_ref = V_ref / A
T     = duree de la fenetre transitoire
Qbar_ref = V_ref / T
```

Dans la phase Boussinesq seule, `Q_ref(t)` et `Q_sim(t)` designent le debit
total relache par le modele:

```text
Q(t) = Q_drain(t) + Q_excess(t)
```

`D_ref` est la lame d'eau ecoulee de reference sur la fenetre transitoire. On
peut construire trois erreurs classiques sur toute la chronique de debit total,
sans extraire au depart de fenetres de recession:

```text
E_Q_forme =
  sqrt((1 / T) * integral((Q_sim(t) - Q_ref(t))^2 dt)) / Qbar_ref

E_Q_lame =
  integral(abs(Q_sim(t) - Q_ref(t)) dt) / V_ref

E_Q_bilan =
  abs(integral(Q_sim(t) - Q_ref(t)) dt) / V_ref
```

- `E_Q_forme` est un RMSE normalise du debit sur toute la chronique. Il garde
  l'esprit d'une calibration classique sur `Q(t)`, mais avec une echelle
  physique explicite: le debit moyen de reference `Qbar_ref`.
- `E_Q_lame` mesure une fraction de volume ecoule mal reproduite, sans
  compensation temporelle.
- `E_Q_bilan` mesure l'erreur de volume signe, donc le biais de bilan.

Le cout debit normalise devient:

```text
C_debit_phys =
  b_forme   * E_Q_forme / eta_Q_forme
  + b_lame  * E_Q_lame  / eta_Q_lame
  + b_bilan * E_Q_bilan / eta_Q_bilan

b_forme + b_lame + b_bilan = 1
```

Valeurs de depart raisonnables:

```text
eta_Q_forme     = 0.10 a 0.20  # RMSE egal a 10-20 % du debit moyen
eta_Q_lame      = 0.05 a 0.10  # 5-10 % du volume ecoule
eta_Q_bilan     = 0.02 a 0.05  # biais de bilan plus strict

b_forme  = 0.5
b_lame   = 0.4
b_bilan  = 0.1
```

Lecture progressive des facteurs de normalisation du debit:

1. `eta_Q_forme` fixe la tolerance sur l'ajustement classique de la chronique
   `Q(t)`. Le terme est volontairement calcule sur tous les pas de temps, sans
   segmentation hydrologique. Une valeur de 0.10 a 0.20 signifie que l'erreur
   quadratique typique acceptee vaut 10 a 20 % du debit moyen de reference. Ce
   seuil doit rester assez large au debut pour ne pas transformer le probleme
   en ajustement point par point trop sensible au pas hebdomadaire.

2. `eta_Q_lame` fixe la tolerance sur l'hydrogramme integre en valeur absolue.
   C'est une tolerance de forme et de volume non compensee: un pic trop tot ou
   trop tard est penalise meme si le volume total est correct. En synthetique
   propre, 2-5 % peut suffire. Pour un premier testbed plus robuste, 5-10 % est
   preferable, car cette erreur absorbe aussi les effets de discretisation
   temporelle et de seuils numeriques.

3. `eta_Q_bilan` fixe la tolerance sur le biais de bilan. Elle peut etre plus
   stricte que `eta_Q_lame`, parce qu'une erreur de volume total indique une
   erreur de fermeture hydrologique: recharge, stockage final, drainage ou
   conditions limites. Une plage 2-5 % est un bon premier choix. Dans un cas
   synthetique sans bruit, ce seuil peut devenir un test de conservation de la
   chaine de calcul.

4. Les poids `b_forme`, `b_lame`, `b_bilan` doivent garder le probleme comme
   une calibration de debit classique. `b_forme` domine parce qu'on veut
   ajuster la chronique complete. `b_lame` controle l'erreur hydrologique
   integree. `b_bilan` reste plus faible dans la somme, mais son seuil
   `eta_Q_bilan` est plus strict; il agit donc comme garde-fou de conservation.

Avec ces definitions, une valeur `C_debit_phys = 1` signifie que l'hydrogramme
simule est au seuil d'acceptabilite hydrologique moyen sur la fenetre
transitoire. Comme pour le reseau, il faut garder les composantes separees:

```text
E_Q_forme     / eta_Q_forme     <= 1
E_Q_lame      / eta_Q_lame      <= 1
E_Q_bilan     / eta_Q_bilan     <= 1
```

Les approximations de type recession ou basse-eau ne doivent donc pas etre dans
le cout principal au depart. Elles peuvent en revanche etre testees comme
contraintes d'exclusion simples dans l'inversion. Par exemple:

```text
J_filtre(theta) = J(theta) si g_m(theta) <= 1 pour toutes les contraintes
J_filtre(theta) = rejete, ou J(theta) + penalite, sinon
```

ou `g_m` peut representer un diagnostic approximatif: pente de recession
grossiere, debit de basse-eau minimal, temps de reponse recharge-debit, ou
absence de debit negatif/non physique. Dans ce role, ces approximations ne
calibrent pas directement `K` et `Sy`; elles excluent seulement des candidats
physiquement incompatibles.

#### Choix de `w_reseau` et `w_debit`

Une fois les deux blocs normalises physiquement, le choix de depart peut etre:

```text
w_reseau = 0.5
w_debit  = 0.5
```

Cette egalite n'est defensable que parce que `C_reseau_phys = 1` et
`C_debit_phys = 1` veulent dire la meme chose: une erreur au seuil
d'acceptabilite physique du bloc.

Pour eviter qu'un bon score debit masque un reseau mauvais, il faut conserver
les deux diagnostics separes et ajouter un critere de passage:

```text
C_reseau_phys <= 1
C_debit_phys  <= 1
```

Une alternative plus stricte pour les tests synthetiques est un objectif de
type max:

```text
J_max(theta) = max(C_reseau_phys(theta), C_debit_phys(theta))
```

Cet objectif cherche un compromis qui satisfait les deux contraintes, au lieu
de compenser fortement l'une par l'autre. Il peut etre moins lisse pour
l'optimisation, mais il est tres lisible comme diagnostic de faisabilite.

## 5. Parametres candidats

La cible retenue est volontairement ambitieuse sur les observables mais
restreinte sur la dimension inverse: deux parametres calibres, `K` et `Sy`.
Cette restriction est importante. Elle permet de tester la calibration
conjointe stricte sans confondre l'analyse avec un probleme de trop grande
dimension.

- `K`: conductivite hydraulique. Premier choix: scalaire global dans les cas
  synthetiques, puis multiplicateur global d'une carte de `K` dans les cas
  naturels. Les zones geologiques et multiplicateurs par famille geologique
  viendront apres.
- `Sy`: rendement specifique, choisi comme parametre de stockage initial pour
  les formulations nappe libre et Boussinesq. Si un cas impose une formulation
  differente, il faudra creer une variante explicite avec `Ss` ou un
  coefficient d'emmagasinement equivalent, sans melanger cette variante avec le
  premier testbed `K + Sy`.

Les autres parametres doivent rester fixes pendant cette phase:

- conductance de drainage: tres influente sur le reseau actif, mais a garder
  fixe d'abord pour mesurer ce que `K` et `Sy` expliquent seuls;
- multiplicateur de recharge: a fixer, sinon il risque d'absorber les erreurs
  de bilan et de masquer l'identifiabilite de `K` et `Sy`;
- `runoff_ratio`: a fixer ou a neutraliser dans les cas synthetiques, sauf si
  l'objectif explicite est de calibrer un debit total incluant un ruissellement
  rapide.

Pour les premiers tests de la version ambitieuse:

1. `K + Sy` sur un cas transitoire debit deja proche des benchmarks existants.
2. `K + Sy` sur un cas permanent reseau, meme si `Sy` est peu actif en permanent:
   cela permet de verifier que le bloc reseau contraint surtout `K` et que `Sy`
   reste identifie par le bloc transitoire.
3. `K + Sy` sur deux scenarios par candidat: permanent reseau + transitoire
   debit.
4. Seulement ensuite, tester si la conductance de drainage doit devenir un
   troisieme parametre.

## 6. Ce qui est possible dans la discussion scientifique

On peut formuler le probleme comme une calibration multi-information, pas comme
une calibration "debit seulement". Le reseau permanent contraint la geometrie
des zones drainantes et la position de l'exfiltration; le debit transitoire
contraint la dynamique de stockage, la forme de la chronique et le bilan.

Interet attendu:

- reduire l'equifinalite d'une calibration uniquement sur `Q(t)`;
- eviter des parametres qui reproduisent le debit mais activent un reseau
  spatialement absurde;
- separer partiellement les roles de `K`, `Sy`, recharge et drainage;
- rendre le testbed plus proche des diagnostics hydrogeologiques reels.

Limites a expliciter:

- le reseau observe n'est pas forcement le reseau actif permanent au sens du
  modele; il peut representer une trace cartographique, un talweg, un reseau
  perenne, intermittent, entretenu ou artificiel;
- un reseau binaire est une observable discontinue, donc difficile pour des
  optimiseurs locaux;
- le poids relatif reseau/debit influence fortement le resultat;
- un bon score spatial peut degrader le debit, et inversement;
- l'ajout de ruissellement rapide est necessaire si la station mesure un debit
  total et que le modele souterrain ne produit qu'un drainage lent;
- l'objectif doit rester diagnostique: on veut comprendre les compromis, pas
  seulement produire un "meilleur parametre".

Dans un article ou une discussion de rapport, la calibration conjointe doit
donc etre presentee comme un probleme inverse multi-critere, avec exploration
des compromis, plutot que comme une estimation unique definitive.

## 7. Programme synthetique propose

Avant de coder directement l'objectif conjoint, il faut organiser la demarche
comme une suite de questions de plus en plus fortes. Chaque niveau doit avoir
une reponse lisible, sinon le niveau suivant melangera plusieurs difficultes.

Questions a traiter dans l'ordre:

1. Est-ce que les couts `C_reseau_phys` et `C_debit_phys` reagissent dans le
   bon sens sur des erreurs controlees?
2. Est-ce que le debit transitoire permet d'identifier le couple `K/Sy`, ou
   seulement une diffusivite effective du type `K/Sy`?
3. Est-ce que le reseau permanent contraint effectivement `K`, et reste
   presque insensible a `Sy` comme attendu physiquement?
4. Est-ce que l'objectif conjoint reduit l'equifinalite par rapport au debit
   seul?
5. Est-ce que la solution conjointe respecte simultanement les seuils
   d'acceptabilite `C_reseau_phys <= 1` et `C_debit_phys <= 1`?
6. Est-ce que les compromis restants indiquent une limite des deux parametres
   `K + Sy`, ou seulement un mauvais choix de normalisation?

Cette progression est importante pour eviter une conclusion trop rapide. Si le
debit seul identifie mal `K` et `Sy`, ce n'est pas forcement un echec: c'est
precisement la raison scientifique d'ajouter le reseau. Si le reseau seul ne
contraint pas `Sy`, ce n'est pas un echec non plus: c'est le comportement
physique attendu pour un observable permanent.

### Critere de passage entre niveaux

Chaque niveau synthetique devrait produire au minimum:

```text
argmin C_reseau_phys
argmin C_debit_phys
argmin J
cartes ou coupes de cout dans le plan log10(K), log10(Sy)
valeurs elementaires c_k = E_k / eta_k au meilleur point
```

Le niveau suivant ne devrait etre lance que si:

- les metriques elementaires ont une interpretation physique claire;
- le minimum synthetique est proche du vrai parametre quand l'information le
  permet;
- les directions plates ou equifinales sont visibles, pas cachees;
- les deux blocs de cout peuvent etre lus separement;
- le `J = 0.5 * C_reseau_phys + 0.5 * C_debit_phys` ne compense pas un bloc
  inacceptable.

En pratique, on doit donc analyser `J`, mais aussi les surfaces
`C_reseau_phys` et `C_debit_phys`. Le produit attendu n'est pas seulement un
meilleur parametre: c'est une demonstration de ce que chaque observable
contraint.

### Choix du moteur numerique initial

Le premier cycle synthetique doit etre mene en Boussinesq seul:

```text
truth model     = Boussinesq
candidate model = Boussinesq
theta           = {K, Sy}
```

Ce choix est volontairement pragmatique. Il maximise la vitesse des evaluations
et permet de tester la robustesse du solveur cible avant d'ajouter une
comparaison inter-modele. Le but n'est pas encore de montrer que Boussinesq
reproduit MF6. Le but est de verifier que, dans un cadre controle, Boussinesq
peut supporter une boucle inverse sur:

- un debit transitoire hebdomadaire de 3 a 4 ans;
- un reseau permanent extrait d'un run permanent Boussinesq;
- deux parametres `K` et `Sy`;
- un objectif composite `J = 0.5 * C_reseau_phys + 0.5 * C_debit_phys`.

Les diagnostics de robustesse deviennent donc des sorties de premier rang:

- temps moyen par evaluation;
- taux d'echec solveur;
- nombre d'iterations ou sous-pas PETSc/VI;
- fermeture de bilan;
- sensibilite au pas hebdomadaire et aux sous-pas internes;
- stabilite du reseau actif vis-a-vis du seuil `tau_network`.

La comparaison avec MODFLOW 6 peut venir ensuite comme phase externe, une fois
que les metriques et l'inversion Boussinesq -> Boussinesq sont stables.

### S0 - Banc objectif sans solveur

But: tester la construction des metriques avant d'impliquer un solveur.

Question physique:

- est-ce que les normalisations transforment bien une erreur controlee en un
  nombre de tolerances lisible?

Principe:

- generer un reseau reference simple sur une grille;
- generer un `Q_ref(t)` analytique ou semi-analytique;
- definir des parametres fictifs qui deplacent le reseau et modifient la
  reponse temporelle;
- verifier que les metriques retrouvent les parametres vrais.

Sorties attendues:

- surface objectif reseau;
- surface objectif debit;
- surface objectif composite;
- sensibilite aux poids.

Condition de passage:

- les minima des couts elementaires doivent etre interpretabes;
- une erreur imposee de `0.5 * eta_k`, `1 * eta_k` ou `2 * eta_k` doit produire
  un cout elementaire proche de `0.5`, `1` ou `2`;
- aucune composante ne doit dominer seulement parce que son echelle numerique
  est plus grande.

Ce niveau peut vivre hors workflow HydroModPy, dans `validation_cases` ou
`scratch_tests`, car il valide d'abord la mathematique de l'objectif.

### S1 - Twin transitoire debit avec Boussinesq

But: construire un premier twin transitoire rapide avec le solveur cible.

Question physique:

- avec une chronique `Q(t)` seule, identifie-t-on vraiment `K` et `Sy`
  separement, ou seulement une combinaison dynamique du type diffusivite
  hydraulique?

Base disponible:

- validations transitoires Boussinesq existantes: recharge step, recharge
  periodique, recession de type Brutsaert, cas de pulse/overflow;
- testbeds Boussinesq synthetiques deja capables de produire des chroniques de
  recharge et des historiques d'etat;
- sorties Boussinesq deja disponibles dans les scratchs ou le catalogue, a
  aligner avec le contrat calibration.

Definition retenue pour le debit de calibration:

```text
Q(t) = Q_drain(t) + Q_excess(t)

Q_drain(t)  = sum_i drainage_flux_i(t)
Q_excess(t) = sum_i surface_excess_i(t)
```

ou, si l'on repart des historiques Boussinesq bruts:

```text
Q_drain(t)  = sum_i drainage_flux_history_m3_s[t, i]
Q_excess(t) = sum_i saturation_excess_history_m_s[t, i] * area_i
```

Le debit calibre est donc le flux total qui quitte l'aquifere vers la surface:
drainage explicite plus exces de surface/saturation si le modele en produit.
C'est le choix le plus coherent pour un premier twin Boussinesq, car il evite
de calibrer seulement la composante drain tout en ignorant une sortie de masse
physiquement produite par la formulation VI/obstacle.

Les deux composantes doivent rester exportees separement:

```text
Q_drain(t)
Q_excess(t)
Q_total_release(t) = Q_drain(t) + Q_excess(t)
```

mais le cout principal `C_debit_phys` utilise `Q_total_release(t)`. Cela permet
de verifier si un candidat reproduit le bon debit total pour de mauvaises
raisons, par exemple trop d'exces de surface et pas assez de drainage.

Chemin d'extraction recommande:

1. lire `release_flux` si le champ derive est disponible, puis sommer sur le
   domaine ou le support choisi;
2. sinon reconstruire `Q_total_release` depuis `drainage_flux_history_m3_s` et
   `saturation_excess_history_m_s`;
3. conserver en diagnostic les series separees `drainage_flux` et
   `surface_excess`.

Dans un premier twin rapide, on utilise le total domaine. Dans une version plus
hydrologique, on route ce flux vers un exutoire et on utilise
`release_accumulation_flux` ou un equivalent routable au point aval.

Evolution cible pour un signal plus realiste:

- remplacer le signal analytique court par une chronique de recharge de 3 a 4
  ans;
- utiliser un pas de stress hebdomadaire, soit environ 156 a 208 valeurs;
- demarrer de preference au debut d'une annee hydrologique;
- garder une condition initiale construite avec la recharge moyenne de la
  chronique, puis exclure si besoin les premiers mois du score pour eviter que
  l'identification soit dominee par l'ajustement initial;
- conserver exactement la meme chronique pour le run "truth" et tous les
  candidats, afin que la calibration porte sur `K` et `Sy`, pas sur une erreur
  de forcage.

La generation de la recharge doit s'appuyer sur les briques deja presentes
dans la plateforme plutot que sur un generateur ad hoc. Deux voies existent:

1. Utiliser directement une source `data.recharge` synthetique avec une liste
   de valeurs en `mm/day`, comme dans les cas testbed mensuels existants. La
   version hebdomadaire consiste alors a fournir `freq = "7D"` ou une frequence
   hebdomadaire equivalente, `periods = 156` ou `208`, et la liste des valeurs.
2. Generer d'abord une chronique journaliere avec
   `hydromodpy.physics.hydrology.synthetic.forcing`, notamment
   `generate_daily_precipitation`, `precipitation_to_inflow` ou
   `build_recharge_from_reservoir_chronicle`, puis agregger en moyennes
   hebdomadaires avant injection dans `[data.recharge]`.

La seconde voie est preferable pour la version ambitieuse: elle donne une
chronique plus hydrologique, avec saisonnalite, evenements pluvieux,
intermittence et phases de decrue. La premiere voie reste utile pour un
cas controle minimal et reproductible.

Esquisse declarative attendue:

```toml
[data.recharge]
date_start = "2000-10-01"
date_end = "2004-09-30"

[[data.recharge.sources]]
source = "synthetic"
freq = "7D"
start_date = "2000-10-01"
periods = 208
values = [
  # valeurs hebdomadaires en mm/day generees par les utilitaires synthetiques
]
runoff_ratio = 0.0

[flow.ic]
type = "steady_state"
source = "mean_recharge"
recharge_statistic = "time_mean"

[flow.sinks_sources.recharge]
first_clim = "mean"
negative_to_evt = true
```

Le signal doit etre choisi pour exciter les deux roles de `K` et `Sy`:

- plusieurs saisons humides et seches pour contraindre le bilan et le regime
  moyen;
- quelques impulsions nettes pour tester la propagation et le temps de reponse;
- des phases naturelles de baisse du debit, sans les extraire comme metrique
  principale;
- une amplitude realiste, sans forcer le systeme dans un regime numeriquement
  extreme qui ferait dominer les conditions limites ou les drains.

Un bon compromis est une simulation de 4 ans avec une premiere annee
eventuellement consideree comme mise en regime, puis un score sur les 3 annees
suivantes. Pour un test plus leger, 3 ans complets peuvent suffire si la
condition initiale par recharge moyenne est stable.

Ce niveau sert a etablir le comportement des optimiseurs:

- random search pour reference robuste;
- CMA-ES pour recherche continue;
- Nelder-Mead/simplex pour cas faible dimension;
- GP mapping et DA-MH-GP pour cartographier ou echantillonner l'incertitude.

Sorties attendues:

- surface `C_debit_phys(log10 K, log10 Sy)`;
- orientation des vallees d'equifinalite;
- contribution separee de `E_Q_forme`, `E_Q_lame` et `E_Q_bilan`;
- decomposition du debit total en `Q_drain(t)` et `Q_excess(t)`;
- figure recharge-debit montrant le decalage entre les pics de recharge et les
  pics de debit;
- comparaison avec une metrique statistique classique, par exemple NSE ou KGE,
  pour montrer ce que la normalisation physique change;
- tests exploratoires de contraintes d'exclusion simples, separes du cout
  principal.

Condition de passage:

- la reference synthetique doit etre retrouvee si la chronique contient assez
  d'information;
- si une vallee equifinale demeure, elle doit etre explicite et reliee a la
  physique, pas interpretee comme un echec numerique;
- le score sur toute la chronique doit montrer si `K` et `Sy` sont separes ou
  restent couples dans une direction d'equifinalite.

Approximations a tester seulement comme exclusions:

- pente de recession estimee grossierement sur les periodes de faible recharge;
- debit de basse-eau trop faible ou trop eleve;
- temps de reponse recharge-debit hors d'une plage realiste;
- stockage final incompatible avec le bilan de la chronique.

Ces criteres peuvent etre utiles pour accelerer ou stabiliser le probleme
inverse, par rejet de candidats manifestement incompatibles. Ils ne doivent pas
remplacer le cout principal `C_debit_phys`, qui reste une calibration classique
sur `Q(t)`.

### S2 - Twin permanent reseau avec Boussinesq

But: creer une reference de reseau actif a partir d'un cas permanent
synthetique.

Question physique:

- le reseau permanent contraint-il principalement `K`, comme attendu, et
  laisse-t-il `Sy` quasi neutre?

Principe:

1. definir un petit domaine synthetique 2D;
2. lancer un run Boussinesq "truth" permanent avec `K_true` et
   `R_steady_ref`;
3. extraire `outflow_drain` ou `accumulation_flux`;
4. seuiller pour obtenir un masque actif reference;
5. calibrer un candidat sur ce masque.

Question suivante a trancher: comment definit-on le reseau actif de reference?
Il faut eviter un seuil choisi apres coup pour rendre les cartes jolies. Le
seuil doit etre defini avant la calibration, puis applique identiquement a la
reference et a tous les candidats.

Pour le twin synthetique, la reference devrait contenir trois objets figes:

```text
q_ref_i       = flux de drainage permanent de reference
R_ref         = support actif reference
tau_network   = seuil d'activation du reseau
```

Le choix le plus robuste est de definir `tau_network` relativement au drainage
total de reference ou a une aire contributive equivalente, par exemple:

```text
tau_network = max(
  tau_abs,
  f_tau * Q_ref_steady
)
```

ou `tau_abs` evite d'activer des pixels numeriquement residuels, et `f_tau`
fixe une fraction minimale du drainage permanent total. Dans un premier
testbed, `f_tau` peut etre tres faible, par exemple `1e-4` a `1e-3`, puis teste
en sensibilite. Une autre option est de retenir un quantile de
`q_ref_i[q_ref_i > 0]`, mais il faut alors garder ce quantile et le seuil
resultant fixes pour tous les candidats.

Pour un candidat, on calcule donc:

```text
R_sim(theta) = {i | q_sim_i >= tau_network}
```

et non un seuil recalcule sur `q_sim_i`. C'est le meme principe que pour les
normalisations: le seuil appartient au probleme inverse, pas au candidat.

Il faut aussi conserver le champ continu `q_i`, pas seulement le masque
binaire. Le masque sert a la longueur et a la distance; le flux continu sert a
ponderer les erreurs et evite qu'une petite branche numerique ait le meme poids
qu'un axe de drainage majeur.

Sur le choix de la variable:

- `outflow_drain` est le plus proche de l'exfiltration locale; il mesure ou
  l'eau sort du domaine souterrain vers la surface;
- `accumulation_flux` est plus proche d'une emprise hydrographique routable; il
  integre l'organisation aval du drainage;
- pour un premier test, il faut choisir une variable principale et garder
  l'autre comme diagnostic. La recommandation est de partir de
  `accumulation_flux` pour le masque reseau, tout en conservant `outflow_drain`
  pour controler la distribution locale des sorties.

Metriques minimales:

- Jaccard sur masque actif;
- distance moyenne au reseau reference;
- longueur active relative.

Dans la version normalisee proposee plus haut, ces metriques minimales sont
remplacees ou completees par:

```text
C_reseau_phys =
  a_flux * E_flux / eta_flux
  + a_dist * E_dist / eta_dist
  + a_len  * E_len  / eta_len
```

Le Jaccard peut rester affiche comme diagnostic de lisibilite, mais il ne doit
pas etre le score principal: il donne le meme poids a une erreur sur une petite
branche marginale et a une erreur sur un axe de drainage majeur.

Dans cette etape, on garde deja le vecteur candidat `theta = {K, Sy}` meme si
le score permanent ne devrait pratiquement contraindre que `K`. C'est un test
utile: le bloc reseau doit produire une surface sensible a `K` et plate, ou
presque plate, selon `Sy`. Si `Sy` influence fortement le score permanent, c'est
probablement que le scenario n'est pas vraiment permanent ou que la condition
initiale/transitoire contamine l'observable reseau.

Points de controle specifiques:

- la recharge permanente utilisee par S2 est definie comme une entree propre
  du probleme permanent, notee `R_steady_ref`; elle n'est pas estimee a partir
  du debit transitoire;
- toute la reference reseau est construite exclusivement depuis le run
  permanent: `q_ref_i`, `R_ref`, `Q_ref_steady`, `L_ref`, `tau_network` et les
  normalisations reseau;
- la conductance de drainage reste fixe, sinon elle absorbera une partie du
  role de `K`;
- la maille, le reseau de routage et le seuil `tau_network` restent fixes pour
  tous les candidats;
- `Sy` est present dans `theta` mais ne doit pas etre interprete depuis S2
  seul.

Sorties attendues:

- surface `C_reseau_phys(log10 K, log10 Sy)`;
- verification que la pente principale est selon `K`;
- cartes du reseau actif pour quelques candidats: trop diffus, trop court,
  decale, ou trop ramifie;
- diagnostic separe `c_flux`, `c_dist`, `c_len`.
- sensibilite au seuil `tau_network`, realisee hors calibration en relancant
  seulement l'analyse pour 2 ou 3 seuils fixes.

Condition de passage:

- `C_reseau_phys` doit discriminer les mauvais `K`;
- la dependance a `Sy` doit etre faible en regime permanent;
- les erreurs de localisation doivent etre lisibles spatialement, pas seulement
  dans une valeur scalaire.
- le minimum reseau seul doit etre coherent avec `K_true`, meme si la direction
  `Sy` reste plate.

### S3 - Twin conjoint sur une seule simulation transitoire

But: eviter dans un premier temps le multi-run strict.

Question physique:

- peut-on deja montrer le benefice d'un score spatial + temporel sans lancer
  deux scenarios separes par candidat?

Approche:

- utiliser un run transitoire Boussinesq avec une premiere periode
  representative;
- scorer le reseau sur le premier pas ou sur un pas moyen;
- scorer le debit sur toute la chronique;
- composer les deux couts.

Ce n'est pas encore "permanent + transitoire" au sens strict, mais c'est un bon
prototype car un seul solver run suffit par candidat.

Limite:

- si le reseau permanent doit etre obtenu avec une recharge moyenne differente
  de la chronique, cette approximation devient discutable.

Condition de passage:

- l'objectif conjoint doit deplacer ou resserrer le minimum par rapport au
  debit seul;
- le score reseau ne doit pas etre une simple redondance du score debit;
- les deux diagnostics `C_reseau_phys` et `C_debit_phys` doivent rester
  affiches.

### S4 - Twin conjoint strict deux scenarios

But: cible scientifique propre.

Question physique:

- le meme couple `K/Sy` peut-il satisfaire simultanement une structure de
  drainage permanent et une dynamique transitoire de debit?

Pour chaque candidat:

```text
theta = {K, Sy}
  -> run A: steady_network_boussinesq(theta)
       -> score_network
  -> run B: transient_discharge_boussinesq(theta)
       -> score_Q
  -> score_total = w_network * score_network + w_Q * score_Q
```

Dans la premiere phase, les deux runs sont donc Boussinesq. On conserve le meme
moteur numerique pour la verite synthetique et les candidats, afin de tester
d'abord l'inversion et la robustesse du solveur sans erreur de modele externe.

Le run permanent A doit rester la source exclusive de la reference reseau. On
definit donc d'abord une recharge permanente de reference:

```text
R_steady_ref = recharge permanente choisie pour le scenario reseau
```

Puis on genere la chronique transitoire B de facon coherente avec ce permanent,
par exemple en la rescalant pour que sa moyenne temporelle egale
`R_steady_ref`:

```text
mean(R_transient(t)) = R_steady_ref
```

Ainsi le reseau permanent ne depend pas de la simulation transitoire. Le
permanent definit la structure moyenne de drainage; le transitoire teste la
dynamique du meme systeme autour de cette recharge moyenne. Cette orientation
est plus propre que de calculer d'abord la chronique transitoire puis d'en
deduire le permanent, car elle preserve l'autonomie du bloc reseau.

Cela demande une extension du moteur de calibration:

- soit un `metric_fn` specifique qui lance explicitement deux configurations;
- soit une extension declarative du schema de calibration avec scenarios.

Esquisse declarative non implementee:

```toml
[[calibration.scenario]]
id = "steady_network"
base_config = "synthetic_network_steady.toml"

[[calibration.scenario]]
id = "transient_discharge"
base_config = "synthetic_discharge_transient.toml"

[[calibration.outputs]]
name = "active_network"
scenario = "steady_network"
variable = "accumulation_flux"
support = "network"
observed_path = "truth/active_network_reference.tif"

[[calibration.outputs]]
name = "q_outlet"
scenario = "transient_discharge"
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observed_path = "truth/q_outlet.csv"
```

Cette forme serait plus robuste a long terme que des scripts ad hoc.

Sorties attendues:

- surfaces `C_reseau_phys`, `C_debit_phys` et `J`;
- meilleur point selon chaque bloc et selon l'objectif conjoint;
- verification des seuils `C_reseau_phys <= 1` et `C_debit_phys <= 1`;
- representation du compromis dans le plan
  `(C_reseau_phys, C_debit_phys)`;
- comparaison avec une calibration debit seul.

Condition de passage:

- si le point vrai n'est pas retrouve en twin experiment propre, il faut
  suspecter l'objectif, les extracteurs ou la coherence entre scenarios;
- si le point vrai est retrouve mais que le compromis est tres plat, il faut
  documenter l'equifinalite residuelle;
- si aucun couple `K/Sy` ne satisfait les deux blocs, cela peut indiquer que
  deux parametres ne suffisent pas ou que les deux references ne correspondent
  pas au meme systeme physique.

### S5 - Passage naturel controle

But: passer du twin synthetique a des cas naturels sans perdre le controle.

Etapes recommandees:

1. choisir 2 ou 3 bassins du testbed naturel;
2. utiliser Boussinesq haute resolution ou une parametrisation Boussinesq
   "truth" comme reference pseudo-observee;
3. degrader volontairement la parametrisation candidate;
4. calibrer `K` et `Sy`, ou des multiplicateurs globaux de `K` et `Sy`;
5. comparer ce que le reseau ajoute par rapport a une calibration debit seul.

Ce n'est qu'apres ce niveau qu'il faut utiliser simultanement hydrographie
observee et hydrometrie reelle.

Une comparaison MF6 haute resolution peut etre ajoutee plus tard comme test
externe de fidelite physique, mais elle n'est pas necessaire pour la premiere
evaluation de robustesse Boussinesq.

## 8. Extensions techniques a prevoir

### 8.1. Observable reseau

Ajouter un support de calibration spatial:

```toml
[calibration.outputs.active_network]
variable = "accumulation_flux"
support = "network"
time = "last"
observed_path = "truth/active_network_reference.tif"
threshold = 1.0e-6
```

ou:

```toml
[calibration.outputs.drain_mask]
variable = "outflow_drain"
support = "map"
time = "last"
observed_path = "truth/drain_mask_reference.tif"
reducer = "network_similarity"
```

Le schema actuel ne contient pas `observed_path`. Les cas synthetiques peuvent
utiliser `observed_values`, mais une carte complete ne rentre pas proprement
dans ce champ.

### 8.2. Metriques reseau

Creer un module cible, par exemple:

```text
hydromodpy/calibration/network_metrics.py
```

Fonctions minimales:

- `binary_jaccard(sim_mask, obs_mask)`;
- `precision_recall_f1(sim_mask, obs_mask)`;
- `mean_distance_to_reference(sim_mask, obs_mask, cell_size)`;
- `active_length_error(sim_mask, obs_mask, cell_size)`;
- `network_flux_rmse(sim_flux, obs_flux, mask=None, log=True)`.

Ces metriques doivent retourner des couts finis, normalises et bien documentes.

### 8.3. Extraction MODFLOW

Non prioritaire pour la phase Boussinesq seule. Le chemin actuel lit les
budgets binaires pour sommer DRAIN. Pour le reseau, il
faudra aussi extraire le champ spatial par pas de temps:

- DRAIN par cellule;
- eventuellement CHD/RIV si les cas les utilisent;
- `accumulation_flux` si disponible en sortie derivee, ou equivalent calcule a
  la volee sur le support de drainage.

Pour la calibration legere, idealement on lit les binaires sans passer par le
catalogue complet, afin de garder les iterations rapides.

### 8.4. Extraction Boussinesq

Prioritaire pour la phase initiale. Ajouter au
`BoussinesqFlowAdapter.extract_calibration_series` ou a un extracteur dedie:

- serie de debit total de calibration:
  `Q_total_release = drainage + surface_excess`;
- series separees de diagnostic: `Q_drain` et `Q_excess`;
- champ `drainage_flux_m3_s`;
- champ ou budget `surface_excess`, ou reconstruction depuis
  `saturation_excess_history_m_s`;
- champ derive `release_flux` si disponible;
- serie de charge a un point ou une cellule;
- selection temporelle compatible avec `time = "all"`, `first`, `last`.
- champ reseau permanent derive ou relu depuis les sorties:
  `outflow_drain`, `release_flux`, `accumulation_flux`,
  `release_accumulation_flux`, ou equivalent routable.

Le module Boussinesq a deja des historiques de flux et d'etat. Le travail est
principalement d'aligner ces sorties avec le contrat calibration.

### 8.5. Multi-scenario calibration

Le vrai saut conceptuel est de permettre plusieurs runs par candidat. Deux
options:

1. `metric_fn` specifique pour les prototypes S4.
2. Extension generique du schema avec scenarios.

L'option 1 est plus rapide pour apprendre. L'option 2 est meilleure pour la
maintenance et pour des campagnes naturelles reproductibles.

## 9. Premier plan de travail

1. Documenter le probleme et les limites actuelles: ce fichier.
2. Auditer les sorties Boussinesq disponibles pour charge, flux total,
   drainage local et etats transitoires.
3. Ajouter un extracteur Boussinesq leger pour la calibration debit.
4. Ajouter un micro-benchmark objectif sans solveur pour les metriques reseau.
5. Ajouter un cas synthetique permanent Boussinesq qui produit un masque de
   drainage reference.
6. Brancher une `metric_fn` prototype reseau + debit sur un seul run
   Boussinesq.
7. Brancher le prototype S4 avec deux runs Boussinesq par candidat.
8. Decider ensuite si l'extension declarative multi-scenario est justifiee.

Le critere de passage n'est pas seulement "le meilleur cout baisse". Il faut
verifier:

- recuperation des parametres vrais dans les cas twin simples;
- forme lisible de la surface objectif;
- compromis visible entre reseau et debit;
- stabilite des resultats quand on change les poids;
- cout par evaluation acceptable;
- taux d'echec solveur faible.

## 10. Position recommandee

La cible reste la version ambitieuse: un meme `theta = {K, Sy}` evalue par deux
scenarios. La trajectoire reste progressive dans l'implementation, mais chaque
jalon doit rester oriente vers cette cible:

```text
objectif mathematique simple
  -> extraction Boussinesq calibration
  -> twin Boussinesq debit transitoire
  -> twin Boussinesq reseau permanent
  -> objectif conjoint Boussinesq K+Sy sur un run
  -> objectif conjoint Boussinesq K+Sy sur deux scenarios
  -> pseudo-observations naturelles Boussinesq
  -> comparaison externe MF6 optionnelle
  -> observations reelles
```

Il ne faut pas commencer directement par un bassin naturel avec hydrographie et
debit observes. Ce serait difficile a interpreter: on ne saurait pas si un
echec vient de la metrique reseau, du solveur, des donnees, de la recharge, du
poids des objectifs ou de l'identifiabilite.

Le code actuel est suffisamment avance pour lancer la phase synthetique. Il
manque surtout une couche d'observables spatiales de calibration et, a terme,
un vrai support multi-scenario par candidat.
