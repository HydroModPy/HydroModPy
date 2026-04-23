# Architecture du solveur Boussinesq 2D

Liens : [glossary.md](glossary.md),
[design_patterns.md](design_patterns.md),
[boussinesq_linux_ci.md](boussinesq_linux_ci.md),
[boussinesq_petsc_vs_marcais_2017.md](boussinesq_petsc_vs_marcais_2017.md),
[boussinesq_petsc_headwater_100km2_diagnostic.md](boussinesq_petsc_headwater_100km2_diagnostic.md),
[modflow_contracts.md](modflow_contracts.md).

Code : `hydromodpy/solver/boussinesq/`.

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

Pour la premiere implementation, on retient donc explicitement :

- `h` comme inconnue primaire du solveur,
- `b(h)`, `T(h)`, `S(h)` et `q_ex(h)` comme quantites derivees,
- une discretisation ecrite directement en `h`, sans conversion structurelle
  `h <-> S` dans le coeur du schema.

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
| `h(x,t)` | charge hydraulique / cote piezometrique, inconnue primaire |
| `S(x,t)` | stockage diagnostique surfacique, par ex. `S = f b(h)` |
| `S_c(x)` | stockage diagnostique maximal, `S_c = f(z_s-z_b)` |
| `H(x,t)` | notation optionnelle pour la charge, ici identique a `h` |
| `z_s(x)` | altitude de surface (`surface_topo`) |
| `z_b(x)` | altitude du substratum (`domain.substratum`) |
| `b(x,t)` | epaisseur saturee, `b = max(h - z_b, 0)` |
| `C(x,t)` | coefficient de stockage plan, par ex. `C = Sy + Ss b` |
| `T(x,t)` | transmissivite locale, `T = K b(h)` |
| `K(x)` | conductivite hydraulique horizontale |
| `f(x)` | coefficient utilise pour les quantites diagnostiques `S` et `S_c` |
| `Sy(x)` | emmagasinement libre effectif |
| `Ss(x)` | stockage specifique / contribution elastique |
| `N(x,t)` | recharge diffuse vers la nappe |
| `q_w(x,t)` | source/sink volumique equivalent des puits |
| `q_bc(x,t)` | flux impose par BC de type Cauchy/Robin |
| `q_in^{surf}(x,t)` | ensemble explicite des apports de surface autorises a alimenter `q_ex` |
| `q_drn(x,t)` | terme de drainage head-dependent |
| `q_evt(x,t)` | terme de soutirage surfacique de type ET |
| `q_ex(x,t)` | debit surfacique de saturation-excess |

Remarque importante :

- dans le schema numerique detaille, l'inconnue assemblee est `h` ;
- `b`, `T`, `S` et `S_c` sont reconstruits localement a partir de `h` ;
- `Sy` reste le parametre cle du modele transient libre ;
- `Ss` doit rester disponible si l'on veut que le solveur couvre naturellement les fonctions de stockage transitoire actuellement portees par MODFLOW ;
- en pratique, le stockage plan peut etre ecrit `C(h) = Sy + Ss b(h)` ;
- `S = f b(h)` reste utile comme variable diagnostique pour les sorties et pour
  la regularisation `S/S_c` ;
- si le bundle de maillage ne fournit qu'un `storage_coefficient`, il doit etre
  interprete comme un proxy de la storativite totale 2D.

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
regularisee proposee dans la note initiale, ecrite ici en fonction de `h` et
de quantites diagnostiques derivees.

On introduit un taux de saturation local :

```math
\theta(h) =
\mathrm{clip}\left(
\frac{h-z_b}{z_s-z_b},
0,
1
\right)
```

On introduit aussi un ensemble explicite des apports de surface :

```math
q_{in}^{surf} = q_{rch} + q_{bc}^{surf,+}
```

ou :

- `q_{rch}` est la recharge diffuse ;
- `q_{bc}^{surf,+}` regroupe seulement les apports positifs provenant
  d'operateurs de surface ou de bord explicitement relies a la surface ;
- les puits, meme injecteurs, n'entrent pas directement dans `q_{in}^{surf}`
  en V1.

Dans la base V1 la plus simple, on prend :

```math
q_{bc}^{surf,+} = 0
```

et donc :

```math
q_{in}^{surf} = q_{rch} = N
```

L'operateur d'exfiltration devient :

```math
q_{ex}
=
G_r\left(\theta(h)\right)
R\left(
- \nabla \cdot \left(T(h)\nabla h\right)
+ q_{in}^{surf}
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

Autrement dit, `q_ex` n'est pas declenche par tous les termes entrants du
bilan, mais seulement par les apports explicitement rattaches a la surface.

Interpretation :

- tant que la saturation locale reste loin de 1, `G_r` garde `q_ex` faible ;
- a l'approche de la surface, `G_r` active progressivement l'exfiltration ;
- seule la partie positive du desequilibre local de surface produit du
  `saturation-excess`.

Cette approche a un avantage pratique pour V1 :

- elle colle directement a la methode que tu avais proposee ;
- elle s'insere dans une boucle non lineaire Newton ou Picard ;
- elle evite d'introduire tout de suite une logique d'ensemble actif ou de
  projection.

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

Au vu des choix retenus, le solveur doit recevoir comme maillage canonique V1
le maillage 2D issu du workflow `gmsh`, materialise par un
`CatchmentMeshBundle`.

Le point important est le suivant :

- le workflow `gmsh` produit deja un objet qui porte noeuds, cellules, aretes,
  topographie, substratum, proprietes et tags de bord ;
- cet objet est suffisamment proche des besoins d'un schema volumes finis ;
- il devient donc le contrat d'entree numerique de la V1.

Le solveur doit pouvoir consommer :

- soit un `CatchmentMeshBundle` deja construit en memoire ;
- soit un `CatchmentMeshBundle` recharge depuis son export ;
- mais il n'a pas a supporter plusieurs contrats de maillage concurrents en V1.

Le support en memoire doit fournir les ingredients dont un schema volumes finis a besoin :

- geometrie des cellules,
- adjacence par aretes,
- longueurs d'aretes,
- topographie aux noeuds et par cellule,
- proprietes hydrauliques par cellule,
- flags de bord et d'interfaces.

Champs minimaux obligatoires du contrat V1 `CatchmentMeshBundle` :

- noeuds 2D et connectivite des cellules triangulaires ;
- aires de cellules et longueurs d'aretes ;
- relation cellule-cellule et cellule-arete ;
- `z_top` ou equivalent de surface ;
- `z_bottom` ou equivalent de substratum ;
- `hydraulic_conductivity_m_s` par cellule, ou une regle claire de projection ;
- `storage_coefficient` ou un couple de proprietes permettant de reconstruire
  `Sy` et/ou `Ss` ;
- `edge_kind` pour distinguer bord / interieur / interfaces speciales ;
- `is_river` ou tag equivalent si la projection `stream` doit etre activee ;
- identifiants de cellules et d'aretes stables pour les sorties et diagnostics.

### 5.2 Inconnues discretes

Le solveur V1 est centre cellules :

- 1 inconnue `h_i` par cellule 2D,
- 1 epaisseur saturee `b_i = max(h_i-z_{b,i},0)` reconstruite par cellule,
- 1 stockage diagnostique `S_i = f_i b_i` si necessaire pour les sorties et la regularisation,
- 1 terme `q_{ex,i}` par cellule lorsque la regularisation de surface est active.

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

Le schema retenu en V1 est un schema primal en volumes finis centres cellules,
ecrit directement en `h`.

Il s'agit :

- d'une discretisation 2D horizontale sur cellules triangulaires ;
- d'une inconnue principale `h_T` par cellule ;
- de flux d'aretes reconstruits a partir de `h` ;
- d'un terme `q_ex(h)` pilote par un desequilibre de surface explicitement
  defini ;
- d'un schema implicite en temps.

Une variante mixte ou hybride reste possible plus tard en introduisant des
flux `q_e` comme inconnues supplementaires.

### 6.1 Variables discretes

Pour un maillage triangulaire :

- `T` : ensemble des cellules ;
- `e` : ensemble des aretes.

Inconnue principale :

- `h_T^n` : charge dans la cellule `T` au temps `t^n`.

Quantites reconstruites :

```math
b_T = \max(h_T-z_{b,T}, 0)
```

```math
T_T = K_T b_T
```

```math
S_T = f_T b_T
```

```math
S_{c,T} = f_T (z_{s,T} - z_{b,T})
```

### 6.2 Flux internes aux aretes

Pour chaque arete interne `e` entre cellules `T_L` et `T_R` :

```math
F_{L,e} = - \tau_e(h) (h_{T_R} - h_{T_L})
```

avec :

```math
\tau_e(h) = \frac{K_e b_e(h) |e|}{d_{LR}}
```

et :

- `F_{L,e}` compte positivement lorsqu'il sort de `T_L` ;
- `F_{R,e} = -F_{L,e}` ;
- `b_e(h)` est une epaisseur saturee moyenne reconstruite sur l'arete ;
- `K_e` est une moyenne harmonique ou arithmetique selon le choix de V1.

### 6.3 Operateurs de bord V1

Le schema V1 fixe explicitement les traitements suivants :

- Dirichlet : imposee via un flux de bord reconstruit avec une valeur de charge
  de bord `h_D`, et non par changement de variable dans le coeur du schema ;
- Neumann : flux impose directement sur l'arete de bord ;
- Robin / Cauchy : flux lineique dependant de `h` sur l'arete de bord ;
- `drainage` : operateur unilateral de type head-dependent ;
- `stream` / `ocean` : cas particuliers de projection spatiale de Dirichlet ou
  Robin selon la strategie retenue.

Le point cle est qu'en V1, tous les operateurs de bord entrent dans la
residuale comme des contributions de flux, ce qui preserve une ecriture
conservative unique.

### 6.4 Residuale discrete canonique V1

Pour chaque cellule `T`, la residuale complete retenue en V1 est :

```math
R_T(h^{n+1}) =
\frac{|T|}{\Delta t}\,\overline{C}_T(h^{n+1})\,(h_T^{n+1}-h_T^n)
+ \sum_{e \in \partial T \cap \mathcal{E}_{int}} F_{T,e}(h^{n+1})
+ Q^{dir}_T(h^{n+1})
+ Q^{neu}_T(h^{n+1})
+ Q^{rob}_T(h^{n+1})
+ Q^{drn}_T(h^{n+1})
+ |T|q_{evt,T}(h^{n+1})
+ |T|q_{ex,T}(h^{n+1})
- |T|N_T^{n+1}
- Q_{w,T}^{n+1}
```

et on cherche :

```math
R_T(h^{n+1}) = 0
```

Conventions de signe V1 :

- les termes de flux sortants du domaine souterrain sont positifs dans la
  residuale ;
- `N_T > 0` est une recharge vers la nappe ;
- `Q^{neu}_T < 0` represente un flux impose entrant ;
- `Q_{w,T} > 0` est une injection, `Q_{w,T} < 0` un pompage ;
- `q_{ex}`, `q_{evt}` et `q_{drn}` sont des termes sortants.

Cette residuale est la reference unique a coder dans l'assembleur V1.

Choix pratique pour le terme temporel :

- en V1, `\overline{C}_T(h^{n+1})` peut etre pris comme `C(h_T^{n+1})` ;
- une moyenne plus sophistiquee ou une linearisation specifique reste possible
  plus tard si les tests de robustesse l'exigent ;
- le point important est de garder une unique convention dans tout
  l'assembleur et dans tous les tests de masse.

Table de synthese des operateurs V1 :

| Terme | Support | Unite effective | Signe dans `R_T` | Remarque |
| --- | --- | --- | --- | --- |
| `\sum F_{T,e}` | aretes internes | m3/s equivalent | `+` si sortant | flux Darcy cellule-cellule |
| `Q_T^{dir}` | aretes de bord | m3/s equivalent | `+` si sortant | flux reconstruit vers charge imposee |
| `Q_T^{neu}` | aretes de bord | m3/s equivalent | signe impose | flux de bord prescrit |
| `Q_T^{rob}` | aretes de bord | m3/s equivalent | `+` si sortant | echange head-dependent |
| `Q_T^{drn}` | aretes/cellules | m3/s equivalent | `+` | sink unilateral |
| `|T|q_{evt,T}` | cellule | m3/s equivalent | `+` | sink surfacique |
| `|T|q_{ex,T}` | cellule | m3/s equivalent | `+` | exfiltration de surface |
| `|T|N_T` | cellule | m3/s equivalent | `-` | recharge diffuse |
| `Q_{w,T}` | cellule | m3/s | `-` | injection positive, pompage negatif |

### 6.5 Terme saturation-excess

Le desequilibre de surface utilise dans la V1 est :

```math
B_T = - \frac{1}{|T|}\left(
\sum_{e \in \partial T \cap \mathcal{E}_{int}} F_{T,e}
+ Q_T^{dir}
+ Q_T^{rob,surf}
\right)
+ q_{in,T}^{surf}
```

avec, en V1 de base :

```math
q_{in,T}^{surf} = N_T
```

Extension possible, mais explicite seulement :

- ajout de certains apports de bord relies a la surface dans
  `q_{in,T}^{surf}` ;
- exclusion des puits injecteurs et des termes non interpretes comme apports de
  surface.

Regle de coherence :

- un apport de bord deja represente comme flux Darcy de bord dans
  `Q^{rob,surf}` ne doit pas etre rajoute une seconde fois dans
  `q_{in}^{surf}`.

La regularisation reste :

```math
R(B_T) = \max(B_T, 0)
```

```math
\sigma_T = \frac{S_T}{S_{c,T}}
```

```math
G_r(\sigma_T) = \exp\left(-\frac{1-\sigma_T}{r}\right)
```

```math
q_{ex,T} = G_r(\sigma_T) R(B_T)
```

### 6.6 Schema implicite en temps

Le schema temporel de reference de la V1 est un Euler implicite :

```math
\frac{|T|}{\Delta t}\,\overline{C}_T(h^{n+1})\,(h_T^{n+1}-h_T^n)
+ \mathcal{F}_T(h^{n+1})
+ \mathcal{Q}_T(h^{n+1})
= 0
```

ou :

- `\mathcal{F}_T` regroupe les flux Darcy internes et de bord ;
- `\mathcal{Q}_T` regroupe `q_ex`, `q_drn`, `q_evt`, recharge et puits.

### 6.7 Algorithme global Newton

Initialisation :

```math
h^{(0)} = h^n
```

Boucle Newton pour `k = 0,1,...` :

1. reconstruire `b_T^{(k)}`, `T_T^{(k)}`, `S_T^{(k)}` ;
2. calculer les flux internes et de bord ;
3. calculer `B_T^{(k)}` puis `q_{ex,T}^{(k)}` ;
4. construire la residuale `R^{(k)}` ;
5. construire le jacobien `J^{(k)}` ;
6. resoudre :

```math
J^{(k)} \delta h = -R^{(k)}
```

7. mettre a jour :

```math
h^{(k+1)} = h^{(k)} + \delta h
```

Un Picard ou un Newton simplifie reste acceptable pour un demarrage local, mais
la reference theorique de la V1 est bien un solveur implicite sur `h`.

### 6.8 Nature du systeme et integration en temps

Avec les flux et operateurs reconstruits algebriquement a partir de `h`, le
systeme semi-discret s'ecrit :

```math
M(h)\frac{dh}{dt} = F(h,t)
```

Il s'agit d'une ODE raide non lineaire.

Si une V2 introduit explicitement des flux `Q_e` comme inconnues, on pourra
alors ecrire une DAE implicite d'index 1.

Pour la V1, le choix fixe est :

- ODE raide en `h` ;
- schema implicite Euler ;
- resolution non lineaire de type Newton ;
- coeur numerique independant du backend lineaire et temporel.

### 6.9 V2 proposee : formulation mixte DAE index 1

Une V2 pourra conserver explicitement :

- `h_T` au centre des cellules ;
- `Q_e` sur les aretes ;
- eventuellement `q_{ex,T}` comme inconnue auxiliaire.

Le systeme prendra alors la forme :

```math
F(t,U,\dot U) = 0
```

avec une composante differentielle en `h` et des composantes algebriques sur
les flux et la fermeture de surface.

### 6.10 Jacobien

Le jacobien V1 contient :

- terme temporel : dependance en `\overline{C}_T(h)` ;
- flux Darcy : dependance via `b(h)` et les differences de charge ;
- operateurs de bord head-dependent ;
- terme `q_{ex}` via `G_r` et `R`.

En V2 mixte/DAE, le jacobien deviendra un jacobien de bloc sur les inconnues
`(h,Q,q_{ex})`.

### 6.11 Bords et operateurs additionnels

Les operateurs V1 se branchent tous sur la meme residuale :

- `recharge` : terme surfacique source par cellule ;
- `wells` : debit ponctuel projete sur cellule ;
- Dirichlet : flux de bord reconstruit a partir d'une charge imposee ;
- Neumann : flux de bord impose ;
- Robin / Cauchy : flux de bord dependant de `h` ;
- `drainage` : flux sortant unilateral ;
- `evt` : sink surfacique ;
- `saturation-excess` : flux sortant de surface ;
- `ocean` / `stream` : projection spatiale de BC ou d'operateurs de bord.

### 6.12 Structure de donnees recommandee

```python
cells = [T1, T2, ...]
edges = [e1, e2, ...]

h[T]
zb[T]
zs[T]
K[T]
Sy[T]
Ss[T]
f[T]

neighbors[e] = (T_left, T_right)
normal[e]
length[e]
edge_kind[e]
```

Pour les sorties et diagnostics :

```python
b[T]
S[T]
Sc[T]
qex[T]
```

### 6.13 Backends lineaires et runtime solveur

La bonne abstraction n'est pas "PETSc ou non", mais :

- un coeur numerique qui expose residuale et jacobien ;
- un backend runtime charge de l'integration temporelle et des resolutions
  lineaires/non lineaires.

Recommandation V1 :

- backend local de reference possible pour petits cas et validation ;
- backend PETSc recommande pour runs cibles et maillages plus grands ;
- confinement des imports et objets PETSc dans `runtimes/` ;
- absence de dependance PETSc dans le contrat `Flow` et dans la theorie du
  schema.

## 7. Reutilisation du contrat process existant

### 7.1 Conditions initiales

`flow.ic.h` devient directement l'etat initial :

- `type = top` -> `h_0 = z_s`,
- `type = bottom` -> `h_0 = z_b`,
- `type = custom` -> `h_0 = valeur`.

Les quantites derivees sont ensuite reconstruites localement :

```math
b_0 = \max(h_0-z_b,0)
```

```math
S_0 = f \, b_0
```

Il n'y a donc pas besoin d'un nouveau format d'IC pour le solveur Boussinesq,
ni d'une conversion structurelle `Flow -> stockage interne`.

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

Dans la V1 retenue, c'est aussi le terme de reference qui alimente
`q_{in}^{surf}` pour la regularisation du `saturation-excess`.

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
      boussinesq.py
      mesh.py
      runtime_contract.py
      runtime_selection.py
      solver_contract.py
      assembly/
      core/
      drivers/
      forcing/
      jacobian/
      runtimes/
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
- en V1, il est construit a partir d'un `CatchmentMeshBundle` issu du workflow
  `gmsh` ;
- une conversion vers `HydroMesh` peut etre faite plus tard pour exporter des
  champs, mais ne doit pas conditionner l'entree du solveur.

#### `BoussinesqState`

Responsabilite :

- stocker `h`,
- reconstruire `b`, `T`, `S` et `S_c`,
- stocker `q_ex`,
- porter les sorties du dernier pas resolu.

#### `BoussinesqAssembler`

Responsabilite :

- assembler residual et jacobienne en variable `h`,
- traiter flux internes, BC et termes sources,
- appliquer la regularisation de `saturation-excess`.

#### `BoussinesqSolver`

Responsabilite :

- piloter l'integration en temps via un backend runtime,
- appeler les binders de temps deja existants en amont,
- fournir residuale et jacobienne au backend choisi,
- stocker les resultats et les exports.

### 8.3 Sources de donnees pour les proprietes

Ordre de priorite recommande :

1. proprietes explicites du `CatchmentMeshBundle` issu du workflow `gmsh`,
2. sinon projection des parametres `flow.parameters` via les supports de `Domain`,
3. sinon erreur explicite.

Cela permet d'utiliser :

- soit un maillage `gmsh`/`CatchmentMeshBundle` totalement autonome pour le solveur,
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
- contrat maillage V1 = `CatchmentMeshBundle` issu du workflow `gmsh`,
- volumes finis centres cellules,
- inconnue primaire `h`,
- `b`, `T`, `S` et `S_c` reconstruits a partir de `h`,
- ODE raide semi-discrete en `h`,
- Euler implicite + Newton en reference theorique,
- recharge, puits, Dirichlet, Robin/Cauchy,
- drainage et autres echanges head-dependent,
- routage possible vers un operateur ET/surface,
- saturation-excess via regularisation `G_r(S/S_c) R(B)` avec
  `q_in^{surf}` explicite,
- pas de dependance directe a `modflow_common`,
- maillage d'entree recu depuis le pipeline `gmsh`,
- coeur solveur independant du backend runtime,
- backend independant de FLOPY/MODFLOW.

### 9.2 Ce qui peut venir ensuite

- prise en charge d'autres contrats de maillage (`HydroMesh`, `SolverMesh`, autres),
- projection de BC plus riche a partir des tags `is_river` / `edge_kind`,
- PETSc comme backend principal de production si desire,
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
- recevoir un `CatchmentMeshBundle` issu du workflow `gmsh`,
- construire `BoussinesqMesh` a partir de ce contrat unique,
- resoudre un cas stationnaire avec Dirichlet + recharge uniforme,
- faire tourner un backend local de reference.

### Phase 2

- brancher `flow.ic`,
- brancher `flow.sinks_sources.recharge`,
- brancher `flow.sinks_sources.wells`,
- brancher les BC laterales,
- ecrire la residuale discrete V1 complete dans l'assembleur.

### Phase 3

- ajouter le transient implicite,
- brancher les binders temporels existants,
- ajouter `saturation_excess`,
- auditer strictement le bilan de masse,
- brancher `runtimes/petsc_partition.py` comme backend optionnel.

### Phase 4

- valider sur cas analytiques Boussinesq deja presents dans le depot,
- comparer avec MODFLOW sur cas simples,
- ajouter export VTU et series temporelles,
- consolider les options PETSc et le preconditionnement.

### Phase 5

- introduire la formulation mixte `h/Q/q_ex`,
- passer a la DAE index 1,
- utiliser `TSBDF` PETSc sur la formulation implicite complete,
- consolider le preconditionnement de bloc.

## 11. Besoins restants, tests et visualisation

### 11.1 Decisions fixees pour la V1

Les choix structurants de la V1 sont maintenant fixes :

- inconnue primaire = `h` ;
- `b`, `T`, `S` et `S_c` reconstruits a partir de `h` ;
- contrat maillage V1 = `CatchmentMeshBundle` issu du workflow `gmsh` ;
- `HydroMesh` reserve aux exports et a la visualisation ;
- `q_ex` pilote par un ensemble explicite d'apports de surface,
  avec `q_{in}^{surf} = N` dans la base V1 ;
- residuale discrete unique ecrite en `h` ;
- coeur solveur independant du backend runtime ;
- `runtimes/petsc_partition.py` prepare des la conception, mais non impose au contrat
  theorique du solveur.

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
- verification du nombre d'iterations non lineaires et de la convergence
  temporelle ;

#### Niveau 3 : tests de contrat avec `Flow`

Objectif : verifier que le nouveau backend respecte le meme contrat metier que
les solveurs MODFLOW existants.

Tests recommandes :

- lecture et application de `flow.ic` ;
- lecture et projection de `flow.bc` ;
- lecture et application de `flow.sinks_sources.recharge` ;
- lecture et application de `flow.sinks_sources.wells` ;
- respect du decoupage temporel canonique derive de `simulation.time` en
  transient ;
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
- assembler residuale et jacobienne en `h` ;
- faire tourner d'abord le backend local de reference ;
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
- assemble sur un `CatchmentMeshBundle` issu du workflow `gmsh`,
- formule comme un bilan 2D libre extensible par operateurs de source, sink et echange,
- et capable de reutiliser sans changement majeur :
  - `flow.ic`,
  - `flow.bc`,
  - `flow.sinks_sources`,
  - `simulation.time`.

Autrement dit, la vraie independance vis-a-vis de MODFLOW doit se faire au niveau du backend numerique, pas au niveau du contrat metier expose aux autres briques d'HydroModPy.
