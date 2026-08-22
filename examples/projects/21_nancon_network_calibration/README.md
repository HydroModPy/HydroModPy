# Nançon — calibration par le réseau hydrographique, puis par le débit

Bassin du Nançon à Fougères (station J001401001, 64,7 km², Ille-et-Vilaine),
calibré en deux étages selon la méthode d'Abherve et al. (HESS 2023, WRR 2025) :

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

## Ce que le critère mesure

`D_so` est la distance moyenne, mesurée le long des chemins de descente du MNT,
du réseau de suintement **simulé** vers le linéaire **cartographié**. `D_os` est
la distance inverse. La calibration cherche le **zéro** de `J = D_so - D_os`,
pas le minimum d'une erreur : les deux ne sont pas au même endroit.

Un `K` trop fort assèche les versants, le réseau simulé se rétracte dans les
talwegs, `D_os` grandit et `J` devient négatif. Un `K` trop faible fait suinter
les versants, `D_so` grandit et `J` devient positif. Entre les deux il existe une
valeur où les deux réseaux ont la même extension, et c'est elle qu'on cherche.

## Les données, et d'où elles viennent

| Fichier sous `examples/data/` | Contenu | Origine |
|---|---|---|
| `dem/DEM_nancon_50m.tif` | MNT de routage, 283 × 305 mailles | découpé et rééchantillonné depuis `DEM_ille_vilaine_5m.tif`, boîte du bassin + 2 km |
| `hydrography/nancon_stream_network.gpkg` | 945 tronçons, 181,7 km | BD TOPO régionale, filtrée sur `NATURE = "Écoulement naturel"`, sans tracés fictifs ni segments enterrés |
| `recharge/recharge_custom_NANCON_REA_19900101_20201231_D.csv` | recharge journalière, 242 mm/an | réanalyse REA, moyenne surfacique sur les 6 mailles SIM2 du bassin |
| `runoff/runoff_custom_NANCON_REA_19900101_20201231_D.csv` | ruissellement journalier, 80 mm/an | même source |
| `hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv` | débit observé journalier, 0 lacune | station J001401001 |

**Le bilan hydrologique boucle à 3 %.** Le forçage donne 322 mm/an
(242 de recharge, 80 de ruissellement) contre 312 mm/an de lame écoulée observée
sur 1990-2020. C'est la vérification indépendante que la moyenne surfacique sur
les mailles météo et leur pondération sont bonnes.

La moyenne est **pondérée par la surface** que chaque maille météo apporte au
bassin : la maille 2139 en couvre 83 %, les cinq autres se partagent le reste.
Prendre la seule maille où tombe l'exutoire serait une approximation gratuite.

## Les trois conditions de validité

Elles ne sont pas des options de confort. Le TOML de base les pose, et les
commentaires y disent pourquoi.

**Le linéaire doit suivre les talwegs du MNT.** Le critère mesure des longueurs
le long des chemins de descente ; si le tracé ne les suit pas, le nombre produit
mesure un désaccord entre deux jeux de données. `[geographic.enforce_streams]`
entaille le réseau dans la surface de routage, et chaque run publie
`alpha_obs_closure`. **Sur ce bassin : 0,994.** Sous 0,90 le run avertit.

**La conductance de drain doit rester proportionnelle à la conductivité.**
`[flow.bc.cauchy.drainage] value = 0.0` sélectionne le repli `C = K·A/e`. C'est
cette proportionnalité qui fait du rapport `K/R` la quantité calibrée. Le runner
refuse une calibration de réseau si la valeur n'est pas nulle.

**La recharge doit être gelée pendant le premier étage.** Le critère à un pour
cent porte sur le rapport ; il ne vaut un pour cent sur la conductivité que si
`R` ne bouge pas. Chaque essai publie `R_mean_m_s`, et un déplacement entre deux
constructions lève un avertissement nommant les deux valeurs.

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

## Lire les résultats

Chaque essai écrit une trentaine de diagnostics dans `trials.jsonl` et dans la
table d'itérations. Les premiers à regarder :

- `J_signed` : le résidu signé. Son signe dit de quel côté de la balance l'essai
  se trouve, et c'est lui que la recherche encadre. S'il ne change jamais de
  signe sur le balayage, la recherche s'arrête et le dit, au lieu de rendre la
  meilleure des deux bornes.
- `roptim` et `roptim_valid` : l'indicateur de validité de l'équation 4. Il
  **qualifie** le résultat, il ne le retient jamais. Et il mesure un accord, pas
  une justesse : ne pas le lire comme une note de qualité du modèle.
- `n_valid`, `n_excess`, `n_missing` : les trois classes. Le critère équilibre
  les deux dernières l'une contre l'autre, ce que dessine la carte de confusion.
- `D_so_median`, `D_so_p90`, `D_so_top5_share` : la forme de la queue. La médiane
  est souvent nulle et quelques longues branches portent l'essentiel, donc la
  moyenne n'est pas un écart typique.

## Les figures

`render_figures.py` produit les figures de la méthode depuis la session :

```console
$ python examples/projects/21_nancon_network_calibration/render_figures.py
```

Le croisement `D_so` / `D_os`, la trajectoire de la dichotomie, le profil de coût
et la carte deux étages se lisent depuis le run. La carte de confusion, la
superposition des réseaux et la carte des distances reçoivent leurs masques en
argument : le critère les construit pendant la calibration et rien ne les
persiste.

## État : le premier étage ne va pas encore au bout

**Ce qui marche, mesuré sur ce bassin :** la délimitation (64,68 km² contre 67 km²
annoncés par la fiche de station), le burning du réseau avec
`alpha_obs_closure = 0,994`, le bilan hydrologique à +3 %, et un run permanent
MODFLOW-NWT qui converge en 9 s.

**Ce qui bloque :** le critère construit son graphe de descente sur le toit du
maillage, qui n'est **jamais conditionné** — c'est délibéré, conditionner le toit
ferait descendre toutes les cotes de drain. Sur ce maillage de 60 395 mailles,
ce toit brut porte **689 cuvettes**, qui le fragmentent en centaines de petits
bassins : les six plus gros ne couvrent que 5,8 % du maillage.

Le critère définit ensuite le bassin comme les mailles dont la descente atteint
un exutoire, et cet exutoire est choisi comme le maximum d'accumulation. Sur une
surface fragmentée, ce maximum tombe dans une dépression interne, ici à 141,5 m
alors que le point bas du maillage est à 95,9 m. Le bassin obtenu fait **2,3 %**
du maillage, et **aucune** maille du linéaire cartographié n'y tombe. Chaque essai
lève alors :

```
the observed stream network holds no cell inside the catchment
```

et la dichotomie refuse proprement, en code de sortie 21 :

```
the bisection adapter has no usable residual: every evaluation failed
```

**Ce n'est pas un défaut de cet exemple ni de ces données.** C'est le critère qui
suppose que la descente atteint un exutoire sans que rien ne le garantisse.
Trois issues possibles, et le choix est scientifique, pas mécanique :

1. router les cuvettes vers leur exutoire de rive avant de descendre, ce qui est
   le traitement standard des dépressions ;
2. bâtir le graphe sur la surface de routage conditionnée que le pipeline
   géographique produit déjà, au lieu du toit du modèle ;
3. restreindre le graphe au bassin délimité et sceller la station comme exutoire,
   ce qui est ce que la section 4.4 de la spécification semble supposer quand elle
   mesure la fraction non atteignante « sur le bassin topographique ».

La troisième est la plus proche de l'intention du papier. Aucune n'est tranchée.

## Ce que cet exemple ne dit pas

La méthode **sur-estime `K/R`**, d'autant plus que la carte du réseau est moins
dense que le réseau réel. `roptim` s'améliore quand ce biais empire. Le second
étage identifie `Sy/T` et non `Sy`, donc il absorbe invisiblement un premier
étage faux. Publier `T/R` avant `K`, et lire la section « biais connus » de
`docs/source/theory/streams_and_seepage/downslope-distance-calibration.rst`
avant de réutiliser l'un des trois nombres.
