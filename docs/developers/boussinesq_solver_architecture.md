# Solveur Boussinesq 2D pour HydroModPy

## 1. Objectif

Definir un solveur d'ecoulement libre 2D, independant de MODFLOW, qui :

- reutilise les objets runtime deja exposes par `Flow`,
- s'appuie sur le maillage triangulaire deja produit par HydroModPy,
- reste compatible avec les memes conditions initiales, conditions aux limites et termes puits/sources que le backend MODFLOW,
- gere explicitement la contrainte de surface et la production de `saturation-excess`.

L'objectif n'est donc pas de redefinir le processus `Flow`, mais d'ajouter un nouveau solveur `boussinesq` compatible avec le contrat `Flow` deja en place dans le depot, avec des changements limites au strict necessaire.

## 2. Recentrage par rapport a l'existant HydroModPy

Le point cle du code actuel est le suivant :

- le processus `Flow` est deja solver-agnostique ;
- les conditions initiales portent sur une charge `h` en metres ;
- les conditions aux limites Dirichlet/Cauchy/Robin sont deja normalisees ;
- les puits et la recharge sont deja portes par `flow.sinks_sources` ;
- le maillage est deja disponible dans plusieurs representations
  (`HydroMesh`, `SolverMesh`, `CatchmentMeshBundle`), mais elles n'ont pas
  vocation a devenir toutes des dependances du coeur solveur.

Le contrat process reste naturellement exprime en charge `h`, car :

- `flow.ic.h` initialise deja une charge,
- les BC Dirichlet sont exprimees en metres,
- les forcages existants sont deja alignes sur cette logique.

En revanche, pour le schema numerique implemente, on peut tout a fait retenir
un stockage surfacique `S` comme inconnue interne, avec reconstruction de la
charge via :

```math
H = z_b + \frac{S}{f}
```

Autrement dit :

- l'interface metier du processus `Flow` reste en `h`,
- le solveur `boussinesq` peut assembler en `S`,
- l'adapter du solveur assure la conversion `h <-> S` au besoin.

Positionnement d'implementation vise :

- pas de dependance directe du coeur `boussinesq` a `modflow_common` ;
- pas d'obligation d'utiliser `HydroMesh` comme maillage d'entree ;
- reutilisation prioritaire du maillage runtime deja construit par la chaine ;
- `HydroMesh` reserve en pratique aux exports et a la visualisation ;
- confinement de la logique PETSc dans une couche runtime dediee, sans fuite
  dans le contrat `Flow`.

## 3. Variables retenues

| Symbole | Sens dans le solveur Boussinesq |
| --- | --- |
| `h(x,t)` | charge hydraulique / cote piezometrique |
| `S(x,t)` | stockage numerique interne par unite de surface |
| `S_c(x)` | stockage maximal correspondant a la saturation de surface |
| `H(x,t)` | charge reconstruite pour le calcul des flux, `H = z_b + S/f` |
| `z_s(x)` | altitude de surface (`surface_topo`) |
| `z_b(x)` | altitude du substratum (`domain.substratum`) |
| `b(x,t)` | epaisseur saturee, `b = max(h - z_b, 0)` |
| `C(x,t)` | coefficient de stockage plan, par ex. `C = Sy + Ss b` |
| `K(x)` | conductivite hydraulique horizontale |
| `f(x)` | porosite / coefficient de conversion entre `S` et hauteur saturee |
| `Sy(x)` | emmagasinement libre effectif |
| `Ss(x)` | stockage specifique / contribution elastique |
| `N(x,t)` | recharge diffuse vers la nappe |
| `Q_w(x,t)` | puits/sources localises |
| `q_bc(x,t)` | flux impose par BC de type Cauchy/Robin |
| `q_drn(x,t)` | terme de drainage head-dependent |
| `q_evt(x,t)` | terme de soutirage surfacique de type ET |
| `q_ex(x,t)` | debit surfacique de saturation-excess |

Remarque importante :

- dans le schema numerique detaille, l'inconnue assemblee est `S` ;
- `H` ou `h` sont alors des quantites reconstruites a partir de `S` ;
- `Sy` reste le parametre cle du modele transient libre ;
- `Ss` doit rester disponible si l'on veut que le solveur couvre naturellement les fonctions de stockage transitoire actuellement portees par MODFLOW ;
- en pratique, le stockage plan peut etre ecrit `C(h) = Sy + Ss b(h)` ;
- si le bundle de maillage ne fournit qu'un `storage_coefficient`, il doit etre interprete comme un proxy de la storativite totale 2D.

## 4. Modele continu retenu

### 4.1 Equation de base

On retient la forme Dupuit-Boussinesq suivante :

```math
C(h) \, \partial_t h - \nabla \cdot \left( K \, b \, \nabla h \right) + q_{ex}
= N + q_{w} + q_{bc}
```

avec :

```math
b = \max(h - z_b, 0)
```

et par exemple :

```math
C(h) = Sy + Ss \, b
```

Cette ecriture est la plus naturelle pour HydroModPy car :

- l'inconnue est la meme que dans les IC et BC existantes ;
- le passage aux BC Dirichlet et Robin est direct ;
- la quantite `b` se deduit localement de `h` et du substratum deja construit par `Domain`.

### 4.2 Contrainte de surface et saturation-excess

Pour un premier schema, il est raisonnable de partir directement de la loi
regularisee proposee dans la note initiale, ecrite de maniere equivalente en
`h` ou en `S/S_c`.

On introduit un taux de saturation local :

```math
\theta(h) =
\mathrm{clip}\left(
\frac{h-z_b}{z_s-z_b},
0,
1
\right)
```

et un operateur d'exfiltration :

```math
q_{ex}
=
G_r\left(\theta(h)\right)
R\left(
- \nabla \cdot \left(T(h)\nabla h\right)
+ q_{in}
\right)
```

avec :

```math
R(u) = \max(u,0)
```

et :

```math
G_r(u) = \exp(-(1-u)/r)
```

ou `q_in` agrege les termes entrants locaux du bilan.

Interpretation :

- tant que la saturation locale reste loin de 1, `G_r` garde `q_ex` faible ;
- a l'approche de la surface, `G_r` active progressivement l'exfiltration ;
- seule la partie positive du desequilibre local produit du `saturation-excess`.

Cette approche a un avantage pratique pour V1 :

- elle colle directement a la methode que tu avais proposee ;
- elle s'insere dans une boucle non lineaire Newton ou Picard ;
- elle evite d'introduire tout de suite une logique d'ensemble actif ou de projection.

La contrainte forte `h <= z_s` peut rester une variante plus robuste a introduire
ensuite si l'on veut un mode "projection/active-set".

### 4.3 Distinction avec la BC `drainage`

`drainage` et `saturation-excess` ne doivent pas etre confondus :

- `drainage` est une BC ou un terme d'echange de type conductance ;
- `saturation-excess` est une contrainte de surface du solveur libre.

Les deux peuvent coexister :

- `drainage` decrit un echange preferentiel vers un reseau ou une interface imposee ;
- `saturation-excess` decrit l'incapacite du milieu a stocker davantage sous la surface.

### 4.4 Forme generale compatible avec les fonctions de type MODFLOW

Pour que le nouveau solveur puisse reprendre naturellement tout ce que fait
MODFLOW aujourd'hui, hors discretisation verticale, le bon point de vue n'est
pas une equation fermee avec seulement `N`, `q_w` et `q_bc`, mais un bilan
general a operateurs :

```math
C(h)\partial_t h
- \nabla \cdot \left(T(h)\nabla h\right)
+ q_{ex}(h)
+ \sum_{\alpha \in \mathcal{S}^{-}} q_{\alpha}(h,t)
=
\sum_{\beta \in \mathcal{S}^{+}} q_{\beta}(h,t)
```

avec :

```math
T(h) = K \, b(h)
```

Ou :

- `\mathcal{S}^{+}` regroupe les apports volumiques ou surfaciques ;
- `\mathcal{S}^{-}` regroupe les soutirages et echanges sortants ;
- les conditions de Dirichlet restent imposees sur des sous-ensembles de bord ;
- les echanges head-dependent sont portes par des operateurs du type Robin.

Dans ce cadre :

- la recharge diffuse est un operateur source ;
- les puits sont des operateurs ponctuels/cellulaires ;
- `ocean`, `stream` et les cotes lateraux sont des operateurs de bord ;
- `drainage` est un operateur d'echange unilateral ;
- `negative_to_evt` devient un operateur de sink surfacique ;
- `saturation-excess` peut etre porte en V1 par une loi regularisee du desequilibre local.

Autrement dit, le schema theorique doit etre concu comme un coeur
Dupuit-Boussinesq 2D auquel on greffe une bibliotheque d'operateurs de bilan,
et non comme une equation specialisee seulement pour `recharge + BC`.

## 5. Maillage cible

### 5.1 Support numerique recommande

Au vu de ce que tu souhaites, le solveur doit recevoir directement le maillage
runtime deja construit par la chaine HydroModPy, sans ecriture/lecture
intermediaire dans un bundle sur disque.

L'idee doit donc rester proche du workflow MODFLOW actuel :

- le pipeline de preparation construit le maillage en memoire ;
- le solveur `boussinesq` consomme directement cet objet ou une vue legere de cet objet ;
- une structure export type bundle peut exister pour debug ou echange, mais pas comme contrat principal du solveur.

Le support en memoire doit fournir les ingredients dont un schema volumes finis a besoin :

- geometrie des cellules,
- adjacence par aretes,
- longueurs d'aretes,
- topographie aux noeuds et par cellule,
- proprietes hydrauliques par cellule,
- flags de bord et d'interfaces.

### 5.2 Inconnues discretes

Le solveur V1 est centre cellules :

- 1 inconnue `S_i` par cellule 2D,
- 1 charge reconstruite `H_i = z_{b,i} + S_i/f_i` par cellule,
- 1 terme `Q_ex,i` par cellule lorsque la regularisation de surface est active.

Ce choix colle directement a :

- des aires de cellule deja calculees,
- une connectivite cellule-arete / cellule-cellule deja disponible,
- une topographie de surface et un substratum accessibles sur le maillage,
- des proprietes hydrauliques accessibles par cellule.

### 5.3 Pourquoi ne pas partir en EF/FEniCSx en premiere implementation

Le depot existe deja avec :

- des contrats runtime process bien definis,
- un maillage triangulaire exporte avec une table d'aretes,
- des parametres et forcages portes cellule par cellule,
- une logique solver actuelle largement construite autour de quantites integrees par cellule.

Le backend le plus direct n'est donc pas un backend EF generique, mais un backend volumes finis sur graphe de cellules.

FEniCSx peut rester une perspective ulterieure, mais ne doit pas piloter la conception V1.

## 6. Schema numerique retenu

Le schema retenu en V1 n'est pas un schema mixte strict.

Il s'agit d'un schema primal en volumes finis centres cellules, avec :

- `S_T` comme inconnue principale par cellule,
- des flux d'aretes reconstruits a partir de `S`,
- la fonction de regularisation pour le `saturation-excess`.

Une variante mixte ou hybride reste possible plus tard en introduisant des
flux `q_e` comme inconnues supplementaires.

### 6.1 Variables discretes

Pour un maillage triangulaire :

- `T` : ensemble des cellules,
- `e` : ensemble des aretes.

Inconnues principales :

- `S_T^n` : stockage dans la cellule `T` au temps `t^n`.

Optionnel selon la methode :

- `q_e` : flux normal a l'arete `e`.

Quantites reconstruites :

```math
H_T = z_{b,T} + \frac{S_T}{f_T}
```

et :

```math
S_{c,T} = f_T (z_{s,T} - z_{b,T})
```

### 6.2 Bilan discret par cellule

Pour chaque cellule `T` :

```math
|T|\frac{S_T^{n+1} - S_T^n}{\Delta t}
=
-\sum_{e \subset \partial T} F_{T,e}^{n+1}
+ |T|N_T^{n+1}
- |T|q_{\mathrm{ex},T}^{n+1}
```

Cette ecriture est la forme minimale.

Dans l'implementation complete, les autres operateurs du solveur
(`wells`, `drainage`, `robin`, `evt`) se rajoutent au meme bilan sans
changer sa structure generale.

### 6.3 Flux aux aretes

Pour chaque arete `e` entre cellules `T_L` et `T_R` :

Gradient approche :

```math
\nabla H_e \approx \frac{H_{T_R} - H_{T_L}}{d_{LR}} \mathbf{n}_{LR}
```

avec :

```math
H_T = z_{b,T} + \frac{S_T}{f_T}
```

Flux :

```math
F_e = -K_e \cdot \frac{S_e}{f_e} \cdot (\nabla H_e \cdot \mathbf{n}_e) \cdot |e|
```

ou :

- `S_e = (S_{T_L} + S_{T_R})/2`,
- `K_e` est une moyenne harmonique ou arithmetique.

### 6.4 Divergence par cellule

```math
(\nabla \cdot \mathbf{q})_T
=
\frac{1}{|T|}
\sum_{e \subset \partial T} F_{T,e}
```

### 6.5 Terme saturation-excess

Etape 1 : bilan entrant

```math
B_T = -(\nabla \cdot \mathbf{q})_T + N_T
```

Etape 2 : fonction rampe

```math
R(B_T) = \max(B_T, 0)
```

Etape 3 : regularisation

```math
G_r(\sigma_T) = \exp\left(-\frac{1 - \sigma_T}{r}\right)
\quad \text{avec} \quad
\sigma_T = \frac{S_T}{S_{c,T}}
```

Etape 4 : flux exfiltre

```math
q_{\mathrm{ex},T}
=
G_r(\sigma_T)\,R(B_T)
```

### 6.6 Schema implicite Euler

On cherche `S^{n+1}` tel que :

```math
R_T(S^{n+1}) = 0
```

avec :

```math
R_T =
\frac{|T|}{\Delta t}(S_T^{n+1} - S_T^n)
+
\sum_e F_{T,e}(S^{n+1})
-
|T|N_T^{n+1}
+
|T|q_{\mathrm{ex},T}(S^{n+1})
```

### 6.7 Algorithme global Newton

Initialisation :

```math
S^{(0)} = S^n
```

Boucle Newton pour `k = 0,1,...` :

1. calculer `H_T^{(k)}`,
2. calculer les flux `F_e^{(k)}`,
3. calculer la divergence `(\nabla \cdot q)_T^{(k)}`,
4. calculer `B_T^{(k)}`,
5. calculer `q_{\mathrm{ex},T}^{(k)}`,
6. construire le residu `R^{(k)}`,
7. construire le jacobien `J^{(k)}`,
8. resoudre :

```math
J^{(k)} \delta S = -R^{(k)}
```

9. mise a jour :

```math
S^{(k+1)} = S^{(k)} + \delta S
```

En pratique, une premiere implementation peut utiliser un Newton simplifie ou
un Picard si l'on veut demarrer plus sobrement, mais la structure de reference
du schema reste bien celle-ci.

Pour le backend `boussinesq` HydroModPy, le choix applique en V1 est un
schema implicite pilote par PETSc.

### 6.8 Nature du systeme et integration en temps

Apres discretisation spatiale, deux points de vue sont possibles.

Si les flux d'aretes et le `saturation-excess` sont reconstruits
algebriquement a partir de `S`, le systeme semi-discret s'ecrit :

```math
M \frac{dS}{dt} = F(S,t)
```

Il s'agit alors d'une ODE raide non lineaire.

Si l'on conserve explicitement les flux `Q_e` comme inconnues du schema mixte,
on peut aussi ecrire :

```math
M \frac{dS}{dt} = f(S,Q,t)
```

et :

```math
0 = g(S,Q,t)
```

Ce point de vue conduit a une DAE d'index 1.

Pour le solveur `boussinesq` vise ici, le choix applique en V1 est :

- formulation pratique en ODE raide sur l'inconnue principale `S`,
- reconstruction algebrique des flux `Q_e` et du terme `q_ex`,
- integration en temps par PETSc `TS` en mode pleinement implicite,
- schema de temps de reference : Euler implicite via `TSBEULER`
  ou `TSTHETA` avec `theta = 1`,
- resolution non lineaire a chaque pas par `SNES`,
- resolution lineaire interne par `KSP`.

Ce choix est le plus direct a implementer et le plus robuste pour une V1.

Autrement dit, meme en V1, la boucle de temps n'est pas geree manuellement :

- le solveur assemble une residuale implicite,
- PETSc `TS` porte l'integration en temps,
- `SNES/KSP` portent la resolution a chaque pas.

### 6.9 V2 proposee : formulation mixte DAE index 1

La V2 proposee consiste a assumer pleinement la formulation mixte en gardant
des flux comme inconnues du systeme.

Un choix naturel est de prendre comme inconnues globales :

- `S_T` au centre des cellules,
- `Q_e` sur les aretes,
- eventuellement `q_{ex,T}` comme inconnue auxiliaire explicite.

Le systeme semi-discret prend alors la forme :

```math
M \frac{dS}{dt} = f(S,Q,q_{ex},t)
```

et :

```math
0 = g_1(S,Q,t)
```

```math
0 = g_2(S,q_{ex},t)
```

ou :

- `g_1` porte la loi de flux sur les aretes,
- `g_2` porte la fermeture regularisee du `saturation-excess`.

Cette formulation est une DAE implicite d'index 1.

La V2 recommandee est alors :

- formulation mixte / DAE index 1,
- integration en temps par PETSc `TS` en formulation implicite generale
  `F(t,U,\dot U) = 0`,
- type de probleme PETSc regle comme DAE implicite d'index 1,
- schema de temps recommande : `TSBDF` pour retrouver une logique proche de
  l'article de Marcais et al. (2017),
- variante robuste possible : `TSTHETA`,
- resolution non lineaire par `SNES`,
- preconditionnement et solveurs lineaires PETSc via `KSP/PC`.

Ce point de vue permet :

- de rester au plus pres du schema mixte de l'article,
- de garder explicitement les flux d'interface,
- de preparer plus naturellement des couplages futurs avec des operateurs de
  bord ou de surface plus riches.

### 6.10 Jacobien

Le jacobien contient :

```math
J = \frac{\partial R}{\partial S}
```

Contributions principales :

- terme temporel : `|T| / \Delta t`,
- flux : dependance via `S` et `\nabla S`,
- exfiltration : dependance non lineaire via `G_r` et `R`.

En V2 mixte/DAE, le jacobien devient un jacobien de bloc sur les inconnues
`(S,Q,q_{ex})`.

### 6.11 Bords et operateurs additionnels

Les conditions de bord et termes supplementaires se greffent sur le meme
schema de base :

- Dirichlet : impose `H` ou une valeur equivalente de `S` sur le bord,
- Neumann : flux impose sur les aretes de bord,
- Robin / Cauchy : terme de flux dependant de la charge,
- `wells` : terme source ponctuel dans le bilan cellule,
- `drainage` : terme de sink head-dependent,
- `evt` : sink surfacique optionnel,
- `ocean` / `stream` : application de Dirichlet ou Robin sur sous-domaines de bord.

### 6.12 Structure de donnees recommandee

```python
cells = [T1, T2, ...]
edges = [e1, e2, ...]

S[T]
Sc[T]
zb[T]
f[T]
K[T]

neighbors[e] = (T_left, T_right)
normal[e]
length[e]
```

Pour la V2 mixte :

```python
Q[e]
qex[T]
```

### 6.13 Algebre lineaire et integration PETSc

La bonne abstraction n'est pas "FEniCSx ou non", mais "backend implicite PETSc
pilote par residuale et jacobien".

Recommendation :

- vecteurs et matrices PETSc comme backend cible,
- `TS` pour l'integration en temps,
- `SNES` pour les non-linearites,
- `KSP/PC` pour les resolutions lineaires,
- assemblage creux explicite possible en `AIJ`,
- SciPy possible seulement comme backend de validation local, pas comme cible principale.

## 7. Reutilisation du contrat process existant

### 7.1 Conditions initiales

`flow.ic.h` devient directement l'etat initial :

- `type = top` -> `h_0 = z_s`,
- `type = bottom` -> `h_0 = z_b`,
- `type = custom` -> `h_0 = valeur`.

Le solveur peut ensuite convertir cet etat initial en stockage numerique :

```math
S_0 = f \, \max(h_0 - z_b, 0)
```

Il n'y a donc pas besoin d'un nouveau format d'IC pour le solveur Boussinesq.

### 7.2 Conditions aux limites

Les objets `FlowBoundaryConditionConfig` existants peuvent etre reutilises tels quels.

Mapping propose :

| BC HydroModPy | Usage Boussinesq |
| --- | --- |
| `ocean` | Dirichlet sur un sous-ensemble d'aretes ou cellules de bord |
| `stream` | Dirichlet localisee ou Robin selon le tag spatial retenu |
| `north_side`, `south_side`, `east_side`, `west_side` | Dirichlet sur groupes d'aretes de bord |
| `drainage` | flux de type Cauchy/Robin sur aretes ou cellules cibles |

Le solveur a besoin d'une couche de projection spatiale supplementaire pour passer :

- d'un identifiant logique de BC,
- a une liste d'aretes de bord ou de cellules cibles sur le maillage triangulaire.

### 7.3 Recharge

`flow.sinks_sources.recharge` reste la source canonique.

Le solveur doit accepter les memes formes d'entree que MODFLOW aujourd'hui :

- scalaire uniforme,
- liste par stress period,
- mapping `{kper: value}`,
- source heterogene deja resolue par les binders.

Il doit aussi pouvoir distinguer naturellement :

- la recharge effective vers la nappe,
- la part eventuellement reroutee vers un operateur de type ET lorsque la logique `negative_to_evt` est active.

La recharge devient un terme surfacique cellule :

```math
A_i N_i
```

### 7.4 Puits et sources localises

`flow.sinks_sources.wells` peut etre reutilise sans changement conceptuel :

- chaque puits est projete sur une cellule du maillage,
- son debit `m3/s` alimente le second membre de cette cellule.

Sur maillage triangulaire, il faut simplement remplacer la logique `(lay,row,col)` par :

- soit une resolution geometrique XY -> `cell_id`,
- soit un adressage deja preprojete sur le bundle.

### 7.5 Forcages temporels

Les binders existants doivent rester la source de verite pour resoudre :

- `flow.bc.*.forcing`,
- `flow.sinks_sources.wells.*.forcing`,
- la recharge issue des data managers.

Autrement dit :

- la conversion temps -> valeurs par periode reste en amont du solveur,
- le solveur Boussinesq consomme des valeurs deja alignees sur `simulation.time`,
- comme le font deja les adapters MODFLOW.

## 8. Architecture logicielle recommandee

### 8.1 Positionnement dans le depot

```text
hydromodpy/
  solver/
    boussinesq/
      __init__.py
      boussinesq_config.py
      boussinesq_solver.py
      mesh.py
      operators.py
      assembly.py
      nonlinear.py
      petsc_runtime.py
      boundary_mapping.py
      source_mapping.py
      results.py
      postprocess.py
  simulation/
    adapters/
      flow/
        boussinesq.py
```

Et extension des points d'entree existants :

- `SolverEngine` -> ajouter `boussinesq`,
- `simulation.adapters.registry` -> ajouter `("flow", "boussinesq")`,
- config solveur -> ajouter une section `boussinesq`.

Important :

- l'adapter `simulation.adapters.flow.boussinesq` doit etre un pair des
  adapters MODFLOW existants, pas une surcouche de `modflow_common` ;
- `modflow_common` peut servir de reference de structure pour le cycle
  `pre/process/post`, mais ne doit pas devenir une dependance directe du
  backend `boussinesq` tant qu'il transporte des types et options MODFLOW ;
- si un vrai besoin de mutualisation apparait, il faudra extraire plus tard
  une couche generique `flow_common`, et non empiler `boussinesq` sur
  `modflow_common`.

### 8.2 Objets coeur

#### `BoussinesqMesh`

Responsabilite :

- recevoir directement le maillage runtime deja construit par la chaine,
- construire au besoin une vue solver legere, sans imposer de serialisation intermediaire,
- construire les tables topologiques utiles a l'assembleur,
- exposer :
  - `n_cells`,
  - `areas`,
  - `centroids`,
  - `boundary_edges`,
  - `internal_edges`,
  - `edge_lengths`,
  - `neighbor_pairs`.

Remarque :

- `BoussinesqMesh` n'est pas un alias de `HydroMesh` ;
- il s'agit d'une vue interne minimale adaptee au calcul ;
- une conversion vers `HydroMesh` peut etre faite plus tard pour exporter des
  champs, mais ne doit pas conditionner l'entree du solveur.

#### `BoussinesqState`

Responsabilite :

- stocker `S`,
- reconstruire `H = z_b + S/f`,
- reconstruire `h` ou `b` si necessaire pour les sorties,
- stocker `q_ex`,
- porter les sorties du dernier pas resolu.

#### `BoussinesqAssembler`

Responsabilite :

- assembler residual et jacobienne en variable `S`,
- traiter flux internes, BC et termes sources,
- appliquer la regularisation de `saturation-excess`.

#### `BoussinesqSolver`

Responsabilite :

- configurer et piloter PETSc `TS`,
- appeler les binders de temps deja existants en amont,
- fournir residuale et jacobienne a `TS/SNES`,
- stocker les resultats et les exports.

### 8.3 Sources de donnees pour les proprietes

Ordre de priorite recommande :

1. proprietes explicites du `CatchmentMeshBundle` si disponibles,
2. sinon projection des parametres `flow.parameters` via les supports de `Domain`,
3. sinon erreur explicite.

Cela permet d'utiliser :

- soit un maillage totalement autonome exporte pour le solveur,
- soit la logique de parametrage HydroModPy existante.

### 8.4 Sorties attendues

Le solveur doit produire au minimum :

- `head` par cellule et par pas,
- `saturated_thickness` par cellule,
- `saturation_excess` par cellule,
- `drainage_flux` et plus generalement les flux d'echange head-dependent,
- `edge_flux` par arete,
- `cell_balance` pour audit de masse,
- debit sortant total sur les bords cibles.

Pour rester un vrai substitut fonctionnel de MODFLOW, il est souhaitable de
retrouver aussi les familles de sorties suivantes :

- `watertable_elevation`,
- `watertable_depth`,
- `seepage_areas`,
- `outflow_drain`,
- `groundwater_storage`,
- `accumulation_flux`,
- `persistency_index`,
- `intermittency_*`.

Formats cibles :

- arrays `numpy`,
- VTU via `HydroMesh.with_cell_data(...)` si un export maillage est demande,
- series temporelles pour post-traitement.

Autrement dit, `HydroMesh` est ici un support d'export et de visualisation,
pas le contrat d'entree du solveur `boussinesq`.

## 9. Choix de conception a figer

### 9.1 Ce qui doit etre V1

- 2D horizontal,
- nappe libre monolayer,
- maillage triangulaire non structure,
- volumes finis centres cellules,
- stockage en variable `S` avec reconstruction de `H`,
- ODE raide semi-discrete en `S`,
- PETSc `TS` pleinement implicite,
- Euler implicite PETSc en V1,
- recharge, puits, Dirichlet, Robin/Cauchy,
- drainage et autres echanges head-dependent,
- routage possible vers un operateur ET/surface,
- saturation-excess via regularisation `G_r(S/S_c) R(B)`,
- pas de dependance directe a `modflow_common`,
- maillage d'entree recu directement depuis le runtime,
- backend independant de FLOPY/MODFLOW.

### 9.2 Ce qui peut venir ensuite

- prise en charge directe des maillages quadrangles ou `HydroMesh` mixtes,
- projection de BC plus riche a partir des tags `is_river` / `edge_kind`,
- formulation mixte DAE index 1,
- `TSBDF` PETSc sur la formulation implicite generale,
- jacobienne de bloc analytique ou semi-analytique,
- couplage surface/subsurface plus fin,
- backend EF/FEniCSx si un vrai besoin apparait.

### 9.3 Ce qui ne doit pas guider V1

- la recherche immediate d'une abstraction VF/EF totalement neutre,
- la reproduction exacte des packages MODFLOW,
- une dependance forte a FEniCSx pour un probleme deja naturellement pose sur graphe de cellules.

## 10. Roadmap de mise en oeuvre

### Phase 1

- ajouter `solver_engine = "boussinesq"`,
- ajouter l'adapter de simulation,
- recevoir directement le maillage runtime dans le solveur,
- resoudre un cas stationnaire avec Dirichlet + recharge uniforme,
- brancher PETSc `TS/SNES/KSP` des la premiere implementation.

### Phase 2

- brancher `flow.ic`,
- brancher `flow.sinks_sources.recharge`,
- brancher `flow.sinks_sources.wells`,
- brancher les BC laterales.

### Phase 3

- ajouter le transient implicite,
- brancher les binders temporels existants,
- ajouter `saturation_excess`,
- auditer strictement le bilan de masse.

### Phase 4

- valider sur cas analytiques Boussinesq deja presents dans le depot,
- comparer avec MODFLOW sur cas simples,
- ajouter export VTU et series temporelles,
- consolider les options PETSc et le preconditionnement.

### Phase 5

- introduire la formulation mixte `S/Q/q_ex`,
- passer a la DAE index 1,
- utiliser `TSBDF` PETSc sur la formulation implicite complete,
- consolider le preconditionnement de bloc.

## 11. Besoins restants, tests et visualisation

### 11.1 Decisions qu'il reste a figer avant implementation

La theorie du solveur est suffisamment cadre pour commencer le developpement.
Les derniers points a figer relevent surtout du perimetre V1 et de la
validation.

Points a arbitrer explicitement :

- perimetre fonctionnel exact de la V1 : `ic`, `recharge`, `wells`,
  Dirichlet laterales, `drainage`, `ocean`, `stream`, ET ;
- ordre de priorite entre validation analytique rapide et integration
  complete dans le launcher `Flow` ;
- convention V1 pour les cas ambigus :
  - recharge negative reroutee ou non vers un operateur ET,
  - projection de `stream` et `ocean` sur le maillage triangulaire,
  - forme exacte du `drainage` sur aretes ou cellules ;
- cible PETSc pratique :
  - `petsc4py` impose en environnement de dev et CI,
  - ou backend local de validation plus leger maintenu en parallele ;
- liste des cas de reference a faire passer en premier pour considerer la V1
  utilisable.

En pratique, les cas de reference recommandes pour demarrer sont :

1. Dupuit/Boussinesq stationnaire 1D a charge imposee,
2. recharge uniforme 1D ou pseudo-2D,
3. petit cas transient avec recharge variable,
4. puits ponctuel simple,
5. premier cas triangulaire de type `catchment`.

### 11.2 Strategie de test proposee

La validation du solveur doit etre construite par couches, des operateurs
numeriques elementaires jusqu'au launcher complet.

#### Niveau 1 : tests unitaires du noyau numerique

Objectif : valider les briques elementaires sans passer par le runtime
HydroModPy complet.

Tests recommandes :

- calcul des aires, longueurs d'aretes, voisinages, normales ;
- flux internes antisymetriques sur chaque arete partagee ;
- conservation stricte sur domaine ferme sans source ni sink ;
- positivite de `S` et absence de valeurs non physiques ;
- comportement monotone du terme `q_ex = G_r(S/S_c) R(B)` ;
- verification de la jacobienne locale si elle est codee analytiquement.

#### Niveau 2 : tests d'integration solveur local

Objectif : valider le schema implicite complet sur de petits cas synthetiques,
sans passer encore par le launcher.

Tests recommandes :

- etat stationnaire constant conserve ;
- cas `fixed-head + recharge uniforme` ;
- cas transient avec pas de temps imposes ;
- puits localise simple ;
- drainage unilaterale simple ;
- verification du bilan de masse global et par cellule ;
- verification du nombre d'iterations `SNES` et de la convergence temporelle.

#### Niveau 3 : tests de contrat avec `Flow`

Objectif : verifier que le nouveau backend respecte le meme contrat metier que
les solveurs MODFLOW existants.

Tests recommandes :

- lecture et application de `flow.ic` ;
- lecture et projection de `flow.bc` ;
- lecture et application de `flow.sinks_sources.recharge` ;
- lecture et application de `flow.sinks_sources.wells` ;
- respect du maillage canonique derive de `simulation.time` en transient ;
- generation des sorties minimales attendues par le reste de la chaine.

#### Niveau 4 : validation scientifique

Objectif : comparer le solveur Boussinesq a des solutions de reference.

Tests recommandes :

- reprise des cas analytiques deja presents dans `tests/validation/analytical` ;
- comparaison a des profils de charge analytiques ou semi-analytiques ;
- comparaison de cas simples `modflow6` / `modflownwt` contre `boussinesq`
  lorsque la physique est comparable ;
- suivi d'indicateurs quantitatifs :
  - RMSE sur les charges,
  - erreur absolue maximale,
  - ecart-type transverse,
  - erreur de bilan de masse.

#### Niveau 5 : regression launcher

Objectif : figer un petit cas `flow/boussinesq` executable dans les campagnes
de tests et de regression du depot.

Tests recommandes :

- un cas rapide "smoke test" avec maillage reduit ;
- un cas plus representatif avec recharge et condition de bord laterale ;
- signatures sur tableaux de sortie,
- signatures sur bilans integres,
- verification de la production des artefacts `VTU` et series temporelles.

### 11.3 Visualisation minimale dynamique

La V1 ne doit pas attendre un gros chantier de post-traitement pour etre
inspectable. Une visualisation simple mais systematique suffit pour voir
rapidement si le solveur "passe" ou non.

Sorties graphiques minimales recommandees :

- cartes 2D par cellule de `head`, `S`, `saturated_thickness` et `q_ex` ;
- carte des flux d'aretes ou, a minima, carte du bilan cellulaire ;
- courbe temporelle du bilan de masse global ;
- courbe du residu non lineaire et du nombre d'iterations par pas ;
- debit total sortant sur les bords cibles ;
- animation GIF ou HTML des champs principaux sur les dates de sortie.

Support technique recommande dans le depot :

- generation de snapshots PNG via le maillage runtime ou une conversion
  legere vers `HydroMesh` uniquement cote sortie ;
- export `VTU` en injectant les champs solveur dans `HydroMesh.with_cell_data(...)`
  uniquement au moment de l'export ;
- construction d'un GIF simple a partir des snapshots ;
- conservation d'un mode "headless" pour la CI.

Le minimum utile pour la premiere iteration est :

1. snapshots PNG pour quelques dates clefs,
2. un GIF `head` et un GIF `saturation_excess`,
3. un export `VTU` du dernier pas,
4. un fichier de synthese JSON contenant :
   - bilan de masse,
   - nombre d'iterations,
   - pas de temps,
   - erreurs eventuelles.

### 11.4 Planning de developpement recommande

Le developpement peut etre mene en quatre blocs techniques, chacun associe a
une famille de tests.

#### Bloc A : branchement minimal dans HydroModPy

- ajouter `solver_engine = "boussinesq"` ;
- ajouter l'adapter `simulation.adapters.flow.boussinesq` ;
- brancher le solveur sur le meme cycle `pre/process/post` que les solveurs
  flow existants, sans dependance directe a `modflow_common` ;
- ajouter des tests de contrat simples sur le registre d'adapters.

#### Bloc B : noyau numerique stationnaire et transient simple

- construire `BoussinesqMesh`, `BoussinesqState` et `BoussinesqAssembler` ;
- assembler residuale et jacobienne en `S` ;
- brancher `PETSc TS/SNES/KSP` ;
- faire passer les tests de conservation, flux et recharge uniforme.

#### Bloc C : operateurs HydroModPy

- brancher `flow.ic` ;
- brancher `recharge` et `wells` ;
- brancher Dirichlet laterales puis `drainage` ;
- ajouter les tests d'integration runtime correspondants.

#### Bloc D : validation et visualisation

- ajouter les cas analytiques prioritaires ;
- ajouter exports `VTU`, PNG, GIF et JSON de synthese ;
- ajouter un cas launcher rapide de regression ;
- comparer a MODFLOW sur un ou deux cas de reference simples.

## 12. Translation theorique des fonctions MODFLOW

### 12.1 Principe

Le solveur Boussinesq doit etre pense comme un remplacant du solveur flow
MODFLOW au niveau fonctionnel, pas seulement comme un solveur de recharge
diffuse.

Le bon parallele theorique est donc :

- `MODFLOW = bilan de masse + operateurs packages`,
- `Boussinesq = bilan de masse 2D libre + operateurs de bilan sur support 2D`.

La seule reduction assumee ici est la suppression de la discretisation
verticale multicouche.

### 12.2 Table de correspondance conceptuelle

| Fonction cote MODFLOW | Traduction naturelle dans le solveur Boussinesq |
| --- | --- |
| IC (`top`, `bottom`, `custom`) | etat initial `h(t=0)` |
| stockage transitoire | `C(h) = Sy + Ss b(h)` ou loi equivalente |
| transmissivite / conductance milieu | `T(h) = K b(h)` |
| CHD `ocean` / limites laterales | Dirichlet sur sous-ensembles d'aretes ou cellules |
| BC Robin/Cauchy | operateur d'echange lineique/cellulaire |
| `drainage` | operateur unilateral `q_drn(h)` distinct de `q_ex` |
| `recharge` | source surfacique diffuse |
| `negative_to_evt` / EVT | operateur de sink surfacique branche sur le meme bilan |
| `wells` | source/puits localise projete sur une cellule |
| `stream` | Dirichlet localisee ou echange head-dependent sur support hydrographique |
| `watertable_*` | derive directement de `h` et `z_s` |
| `seepage_areas` | derive de l'ensemble actif `h = z_s` ou `q_ex > 0` |
| `outflow_drain` | derive de `q_drn` |
| `groundwater_storage` | derive de `C(h)`, `b(h)` et des aires de cellule |
| `accumulation_flux`, `persistency_index`, `intermittency_*` | derives des champs de flux sortants exportes par le solveur |

### 12.3 Consequences de conception

Ce cadrage impose plusieurs choix :

- il ne faut pas eliminer `Ss` de la theorie si l'on veut couvrir le meme champ fonctionnel que MODFLOW en transient ;
- `drainage`, `stream`, `ocean`, ET et `saturation-excess` doivent etre traites comme des operateurs distincts, meme s'ils vivent tous dans le meme bilan ;
- les sorties de post-traitement doivent etre pensees des le depart comme des derives du bilan et des operateurs, pas comme des ajouts cosmetiques ;
- l'independance vis-a-vis de MODFLOW ne signifie pas perdre ses capacites, mais les reexprimer dans une formulation 2D libre plus directe.

## 13. Conclusion

Le bon "autre solveur" pour HydroModPy n'est pas un clone conceptuel de MODFLOW, ni un document generique VF/EF, mais :

- un backend `boussinesq` branche sur le meme processus `Flow`,
- utilisant `h` comme inconnue principale,
- assemble sur le maillage triangulaire deja exporte,
- formule comme un bilan 2D libre extensible par operateurs de source, sink et echange,
- et capable de reutiliser sans changement majeur :
  - `flow.ic`,
  - `flow.bc`,
  - `flow.sinks_sources`,
  - `simulation.time`.

Autrement dit, la vraie independance vis-a-vis de MODFLOW doit se faire au niveau du backend numerique, pas au niveau du contrat metier expose aux autres briques d'HydroModPy.
