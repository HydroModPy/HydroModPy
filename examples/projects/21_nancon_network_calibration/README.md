# Nançon, calibration par le réseau hydrographique puis par le débit

Bassin du Nançon à Fougères (station J001401001, 64,68 km² délimités,
Ille-et-Vilaine), calibré en deux étages selon la méthode d'Abherve et al.
(HESS 2023, WRR 2025) :

1. **`K/R` sur l'extension du réseau**, en régime permanent, par recherche du
   zéro de l'écart signé entre deux distances. **Aucune donnée de débit n'entre
   dans cet étage.**
2. **`Sy` sur l'hydrogramme observé**, en transitoire, `K` étant gelé à la
   valeur que l'étage 1 a trouvée.

## Lancer

```console
$ hmp calibrate examples/projects/21_nancon_network_calibration/calibration_two_stage.toml
$ hmp calibrate .../calibration_two_stage.toml --list-phases
$ hmp calibrate .../calibration_two_stage.toml --phase steady_k_over_r
```

Le second étage ne peut pas être lancé seul : il dépend des valeurs que le
premier gèle, et le runner le refuse plutôt que de le calibrer contre des
paramètres non gelés.

Deux variantes ne font tourner que le premier étage, celui qui teste le
critère, sur le même bassin et le même linéaire :

```console
$ hmp calibrate .../calibration_network_mf6.toml      # MODFLOW 6, drain seul
$ hmp calibrate .../calibration_network_mf6_sfr.toml  # MODFLOW 6, SFR + drain
```

## Ce que le critère mesure

`D_so` est la distance moyenne, mesurée le long des chemins de descente du
maillage, du réseau de suintement **simulé** vers le linéaire **cartographié**.
`D_os` est la distance inverse. La calibration cherche le **zéro** de
`J = D_so - D_os`, pas le minimum d'une erreur : les deux ne sont pas au même
endroit.

Un `K` trop fort assèche les versants, le réseau simulé se rétracte dans les
talwegs, `D_os` grandit et `J` devient négatif. Un `K` trop faible fait suinter
les versants, `D_so` grandit et `J` devient positif. Entre les deux il existe une
valeur où les deux réseaux ont la même extension, et c'est elle qu'on cherche.

## Les données, et d'où elles viennent

| Fichier sous `examples/data/` | Contenu | Origine |
|---|---|---|
| `dem/DEM_nancon_50m.tif` | MNT de routage, 283 × 305 mailles à 50 m | découpé et rééchantillonné depuis `DEM_ille_vilaine_5m.tif` |
| `hydrography/nancon_stream_network.gpkg` | 945 tronçons, 181,7 km, dont 45,6 km dans le bassin | BD TOPO régionale, `NATURE = "Écoulement naturel"`, `FICTIF = "Non"`, `POS_SOL = 0`, `PERSISTANC = "Permanent"` |
| `recharge/recharge_custom_NANCON_REA_19900101_20201231_D.csv` | recharge journalière, 242 mm/an | réanalyse REA, moyenne surfacique sur les mailles SIM2 du bassin |
| `runoff/runoff_custom_NANCON_REA_19900101_20201231_D.csv` | ruissellement journalier, 80 mm/an | même source |
| `hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv` | débit observé journalier, 14 604 jours sans lacune | station J001401001 |

**Le bilan hydrologique boucle à 3 %.** Le forçage donne 322 mm/an
(242 de recharge, 80 de ruissellement) contre 312 mm/an de lame écoulée observée
sur 1990-2020. C'est la vérification indépendante que la moyenne surfacique sur
les mailles météo et leur pondération sont bonnes. La moyenne est **pondérée par
la surface** que chaque maille météo apporte au bassin ; prendre la seule maille
où tombe l'exutoire serait une approximation gratuite.

**Le linéaire retenu est le réseau permanent seul**, et sa densité de drainage
dans le bassin vaut 0,70 km/km². C'est la carte, pas le réseau réel, et cet
écart est la première cause du biais décrit en fin de page.

## Les trois conditions de validité

Elles ne sont pas des options de confort. Le TOML de base les pose, et les
commentaires y disent pourquoi.

**Le linéaire doit suivre les talwegs de la surface de routage.**
`[geographic.enforce_streams]` entaille le réseau dans cette surface avant la
délimitation, et l'étape géographique publie le rapport `alpha` dans
`stream_dem_agreement.json`. Avec le burning de 30 m il vaut 0,994 sur ce
bassin ; il valait 0,685 tant que la table du pointeur D8 était celle d'ESRI et
non celle que whitebox écrit, défaut corrigé en chemin.

**Cette mesure n'est pas celle que le critère publie**, et les deux ne peuvent
pas coïncider par construction. Le burning ne touche que la surface de routage :
le toit du maillage reste sur le MNT brut, sans quoi le modèle suinterait le
long du linéaire par construction. Or le critère mesure ses distances sur ce
toit. Le `alpha_obs_closure` publié à chaque essai vaut donc **0,306** ici, sous
le seuil de 0,90, et chaque essai émet l'avertissement correspondant. Le
résultat de l'étage 1 est à lire avec cette réserve : sur ce bassin, une bonne
part du chemin de descente issu des mailles cartographiées quitte le linéaire
dès les premiers pas.

**La conductance de drain doit rester proportionnelle à la conductivité.**
`[flow.bc.cauchy.drainage] value = 0.0` sélectionne le repli `C = K·A/e`. C'est
cette proportionnalité qui fait du rapport `K/R` la quantité calibrée. Le
préflight refuse une calibration de réseau si la valeur est strictement
positive.

**La recharge doit être gelée pendant le premier étage.** Le critère à un pour
cent porte sur le rapport ; il ne vaut un pour cent sur la conductivité que si
`R` ne bouge pas. Chaque essai publie `R_mean_m_s`, et un déplacement entre deux
constructions lève un avertissement nommant les deux valeurs. Sur les 15 essais
de l'étage 1, `R_mean_m_s` vaut 1,392e-8 m/s sans varier d'un chiffre.

## Ce que chaque étage déclare, et pourquoi

`method = "bisection"` au premier étage : une recherche de racine, pas un
minimiseur. Elle s'arrête sur la **largeur du crochet**, jamais sur la taille du
résidu, parce que l'écart signé est une fonction en escalier qui saute par-dessus
zéro et ne devient jamais petit. Elle refuse un paramètre qui n'est pas en
`transform = "log"` : sa tolérance et son expansion d'une décade sont des énoncés
sur la variable logarithmique.

`sweep_points = 7` : un balayage logarithmique grossier avant la dichotomie. Il
vérifie la monotonie au lieu de la supposer, il voit tous les croisements, et les
courbes de la figure de croisement sortent des mêmes résolutions.

`[calibration.phases.overrides]` : le premier étage est permanent, le second
transitoire au pas mensuel. Le régime d'écoulement est une propriété du modèle et
non de la recherche, donc c'est la phase qui le dit.

`variable` et `objective` sur le second étage seulement : les déclarer choisit la
route mono-métrique, et la phase n'hérite alors ni des sorties ni des blocs du
premier étage. C'est ce qui l'empêche d'être scorée sur le critère de réseau.

`nse_log` plutôt que `nse` : l'efficacité de Nash-Sutcliffe sur les logarithmes
pondère les récessions, qui sont la partie de l'hydrogramme que l'emmagasinement
commande. Ne pas écrire `transform = "log"` pour cela : c'est le logarithme d'un
coût déjà calculé, une opération sans rapport.

`method = "grid"` au second étage donne **5 points**, pas `max_iter`. La densité
de la grille est `points_per_dim`, qui vaut 5 par défaut ; `max_iter` n'est
qu'un plafond.

## Ce que l'exemple produit

### Étage 1, `K` par dichotomie sur le zéro de l'écart signé

MODFLOW-NWT, maillage du bassin délimité, 60 395 mailles à 50 m, `L_ref = 50 m`,
1 119 mailles cartographiées dans le bassin. 15 essais en 6 min 23.

Le balayage de 7 points couvre quatre décades et change de signe **une seule
fois**, entre 2,15e-4 et 1,0e-3. Voici ses sept points, puis les deux essais de
la dichotomie qui encadrent la racine :

| `K` (m/s) | `D_so` (m) | `D_os` (m) | `J = D_so - D_os` | |
|---|---|---|---|---|
| 1,0e-7 | 1167 | 0 | +1167 | balayage |
| 4,64e-7 | 1182 | 0,22 | +1182 | balayage |
| 2,15e-6 | 1160 | 3,1 | +1157 | balayage |
| 1,0e-5 | 692 | 8,6 | +683 | balayage |
| 4,64e-5 | 407 | 27 | +380 | balayage |
| 2,15e-4 | 228 | 233 | **-4,4** | balayage |
| 1,0e-3 | 278 | 608 | -330 | balayage |
| 2,078e-4 | 234 | 229 | +4,2 | dichotomie |
| **2,103e-4** | **229** | **229** | **-0,89** | **racine** |

**La racine est `K = 2,103e-4 m/s`**, pour `R = 1,392e-8 m/s`. Le critère y
équilibre bien ses deux classes d'erreur : **602 mailles valides, 550 en excès,
517 manquantes**. La médiane des deux distances est nulle et leurs p90 valent
700 et 900 m ; quelques longues branches portent l'essentiel, donc la moyenne
n'est pas un écart typique. Le maillage étant uniforme, les pondérations `cell`
et `area` donnent le même nombre au chiffre près.

`roptim` vaut **4,58**, au-delà de sa borne de 2. Le résultat est donc
**qualifié, pas retenu** : `on_roptim_violation` vaut `warn` par défaut, la
valeur revient avec son avertissement.

La configuration de base porte `K = 6,4e-5 m/s` comme valeur a priori. La
méthode **sur-estime d'un facteur 3,3**, ce qui tombe dans la fourchette 2,7 à
7,5 documentée pour une carte de réseau moins dense que le réseau réel.

### Étage 2, `Sy` sur `nse_log`, `K` gelé

Transitoire au pas mensuel sur 2000-2009, scoré sur 2001-2009 : la première
année sert de mise en régime, 108 des 120 pas sont scorés. 5 essais en 30 min.

| `Sy` | `NSElog` |
|---|---|
| **0,005** | **-0,001** |
| 0,0139 | -0,174 |
| 0,0387 | -0,600 |
| 0,108 | -1,092 |
| 0,300 | -1,467 |

**Le meilleur point est collé à la borne inférieure.** L'hydrogramme dit
pourquoi : la dynamique est bonne, les récessions et le calage des étiages
suivent l'observé, mais les pics simulés sont au-dessus. C'est un biais de
volume, que l'emmagasinement ne peut pas corriger puisqu'il ne fait que donner
sa forme à la récession. C'est le mécanisme que la page théorie annonce : le
second étage identifie `Sy/T` et non `Sy`, donc il absorbe un premier étage
biaisé. Ici il ne l'absorbe pas, il sature, ce qui est la façon visible de le
dire.

### D'un solveur et d'un package à l'autre

Trois montages, même bassin, même linéaire, même forçage :

| | Solveur | Réseau | `K` racine (m/s) | `roptim` | valides / excès / manquantes |
|---|---|---|---|---|---|
| A | MODFLOW-NWT | DRN | 2,103e-4 | 4,58 | 602 / 550 / 517 |
| B | MODFLOW 6 | DRN | 1,866e-4 | 2,21 | 291 / 196 / 212 |
| C | MODFLOW 6 | SFR + DRN | non recalculée depuis les correctifs | | |

**A contre B isole le solveur**, la grille et la discrétisation : onze pour cent
d'écart sur un paramètre cherché sur quatre décades. Les comptes absolus ne se
comparent pas, la grille structurée de MF6 étant plus grossière (`L_ref` de
107 m contre 50 m), et c'est aussi pourquoi `roptim` y est meilleur sans que
rien du modèle ne se soit amélioré.

**B contre C isole le package**, et C est le cas qui met à l'épreuve l'union du
`release_flux`. Dès que les biefs principaux sont modélisés au lieu d'être
drainés, l'essentiel du suintement sort par le package de cours d'eau : sur ce
bassin l'aquifère envoie **1,33 de ses 2,10 m³/s** par SFR contre 0,80 restés
sur le drain. Une union qui ne lirait que le drain rendrait 63 % de cette eau
en terre sèche, exactement là où ce package draine, c'est-à-dire exactement là
où le critère vise. Les deux extracteurs lisent désormais l'exigence sur le
fichier de budget et refusent un enregistrement de relâchement qu'aucun package
déclaré ne couvre.

Le symptôme, quand ce garde-fou n'était pas là, était un résidu qui cesse de
répondre au paramètre : la session de ce dossier fermait sur `K = 5,6e-1 m/s`,
trois décades au-dessus des bornes déclarées, avec un `roptim` de 1,50
confortablement dans la sienne. Un réseau simulé qui tient ses mailles par
construction ne se rétracte jamais, et le critère s'équilibre alors contre un
squelette fixe.

## Lire les résultats

Chaque essai écrit 38 diagnostics dans `trials.jsonl` et dans la table
d'itérations, tous préfixés du nom de la sortie (`seepage_network.J_signed`,
etc.). Les premiers à regarder :

- `J_signed` : le résidu signé. Son signe dit de quel côté de la balance l'essai
  se trouve, et c'est lui que la recherche encadre. S'il ne change jamais de
  signe sur le balayage, la recherche élargit, puis s'arrête et le dit, au lieu
  de rendre la meilleure des deux bornes.
- `roptim` et `roptim_valid` : l'indicateur de validité de l'équation 4. Il
  **qualifie** le résultat, il ne le retient jamais. Et il mesure un accord, pas
  une justesse : ne pas le lire comme une note de qualité du modèle, ni comparer
  deux valeurs mesurées sur des maillages différents.
- `alpha_obs_closure` : ici 0,306, et c'est la réserve principale sur ce cas.
- `n_valid`, `n_excess`, `n_missing` : les trois classes. Le critère équilibre
  les deux dernières l'une contre l'autre, ce que dessine la carte de confusion.
- `D_so_median`, `D_so_p90`, `D_so_top5_share` : la forme de la queue.
- `R_mean_m_s` : le dénominateur du rapport calibré, à relire d'un essai à
  l'autre avant de lire la valeur calibrée comme un `K`.

## Les figures

```console
$ python examples/projects/21_nancon_network_calibration/render_figures.py
```

Le script écrit dans `figures/calibration/` : le croisement des deux distances,
la trace de la dichotomie, le profil de coût, la superposition du réseau simulé
sur le linéaire cartographié, la carte de confusion à trois classes, la carte
des distances, et l'hydrogramme observé contre simulé sur axe logarithmique.

Les figures de session se lisent directement depuis le run. Les trois cartes de
réseau, non : **le script reconstruit les supports par maille du critère**,
parce que le critère les construit pendant un essai et que rien ne les persiste.
Il rejoue la même chaîne depuis le run promu (seuil de suintement spécifique,
fermeture aval, intersection avec le bassin délimité, descente sur une surface
dont les cuvettes sont résolues sur le graphe du maillage). La reconstruction
retombe **exactement** sur les comptes de l'essai, 602 / 550 / 517, ce qui est
la vérification que c'est bien le même objet qui est dessiné.

`abherve_two_stage_card` est une grille de panneaux : elle se dessine par
`plot()` et non par `render(sim, ax)`, donc le fichier que le script écrit
aujourd'hui pour elle est le carton de repli et non la carte.

## Ce que cet exemple ne dit pas

La méthode **sur-estime `K/R`**, d'autant plus que la carte du réseau est moins
dense que le réseau réel, et ce bassin en donne un cas net : réseau permanent
seul, 0,70 km/km², facteur 3,3 sur la conductivité a priori. `roptim` s'améliore
quand ce biais empire, et il s'améliore aussi quand la maille grossit. Le second
étage identifie `Sy/T` et non `Sy`, donc il absorbe un premier étage faux ; ici
il sature contre sa borne au lieu d'absorber.

Publier `T/R` avant `K`, et lire la section « biais connus » de
`docs/source/theory/streams_and_seepage/downslope-distance-calibration.rst`
avant de réutiliser l'un de ces nombres.
