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

- a tres court terme, le choix retenu est de partir avec MODFLOW 6 comme
  solveur de reference et comme solveur candidat;
- cela permet de s'appuyer d'abord sur les budgets DRAIN et les sorties
  derivees deja presentes dans la chaine MODFLOW 6;
- avec ces briques, on peut ajouter une metrique reseau sur une
  seule simulation candidate;
- avec un developpement plus structurant, on peut faire la calibration
  conjointe stricte "permanent reseau + transitoire debit";
- Boussinesq reste une etape ulterieure de comparaison et de robustesse, une
  fois les metriques et les normalisations stabilisees.

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

[calibration.outputs.q_total_release]
variable = "total_release"
support = "domain"
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
uses_outputs = ["q_total_release"]
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

Pour le plan MODFLOW 6 initial, on peut repartir de ce chemin DRAIN, mais il
faut le rendre explicite dans le langage de cette note: la chronique calibree
est `Q_total_release(t)`, somme des flux de drainage sortants sur tout le
domaine actif. Une `metric_fn` dediee peut etre utilisee au debut pour calculer
`C_debit_phys` sans attendre que le schema composite gere parfaitement ce
support `domain`.

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

Le choix de planification retenu ici n'est donc pas de commencer par
Boussinesq. On commence par MODFLOW 6, parce que les budgets et les sorties de
drainage sont plus directement exploitables pour un premier probleme inverse
controle. Boussinesq reste important, mais comme etape suivante:

- verifier que l'objectif construit sur MODFLOW 6 se transpose au solveur
  Boussinesq;
- evaluer la robustesse et la vitesse du solveur Boussinesq une fois les
  observables stabilisees;
- separer clairement les difficultes de metrique des difficultes de
  formulation numerique.

La limite est claire: un twin MODFLOW 6 -> MODFLOW 6 ne teste pas encore
l'erreur de modele entre solveurs. Il teste d'abord la robustesse de l'objectif,
de l'extraction et de l'inversion dans un cadre numerique controle. Les
comparaisons Boussinesq restent utiles ensuite, mais comme validation externe
ou comme transfert de la methode.

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
cost_network_flux = rmse(log1p(outflow_drain_sim), log1p(outflow_drain_ref))
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
cost_Q = RMSE(Q_sim, Q_ref)
```

Dans l'objectif composite, ce RMSE doit seulement etre normalise pour devenir
comparable au cout reseau. On ne rajoute pas de decomposition en volume, bilan
ou recession dans le cout principal B0.

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
c_Q_rmse, C_debit_phys
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
  d_ref_i, a_ref_i, R_ref, Q_ref_steady, L_ref, d_tol
  eta_flux, eta_dist, eta_len
  a_flux, a_dist, a_len

debit transitoire:
  Q_ref(t), V_ref, Qbar_ref, T, pas de temps / poids temporels
  alpha_Q

objectif conjoint:
  w_reseau = 0.5
  w_debit  = 0.5
```

Ensuite, pour chaque candidat `theta = {K, Sy}`, seules les sorties simulees
changent: `d_sim_i`, `a_sim_i`, `R_sim`, `L_sim`, `Q_sim(t)`. Les denominateurs
et les seuils de normalisation restent ceux de la reference. C'est indispensable
pour que deux candidats soient compares sur la meme echelle.

Si l'on change la fenetre temporelle, la chronique de recharge, la maille, le
seuil de detection du reseau, ou le bassin, alors il faut recalculer les
normalisations une fois pour ce nouveau cas. Mais a l'interieur d'un meme
probleme inverse, elles restent figees.

#### Normalisation du reseau

Le reseau ne doit pas etre score seulement par un Jaccard de pixels. Il faut
donner plus de poids aux erreurs qui deplacent ou perdent du drainage
significatif. Pour le premier testbed MODFLOW 6, on distingue deux champs:

```text
d_ref_i = outflow_drain permanent de reference sur la cellule i
d_sim_i = outflow_drain permanent simule sur la cellule i

a_ref_i = accumulation_flux permanent de reference sur la cellule/arete i
a_sim_i = accumulation_flux permanent simule sur la cellule/arete i

Q_ref_steady  = sum_i d_ref_i
tau_network   = 0
R_ref         = {i | d_ref_i > tau_network}
```

Choix corrige pour B0: `outflow_drain` porte le bilan local, le lien avec
`Q_total_release`, la repartition spatiale des sorties et le calcul des
distances. `accumulation_flux` reste utile comme diagnostic routable, mais il
n'est pas la base du cout de distance dans le premier testbed.

Trois erreurs physiques sont utiles:

```text
E_flux =
  sum_i abs(d_sim_i - d_ref_i) / Q_ref_steady

E_dist =
  [sum_i d_sim_i * d(i, R_ref) + sum_i d_ref_i * d(i, R_sim)]
  / [2 * d_tol * Q_ref_steady]

E_len =
  abs(L_sim - L_ref) / L_ref
```

- `E_flux` mesure une fraction du drainage permanent local mal reproduite.
- `E_dist` mesure une distance moyenne de mauvais placement, ponderee par le
  flux de drainage sortant. `d_tol` est la largeur de corridor acceptable: une
  largeur de vallee synthetique, une incertitude cartographique, ou une taille
  de maille dans le cas B0 retenu. Le denominateur utilise
  `Q_ref_steady`, pas le flux total du candidat, afin que la normalisation reste
  fixe pendant l'inversion.
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

Valeurs retenues pour B0:

```text
eta_flux = 0.05 a 0.10    # 5-10 % du drainage permanent
eta_dist = 1.0            # deplacement moyen egal a d_tol
eta_len  = 0.10           # 10 % d'erreur de longueur active
d_tol    = 1 * dx         # B0: une taille de maille; 2 * dx en sensibilite

a_flux = 0.4
a_dist = 0.4
a_len  = 0.2
```

Lecture progressive des facteurs de normalisation du reseau:

1. `eta_flux` fixe la tolerance sur la repartition spatiale du drainage
   permanent. Il ne s'agit pas d'une tolerance sur le debit total seulement:
   `sum_i abs(d_sim_i - d_ref_i)` penalise aussi un flux deplace d'une branche
   a une autre. Pour un twin experiment sans bruit, on pourrait descendre vers
   1-2 %, mais ce serait surtout tester la reproductibilite numerique. Pour un
   testbed robuste aux effets de maille, de seuil de drainage et de solveur,
   5-10 % est plus defendable. Si la recharge synthetique elle-meme est
   perturbee, `eta_flux` doit etre au moins de l'ordre de cette incertitude de
   bilan.

2. `d_tol` fixe l'echelle physique d'un mauvais placement acceptable. Ce n'est
   pas un poids: c'est une longueur. Pour B0, le choix retenu est
   `d_tol = 1 * dx`, donc une taille de maille. Avec `eta_dist = 1`, un
   decalage moyen d'une maille vaut un cout elementaire de 1 pour la composante
   distance. Une variante `d_tol = 2 * dx` peut etre testee hors calibration
   pour verifier la sensibilite a la tolerance spatiale. En naturel, `d_tol`
   devrait plutot etre relie a la largeur effective du fond de vallee, a
   l'incertitude de position du talweg, ou a l'echelle a laquelle une erreur de
   position change vraiment l'interpretation hydrologique.

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
V_ref = integral(Q_ref(t) dt) sur la fenetre scoree
A     = surface du bassin
D_ref = V_ref / A
T     = duree de la fenetre scoree
Qbar_ref = V_ref / T
```

Dans la phase MODFLOW 6 initiale, `Q_ref(t)` et `Q_sim(t)` designent le debit
total relache par le modele sur le domaine actif. Pour B0, on le definit comme
la somme des sorties DRAIN:

```text
Q(t) = Q_total_release(t) = Q_drain(t)
```

Une composante `Q_excess(t)` pourra etre ajoutee plus tard si une formulation
ou un solveur produit explicitement un exces de surface. Elle n'appartient pas
au B0-MODFLOW 6 initial.

Pour B0, on simplifie volontairement: le bloc debit est un RMSE entre les
valeurs observees/synthetiques et les valeurs simulees. On ne decompose pas le
score en forme, lame ecoulee et bilan.

```text
RMSE_Q =
  sqrt((1 / N) * sum_n (Q_sim(t_n) - Q_ref(t_n))^2)

C_debit_phys = RMSE_Q / (alpha_Q * Qbar_ref)
```

Pour B0, `N = 36`: on calcule le RMSE sur les 36 mois scores apres la premiere
annee de mise en regime.

`RMSE_Q` garde les unites du debit. Le denominateur `alpha_Q * Qbar_ref`
exprime directement la tolerance admise comme fraction du debit moyen de
reference. Cette normalisation minimale suffit pour integrer le debit dans
l'objectif conjoint sans introduire de sous-composantes.

Valeur retenue pour B0:

```text
alpha_Q = 0.10  # RMSE egal a 10 % du debit moyen de reference
```

Avec cette definition, une valeur `C_debit_phys = 1` signifie que le RMSE de la
chronique simulee atteint la tolerance fixee, ici 10 % du debit moyen de
reference. Des sensibilites `alpha_Q = 0.05`, `0.15` et `0.20` peuvent etre
testees hors calibration si le bloc debit domine trop ou pas assez le compromis.
Le diagnostic a conserver est donc simplement:

```text
RMSE_Q
RMSE_Q / Qbar_ref
alpha_Q
C_debit_phys
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

Le premier cycle synthetique doit etre mene en MODFLOW 6:

```text
truth model     = MODFLOW 6
candidate model = MODFLOW 6
theta           = {K, Sy}
```

Ce choix est volontairement pragmatique. Il exploite d'abord le solveur et les
extracteurs les plus directement alignes avec les sorties de drainage deja
utilisees dans la plateforme. Le but n'est pas encore de comparer MODFLOW 6 et
Boussinesq. Le but est de verifier que, dans un cadre controle, l'objectif
physique peut supporter une boucle inverse sur:

- un debit transitoire mensuel de 4 ans;
- un reseau permanent extrait d'un run permanent MODFLOW 6;
- deux parametres `K` et `Sy`;
- un objectif composite `J = 0.5 * C_reseau_phys + 0.5 * C_debit_phys`.

Les diagnostics de robustesse deviennent donc des sorties de premier rang:

- temps moyen par evaluation;
- taux d'echec solveur;
- nombre d'iterations ou pas internes du solveur;
- fermeture de bilan;
- sensibilite au pas mensuel et aux sous-pas internes;
- stabilite du reseau actif sans seuil positif, avec controle d'un epsilon
  numerique eventuel.

La comparaison avec Boussinesq peut venir ensuite comme phase externe, une fois
que les metriques et l'inversion MODFLOW 6 -> MODFLOW 6 sont stables.

### Petit domaine controle initial

Le domaine initial doit etre directement un petit bassin 2D issu de la chaine
geographique, pas un cas 1D abstrait ni une geometrie entierement artificielle.
Le cas reste simple, mais il doit deja contenir les objets que l'on veut
calibrer ensuite:

- une topographie issue du MNT avec un exutoire explicite;
- un masque de bassin et un domaine actif fixes;
- une recharge permanente `R_steady_ref` pour le reseau;
- une chronique de recharge mensuelle coherente avec `R_steady_ref`;
- une formulation MODFLOW 6 avec drainage explicite;
- des sorties permettant de construire a la fois `Q_total_release(t)` et le
  reseau actif permanent.

Ce choix est plus ambitieux qu'un strip 1D ou qu'une surface analytique, mais il
evite de valider une calibration qui ne testerait pas encore la geometrie de
drainage. Le bassin doit rester petit pour garder le cout par evaluation
faible: `K` et `Sy` homogenes ou multiplicateurs globaux, conductance de
drainage fixee, une seule sortie hydrologique principale.

Le niveau retenu pour le premier cycle est donc B0:

```text
B0 - petit domaine naturel controle
  topographie MNT reelle ou pseudo-reelle
  exutoire explicite pour structurer le bassin
  maillage et domaine actif fixes
  K uniforme ou multiplicateur global de K
  Sy uniforme
  recharge permanente uniforme
  chronique de recharge mensuelle uniforme spatialement
  conductance de drainage fixee
  debit calibre = Q_total_release sur tout le domaine actif
```

On ne passe pas a B1/B2 tant que B0 n'a pas demontre:

- recuperation de `K_true` et `Sy_true` dans le twin transitoire debit;
- sensibilite du reseau permanent principalement a `K`;
- faible dependance du score reseau a `Sy`;
- stabilite numerique MODFLOW 6 sur la chronique 3-4 ans;
- cout par evaluation compatible avec une exploration 2D du plan
  `log10(K), log10(Sy)`;
- interpretation claire des surfaces `C_debit_phys`, `C_reseau_phys` et `J`.

Exploration initiale retenue pour B0:

```text
O0a: grille reguliere 15 x 15 dans le plan log10(K), log10(Sy)
O0b: grille reguliere 25 x 25 si O0a donne une surface coherente
```

Les bornes de depart restent physiques mais volontairement larges:

```text
K  in [0.1 * K_true, 10 * K_true]
Sy in [max(0.005, Sy_true / 3), min(0.35, 3 * Sy_true)]
```

La grille `15 x 15` sert a verifier rapidement les echecs solveur, la forme de
la surface objectif et la coherence des normalisations. La grille `25 x 25`
n'est lancee qu'ensuite, pour affiner la geometrie du minimum et des vallees
d'equifinalite.

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

### S1 - Twin transitoire debit avec MODFLOW 6

But: construire un premier twin transitoire controle avec MODFLOW 6.

Question physique:

- avec une chronique `Q(t)` seule, identifie-t-on vraiment `K` et `Sy`
  separement, ou seulement une combinaison dynamique du type diffusivite
  hydraulique?

Base disponible:

- validations et exemples MODFLOW 6 deja presents dans les workflows;
- extracteurs legers capables de lire des budgets DRAIN globaux;
- sorties derivees `outflow_drain` et `accumulation_flux` deja utilisees dans
  les diagnostics et comparaisons;
- generation de recharge synthetique deja disponible dans la plateforme.

Definition retenue pour le debit de calibration:

```text
Q_total_release(t) = Q_drain(t)
Q_drain(t) = sum_{i in domaine actif} outflow_drain_i(t)
```

Le debit calibre est donc le flux total qui quitte l'aquifere vers la surface
par les drains MODFLOW 6, somme sur tout le domaine actif. On ne cherche pas a
reconstruire un debit route a l'exutoire dans B0. L'exutoire sert a structurer
la topographie du petit bassin, mais l'observable de debit reste
`Q_total_release(t)`.

Une composante d'exces de surface peut rester dans le vocabulaire general de la
note, mais elle vaut zero ou est absente dans le premier cas MODFLOW 6:

```text
Q_drain(t)
Q_excess(t) = 0  # B0-MODFLOW 6 initial
Q_total_release(t) = Q_drain(t)
```

Le cout principal `C_debit_phys` utilise `Q_total_release(t)`. Si une variante
ulterieure ajoute un mecanisme explicite d'exces de surface, les series
separees `Q_drain` et `Q_excess` devront etre conservees comme diagnostics.

Chemin d'extraction recommande:

1. lire les budgets DRAIN MODFLOW 6 par pas de temps;
2. sommer les sorties positives sur tout le domaine actif;
3. exposer la serie sous le nom `Q_total_release`;
4. conserver si possible un champ spatial `outflow_drain_i(t)` pour le lien
   avec la metrique reseau.

Dans le premier twin, on utilise donc le total sur tout le domaine actif. Ce
choix est volontaire: il supprime l'incertitude de routage vers un exutoire et
teste d'abord la reponse hydrologique globale du modele. On ne conserve donc
pas de debit route a l'exutoire dans cette phase. L'exutoire reste utile pour
definir une topographie de bassin lisible, mais pas comme observable de debit.

Evolution cible pour un signal plus realiste:

- remplacer le signal analytique court par une chronique de recharge mensuelle
  de 4 ans;
- utiliser un pas de stress mensuel, soit 48 valeurs;
- demarrer de preference au debut d'une annee hydrologique;
- garder une condition initiale construite avec la recharge moyenne de la
  chronique;
- exclure la premiere annee du score RMSE et scorer les 36 mois suivants, pour
  eviter que l'identification soit dominee par l'ajustement initial;
- conserver exactement la meme chronique pour le run "truth" et tous les
  candidats, afin que la calibration porte sur `K` et `Sy`, pas sur une erreur
  de forcage.

La generation de la recharge doit s'appuyer sur les briques deja presentes
dans la plateforme plutot que sur un generateur ad hoc. Deux voies existent:

1. Utiliser directement une source `data.recharge` synthetique avec une liste
   de valeurs en `mm/day`, comme dans les cas testbed mensuels existants. La
   version B0 consiste alors a fournir `freq = "MS"`, `periods = 48`, et la
   liste des valeurs mensuelles.
2. Generer d'abord une chronique journaliere avec
   `hydromodpy.physics.hydrology.synthetic.forcing`, notamment
   `generate_daily_precipitation`, `precipitation_to_inflow` ou
   `build_recharge_from_reservoir_chronicle`, puis agregger en moyennes
   mensuelles avant injection dans `[data.recharge]`.

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
freq = "MS"
start_date = "2000-10-01"
periods = 48
values = [
  # valeurs mensuelles en mm/day generees par les utilitaires synthetiques
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

Le compromis retenu pour B0 est une simulation mensuelle de 4 ans: 48 pas
mensuels au total, une premiere annee de mise en regime non scoree, puis un RMSE
calcule sur les 36 mois restants. Pour un test plus leger, 3 ans complets
peuvent suffire si la condition initiale par recharge moyenne est stable, mais
ce n'est pas la trajectoire principale.

Ce niveau sert a etablir le comportement des optimiseurs:

- random search pour reference robuste;
- CMA-ES pour recherche continue;
- Nelder-Mead/simplex pour cas faible dimension;
- GP mapping et DA-MH-GP pour cartographier ou echantillonner l'incertitude.

Sorties attendues:

- surface `C_debit_phys(log10 K, log10 Sy)`;
- orientation des vallees d'equifinalite;
- diagnostic `RMSE_Q`, `RMSE_Q / Qbar_ref` et `C_debit_phys`;
- decomposition du debit total en `Q_drain(t)` et, plus tard seulement,
  `Q_excess(t)` si le solveur ou la formulation en produit;
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
- le score sur la fenetre scoree, c'est-a-dire les 36 derniers mois, doit
  montrer si `K` et `Sy` sont separes ou restent couples dans une direction
  d'equifinalite.

Approximations a tester seulement comme exclusions:

- pente de recession estimee grossierement sur les periodes de faible recharge;
- debit de basse-eau trop faible ou trop eleve;
- temps de reponse recharge-debit hors d'une plage realiste;
- stockage final incompatible avec le bilan de la chronique.

Ces criteres peuvent etre utiles pour accelerer ou stabiliser le probleme
inverse, par rejet de candidats manifestement incompatibles. Ils ne doivent pas
remplacer le cout principal `C_debit_phys`, qui reste une calibration classique
sur `Q(t)`.

### S2 - Twin permanent reseau avec MODFLOW 6

But: creer une reference de reseau actif a partir d'un cas permanent
synthetique.

Question physique:

- le reseau permanent contraint-il principalement `K`, comme attendu, et
  laisse-t-il `Sy` quasi neutre?

Principe:

1. definir le petit domaine controle B0: 2D, maillage fixe, MNT/exutoire
   reels, parametrisation volontairement simple;
2. lancer un run MODFLOW 6 "truth" permanent avec `K_true` et
   `R_steady_ref`;
3. extraire `outflow_drain` pour le masque actif, le bilan local et les
   distances;
4. extraire `accumulation_flux` comme diagnostic routable secondaire;
5. seuiller `outflow_drain` pour obtenir un support actif de reference;
6. calibrer un candidat sur ce support et sur les diagnostics associes.

Choix retenu: on ne met pas de seuil positif a priori. Le support actif de
reference est l'ensemble des cellules qui drainent effectivement dans le run
permanent. Il faut donc utiliser une inegalite stricte:

```text
tau_network = 0
R_ref = {i | d_ref_i > 0}
```

La nuance est importante: `d_ref_i >= 0` activerait aussi les cellules sans
drainage si le champ est positif ou nul partout. Le choix physique est bien
"flux sortant strictement positif", pas "cellule non negative".

Pour le twin synthetique, la reference devrait contenir trois objets figes:

```text
d_ref_i       = outflow_drain permanent de reference
a_ref_i       = accumulation_flux permanent de reference, diagnostic
R_ref         = support actif reference issu de outflow_drain
tau_network   = 0
```

Si des flux residuels numeriques apparaissent, on ne change pas d'emblee la
definition principale. On documente d'abord leur amplitude et on teste
eventuellement un epsilon de nettoyage hors calibration, comme diagnostic de
sensibilite.

Pour un candidat, on calcule donc:

```text
R_sim(theta) = {i | d_sim_i > tau_network}
```

et non un seuil recalcule sur `d_sim_i`. C'est le meme principe que pour les
normalisations: le seuil appartient au probleme inverse, pas au candidat.

Il faut aussi conserver les champs continus, pas seulement le masque binaire.
Le masque issu de `outflow_drain` sert a la longueur et a la distance.
`outflow_drain` pondere la geometrie du reseau, controle la distribution locale
des sorties et garde la coherence avec `Q_total_release`. `accumulation_flux`
reste une lecture complementaire de l'organisation aval.

Sur le choix de la variable:

- `outflow_drain` est le plus proche de l'exfiltration locale; il mesure ou
  l'eau sort du domaine souterrain vers la surface;
- `accumulation_flux` est plus proche d'une emprise hydrographique routable; il
  integre l'organisation aval du drainage;
- choix retenu: `outflow_drain` est la variable principale pour le masque
  reseau, le calcul des distances, le bilan local, `Q_total_release` et
  `E_flux`. `accumulation_flux` reste un diagnostic secondaire.

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
  permanent: `d_ref_i`, `a_ref_i`, `R_ref`, `Q_ref_steady`, `L_ref`,
  `tau_network` et les normalisations reseau;
- la conductance de drainage reste fixe, sinon elle absorbera une partie du
  role de `K`;
- la maille, `d_tol = dx`, le reseau de routage et `tau_network = 0` restent
  fixes pour tous les candidats;
- `Sy` est present dans `theta` mais ne doit pas etre interprete depuis S2
  seul.

Sorties attendues:

- surface `C_reseau_phys(log10 K, log10 Sy)`;
- verification que la pente principale est selon `K`;
- cartes du reseau actif pour quelques candidats: trop diffus, trop court,
  decale, ou trop ramifie;
- diagnostic separe `c_flux`, `c_dist`, `c_len`.
- sensibilite a un epsilon numerique eventuel, realisee hors calibration et
  seulement si les flux residuels polluent le support actif.
- sensibilite a `d_tol = 2 * dx`, realisee hors calibration pour verifier que
  le compromis reseau/debit ne depend pas d'une tolerance spatiale trop stricte.

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

- utiliser un run transitoire MODFLOW 6 avec une premiere periode
  representative;
- scorer le reseau sur le premier pas ou sur un pas moyen;
- scorer le debit sur la fenetre retenue, apres mise en regime;
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
  -> run A: steady_network_mf6(theta)
       -> score_network
  -> run B: transient_discharge_mf6(theta)
       -> score_Q
  -> score_total = w_network * score_network + w_Q * score_Q
```

Dans la premiere phase, les deux runs sont donc MODFLOW 6. On conserve le meme
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
variable = "outflow_drain"
support = "network"
observed_path = "truth/active_network_reference.tif"

[[calibration.outputs]]
name = "q_total_release"
scenario = "transient_discharge"
variable = "total_release"
support = "domain"
observed_path = "truth/q_total_release.csv"
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
2. utiliser MODFLOW 6 haute resolution ou une parametrisation MODFLOW 6
   "truth" comme reference pseudo-observee;
3. degrader volontairement la parametrisation candidate;
4. calibrer `K` et `Sy`, ou des multiplicateurs globaux de `K` et `Sy`;
5. comparer ce que le reseau ajoute par rapport a une calibration debit seul.

Ce n'est qu'apres ce niveau qu'il faut utiliser simultanement hydrographie
observee et hydrometrie reelle.

Une comparaison Boussinesq peut etre ajoutee plus tard comme test externe de
transfert entre solveurs, mais elle n'est pas necessaire pour la premiere
evaluation de la methode sur MODFLOW 6.

## 8. Extensions techniques a prevoir

### 8.1. Observable reseau

Ajouter un support de calibration spatial:

```toml
[calibration.outputs.active_network]
variable = "outflow_drain"
support = "network"
time = "last"
observed_path = "truth/active_network_reference.tif"
threshold = 0.0
activation = "strictly_positive"
```

Diagnostic secondaire possible:

```toml
[calibration.outputs.accumulated_network]
variable = "accumulation_flux"
support = "map"
time = "last"
observed_path = "truth/accumulated_network_reference.tif"
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

Prioritaire pour la phase initiale MODFLOW 6. Le chemin actuel lit les budgets
binaires pour sommer DRAIN; il faut en faire une sortie de calibration explicite
et reproductible:

- serie `Q_total_release(t)` calculee comme somme des sorties DRAIN positives
  sur tout le domaine actif;
- DRAIN par cellule et par pas de temps;
- eventuellement CHD/RIV si les cas les utilisent;
- `accumulation_flux` si disponible en sortie derivee, ou equivalent calcule a
  la volee sur le support de drainage.

Pour la calibration legere, idealement on lit les binaires sans passer par le
catalogue complet, afin de garder les iterations rapides.

### 8.4. Extraction Boussinesq

Non prioritaire pour la toute premiere phase MODFLOW 6, mais a conserver comme
extension de robustesse. Ajouter ensuite au
`BoussinesqFlowAdapter.extract_calibration_series` ou a un extracteur dedie:

- serie de debit total de calibration:
  `Q_total_release = drainage + surface_excess`;
- sommation prioritaire sur tout le domaine actif pour un cas Boussinesq
  ulterieur;
- series separees de diagnostic: `Q_drain` et `Q_excess`;
- champ `drainage_flux_m3_s`;
- champ ou budget `surface_excess`, ou reconstruction depuis
  `saturation_excess_history_m_s`;
- champ derive `release_flux` si disponible;
- serie de charge a un point ou une cellule;
- selection temporelle compatible avec `time = "all"`, `first`, `last`;
- champ reseau permanent derive ou relu depuis les sorties:
  `outflow_drain`, `release_flux`, `accumulation_flux`, ou equivalent routable.

Le module Boussinesq a deja des historiques de flux et d'etat. Le travail est
principalement d'aligner ces sorties avec le contrat calibration.

### 8.5. Multi-scenario calibration

Le vrai saut conceptuel est de permettre plusieurs runs par candidat. Deux
options:

1. `metric_fn` specifique pour les prototypes S4.
2. Extension generique du schema avec scenarios.

L'option 1 est plus rapide pour apprendre. L'option 2 est meilleure pour la
maintenance et pour des campagnes naturelles reproductibles.

### 8.6. Exemple B0 isole

Le developpement ne doit pas etre accroche directement a un exemple existant
comme une variante cachee. Il faut creer un nouvel exemple autonome:

```text
examples/projects/12_calibration_network_transient_b0/
```

Cet exemple peut reutiliser un petit domaine connu, par exemple `site_05`, mais
il doit porter son propre contrat de calibration:

```text
README.md
configs/
  truth_steady_network.toml
  truth_transient_discharge.toml
  candidate_steady_network.toml
  candidate_transient_discharge.toml
truth/
  metadata.json
  normalization.json
  steady_network_drain_by_cell.npz
  steady_network_active_mask.npz
  transient_q_total_release.csv
  cell_geometry.npz
```

Le but de ce nouvel exemple est de rendre visible ce qui est specifique au
prototype B0:

- generation des pseudo-observations MODFLOW 6;
- paquet `truth/` fige avant l'inversion;
- metrique reseau fondee sur `outflow_drain`;
- RMSE debit sur `Q_total_release`;
- `metric_fn` specialisee qui orchestre les deux scenarios.

Ainsi les exemples naturels, les comparaisons MF6/Boussinesq et les workflows
existants restent inchanges. L'exemple B0 devient le lieu explicite ou l'on
apprend le contrat avant de le promouvoir dans l'API generale.

## 9. Premier plan de travail

1. Documenter le probleme et les limites actuelles: ce fichier.
2. Verifier les sorties MODFLOW 6 disponibles pour `Q_total_release`,
   `outflow_drain` et `accumulation_flux`.
3. Creer le nouvel exemple isole
   `examples/projects/12_calibration_network_transient_b0/`.
4. Ajouter un micro-benchmark objectif sans solveur pour les metriques reseau.
5. Construire le B0-MODFLOW 6 transitoire avec chronique mensuelle et
   sortie `Q_total_release`.
6. Construire le B0-MODFLOW 6 permanent qui produit le masque de drainage
   reference.
7. Explorer d'abord la grille `15 x 15`, puis `25 x 25` si la surface objectif
   est propre.
8. Brancher une `metric_fn` prototype reseau + debit sur un seul run MODFLOW 6.
9. Brancher le prototype S4 avec deux runs MODFLOW 6 par candidat.
10. Decider ensuite si l'extension declarative multi-scenario est justifiee.
11. Reprendre Boussinesq comme comparaison et test de transfert entre solveurs.

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
  -> extraction MODFLOW 6 q_total_release et reseau
  -> twin MODFLOW 6 debit transitoire
  -> twin MODFLOW 6 reseau permanent
  -> objectif conjoint MODFLOW 6 K+Sy sur un run
  -> objectif conjoint MODFLOW 6 K+Sy sur deux scenarios
  -> pseudo-observations naturelles MODFLOW 6
  -> comparaison externe Boussinesq optionnelle
  -> observations reelles
```

Il ne faut pas commencer directement par un bassin naturel avec hydrographie et
debit observes. Ce serait difficile a interpreter: on ne saurait pas si un
echec vient de la metrique reseau, du solveur, des donnees, de la recharge, du
poids des objectifs ou de l'identifiabilite.

Le code actuel est suffisamment avance pour lancer la phase synthetique. Il
manque surtout une couche d'observables spatiales de calibration et, a terme,
un vrai support multi-scenario par candidat.

## 11. Suite des echanges question-reponse

Cette section reprend le cadrage au point ou la trajectoire a ete recentree sur
un premier cycle MODFLOW 6 -> MODFLOW 6. L'objectif est de transformer la note
methodologique en decisions directement codables, sans lancer trop tot une
campagne multi-scenario lourde.

### 11.1. Quel est le prochain geste concret?

Reponse: commencer par S0, c'est-a-dire un banc objectif sans solveur.

Il ne faut pas commencer par un run MODFLOW 6 complet. Le risque serait de ne
plus savoir si une anomalie vient de la metrique, de l'extraction CBC, du
maillage, du solveur ou de l'optimiseur. Le premier livrable doit donc etre un
petit module de metriques reseau, teste sur des tableaux controles:

```text
d_ref_i, d_sim_i
R_ref, R_sim
cell_area_i ou cell_length_i
distance_to_ref_i
distance_to_sim_i
```

Les tests doivent verifier au minimum:

- cout nul quand simulation et reference sont identiques;
- cout fini si `R_sim` est vide ou si `R_ref` est vide;
- augmentation de `E_dist` quand le reseau simule est decale;
- augmentation de `E_len` quand le reseau simule est trop long ou trop court;
- ponderation correcte par `outflow_drain`, afin qu'une branche majeure compte
  plus qu'une branche residuelle.

Ce banc ne doit pas dependre de FloPy, DuckDB, du catalogue ou d'un fichier
TOML complet.

### 11.2. Peut-on deja declarer `Q_total_release` en TOML standard?

Reponse courte: pas proprement dans le schema composite actuel.

Le chemin legacy `variable = "discharge"` sait deja lire le budget DRAIN et
retourner une serie totale via `extract_discharge_from_cbc`. C'est proche de ce
que l'on veut pour B0:

```text
Q_total_release(t) = somme des sorties DRAIN positives sur le domaine actif
```

Mais le schema enrichi actuel ne contient que:

```text
support = "point" | "boundary" | "cell"
```

Il ne contient pas encore:

```text
support = "domain"
```

De plus, l'adaptateur MODFLOW 6 expose aujourd'hui `variable = "discharge"` en
total DRAIN, mais pas un filtrage propre par `boundary_id`. Donc, pour le
prototype B0, deux chemins sont possibles:

1. utiliser une `metric_fn` dediee qui appelle directement le chemin
   `discharge` total;
2. etendre ensuite le schema avec `support = "domain"` et
   `variable = "total_release"`.

Le premier chemin est le bon pour apprendre vite. Le second est le bon pour une
campagne reproductible a long terme.

### 11.3. Comment obtenir `outflow_drain` spatial pour le score reseau?

Reponse: il manque encore un extracteur spatial de budget DRAIN par cellule.

Le lecteur leger actuel sait sommer le budget DRAIN a chaque pas de temps. Pour
le reseau, il faut un voisin de cet extracteur qui retourne le champ cellulaire,
pas seulement le total:

```text
extract_drain_from_cbc(..., reducer="cell")
  -> tableau [time, cell] ou [cell]
```

Pour B0 permanent, le besoin minimal est encore plus simple:

```text
d_i = DRAIN par cellule au dernier pas ou a l'unique pas permanent
```

Ce champ devient `outflow_drain`. On applique ensuite:

```text
d_i = abs(min(DRAIN_i, 0))
R = {i | d_i > 0}
Q_total_release = sum_i d_i
```

Le point important est de garder une convention de signe unique. Dans les
budgets MODFLOW, les sorties DRAIN apparaissent classiquement comme des flux
negatifs pour le modele souterrain. Pour la calibration, on convertit en flux
sortant positif.

### 11.4. Faut-il bloquer B0 sur `accumulation_flux`?

Reponse: non.

`accumulation_flux` est utile pour visualiser une organisation aval du drainage,
mais il ne doit pas bloquer le premier score. Le cout principal B0 peut etre
entierement fonde sur `outflow_drain`:

- `E_flux` compare les flux locaux;
- `E_dist` compare la localisation ponderee par ces flux;
- `E_len` compare l'extension active.

`accumulation_flux` peut rester un diagnostic produit apres coup, quand le
routage du champ de drainage est disponible. Il ne doit pas etre une
precondition pour tester l'objectif inverse.

### 11.5. Le seuil `tau_network = 0` est-il trop fragile?

Reponse: il est fragile, mais il est volontaire pour B0.

Le contrat physique retenu est:

```text
R = {i | d_i > 0}
```

et non:

```text
R = {i | d_i >= 0}
```

La stricte positivite evite d'activer toutes les cellules a flux nul. Si des
residus numeriques minuscules polluent le masque, il faut d'abord les mesurer:

```text
min_positive_drain
quantiles des d_i positifs
nombre de cellules actives avec d_i << Q_total_release
```

Ensuite seulement, on peut tester hors calibration un epsilon de nettoyage:

```text
R_eps = {i | d_i > eps_clean}
```

Cet epsilon ne doit pas etre choisi apres coup pour ameliorer le score. Il doit
etre documente comme sensibilite numerique, pas comme parametre cache de
calibration.

### 11.6. Quels objets de reference faut-il figer avant l'inversion?

Reponse: tout ce qui definit l'echelle du probleme inverse.

Pour le reseau permanent:

```text
d_ref_i
R_ref
Q_ref_steady
L_ref
d_tol
eta_flux, eta_dist, eta_len
a_flux, a_dist, a_len
```

Pour le debit transitoire:

```text
Q_ref(t)
fenetre scoree
Qbar_ref
alpha_Q
```

Pour l'objectif conjoint:

```text
w_reseau
w_debit
eventuellement J_sum ou J_max comme diagnostic
```

Ces objets doivent etre ecrits dans un repertoire `truth/` ou equivalent. Une
iteration candidate ne doit jamais recalculer ses propres denominateurs de
normalisation.

### 11.7. Comment gerer les deux scenarios dans un prototype S4?

Reponse: commencer par une `metric_fn` specialisee, pas par une extension
declarative complete.

Le moteur de calibration actuel est organise autour d'un run candidat. Pour S4,
un candidat doit declencher deux runs:

```text
theta
  -> config steady_network avec K(theta), Sy(theta)
  -> config transient_discharge avec K(theta), Sy(theta)
  -> C_reseau_phys
  -> C_debit_phys
  -> J
```

La premiere implementation peut donc etre une fonction de metrique explicite
qui:

1. recoit le contexte candidat ou les valeurs `theta`;
2. applique les memes parametres aux deux configurations;
3. lance les deux runs dans des dossiers de scratch distincts;
4. lit les sorties legeres;
5. retourne `J` et les composantes.

Ce prototype apprendra les contraintes pratiques: temps par evaluation,
nettoyage des fichiers, taux d'echec, cache de maillage, et forme des
diagnostics. L'extension TOML `[[calibration.scenario]]` ne doit venir qu'une
fois ce contrat stabilise.

### 11.8. Quel est le critere de validite d'un candidat?

Reponse: un candidat valide n'est pas seulement un candidat avec un cout fini.

Pour B0, il faut au minimum enregistrer:

```text
solver_success
Q_total_release fini et positif
C_reseau_phys fini
C_debit_phys fini
fermeture de bilan si disponible
nombre de cellules actives
minimum/maximum de charge si disponible
```

Un candidat qui reproduit `Q(t)` mais avec un reseau entierement vide, un
budget incoherent ou une charge non physique doit etre marque comme invalide ou
penalise explicitement. Cette regle doit etre separee du cout principal: elle
releve du controle de qualite de simulation, pas de la ponderation
reseau/debit.

### 11.9. Quel ordre de developpement est le plus propre?

Reponse: l'ordre le moins ambigu est le suivant.

1. Ajouter `hydromodpy/calibration/network_metrics.py` avec tests unitaires
   purs.
2. Ajouter un extracteur MODFLOW leger pour DRAIN par cellule, en reutilisant
   la logique de `extract_discharge_from_cbc`.
3. Construire une reference B0 permanente et verifier `d_ref_i`, `R_ref`,
   `Q_ref_steady`, `L_ref`.
4. Construire une reference B0 transitoire et verifier `Q_ref(t)`, `Qbar_ref`,
   la fenetre scoree de 36 mois.
5. Explorer une grille `K/Sy` sans optimiseur complexe.
6. Brancher seulement ensuite random search, CMA-ES ou Nelder-Mead.
7. Prototyper S4 avec deux runs par candidat.

Cet ordre garde le solveur, les metriques et l'optimiseur decouples aussi
longtemps que possible.

### 11.10. Quelle decision reste a trancher pour B0?

Reponse: le choix exact du petit domaine controle, plutot qu'un bassin
synthetique pur.

Deux options sont defendables:

- un petit domaine reel ou pseudo-reel issu de la chaine geographique, plus
  proche des cas naturels et directement utile pour les diagnostics reseau;
- une grille structuree simple, plus facile pour tester les distances et les
  masques, mais moins representative du workflow vise.

La recommandation corrigee est de commencer par un petit domaine naturel
controle, pas par une geometrie entierement artificielle. Il doit etre assez
petit pour permettre une grille `K/Sy` et des relances rapides, mais assez reel
pour tester les memes objets que la suite: MNT, exutoire, drainage, support
cellulaire, hydrographie de reference et extraction de budget DRAIN.

Le point scientifique a ne pas perdre est le suivant: B0 sert a valider
l'objectif inverse sur un domaine geographique interpretable, pas a reproduire
toute la complexite des grandes campagnes naturelles. On accepte donc un petit
domaine avec pseudo-observations MODFLOW 6, recharge controlee et
parametrisation volontairement simple.

### 11.11. Quel petit domaine choisir pour B0?

Reponse: choisir un domaine deja connu de la chaine testbed, avec faible aire,
maillage stable et sorties rapides.

Le candidat ideal n'est pas "le plus naturel possible". C'est un domaine qui
permet de deboguer l'objectif sans que les echecs de workflow dominent
l'analyse. Les criteres de selection sont:

- aire faible, typiquement 5 a 20 km2;
- maillage triangulaire ou DISV deja fonctionnel;
- exutoire et bassin sans ambiguite;
- trace riviere disponible si le mode `geology_rivers` est active;
- pas de collision catalogue ou de dependance a un ancien artefact;
- temps de run compatible avec une grille exploratoire `K/Sy`;
- drainage MODFLOW 6 actif et lisible dans le budget;
- absence d'echec connu d'initialisation stationnaire sur la variante de base.

Sur la base des artefacts naturels deja analyses, `site_05`, `site_06` ou
`site_07` sont de meilleurs candidats que `site_02` ou `site_08`:

- `site_05`, `site_06` et `site_07` ont deja des comparaisons N1 terminees;
- leurs aires restent proches du format petit bassin;
- `site_02` porte un echec d'initialisation MODFLOW 6 stationnaire dans N1 et
  plusieurs echecs Boussinesq recents;
- `site_08` est beaucoup trop grand pour servir de premier B0 rapide.

Le choix le plus prudent est donc:

```text
B0 = petit domaine naturel controle
solveur truth = MODFLOW 6
solveur candidat initial = MODFLOW 6
parametres calibres = multiplicateur global de K, puis Sy
observables = reseau permanent + Q_total_release transitoire
```

Il faut traiter l'hydrographie naturelle comme diagnostic spatial, pas comme
verite hydrologique stricte. Pour le premier B0, la reference de calibration
doit rester une pseudo-observation produite par MODFLOW 6 avec un couple
`K_true/Sy_true` connu. Cela conserve l'avantage du twin experiment tout en
utilisant un petit domaine reel.

La question suivante devient donc: quelle variante exacte de ce petit domaine
sert de `truth`, et comment degrade-t-on le candidat sans changer le domaine,
le maillage ni le forcage?

### 11.12. Quelle variante exacte sert de B0 principal?

Reponse: `site_05` est le meilleur B0 principal dans l'etat actuel des
artefacts.

Ce choix n'est pas fonde sur le fait que `site_05` serait hydrologiquement le
plus representatif. Il est fonde sur son utilite comme premier domaine controle:

- aire d'environ 9.92 km2 dans les sorties de bilan;
- comparaison N1 terminee;
- comparaison candidats reseau terminee avec `mf6_unstructured_reference` et
  `bouss_unstructured_same_mesh`;
- temps de resolution faible dans les artefacts candidats reseau:
  environ 30 s pour MODFLOW 6 triangulaire contraint et environ 5 s pour
  Boussinesq meme maillage;
- bilans numeriques faibles;
- convergence Boussinesq TS VI propre dans la comparaison recente;
- ecart Boussinesq/MODFLOW 6 a meme maillage faible en fin de simulation:
  RMSE `head_map_last` autour de 0.87 m.

Le role de `site_05` n'est pas de prouver l'equivalence entre solveurs. Pour la
calibration initiale, la verite et le candidat restent tous deux MODFLOW 6. Le
role de `site_05` est de fournir un petit support geographique deja robuste
pour tester:

```text
extraction DRAIN par cellule
construction R_ref
construction Q_total_release(t)
normalisation C_reseau_phys / C_debit_phys
exploration K/Sy
```

Deux cas doivent rester en reserve:

- `site_03_low_k` comme B0bis, car il montre un bon accord Boussinesq/MODFLOW 6
  a meme maillage et des metriques reseau naturelles moins nulles que `site_05`;
- `site_01` comme cas technique rapide pour tester la matrice K/drainage, mais
  avec prudence car N1 avait un echec catalogue et le recouvrement au reseau
  naturel peut etre nul.

Donc:

```text
B0 principal = site_05
B0bis        = site_03_low_k, si le reseau pseudo-observe de site_05 est trop peu informatif
```

### 11.13. Quelle simulation sert de `truth`?

Reponse: une nouvelle simulation MODFLOW 6 triangulaire contrainte, regeneree
proprement, pas une simple reutilisation silencieuse d'un artefact de
comparaison.

La simulation de reference doit reprendre l'esprit de
`mf6_unstructured_reference`, mais elle doit etre relancee dans un espace de
travail isole afin de produire des pseudo-observations propres:

```text
truth solver       = MODFLOW 6
truth domain       = site_05
truth mesh         = maillage triangulaire contraint fixe
truth K            = K_true, issu de la configuration de base ou d'un facteur fixe
truth Sy           = Sy_true = 0.05 pour B0
truth drainage     = conductance top-drain fixe
truth recharge     = chronique controlee, moyenne compatible avec le permanent
truth runoff       = 0.0 pour B0
```

Il faut deux sorties de verite:

```text
steady_network_truth:
  run permanent ou pseudo-permanent a recharge moyenne
  -> d_ref_i = outflow_drain par cellule
  -> R_ref = {i | d_ref_i > 0}
  -> Q_ref_steady
  -> L_ref

transient_discharge_truth:
  run transitoire mensuel
  -> Q_ref(t) = Q_total_release(t)
  -> Qbar_ref sur la fenetre scoree
```

Le permanent et le transitoire doivent partager le meme domaine, le meme
maillage, les memes proprietes verticales et la meme conductance de drainage.
Ils different seulement par le regime de forcage temporel.

### 11.14. Comment degrade-t-on le candidat?

Reponse: au debut, on ne degrade pas le domaine, le maillage, le drainage ou la
recharge. On degrade seulement les parametres calibres.

Le premier candidat est donc aussi MODFLOW 6 sur `site_05`, avec exactement le
meme support spatial que la verite. Le vecteur inverse reste:

```text
theta = {mK, Sy}
```

ou:

```text
K_candidate_i = mK * K_base_i
Sy_candidate  = Sy
```

Ce choix est plus propre que de calibrer directement une carte de K. Il permet
de tester si l'objectif conjoint retrouve:

```text
mK_true = 1.0
Sy_true = 0.05
```

Bornes de depart recommandees:

```text
mK in [0.1, 10.0]      en log10
Sy in [0.02, 0.20]     en lineaire, ou logit plus tard
```

Une plage plus courte peut etre utilisee pour le tout premier smoke test:

```text
mK in [0.3, 3.0]
Sy in [0.03, 0.12]
```

Ce qu'il ne faut pas faire dans B0:

- changer le maillage candidat;
- changer la conductance de drainage;
- changer la recharge;
- changer les conditions limites;
- comparer MODFLOW 6 candidat a Boussinesq truth;
- introduire des multiplicateurs geologiques par zone.

Ces variantes viendront apres, quand le cout `C_reseau_phys + C_debit_phys`
aura montre qu'il retrouve deja le couple vrai dans le cas le plus controle.

### 11.15. Quelle chronique utiliser pour le transitoire B0?

Reponse: utiliser une chronique mensuelle controlee, pas la chronique naturelle
comme observation reelle.

Deux options existent:

1. reprendre les 24 mois mensuels deja utilises dans les comparaisons
   naturelles;
2. construire une chronique mensuelle de 48 mois, avec une premiere annee non
   scoree et 36 mois scores.

La recommandation est:

```text
smoke test B0:
  24 mois existants
  score sur les 12 a 18 derniers mois si l'etat initial est stable

B0 de calibration propre:
  48 mois mensuels
  premiere annee de mise en regime non scoree
  score RMSE_Q sur les 36 derniers mois
```

Le permanent reseau doit utiliser une recharge moyenne coherente avec la
chronique transitoire:

```text
R_steady_ref = mean(R_transient(t))
```

ou une valeur choisie explicitement puis imposee comme moyenne de la chronique.
L'important est que le reseau permanent et le debit transitoire representent le
meme systeme physique moyen.

### 11.16. Quels fichiers de reference faut-il produire?

Reponse: il faut produire un petit paquet `truth/` versionne et relisible par
les fonctions de cout, sans relancer la simulation de verite a chaque essai.

Contenu minimal:

```text
truth/
  metadata.json
  steady_network_drain_by_cell.csv ou .npz
  steady_network_active_mask.csv ou .npz
  transient_q_total_release.csv
  normalization.json
  cell_geometry.csv ou .npz
```

`metadata.json` doit contenir:

```text
site_id
truth_solver
truth_config_path
mesh_id ou hash de maillage
K_true ou mK_true
Sy_true
drain_conductance
recharge_summary
time_window_scored
date_generation
```

`normalization.json` doit contenir les denominateurs figes:

```text
Q_ref_steady
L_ref
d_tol
eta_flux
eta_dist
eta_len
a_flux
a_dist
a_len
Qbar_ref
alpha_Q
w_reseau
w_debit
```

La question suivante devient alors strictement technique: faut-il commencer par
coder les metriques reseau pures ou par l'extracteur DRAIN cellulaire MODFLOW 6?

### 11.17. Quel premier code faut-il ecrire?

Reponse: commencer par les metriques reseau pures, puis seulement ensuite
l'extracteur DRAIN cellulaire.

Raison: les metriques peuvent etre testees sans solveur, sans FloPy, sans
catalogue et sans fichiers binaires. Elles sont le noyau de l'objectif. Si elles
sont mal definies, un extracteur parfait ne rendra pas la calibration
interpretable.

Premier module cible:

```text
hydromodpy/calibration/network_metrics.py
```

Fonctions minimales:

```text
network_flux_error(d_sim, d_ref, q_ref_steady)
network_distance_error(d_sim, d_ref, dist_to_ref, dist_to_sim, d_tol, q_ref_steady)
network_length_error(mask_sim, mask_ref, cell_length_or_area)
network_cost(...)
```

Tests unitaires a ecrire avant toute simulation:

- identite: cout nul;
- reseau vide simule: cout fini et eleve;
- reseau reference vide: erreur explicite ou convention documentee;
- decalage d'une maille: `E_dist` proche de 1 si `d_tol = dx`;
- erreur de flux sans decalage: `E_flux` augmente, `E_dist` reste faible;
- branche marginale erronee: cout plus faible qu'une erreur sur l'axe majeur.

Une fois ces tests passes, on peut coder l'extracteur DRAIN cellulaire MODFLOW
6 en reutilisant la logique de `extract_discharge_from_cbc`. L'objectif est de
retourner a la fois:

```text
Q_total_release(t)
DRAIN_by_cell(t, i)
DRAIN_by_cell_last(i)
```

La prochaine question apres les metriques est donc: quelle convention exacte
utiliser pour les distances reseau sur maillage triangulaire, centre cellule ou
geometrie d'aretes?

### 11.18. Quelle convention de distance utiliser sur maillage triangulaire?

Reponse: pour B0, utiliser une convention centre-cellule, pas une geometrie
d'aretes.

Le champ principal est `outflow_drain` par cellule. Le support naturel de la
metrique est donc le centre de cellule:

```text
x_i, y_i = centroide de la cellule i
d_i      = outflow_drain positif de la cellule i
R        = {i | d_i > 0}
```

La distance au reseau est alors:

```text
dist_to_ref_i = min_{j in R_ref} || centroid_i - centroid_j ||
dist_to_sim_i = min_{j in R_sim} || centroid_i - centroid_j ||
```

Cette convention est volontairement simple:

- elle correspond directement au support de `outflow_drain`;
- elle fonctionne sur maillage triangulaire et sur grille structuree;
- elle ne demande pas de reconstruire des lignes hydrographiques;
- elle suffit pour tester la normalisation physique du cout.

Elle ne pretend pas mesurer une vraie distance a une polyligne de riviere. En
B0, le reseau calibre est une emprise cellulaire de drainage, pas encore un
objet vectoriel routable. Une version arete/polyligne pourra venir ensuite si
`accumulation_flux` ou un routage explicite devient l'observable principale.

La longueur active doit suivre la meme logique. Sur un support cellulaire
irregulier, on evite de compter seulement les cellules. Le choix B0 est une
longueur equivalente de ruban:

```text
L(R) = sum_{i in R} area_i / d_tol
```

ou `d_tol` represente la largeur acceptable du corridor de drainage. Cela se
lit comme: aire active divisee par largeur de corridor. Sur grille reguliere,
cette definition revient a une longueur proportionnelle au nombre de cellules
actives. Sur triangles irreguliers, elle evite de favoriser artificiellement
les zones plus raffinees.

### 11.19. Comment calculer ces distances efficacement pendant la calibration?

Reponse: pre-calculer ce qui depend de la reference et reconstruire seulement
ce qui depend du candidat.

Avant l'inversion, on fixe:

```text
centroids[i] = (x_i, y_i)
area_i
R_ref
d_ref_i
dist_to_ref_i = distance de chaque cellule au support R_ref
```

Pendant chaque evaluation candidate:

```text
R_sim = {i | d_sim_i > 0}
dist_to_sim_i = distance de chaque cellule au support R_sim
```

Pour B0, un arbre de plus proches voisins suffit:

```text
KDTree(centroids[R_ref]) -> dist_to_ref
KDTree(centroids[R_sim]) -> dist_to_sim
```

Si `R_sim` est vide, il ne faut pas laisser la distance devenir `NaN`. La
convention recommandee est:

```text
E_flux = sum_i abs(d_sim_i - d_ref_i) / Q_ref_steady
E_dist = penalite_dist_empty
E_len  = 1.0
```

avec `penalite_dist_empty` documentee, par exemple une distance moyenne du
domaine au reseau reference divisee par `d_tol`. Cela rend le candidat tres
mauvais mais encore exploitable par un optimiseur robuste.

La reference vide est un cas different. Si `R_ref` est vide, le domaine ne
convient pas a B0 reseau et doit etre rejete avant calibration. Un B0 sans
reseau de drainage de reference ne teste pas l'objectif spatial.

### 11.20. Quelle est la prochaine action apres cette convention?

Reponse: ecrire un micro-jeu de tests pour `network_metrics.py` qui encode ces
conventions sans lire aucun fichier HydroModPy.

Le micro-jeu minimal peut etre une grille de 5 x 5 cellules avec:

```text
centroids reguliers
area_i = dx * dx
d_tol = dx
R_ref = colonne centrale
d_ref_i = flux fort sur l'axe, flux faible sur une branche laterale
```

Cas de test:

1. `R_sim = R_ref`, `d_sim = d_ref`: cout nul.
2. `R_sim` decale d'une colonne: `E_dist` proche de 1.
3. `R_sim` vide: penalite finie et elevee.
4. flux de l'axe principal manque: `E_flux` eleve.
5. branche laterale manque: `E_flux` plus faible que dans le cas 4.
6. reseau simule deux fois plus large: `E_len` proche de 1 si la longueur
   equivalente double.

Quand ces tests passent, on peut brancher l'extracteur DRAIN cellulaire. A ce
moment-la seulement, les erreurs observees dans B0 auront une interpretation:
elles viendront du solveur, de l'extraction ou de la configuration, pas d'une
metrique non testee.

### 11.21. Quand modifier l'API generale de calibration?

Le bloc "a ne pas modifier au depart" n'est pas secondaire. Au contraire, il
contient probablement l'architecture cible: declaration des observations,
plusieurs scenarios par evaluation, blocs d'objectif normalises physiquement,
diagnostics persistants. La raison pour ne pas le modifier en premier est que
le contrat exact n'est pas encore stabilise. Il faut d'abord transformer l'idee
en exemple executable isole.

Le developpement B0 doit donc utiliser au debut le point d'extension deja
existant: une fonction metrique specialisee, appelee par le moteur de
calibration sans changer l'optimiseur. Ce n'est pas une solution definitive,
mais une specification compacte. Elle permet de verifier que les definitions
suivantes tiennent ensemble:

```text
theta = {mK, Sy}
simulation permanente -> reseau outflow_drain
simulation transitoire -> Q_total_release(t)
C_reseau_phys = metrique reseau / normalisation permanente
C_debit_phys  = RMSE(Q_total_release) / (alpha_Q * Qbar_ref)
J = 0.5 * C_reseau_phys + 0.5 * C_debit_phys
```

Il faudra modifier l'API generale quand au moins une de ces conditions sera
vraie:

1. B0 retrouve correctement `mK` et `Sy` sur `site_05` en 15 x 15 puis 25 x 25.
2. Le meme code metrique sert a un deuxieme cas, par exemple B0bis
   `site_03_low_k`, sans duplication substantielle.
3. On veut lancer la calibration uniquement par fichiers TOML, sans fonction
   Python ad hoc.
4. La fonction metrique commence a gerer elle-meme trop de choses:
   orchestration de scenarios, lecture d'observations, normalisations,
   stockage des diagnostics, rapports.
5. Les diagnostics par composante doivent devenir des sorties standard de la
   plateforme et non des fichiers propres a l'exemple B0.
6. Un deuxieme solveur ou un deuxieme type de cas partage le meme contrat
   `outflow_drain` / `Q_total_release`.

Les modifications a faire a ce moment-la seraient ciblees:

- `CalibrationConfig`: ajouter une declaration de scenarios lies par le meme
  vecteur de parametres, avec chemins d'observations, type d'observation et
  normalisation.
- `objective_blocks`: accepter des observations de type champ cellulaire,
  support de reseau, serie temporelle de debit et metadonnees de normalisation
  physique.
- moteur d'evaluation: executer plusieurs configurations pour un meme
  `theta`, isoler leurs repertoires temporaires, agreger les echecs et passer
  les sorties aux blocs d'objectif.
- persistence et rapports: enregistrer `C_reseau_phys`, `C_debit_phys`, `J`,
  les RMSE, les erreurs de flux, distance et longueur, et les chemins des
  artefacts diagnostiques.
- extracteurs solveur: standardiser deux sorties minimales, `DRAIN_by_cell` en
  permanent et `Q_total_release(t)` en transitoire.

Ce qui ne devrait pas changer, meme lors de cette promotion, est l'optimiseur.
Il doit continuer a voir une fonction scalaire `J(theta)` et des diagnostics.
Le changement porte sur la facon de declarer, executer et tracer l'objectif,
pas sur la logique d'optimisation elle-meme.

Cette sequence limite la croissance de complexite: on ajoute d'abord un
exemple autonome et quelques fonctions testees, puis on promeut seulement les
pieces qui ont prouve qu'elles etaient generiques.

## 12. Premier passage reel MF6 site_01

Un premier smoke test avec vraies simulations MODFLOW 6 a ete lance le
2026-05-14, en restant volontairement hors de l'API generale de calibration.
Le but n'etait pas encore de faire une grille complete, mais de verifier que
le contrat B0 fonctionne sur des catalogues HydroModPy reels:

```text
permanent MF6 -> outflow_drain par cellule
transitoire MF6 mensuel -> Q_total_release(t)
truth package -> normalisation fixe
score candidat -> J = 0.5 C_reseau_phys + 0.5 C_debit_phys
ranking CSV -> classement de candidats
```

### 12.1. Simulations lancees

Les runs ont ete faits depuis WSL avec le TOML courant
`base_site_01_mf6_bouss_transient.toml`, en redirigeant seulement les sorties
vers:

```text
examples/projects/12_calibration_network_transient_b0/outputs/real_runs/
```

Runs realises:

| role | dossier | regime | periodes | statut |
|---|---|---|---:|---|
| verite reseau | `base_site_01_truth_steady_mf6` | steady | 1 | termine |
| verite debit | `base_site_01_truth_transient_mf6` | transient | 24 mois | termine |
| candidat reseau | `candidate_mK_1p25_Sy_0p08_steady_mf6` | steady | 1 | termine |
| candidat debit | `candidate_mK_1p25_Sy_0p08_transient_mf6` | transient | 24 mois | termine |

Le permanent utilise une recharge moyenne de la chronique synthetique
existante:

```text
R_mean = 0.6629166666666667 mm/day
```

Le transitoire reste, pour ce premier passage, la chronique deja presente dans
le testbed naturel existant: 24 pas mensuels. Ce n'est pas encore la cible
finale de 3-4 ans, mais cela suffit pour verifier le chemin complet avec des
sorties reelles.

### 12.2. Truth package obtenu

Le package verite a ete ecrit dans:

```text
examples/projects/12_calibration_network_transient_b0/outputs/real_runs/site_01_truth_package/
```

Normalisation obtenue:

| grandeur | valeur |
|---|---:|
| `n_cells` | 560 |
| `n_timesteps` | 24 |
| `n_ref_active` | 22 |
| `Q_ref_steady` | `0.0181266463129 m3/s` |
| `Qbar_ref` | `0.0187350366498 m3/s` |
| `L_ref` | `938.665320108 m` |
| `d_tol` | `63.1860433499 m` |
| `alpha_Q` | `0.10` |
| `w_reseau`, `w_debit` | `0.5`, `0.5` |

Le score identite donne bien un cout nul a l'arrondi numerique pres:

```text
J = 1.56662214037e-14
C_reseau_phys = 0.0
C_debit_phys  = 3.13324428074e-14
```

### 12.3. Premier candidat perturbe

Un candidat reel a ete lance avec:

```text
mK = 1.25
Sy = 0.08
```

La modification `mK` a ete appliquee en copiant le CSV de conductivite
geologique et en multipliant la colonne `K_value` par `1.25`. `Sy` a ete
injecte par overlay TOML.

Score obtenu:

```text
J = 1.6074502402326274
C_reseau_phys = 2.2499458514167916
C_debit_phys  = 0.9649546290484632
```

Composantes principales:

| composante | valeur |
|---|---:|
| `E_flux` | `0.2097992550` |
| `E_dist` | `0.0477128178` |
| `E_len` | `0.2762333420` |
| `RMSE_Q` | `0.0018078460 m3/s` |
| `RMSE_Q / Qbar_ref` | `0.0964954629` |
| `n_sim_active` | 15 |

Le classement a ete ecrit dans:

```text
examples/projects/12_calibration_network_transient_b0/outputs/real_runs/site_01_candidate_scores.csv
```

Il classe correctement:

1. `truth_identity`, `J ~= 0`;
2. `mK_1p25_Sy_0p08`, `J ~= 1.607`.

Ce test confirme que le contrat B0 fonctionne maintenant avec:

- des catalogues MODFLOW 6 reels;
- un permanent separe;
- un transitoire separe;
- une normalisation fixe issue de la reference;
- une extraction `outflow_drain` par cellule;
- une agregation `Q_total_release(t)`;
- un classement de candidats.

### 12.4. Points techniques observes

1. Les anciens TOML generes dans `outputs/` ne sont pas tous relancables tels
   quels avec le schema courant. Il faut repartir des TOML sources courants ou
   regenerer les configs.
2. Pour un permanent, `flow.ic.type = "steady_state"` doit etre remplace par
   une initialisation directe, par exemple `type = "top"`, car
   `steady_state` est reserve aux runs transitoires.
3. Le script `score_candidate_table.py` lit maintenant les CSV en
   `utf-8-sig`, afin de supporter les fichiers ecrits par PowerShell avec BOM.
4. Les runs reels doivent etre lances sous WSL pour garder le meme environnement
   que MODFLOW 6 et les dependances de lecture Zarr/Dask.

### 12.5. Prochaines etapes concretes

La prochaine etape utile est de transformer ce passage reel manuel en petit
driver reproductible B0:

1. generer une liste de candidats `{mK, Sy}`;
2. materialiser pour chacun un CSV `K_value * mK` et deux overlays;
3. lancer `steady` puis `transient` MF6;
4. construire ou reutiliser le truth package;
5. scorer tous les candidats dans `site_01_candidate_scores.csv`;
6. verifier que le minimum est proche de `{mK=1.0, Sy=0.05}`.

Seulement ensuite, il faudra passer au site cible B0 naturel choisi pour le
petit bassin et allonger la chronique transitoire a 36-48 mois mensuels.
Cette progression garde la complexite sous controle: le code metrique reste
pur et teste, les solveurs restent lances par les workflows existants, et la
promotion vers l'API generale n'est justifiee qu'apres une grille reelle
reproductible.

### 12.6. Utilitaires calibration deja disponibles

Il existe deja plusieurs briques a reutiliser dans `hydromodpy/calibration`:

- `ParameterSpace` et `CalibParameter` pour declarer `{mK, Sy}`, leurs bornes,
  leurs transformations et leurs modes `replace` / `scale`;
- `materialize_candidate()` pour ecrire un overlay TOML rejouable pour un
  candidat;
- `apply_parameter_to_config()` pour appliquer un parametre a une config en
  memoire;
- `objective_blocks` pour composer plusieurs contributions d'objectif quand
  les sorties sont deja exposees comme observables simples;
- `diagnostics.py` pour transformer une trace d'iterations en DataFrame et
  calculer des diagnostics de convergence/correlation.

Ces briques ne couvrent pas encore directement le cas B0 complet, pour trois
raisons:

1. un candidat B0 doit lancer deux scenarios lies par le meme vecteur
   `theta = {mK, Sy}`: un permanent reseau et un transitoire debit;
2. `mK` agit actuellement sur une colonne `K_value` d'un CSV geologique
   heterogene, pas sur une valeur scalaire TOML directement multipliable par
   `materialize_candidate()`;
3. l'observable reseau est un champ cellulaire `outflow_drain` transforme en
   support actif, distance et longueur equivalente, pas une simple serie ou un
   scalaire deja standardise par l'API calibration.

Conclusion de developpement: il faut reutiliser les utilitaires existants pour
les parties generiques, mais garder dans l'exemple B0 les deux pieces encore
specifiques:

- le petit transformateur `K_value * mK` pour produire un CSV K candidat;
- l'orchestration `steady + transient -> truth package -> score`.

Si B0 devient stable, la promotion naturelle ne sera pas un nouvel optimiseur:
ce sera une extension ciblee de la materialisation pour les champs externes et
une declaration de scenarios couples dans la config de calibration.

### 12.7. Balayage permanent de `mK` pour choisir une verite plus informative

Le premier choix `mK = 1.0` n'etait pas un choix physique. C'etait seulement le
multiplicateur neutre de la table geologique existante
`geology_K_dummy_demo.csv`. Le resultat permanent confirme que ce choix produit
une zone de drainage active assez reduite:

```text
mK = 1.0 -> 22 cellules actives sur 560, soit 3.93 %
```

Pour eviter une reference trop pauvre en affleurements/suintements, un balayage
permanent MF6 a ete lance avec la meme recharge moyenne et le meme maillage,
en ne changeant que le multiplicateur de la colonne `K_value`.

Fichier de synthese:

```text
examples/projects/12_calibration_network_transient_b0/outputs/real_runs/steady_mK_network_extent_summary.csv
```

Resultats avec `outflow_drain > 0`:

| `mK` | cellules actives | fraction active | longueur equivalente | `Q_total_release` | `q_max` |
|---:|---:|---:|---:|---:|---:|
| 0.50 | 38 / 560 | 6.79 % | 1868.8 m | `0.018126638` | `0.004981191` |
| 0.60 | 32 / 560 | 5.71 % | 1509.3 m | `0.018126569` | `0.005304903` |
| 0.65 | 31 / 560 | 5.54 % | 1425.6 m | `0.018126594` | `0.005444617` |
| 0.70 | 28 / 560 | 5.00 % | 1203.8 m | `0.018126562` | `0.005574024` |
| 0.75 | 26 / 560 | 4.64 % | 1169.2 m | `0.018126615` | `0.005696294` |
| 1.00 | 22 / 560 | 3.93 % | 938.7 m | `0.018126646` | `0.006211848` |
| 1.25 | 15 / 560 | 2.68 % | 679.4 m | `0.018126591` | `0.006560608` |

La somme totale de drainage reste quasiment constante parce que le permanent
equilibre la recharge imposee. Ce qui change vraiment avec `K` est donc la
repartition spatiale: plus `K` est faible, plus la nappe affleure/drainage se
repartit sur un support etendu; plus `K` est fort, plus le reseau actif se
contracte et les flux se concentrent.

Pour B0, le meilleur compromis actuel est:

```text
mK_truth = 0.65
Sy_truth = 0.05
```

`mK = 0.65` donne une zone active d'environ 31 cellules, soit 5.5 % du domaine.
C'est assez plus informatif que `mK = 1.0`, sans etendre le drainage autant que
`mK = 0.50`. Si l'objectif prioritaire est de rendre le signal reseau encore
plus visible dans le premier test inverse, `mK = 0.60` est une variante
defendable.

La prochaine verite B0 doit donc etre regeneree avec `mK_truth = 0.65`, puis la
grille inverse doit chercher autour de cette valeur, par exemple:

```text
mK in [0.40, 0.50, 0.60, 0.65, 0.75, 0.90, 1.10]
Sy in [0.02, 0.05, 0.08, 0.12]
```

### 12.8. Premier diagnostic HTML

Un premier rapport HTML local a ete ajoute cote exemple, sans changer l'API
generale:

```text
examples/projects/12_calibration_network_transient_b0/build_real_run_diagnostic_html.py
examples/projects/12_calibration_network_transient_b0/outputs/real_runs/web/index.html
```

La page a ete amelioree en reutilisant des morceaux existants plutot qu'en
recreant un mini-framework HTML:

- `hydromodpy.analysis.comparison.web.html_utils` pour les liens et
  echappements HTML statiques;
- `hydromodpy.display.figures.watershed_id_card.WatershedIdCardFigure` pour le
  contexte bassin/exutoire;
- `hydromodpy.display.figures.water_budget.WaterBudget` pour le bilan solveur;
- `hydromodpy.display._ugrid.render_face_field` pour dessiner correctement les
  cartes DISV de `outflow_drain`;
- les motifs de `examples/projects/10_testbed_workflow/generate_nwt_flux_testbed_web_report.py`
  pour les vues recharge/debit et reseau observe vs suintement.

Elle affiche maintenant:

- les constantes de normalisation du truth package;
- un contexte spatial du bassin et un budget steady sur le run `mK = 0.65`;
- le balayage `mK` permanent sous forme de tableau et de figure PNG;
- des cartes maillées de `outflow_drain` pour quelques valeurs de `mK`, ce qui
  remplace les simples cartes de centroides;
- le tableau des scores candidats deja calcules;
- l'hydrogramme PNG `Q_total_release(t)` reference/candidat quand le run
  transitoire est disponible.
- une decomposition graphique des contributions `C_reseau_phys` et
  `C_debit_phys`.

Figures produites:

```text
outputs/real_runs/web/figures/watershed_id_card.png
outputs/real_runs/web/figures/water_budget_mK_0p65.png
outputs/real_runs/web/figures/k_sweep_network_extent.png
outputs/real_runs/web/figures/outflow_drain_maps.png
outputs/real_runs/web/figures/network_support_diagnostics.png
outputs/real_runs/web/figures/q_total_release_timeseries.png
outputs/real_runs/web/figures/score_components.png
```

Les vues encore utiles pour le diagnostic de calibration complet seront:

1. carte reference/candidat du support `outflow_drain > tau_network`: ajoutee
   pour le premier candidat score;
2. carte des cellules ratees: faux positifs, faux negatifs, deplacement vers
   le plus proche reseau reference;
3. histogramme des flux drainants par cellule;
4. hydrogramme `Q_total_release(t)` reference/candidat;
5. decomposition de `J`: `C_reseau_phys`, `C_debit_phys`, puis
   `E_flux`, `E_dist`, `E_len`, `RMSE_Q / Qbar_ref`;
6. vue grille `{mK, Sy}`: heatmap de `J`, et heatmaps separees reseau/debit;
7. rappel des normalisations fixes: `Q_ref_steady`, `Qbar_ref`, `L_ref`,
   `d_tol`, `alpha_Q`.

La figure `network_support_diagnostics.png` couvre deja une partie du point 2:
elle colore les mailles communes, les manques du candidat et les exces du
candidat, puis trace l'histogramme des distances normalisees par `d_tol`.
Elle reste pour l'instant limitee au premier candidat complet de
`site_01_candidate_scores.csv`; elle devra devenir une petite galerie quand la
grille `{mK, Sy}` reelle contiendra plusieurs candidats.

La logique de visualisation doit rester dans l'exemple tant que le contrat B0
n'a pas ete valide par une grille reelle. Une fois le protocole stable, on
pourra extraire seulement les morceaux generiques dans un rapport calibration
standard.

### 12.9. Reference reelle `mK = 0.65`

Apres le balayage permanent, une premiere reference coherente avec
`mK_truth = 0.65` a ete regeneree:

```text
steady   : candidate_mK_0p65_Sy_0p05_steady_mf6
transient: candidate_mK_0p65_Sy_0p05_transient_mf6
truth    : site_01_truth_package_mK_0p65
scores   : site_01_candidate_scores_mK_0p65.csv
```

Le lancement a ete fait depuis le TOML source courant
`base_site_01_mf6_bouss_transient.toml`, pas depuis les TOML archives sous
`outputs/real_runs/configs/`, car ces derniers utilisent encore l'ancien schema
`field_heterogeneous` / `field_homogeneous`.

Normalisation obtenue:

| grandeur | valeur |
|---|---:|
| `n_cells` | 560 |
| `n_timesteps` | 24 |
| `n_ref_active` | 31 |
| `Q_ref_steady` | `0.0181265937156 m3/s` |
| `Qbar_ref` | `0.0187096909688 m3/s` |
| `L_ref` | `1425.57983523 m` |

Le score identite reste nul a l'arrondi numerique pres:

```text
J = 1.60834512037e-14
C_reseau_phys = 0.0
C_debit_phys  = 3.21669024074e-14
```

Le candidat perturbe deja disponible `mK = 1.25, Sy = 0.08` devient plus
eloigne sur le terme reseau, ce qui est attendu puisque la reference a un
support actif plus etendu:

```text
J = 3.32642895552
C_reseau_phys = 5.68531159694
C_debit_phys  = 0.967546314096
n_ref_active  = 31
n_sim_active  = 15
```

La page HTML B0 utilise maintenant automatiquement cette reference `mK=0.65`
quand le dossier existe, avec repli vers l'ancien package `mK=1.0` sinon.

Point important: le lancement transitoire `mK=0.65` a affiche une convergence
failure pendant l'initialisation steady interne, puis le run transitoire MF6
principal a termine normalement sur les 24 periodes. Pour une grille reelle
plus large, il faudra persister ce diagnostic dans le tableau des runs, car il
peut signaler une fragilite d'initialisation meme quand le run final est
exploitable.
