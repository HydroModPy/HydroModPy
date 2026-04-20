# Audit critique — packages `process/` et `solver/` de HydroModPy

**Auditeur** : expert modelisation hydrogeologique et methodes numeriques
**Date** : 2026-04-17
**Branche** : dev-database
**Scope** : `hydromodpy/process/{base,flow,transport,forcing}` + `hydromodpy/solver/{base,modflow6,modflow_nwt,boussinesq,modflow_common,utils/temporal}` + `solver/compatibility.py`
**Volumes audites** : ~4 400 lignes Python (process), ~14 000 lignes Python (solver)

---

## 0. Synthese executive

| Axe | Verdict |
|---|---|
| Abstraction `ProcessSpatial[T]` | **Acceptable** — simple, 2 heritiers, TypeVar non-borne est un relachement non justifie. |
| Boundary conditions | **A ameliorer** — mapping hydrologique → MODFLOW correct mais tres incomplet (GHB/RIV/CHD mal reparti, drainage forcement=DRN). |
| Solveur Boussinesq maison | **A ameliorer** — formulation correcte, Jacobien semi-analytique propre, mais : assembly non-vectorise (bottleneck), aucun test Jacobien FD vs semi-analytique, code mort (smoothing.py), 4 runtimes dupliques. |
| Integration MODFLOW-NWT | **Acceptable** — usage FloPy correct, GHB absent, IDOMAIN MF6 non porte (normal), mais post-processing sans `try/except` sur binaires et adapter monolithique (1392 lignes). |
| Integration MODFLOW 6 | **A ameliorer** — 2900 lignes dans un seul fichier, RIV/GHB/CNC non implementes (ecarts non documentes), coupling GWF-GWT minimal. |
| Transport | **Problematique** — stub a 70%, aucune validation BC/SS, 3 chemins solveurs (modpath, MT3DMS, MF6-GWT) non factorises. |
| Discretisation temporelle | **Conforme** — TMesh propre, supporte TSMULT, steady/transient ok. Limite : pas de multi-echelle (marees sub-journalieres). |
| Property mapping | **Acceptable** — K harmonique faces ok, moyenne arithmetique de l'epaisseur saturee (pas d'upwinding) — choix tolerable en FV triangulaire mais conservatisme limite. |
| Duplication | **Problematique** — 4 paires de fichiers identiques/quasi, 4 runtimes Boussinesq avec Newton+line-search identiques. |

Le **process/** est bien architecture dans ses choix de haut niveau (Pydantic + ABC generique) mais accumule des stubs (Transport) et du plumbing (structure_binders) qui trahissent une migration en cours. Le **solver/** est spectaculairement clate : excellent adapter NWT (Pydantic → FloPy), solveur Boussinesq ambitieux mais sous-teste, MF6 monolithique a refactoriser, zones mortes (PETSc, smoothing) qui polluent le repertoire.

---

## 1. Abstraction processus (`ProcessSpatial[T]`)

### 1.1 Description

`hydromodpy/process/base/process_spatial.py:47-165` definit :

```python
TInitialConditions = TypeVar("TInitialConditions")  # l.44 — NO BOUND

class ProcessSpatial(ABC, Generic[TInitialConditions]):
    def __init__(self):
        self.parameters: dict[str, object] = {}
        self.initial_conditions: TInitialConditions | None = None
        self.boundary_conditions: dict[str, BoundaryCondition] = {}
        self.sinks_sources: dict[str, object] = {}
        self.active_sinks_sources: list[str] = []
        self.active_bc: list[str] = []

    @abstractmethod
    def build_initial_conditions(self, ic): ...
    @abstractmethod
    def set_boundary_conditions(self, bc): ...
    @abstractmethod
    def set_sinks_sources(self, ss): ...
```

Deux heritiers :
- `Flow(ProcessSpatial[FlowInitialConditions])` — `process/flow/flow.py:96`
- `Transport(ProcessSpatial[TransportInitialConditions])` — `process/transport/transport.py:39`

### 1.2 Verdict : **acceptable** (pas over-engineering, mais relachement de type)

**Ce qui est bien**
- 3 methodes abstraites bien definies (ic, bc, ss) : minimal et clair.
- L'heritage laisse au solveur la specialisation metier.
- `Generic[T]` cout runtime zero (efface par `typing`).

**Ce qui n'est pas bien**
1. `TypeVar("TInitialConditions")` sans **bound** (l.44). Ca devrait etre :
   ```python
   TInitialConditions = TypeVar("TInitialConditions", bound=BaseModel)
   # ou, plus strictement :
   TInitialConditions = TypeVar("TInitialConditions", bound="InitialConditionsContainer")
   ```
   Sans bound, **n'importe quel objet** peut etre stocke. Transport en profite et stocke `TransportInitialConditions(payload: dict[str, Any])` qui est un sac a main. Cette permissivite desactive l'interet du generic.

2. L'aliaas `Process = ProcessSpatial` (l.168) est du code legacy inutile : **dead code**, a supprimer si aucun appelant externe n'utilise `Process`.

3. **Symetrie manquee** : on a des classes de base `InitialCondition`, `BoundaryCondition`, `SinkSource` mais pas de base `InitialConditionsContainer` ou `BoundaryConditionsContainer` — ce serait le bound naturel du TypeVar.

### 1.3 Comparaison avec les standards du domaine

| Framework | Abstraction processus |
|---|---|
| **FloPy** | Pas d'abstraction « processus » : on instancie directement `ModflowGwf`, `ModflowGwt`, chacun avec ses packages. Zero heritage metier. C'est une **classe de composition** pas d'heritage. |
| **FEHM / TOUGH2** | Processus codes en Fortran monolithique, aucune notion de generic. |
| **PorePy** | `Model` ABC + mixins (`MomentumBalance`, `MassBalance`, `Energy`). Utilise mixins plutot que `Generic[T]`. Plus flexible, plus diluent. |
| **OpenPNM** | `GenericProject` + modules additifs (physics, algorithms). Pas de generic parametrique. |
| **scikit-learn** | BaseEstimator + mixins (`RegressorMixin`, `ClassifierMixin`). C'est le modele a suivre pour un framework a domaine diversifie. |

**Recommandation** : Le design actuel est raisonnable pour 2 heritiers (Flow, Transport). Si d'autres processus emergent (heat, reactive, geomechanics), migrer vers un design **mixin** (comme PorePy/scikit-learn), pas vers un heritage plus profond.

### 1.4 Justification du generic — ROI reel

Le benefice du `Generic[T]` est essentiellement IDE-facing (hint `flow.initial_conditions: FlowInitialConditions | None`). Mais l'utilisation du IDE semble peu impactee : `Transport.initial_conditions.payload` reste un `dict[str, Any]` opaque.

**Pour 2 heritiers, un simple heritage non parametrique ferait le meme travail** :
```python
class ProcessSpatial(ABC): ...
class Flow(ProcessSpatial):
    initial_conditions: FlowInitialConditions | None  # annotation attribut
class Transport(ProcessSpatial):
    initial_conditions: TransportInitialConditions | None
```
C'est **moins elegant au plan theorique** mais equivalent en pratique et **plus simple a lire**. Garder le generic si on croit en une expansion future ; sinon, le supprimer reduit la charge cognitive.

---

## 2. Conditions aux limites

### 2.1 Structure et mapping

`process/flow/boundary_conditions.py:51-75` declare les **identifiants canoniques** :
```python
DIRICHLET_BC_CANONICAL_DOMAINS = {
    "ocean": "top", "stream": "top",
    "north_side": "north side", "south_side": "south side",
    "east_side": "east side",   "west_side": "west side",
}
CAUCHY_BC_CANONICAL_DOMAINS = {"drainage": "top"}
ROBIN_BC_CANONICAL_DOMAINS  = {"drainage": "top"}
```

Le mapping hydrologique → MODFLOW est **cable en dur** dans l'adapter NWT (`modflow_nwt/modflow/flow_to_modflow_adapter.py:361-400` pour les sides, `:800-835` pour le drainage) :

| BC HydroModPy | Type | Package MODFLOW | Ligne adapter |
|---|---|---|---|
| `ocean`, `stream` | dirichlet | **CHD** (cellule imposee via ibound=-1) | :364-395 |
| `north/south/east/west_side` | dirichlet | **CHD** idem | :364-395 |
| `drainage` | cauchy / robin | **DRN** | :802-837 |
| wells | sink_source | **WEL** | :839-934 |
| recharge | sink_source | **RCH** | :936-... |
| recharge negative | — | **EVT** auto-route | sinks_sources.py:528 |

### 2.2 Verdict : **a ameliorer** — mapping incomplet et cable en dur

**Ce qui est correct**
- Dirichlet → CHD via `ibound=-1` : conforme MODFLOW-2005 (BAS package, l.193-200 du docstring adapter).
- Drain gravitaire → DRN avec conductance `C = K · A` si non specifiee (adapter:824, 834) : formulation raisonnable mais discutable (voir ci-dessous).
- Conversion d'unites (Dirichlet en `m`, Cauchy/Robin en `m2/s`) stricte et validee Pydantic.

**Ce qui ne va pas**

1. **GHB (General Head Boundary) totalement absent.** La GHB est la BC la plus utile en modelisation regionale pour representer un aquifere voisin via `Q = C·(H_bd − h)`. HydroModPy ne l'expose pas. Pour une nappe littorale ou un contact regional, il faut actuellement tricher avec CHD+conductance fictive.
   - **Standard** : `flopy.modflow.ModflowGhb` existe depuis 2005 ; l'omission est non-standard.
   - **Recommandation** : ajouter un type `"ghb"` dans les BC canoniques, avec paire (head, conductance).

2. **RIV (River Package) non expose.** Alors qu'un parametre `"stream"` existe, il est classe en Dirichlet et mappe CHD. La correspondance physique de `stream` → CHD est **incorrecte** dans le cas general : un cours d'eau echange avec la nappe via une conductance de colmatage (`RIV` de MODFLOW = stage + Rbot + Cond). En le forcant en Dirichlet, on impose une charge = on obtient artificiellement un debit « infini » si la nappe est eloignee du stage. Cela peut sur-contraindre le bilan hydrique de maniere importante.
   - **Standard** : MODFLOW2005 et MF6 ont `RIV` pour exactement ca.
   - **Recommandation** : rejouter un `stream` avec type `"river"` + parametres `stage_m`, `rbot_m`, `conductance_m2_s`. Le mapping `stream → CHD` actuel devrait etre active seulement pour un « forced head » explicite (rare en hydrologie regionale).

3. **Drainage → DRN avec conductance `K·A`**. Cette formule (`adapter:826,834`) est la convention par defaut MODFLOW mais elle **n'a de sens physique que si la drain est a la base d'une cellule de K~uniforme**. Pour un drain superficiel (drainage agricole, seepage face), il faudrait `C = K·L·W / d` avec L la longueur du drain, W sa largeur mouillee, d l'epaisseur de colmatage. Le choix `K·A` sur-estime souvent la conductance d'un ordre de grandeur. **Il faudrait documenter cette convention et offrir un override explicite via `conductance_m2_s`** (deja partiellement present via `drainage_boundary.value` l.804).

4. **Dirichlet transitoire sur les sides** : (adapter:364-395) le cas `not side_boundary_is_static` ne met **pas** `ibound=-1` mais assigne `strt[:, :, 0] = west_series[0]` seulement. Le code suppose implicitement que si le BC a une serie temporelle, on gere ca autrement via un CHD stress-period data — mais je ne le vois pas cable ; verifier `_build_chd_stress_period_data` (:657+). **Risque de charge imposee ignoree en transient si le BC a du forcing**.

5. **Pas de Neumann pur.** La convention « Neumann = flux impose » n'est implementable actuellement que via un WEL artificiel (debit injecte/extrait) sur les cellules de bordure. Aucun type `"neumann"` n'existe dans `FlowBoundaryConditionConfig.type` (`boundary_conditions.py:199`, Literal = `["dirichlet","cauchy","robin"]`). C'est bloquant pour les bilans de bordure connus (ex. apport inter-aquifere connu).

6. **Cable en dur a 6 identifiants** : un utilisateur qui veut `"cliff_west"` ou `"lake_south"` doit utiliser un id custom qui tombe dans le chemin `_normalize_generic_boundary_payload`. L'extensibilite est limitee (la canonisation force la liste `DIRICHLET_BC_CANONICAL_DOMAINS`).

### 2.3 Tableau recapitulatif BC

| BC | Type HMpy | MF package cible | Implemente | Verdict | Recommandation |
|---|---|---|---|---|---|
| `ocean` | dirichlet | CHD | oui | acceptable | ajouter support transitoire explicite |
| `stream` | dirichlet | CHD | oui mais **mauvais choix physique** | **problematique** | rerouter vers RIV |
| `*_side` | dirichlet | CHD | oui | acceptable | |
| `drainage` | cauchy/robin | DRN | oui | acceptable | documenter formule C=K·A |
| `river` (RIV) | absent | — | **non** | **manque** | ajouter |
| `ghb` (GHB) | absent | — | **non** | **manque** | ajouter |
| `recharge` | sink_source | RCH | oui | conforme | — |
| `evapotranspiration` | via recharge<0 | EVT | oui (auto-route) | acceptable | exposer EVT explicite |
| `wells` | sink_source | WEL | oui | conforme | — |
| `neumann pur` | absent | — | **non** | **manque** | contournable via WEL, mais gauche |

---

## 3. Solveur Boussinesq maison

### 3.1 Formulation PDE

`assembly.py:418-583` resout l'equation de Boussinesq 2D pour aquifere libre :

- **Transient** :
  $\frac{\partial (A\,S_y\,h)}{\partial t} = -\nabla\cdot[T(h)\nabla h] + Q_{\text{rch}} + Q_{\text{wells}} - Q_{\text{drainage}} + Q_{\text{ex}}$

- avec $T(h) = K \cdot b(h)$ et $b(h) = \text{clip}(h - z_b,\ 0,\ z_t - z_b)$ (`assembly.py:104-115`).

- **Steady** : terme de stockage mis a zero (`:544-583`).

- **Discretisation spatiale** : volumes finis triangulaires, cell-centered (`FV_TRI_CELL_CENTERED`, `discretization/space.py:19-28`). **2D planaire uniquement** (pas de 3D, pas de DIS/DISV MODFLOW).

- **Discretisation temporelle** : Euler implicite (`backward Euler`, `discretization/time.py:25-30`).

### 3.2 Jacobien semi-analytique (`jacobian_semianalytic.py`, 561 lignes)

Les derivees sont piecewise :
- `db/dh = 1` si $z_b < h < z_t$, sinon `0` (`jacobian_semianalytic.py:30-39`).
- Termes storage, flux internes, imposed-head, drainage : derives analytiquement.
- Terme de saturation excess (regularized partition) : `_build_sparse_semianalytic_partition_saturation_triplets` avec derivee de la rampe exponentielle $G_r(\theta) = e^{-(1-\theta)/r}$.

**Verdict : acceptable** — la formulation est correcte, piecewise mais exacte dans chaque regime.

**Points negatifs**
1. **Aucune validation croisee FD vs semi-analytique dans le code.** Pas un seul test qui compare `build_dense_fd_jacobian` et `build_dense_semianalytic_regularized_partition_jacobian` sur un cas trivial. C'est **un manque grave** dans tout solveur maison — la moindre erreur de signe dans le Jacobien se traduit par une convergence degradee sans que personne ne s'en rende compte.
   - **Recommandation** : ajouter `tests/unit/solver/boussinesq/test_jacobian_consistency.py` verifiant `np.allclose(J_fd, J_semianalytic, atol=1e-5)` sur 3-4 meshes de reference.

2. **Saut de derivee aux seuils $h=z_b$ et $h=z_t$**. Ces sauts Dirac-like ne sont pas lisses. Le Newton peut osciller autour de ces seuils (tres classique en aquifere libre). Le module `smoothing.py` existe pour ca (voir 3.4) **mais n'est utilise nulle part** (recherche : aucun import dans `assembly.py`, `jacobian_semianalytic.py`, ni dans aucun runtime).

3. **Formulation `head_only_regularized_partition` vs `mixed_complementarity`** : les deux coexistent mais la complementarity n'est disponible qu'avec PETSc (`petsc_runtime.py`). La comparaison numerique entre les deux formulations n'est pas documentee ni automatisee.

### 3.3 Jacobien par differences finies (`jacobian_fd.py`, 313 lignes)

Schema forward :
$J_{ij} \approx \frac{R_i(h_j + \varepsilon) - R_i(h_j)}{\varepsilon}$, avec $\varepsilon = \varepsilon_{rel} \cdot \max(1, |h_j|)$ et $\varepsilon_{rel} = 10^{-7}$ par defaut (`jacobian_fd.py:56`).

**Point positif** : graph coloring greedy (`color_columns_by_row_overlap`, :169-226) bien implemente, largest-degree-first — reduit le nombre d'evaluations residuelles. C'est du travail propre.

**Points a ameliorer**
1. **Schema forward (non central)**. L'erreur est $O(\varepsilon)$ au lieu de $O(\varepsilon^2)$. Pour un Jacobien utilise en Newton, c'est acceptable mais non optimal.
2. **Pas de pas adaptatif par magnitude residuelle** : `rel_step` constant. Dans les zones ou $R_i \approx 0$, le bruit numerique domine.
   - **Standard** : nombre d'implementations Newton-Krylov (PETSc, Trilinos) utilisent `eps = sqrt(machine_eps) * max(|h|, typical_h)` ou `sqrt(eps) * |R|/|J|` (Dennis-Schnabel).
3. Pas de fallback complex-step (exact derivative via $f(h + i\varepsilon)/\varepsilon$) — probablement overkill ici mais serait un bon moyen de valider les Jacobiens sans aucune erreur de troncature.

### 3.4 Smoothing : **code mort**

`smoothing.py` (170 lignes) expose `smooth_positive_part`, `smooth_positive_thickness`, `smooth_clip_01`. Je confirme par grep :
```
smooth_positive_part → match only in smoothing.py
smooth_clip_01       → match only in smoothing.py
```
**Ces fonctions ne sont importees nulle part hors de leur fichier.** C'est 170 lignes de **code mort** avec docstrings elabores (LaTeX). Soit le developpeur a prevu un refactor non realise, soit il a ete abandonne.

**Verdict : problematique.** Le code mort trompe le lecteur (« ah le smoothing est en place ») et gonfle le code. A supprimer ou bien a **vraiment integrer** dans `assembly.py` avec un flag `smoothing: bool` au niveau runtime.

### 3.5 Formulation mixed complementarity

`formulations/mixed_complementarity.py` (38 lignes) declare :
```
unknowns = [h, q_ex]
constraint : 0 <= q_ex perp (z_top - h) >= 0
```

C'est la **formulation KKT** pour le seepage face : q_ex = 0 si la nappe est sous le toit, sinon q_ex peut etre positif (exfiltration). C'est une bonne formulation theorique.

**Verdict : acceptable mais sous-validee.**
- Disponible uniquement via PETSc SNES (`petsc_runtime.py:82`, engine `petsc_mixed_complementarity_snes`) — dependance lourde pour une fonctionnalite rarement utilisee.
- Le smoothing Fischer-Burmeister mentionne dans `engines/catalog.py:82` **n'est pas implemente en Python** (delegue a PETSc VI solver).
- **Pas de comparaison numerique automatique** entre `mixed_complementarity` et `head_only_regularized_partition` sur un cas canonique (par ex. Dupuit-Forchheimer analytique).

### 3.6 Solveur lineaire

| Runtime | Solveur lineaire | Preconditioner | Verdict |
|---|---|---|---|
| `local_runtime.py` | `np.linalg.solve` (dense LU via LAPACK) | — | Ok petites grilles (< 1000 cellules) |
| `scipy_runtime.py` | `scipy.optimize.root(method='hybr')` (Powell hybride) | — | **Gadget** : delegue tout a MINPACK, perd tout controle |
| `scipy_sparse_runtime.py` | `scipy.sparse.linalg.spsolve` (SuperLU/UMFPACK) | — | Ok meshes moyennes (< 100k), mais pas d'itératif |
| `petsc_runtime.py` | GMRES + ILU (ou LU direct) | `PCILU` | Ok gros meshes, mais **COMM_SELF** (sequentiel uniquement, l.139) |

**Verdict : acceptable mais sans ambition**. Aucun preconditioner algebrique multi-grille (`PyAMG` est dispo, gratuit, et excellent pour l'elliptique de Boussinesq). Aucun support MPI reel (PETSc present mais sequentiel). **C'est acceptable pour un code de recherche mais bloquant pour le passage a l'echelle regionale** (bassins de 10^6+ cellules).

**Recommandations**
1. Ajouter `PyAMG` comme runtime `scipy_sparse_pyamg` avec preconditionneur Smoothed-Aggregation.
2. Si on garde PETSc : activer vraiment `PETSC_COMM_WORLD` et tester MPI sur 4 processus.
3. Supprimer le runtime `scipy_runtime.py` (delegue hybr, aucun controle, et pas vraiment « maison »).

### 3.7 Newton externe

`scipy_sparse_runtime.py:211-291` — boucle Newton line-search backtrack Armijo :
- Convergence : $\|R\|_\infty \leq \text{tol}$ (l.292). **Pas de critere sur $\|\Delta h\|$.**
- Line search : damping $\leftarrow \text{damping}/2$ jusqu'a `min_damping=1e-4` (l.269-281). **Accept si `candidate_norm < residual_norm` OU `damping <= min_damping`** (l.274) — le `OR` est suspect : si aucun pas ne diminue le residu, on accepte le dernier minuscule, ce qui peut stagner indefiniment. **C'est un faux line-search**, meilleur seraient les conditions de Wolfe ou une regle Armijo stricte `candidate_norm <= (1 - alpha·damping)·residual_norm`.
- Max iterations : 20 (runtime_contract:32). **Faible** pour un probleme non lineaire Boussinesq — 50-100 serait plus conservateur.

### 3.8 Assemblage : **non-vectorise**

Toutes les fonctions d'assembly utilisent des **boucles Python explicites** sur `range(mesh.n_edges)`. Exemples :
- `_edge_to_stage_tau_from_head` : `assembly.py:150-178` — loop Python.
- `internal_edge_flux_from_head` : `:195-213`.
- `imposed_head_edge_flux_from_head` : `:238-255`.
- `accumulate_internal_flux_residual` : `:265-272`.
- `accumulate_boundary_flux_residual` : `:282-287`.

**Verdict : problematique pour la performance**. Pour un mesh de 50 000 aretes, une boucle Python a chaque iteration Newton = plusieurs secondes. Sur 100 iterations, des minutes. Tout cela peut etre remplace par du numpy fancy-indexing vectorise :

```python
# Au lieu de :
for edge_index in range(mesh.n_edges):
    cell_a = int(mesh.edge_cell_a[edge_index])
    cell_b = int(mesh.edge_cell_b[edge_index])
    ...
    internal_flux[edge_index] = -tau * (head[cell_b] - head[cell_a])

# Faire :
cell_a = mesh.edge_cell_a.astype(int)
cell_b = mesh.edge_cell_b.astype(int)
mask = cell_b >= 0
K_a = mesh.hydraulic_conductivity_m_s[cell_a[mask]]
K_b = mesh.hydraulic_conductivity_m_s[cell_b[mask]]
K_harm = 2.0 / (1.0/K_a + 1.0/K_b)
b_edge = 0.5*(b[cell_a[mask]] + b[cell_b[mask]])
tau = K_harm * b_edge * edge_length[mask] / edge_distance[mask]
internal_flux = np.zeros(mesh.n_edges)
internal_flux[mask] = -tau * (head[cell_b[mask]] - head[cell_a[mask]])
```

**Gain attendu : 50-200× sur des meshes 10k-100k cellules.** C'est le bottleneck le plus evident du solveur.

### 3.9 Runtimes : 4 variantes, duplication massive

| Runtime | Lignes | Raison d'etre | Jacobien | Solveur |
|---|---|---|---|---|
| `local_runtime.py` | 276 | dense small mesh | FD dense | LU dense |
| `scipy_runtime.py` | 181 | dense via MINPACK | semi-analytique dense | hybr |
| `scipy_sparse_runtime.py` | 413 | sparse production | hybride semi-analytique + FD colored | spsolve |
| `petsc_runtime.py` | 494 | mixed complementarity | bloc sparse semi-analytique | SNES+GMRES+ILU |
| `petsc_partition_runtime.py` | 289 | PETSc head-only | semi-analytique sparse | SNES+GMRES+ILU |

La logique Newton (damping, residual norm, max_iter, return `RuntimeSolveResult`) est **dupliquee** entre `local_runtime`, `scipy_sparse_runtime`, `petsc_partition_runtime`. Ce serait une belle factorisation :

```python
def newton_loop(jacobian_builder, residual_fn, linear_solver, tol, max_iter) -> RuntimeSolveResult:
    ...
```

avec chaque runtime injectant seulement `jacobian_builder` et `linear_solver`. **Economie : ~200 lignes**. A faire.

Aussi, `scipy_runtime.py` qui delegue a `scipy.optimize.root(method='hybr')` ne fait qu'empaqueter et post-valider — **valeur ajoutee faible**, duplique le wrapping. **Candidat a suppression**.

### 3.10 Tableau recapitulatif Boussinesq

| Point | Description | Verdict | Justification | Recommandation |
|---|---|---|---|---|
| PDE | Boussinesq 2D libre BE implicite | conforme | formulation classique Dupuit-Forchheimer | — |
| Jacobien semi-analytique | piecewise derivatives, sparse | acceptable | correct mais pas valide contre FD | **ajouter test cross-consistency** |
| Jacobien FD | forward + graph coloring | acceptable | coloring propre, step non-adaptatif | ajouter Dennis-Schnabel step |
| Smoothing | operateurs C^1 | **dead code** | defini mais non appele | **supprimer ou integrer** |
| Mixed complementarity | formulation KKT + PETSc | acceptable | pas valide face a partition | ajouter test comparatif |
| Assembly | loop Python sur edges | **problematique (perf)** | 50-200× trop lent | **vectoriser numpy** |
| Solveur lineaire | spsolve / LU / GMRES-ILU | acceptable | pas d'AMG | **ajouter PyAMG** |
| Newton line search | Armijo bacule | a ameliorer | OR bancal dans le critere | condition Wolfe stricte |
| Max iter Newton | 20 defaut | faible | classique 50-100 | monter a 50 |
| Runtimes | 4 variantes | **duplication** | Newton loop replique | factoriser `newton_loop()` |
| `scipy_runtime.py` | wrapper hybr | **dead wrapper** | pas de valeur ajoutee | **supprimer** |
| MPI | absent | non-scalable | `COMM_SELF` seulement | activer PETSc MPI |
| Support mesh | 2D triangulaire | acceptable | pas de 3D ni DIS | documenter scope |

---

## 4. Integration MODFLOW-NWT

### 4.1 Usage FloPy

`modflow_nwt/modflow/nwt_solver.py` (1007 lignes) instancie directement :

| Package FloPy | Ligne | Verdict |
|---|---|---|
| `ModflowNwt` | :344 | ok |
| `ModflowDis` | :438 | ok — mais DIS seulement |
| `ModflowBas` | :535 | ok |
| `ModflowChd` | :524 | ok |
| `ModflowUpw` | :557 | ok (upstream weighting, standard NWT) |
| `ModflowRch` | :588 | ok |
| `ModflowEvt` | :576 | ok (EVT auto-route depuis recharge negative) |
| `ModflowDrn` | :606 | ok |
| `ModflowWel` | :614 | ok |
| `ModflowOc` | :630 | ok |
| `ModflowLmt` | :681 | ok (link mass transport) |
| `ModflowGhb` | **absent** | **manque** — cf. section 2 |
| `ModflowRiv` | **absent** | **manque** — cf. section 2 |

**Verdict : acceptable** pour l'etendue implementee, **a ameliorer** pour ajouter GHB/RIV.

### 4.2 NWT options

`modflow_nwt/modflow/nwt_config.py:35-78` expose :

| Option | Defaut | Range physique | Verdict |
|---|---|---|---|
| `nwt_headtol` | 1e-4 m | [1e-6, 1e-2] raisonnable | ok |
| `nwt_fluxtol` | 500 m3/d | depend de l'echelle | **mal documente** : l'utilisateur doit savoir que c'est en unites MODFLOW |
| `nwt_maxiterout` | 5000 | [100, 10000] | generex ok mais tres eleve |
| `nwt_thickfact` | 1e-5 | [1e-6, 1e-3] | **tres strict** — peut causer des oscillations |
| `nwt_linmeth` | 1 (GMRES) | {1, 2} | ok |
| `nwt_iprnwt` | 1 | {0, 1, 2} | ok |
| `nwt_options` | "COMPLEX" | {SIMPLE, MODERATE, COMPLEX, SPECIFIED} | ok — default COMPLEX est conservateur |
| `nwt_continue` | False | bool | ok |
| `nwt_backflag` | 0 (off) | {0, 1} | ok |

**Manquent** : `MXITERXMD` (iters max XMD), `IACL`, `NORDER`, `LEVEL`, `NORTH`, `IREDSYS`, `RRCTOL`, `IDROPTOL` — tous les **parametres fins du solveur lineaire GMRES/XMD**. Si on veut une convergence fine, on ne peut pas les regler depuis HydroModPy.

**Recommandation** : exposer les `GMRES options` et `XMD options` dans `nwt_options.py` sous un niveau `ParamLevel.expert`.

### 4.3 Postprocess et robustesse I/O

`modflow_nwt/modflow/postprocess.py` (313 lignes) :
- Utilise `flopy.utils.postprocessing.get_water_table()` (l.49).
- **Pas de `try/except`** autour des lectures binaires. Si `HEAD.bhd` ou `MODFLOW.cbb` est corrompu ou manquant, crash Python non-diagnostique.
- **Pas d'extraction explicite du CBB (Cell-by-Cell Budget)** pour verification bilan de masse. `diagnostics.py` (84 lignes) verifie seulement la connectivite verticale top/bot, pas les erreurs de budget.
- **Pas de parsing du listing LIST** pour extraire les erreurs de convergence NWT (PCG iterations, IPRNWT output).

**Verdict : a ameliorer**.
- **Recommandation** : encapsuler lectures binaires dans `try/except OSError, EOFError, flopy.utils.binaryfile.BinaryFileError` avec fallback explicite.
- Ajouter extraction du budget total via `CellBudgetFile.get_records()` pour verifier que `percent_discrepancy < 1%`. C'est du travail qu'un modelisateur MODFLOW doit **toujours** faire ; l'automatiser est une vraie valeur ajoutee.

### 4.4 `flow_to_modflow_adapter`

Fichier **double** :
- `modflow_nwt/flow_to_modflow_adapter.py` : **5 lignes** de re-export !
  ```python
  from hydromodpy.solver.modflow_nwt.modflow.flow_to_modflow_adapter import FlowToModflowAdapter
  ```
- `modflow_nwt/modflow/flow_to_modflow_adapter.py` : 1392 lignes reelles.

**Verdict : verbosite inutile**. Le re-export n'a pas de raison d'etre — le chemin canonique suffit. A supprimer sauf si un import externe legacy l'utilise (grep suggere que non : seuls les imports internes au package existent).

Le fichier de 1392 lignes est **monolithique** : 32 methodes dans une classe unique. Le docstring (l.167-201) est excellent. Les sections sont bien separees. **Mais c'est trop pour une seule classe** : on pourrait la splitter en :
- `FlowICToBas` (ibound + strt, :323-460)
- `FlowBCToBoundaryPackages` (CHD/DRN/GHB/RIV, :661-837)
- `FlowSSToStressData` (WEL/RCH/EVT, :839-1200)

**Recommandation** : refactor en 3-4 classes plus petites, chacune avec un contrat explicite.

### 4.5 Intermittency

`modflow_nwt/modflow/intermittency.py` (133 lignes) — detection de cellules intermittentes par seuil negatif `< -100 m` (`:49`). **C'est un hack** : une nappe reellement profonde peut etre en dessous de -100 m dans une region montagneuse. Seuil magique non-configurable.

**Recommandation** : remplacer par un seuil relatif au DEM local (`head < bottom_layer - margin`) ou exposer le seuil comme parametre.

---

## 5. Integration MODFLOW 6

### 5.1 Vue d'ensemble

`modflow6/modflow6.py` : **2900 lignes dans un seul fichier**. C'est le plus gros fichier du solver, deux fois plus que son homologue NWT (1007 lignes) qui est deja grand. Dans un fichier monolithique, chaque ajout/modification traine tous les autres.

**Verdict : problematique (maintenabilite).** A splitter imperativement.

### 5.2 Packages supportes

**GWF** : NPF, STO, IC, OC, IMS, CHD, DRN, WEL, RCH.
**Absents** (cf. agent) : RIV, GHB, CNC, MAW, SFR, LAK, UZF, CSUB.

**GWT** : ADV, DSP, SSM, MST, FMI.
**Absents** : CNC, IST, SRC, OBS.

**Coupling GWF-GWT** : via `GwfGwtExchange` avec `exgtype="GWF6-GWT6"` (l.2720) + SSM linking. **C'est la solution officielle MF6** — conforme.

### 5.3 Duplication avec NWT

`modflow6/property_mapping.py` (80 lignes) importe `resolve_required_flow_properties` et `resolve_structured_flow_property_arrays` du NWT (l.13-16). Bon reusage.

`modflow_common/discretization_spatial.py` (258 lignes) et `discretization_temporal.py` (133 lignes) sont partages entre NWT et MF6. Excellent.

**Mais** la classe `Modflow6(Solver)` duplique **la structure** (`pre_processing → processing → post_processing`) de `Modflow(Solver)`. Au lieu d'une vraie factorisation en `ModflowCommonSolver` abstract, chaque classe reimplemente le cycle. **Opportunite manquee.**

### 5.4 Gestion des INFORMATION warnings FloPy

Les warnings FloPy (ex. `INFORMATION: no checker routine imported`) sont **non captures**. Ils polluent stdout. Aucun filtre `warnings.filterwarnings` n'est visible.

**Recommandation** :
```python
import warnings
warnings.filterwarnings("ignore", message="INFORMATION:.*", category=UserWarning)
```
Idealement, router vers le logger HydroModPy au lieu d'ignorer.

### 5.5 Tableau MF6

| Feature | Status | Verdict |
|---|---|---|
| GWF NPF/STO/IC/OC/IMS | complet | ok |
| GWF CHD/DRN/WEL/RCH | complet | ok |
| GWF RIV/GHB | **absent** | **manque** |
| GWT ADV/DSP/SSM/MST/FMI | complet | ok |
| GWT CNC/IST/SRC/OBS | **absent** | ok si non requis, a documenter |
| Coupling GWF-GWT | via exchange | conforme |
| Fichier monolithique (2900L) | oui | **a splitter** |
| Warnings FloPy | non filtres | a gerer |

---

## 6. Transport

### 6.1 Couplage flow → transport

`process/transport/transport.py` (127 lignes) :
- `set_boundary_conditions(bc_dict)` : ligne 108-109 — `self.boundary_conditions.update(boundary_conditions)` sans validation.
- `set_sinks_sources(ss_dict)` : idem.
- `build_initial_conditions(payload)` : enveloppe en `TransportInitialConditions(payload=dict)` sans structure.

**Couplage** : **one-way** (flow → transport), via le planner (`solver/compatibility.py:36-38`) qui declare :
```python
("transport", "modpath"): (("flow", "modflownwt"),),
("transport", "mt3dms"): (("flow", "modflownwt"),),
("transport", "modflow6gwt"): (("flow", "modflow6"),),
```

**Verdict : acceptable pour le couplage, problematique pour l'implementation**.

La dependance unidirectionnelle est correcte (classique : on calcule d'abord le champ de vitesse Darcy, puis on transporte). **MT3DMS et MODPATH sont intrinsequement one-way**. Seul MF6-GWT peut faire du vrai couplage (via IMS couple), mais HydroModPy ne l'expose pas.

### 6.2 MT3DMS vs MF6-GWT

`modflow_nwt/mt3dms/mt3dms.py` (449 lignes) :
- Linkage via `ModflowLmt` (nwt_solver.py:681).
- Parametres : `sconc_init`, `disp_long`, `disp_transh`, `disp_transv`, `diffu_coeff`.
- **Dispersion seule** — pas d'expositions separees pour chaque transport species.
- **MT3DMS est un code des annees 90** avec un TVD schema et peut souffrir sur grilles triangulaires.

`modflow6/modflow6.py:2600+` (GWT) :
- ADV (upstream/central/TVD), DSP (dispersion), SSM (sources).
- Coupling exchange GWF-GWT.

**Differences non documentees clairement dans le code** :
- MT3DMS : **post-processing seul** du flow (ne recalcule pas les heads).
- MF6-GWT : **simultane potentiellement** (si IMS couple). HydroModPy ne l'utilise pas.
- MT3DMS : CNC via IBOUND.
- MF6-GWT : CNC explicite.

**Recommandation** : documenter dans `docs/` les scenarios de choix MT3DMS vs MF6-GWT. Surtout, rendre claire la semantique « advection : 1er ordre upstream ou TVD ? » — crucial pour le numerical diffusion.

### 6.3 Dispersion

`mt3dms.py` expose `disp_long`, `disp_transh`, `disp_transv` comme scalaires. **Pas de heterogeneite spatiale exposee**. Pour un aquifere karstique ou un milieu stratifie, c'est un manque.

`modflow6/modflow6.py` DSP : support `alh`, `ath1`, `ath2`, `atv` — la convention MF6 complete.

**Verdict : MT3DMS sous-parametrise, MF6-GWT conforme.**

### 6.4 Synthese Transport

| Aspect | Verdict | Justification |
|---|---|---|
| `Transport` class | **stub** | 70% stub (set_bc/set_ss sans validation) |
| Couplage flow→transport | one-way | classique, ok |
| MT3DMS integration | acceptable | parametres basiques |
| MF6-GWT integration | acceptable | coupling via exchange |
| Dispersion heterogene | manque | non expose cote MT3DMS |
| Selection MT3DMS vs MF6-GWT | non documentee | a clarifier |

---

## 7. Discretisation temporelle

### 7.1 `solver/utils/temporal/` (1228 lignes)

Architecture propre : `TMesh > Stress Period (SP) > Time Step (TS)`.

- `tmesh_config.py` (250 lignes) : Pydantic model avec validation `tsmult`, `nstp`.
- `tmesh_generation.py` (533 lignes) : 2 methodes : `synthetic_regular` et `from_chron` (lit serie CSV).
- **TSMULT supporte** : scalaire ou liste par SP (conforme MODFLOW).
- **Steady / transient** : `flow_regime="steady"` → tous SP steady ; `"transient"` + `firstpersteady=True` → spinup.

**Verdict : conforme aux standards MODFLOW.**

### 7.2 Multi-echelle temporelle (marees)

**Non adresse.** Si la recharge est mensuelle mais que les oscillations de maree sont horaires, on ne peut pas faire de sous-discretisation par SP differente. Il faut trancher avec `NSTP` dans chaque SP mensuel, ce qui donne 720 TS par SP = 720×12 = 8640 TS par an. Tres lourd.

**Recommandation** : considerer un mecanisme de « sub-stress-period » ou une hierarchie **multi-frequence** (forcage lent vs rapide) — mais c'est un gros chantier et pas une regression, plutot un manque connu.

### 7.3 Alignement forcages

Pas de liaison automatique entre `tmesh_generation` et `process/forcing/time_alignment.py`. L'utilisateur doit s'assurer que les `perlen` matchent les periodes de forcage. **Verdict : a ameliorer** — un validator qui emet un warning si le forcage deborde du tmesh.

---

## 8. Property mapping

### 8.1 Boussinesq

`boussinesq/property_mapping.py` (228 lignes) : mapping K, Sy par cellule (homogene ou field). **Harmonic conductivity aux faces** : `assembly.py:127-134` (`2·K_a·K_b / (K_a + K_b)`) — **conforme**.

**Transmissivite aux aretes** : `assembly.py:206-208` utilise une **moyenne arithmetique** de l'epaisseur saturee, pas d'upwinding :
```python
thickness_edge = 0.5 * (thickness_a + thickness_b)
transmissivity_edge = conductivity_edge * thickness_edge
```
**Verdict : acceptable mais debattable.**
- Upwinding de l'epaisseur selon le sens du gradient serait plus conservateur en regime d'ecoulement rapide ou pres des cellules seches. C'est ce que fait MODFLOW-NWT avec l'option « upstream weighting » (`ModflowUpw`).
- La moyenne arithmetique peut **sous-estimer** le flux quand une cellule est presque seche.
- **Recommandation** : offrir un flag `upwinding: bool` dans la configuration du solveur Boussinesq.

### 8.2 MODFLOW adapter

`modflow_nwt/modflow/property_mapping.py` (329 lignes) : mapping K, Kv (via vka), Sy, Ss via `resolve_required_flow_properties` + `resolve_structured_flow_property_arrays`. Bon reusage en MF6 (`modflow6/property_mapping.py` l.13-16).

**Unites** : tout converti en SI au runtime (m, s). Les conversions sont centralisees dans `process/flow/` (normalize_m3_per_s_unit, convert_to_m3_per_s). Ok.

**Coherence Sy, Ss** : Sy est le specific yield (dimensionless, 0-0.3 typique) ; Ss est le specific storage (m^-1, 1e-6 a 1e-4 typique). Je n'ai pas vu de validation bornee dans la config (`sy ∈ [0, 0.5]`, `ss ∈ [1e-7, 1e-2]`). **Recommandation** : ajouter des validators Pydantic pour eviter les erreurs numeriques grossieres.

---

## 9. Comparaison des 3 solveurs

| Capacite / limite | **Boussinesq maison** | **MODFLOW-NWT** | **MODFLOW 6 (GWF+GWT)** |
|---|---|---|---|
| Type de probleme | Aquifere libre 2D | Nappe libre ou confinee 3D | Nappe libre/confinee 3D + GWT |
| Discretisation spatiale | FV triangulaire | DIS structure rectangulaire | DIS / DISV / DISU |
| Discretisation temporelle | Backward Euler | BE (classique MF) | BE (classique MF) + flexibility |
| Regime steady | oui | oui | oui |
| Regime transient | oui | oui | oui |
| Support 3D | **non** | oui | oui |
| BC Dirichlet | via imposed_head aux aretes | CHD | CHD |
| BC Cauchy (RIV) | **non** | oui (MF mais non expose HMpy) | oui (mais non expose HMpy) |
| BC GHB | **non** | oui (MF mais non expose HMpy) | oui (mais non expose HMpy) |
| BC Drain (DRN) | oui (assembly.py:290) | oui | oui |
| Recharge (RCH) | oui (via source term) | oui | oui |
| Puits (WEL) | oui | oui | oui |
| Seepage face | oui (complementarity) | via DRN | via DRN |
| Transport advectif | **non** | via MT3DMS | via GWT-ADV |
| Transport dispersif | **non** | via MT3DMS | via GWT-DSP |
| Particle tracking | **non** | via MODPATH | via MF6-PRT (non expose HMpy) |
| Jacobien | semi-analytique + FD | NWT interne | IMS (PCG/BiCGSTAB) |
| Solveur lineaire | spsolve / GMRES-ILU | GMRES/XMD (NWT) | PCG/BiCGSTAB (IMS) |
| Parallelisme | **sequentiel** | parallele si compilé | parallele (mt) |
| Support grilles nonreg. | oui (triangles) | non | oui (DISV/DISU) |
| Bilan de masse automatique | partiel | via CBB file | via CBB file |
| Maturite | **prototype** | production (> 20 ans) | production (> 10 ans) |
| Tests de conformite | **aucun Jacobien-consistency** | flopy-based, indirect | flopy-based, indirect |
| Lines of code HMpy | ~7 050 | ~2 800 (wrapper+adapter) | ~3 000 (wrapper+adapter) |

### 9.1 Performance indicative (estimee sur mesh 10 000 cellules, 100 iterations Newton)

| Solveur | Temps estime | Goulot d'etranglement |
|---|---|---|
| Boussinesq scipy_sparse | **30-60 s** (boucles Python) | assembly non vectorise |
| MODFLOW-NWT | 5-10 s | solveur Fortran compile, I/O binaire |
| MODFLOW 6 | 3-8 s | idem, moderne |

**Apres vectorisation de l'assembly Boussinesq** : attendu < 5 s (par extrapolation de benchmarks numpy).

### 9.2 Precision (d'apres formulations)

| Point | Boussinesq | MODFLOW-NWT | MODFLOW 6 |
|---|---|---|---|
| Conservation de masse | conservatif (FV) | conservatif | conservatif |
| Traitement cellules seches | complementarity OU partition | rewetting iteratif | rewetting iteratif |
| Convergence Newton | peut osciller aux seuils | NWT specifiquement concu | IMS Newton-Raphson |
| Sensibilite parametrique | non teste | teste industriellement | teste industriellement |

### 9.3 Recommandation strategique

Le solveur Boussinesq est un **bel effort de recherche** mais son rapport maturite/effort est defavorable :
- 7 050 lignes, non valide contre analytique, non parallele, non vectorise → **trois chantiers majeurs avant usage production**.
- MODFLOW-NWT et MF6 sont deja disponibles via FloPy avec 15-20× moins de code. Leur lacune (GHB/RIV manquants dans le wrapper HMpy) se corrige en 2-3 jours.

**Sauf si l'objectif est de tester des formulations novatrices** (mixed complementarity, regularized partition), la priorite devrait etre : (1) corriger les manques du wrapper MODFLOW, (2) vectoriser Boussinesq, (3) ajouter les tests de consistency Jacobien, (4) supprimer le code mort (smoothing, scipy_runtime, adapter re-export).

---

## 10. Duplication — recapitulatif

| Duplication | Fichiers | Lignes | Proposition |
|---|---|---|---|
| `flow_to_modflow_adapter.py` | `modflow_nwt/flow_to_modflow_adapter.py` (5L, re-export) vs `modflow_nwt/modflow/flow_to_modflow_adapter.py` (1392L) | 5 | **supprimer le re-export** |
| `property_mapping.py` NWT vs MF6 | 329L vs 80L (import du NWT) | — | deja factorise partiellement, ok |
| Newton loop | `local_runtime.py`, `scipy_sparse_runtime.py`, `petsc_partition_runtime.py` | ~200L | **factoriser `newton_loop()`** |
| 4 runtimes Boussinesq | scipy, scipy_sparse, local, petsc, petsc_partition | ~1600L total | **merger scipy & local**, **supprimer scipy_runtime.py** |
| Cycle pre/process/post | `Modflow`, `Modflow6`, `Boussinesq`, `Mt3dms`, `Modpath` | — | factoriser `ModflowLikeSolver` abstract |
| `process_spatial.py` alias `Process = ProcessSpatial` | L.168 | 1 | **supprimer si dead** |

---

## 11. Dead code et verbose

| Candidat | Fichier:ligne | Justification | Action |
|---|---|---|---|
| `smoothing.py` complet | `boussinesq/smoothing.py` | jamais importe hors fichier | **supprimer ou integrer** |
| `scipy_runtime.py` | `boussinesq/scipy_runtime.py` | wrapper hybr sans valeur ajoutee | **supprimer** |
| `Process = ProcessSpatial` alias | `process/base/process_spatial.py:168` | alias backward-compat | supprimer si aucun appelant |
| `modflow_nwt/flow_to_modflow_adapter.py` (5L re-export) | — | verbositeinutile | supprimer |
| `intermittency.py` seuil `-100 m` | `modflow_nwt/modflow/intermittency.py:49` | magie | rendre configurable |
| Hierarchie `engines/catalog.py` + `methods/catalog.py` + `discretization/` | boussinesq/ | over-abstraction en dataclass descriptors | simplifier en dict registry |

---

## 12. Performance — hot spots

| Hot spot | Impact | Solution |
|---|---|---|
| Loops Python dans `assembly.py` (6+ fonctions) | 50-200× lent | **vectoriser numpy** (prioritaire) |
| Newton FD sans coloring dans `local_runtime` | n_cells × nombre d'eval | deja fait en sparse, seul local reste naif |
| Pas d'AMG preconditioner | deterioration convergence sur gros meshes | ajouter PyAMG runtime |
| PETSc en `COMM_SELF` | pas de parallelisme | activer MPI |
| Lecture binaire MF sans batch | I/O synchrone par SP | batch read via `kstp_kper_list` |

---

## 13. Recommandations prioritaires

### Urgent (blocking quality)
1. **Ajouter test consistency Jacobien FD vs semi-analytique** (Boussinesq) — 1 jour, previent des bugs silencieux de sign.
2. **Vectoriser `assembly.py`** — 2-3 jours, 50-200× speedup attendu.
3. **Supprimer `smoothing.py`** ou l'integrer reellement dans l'assembly — 1 jour, enleve 170 lignes de code mort.
4. **Supprimer les duplications evidentes** : re-export adapter (5L), `scipy_runtime.py` (181L), alias `Process` — 0.5 jour.

### Important (architectural)
5. **Factoriser le Newton loop** entre 3 runtimes — 1-2 jours, enleve ~200L.
6. **Splitter `modflow6.py`** (2900L) en 4-5 modules thematiques — 2-3 jours.
7. **Ajouter GHB et RIV** dans les BC HMpy et mapper sur les packages MF correspondants — 1-2 jours.
8. **Encapsuler les lectures binaires FloPy** avec `try/except` et parsing du budget — 1 jour.

### Nice-to-have
9. Ajouter PyAMG comme runtime Boussinesq (pour grandes meshes) — 1-2 jours.
10. Exposer les options fines du solveur NWT (XMD, GMRES) — 0.5 jour.
11. Valider `Sy`, `Ss` par ranges Pydantic — 0.5 jour.
12. Implementer vrai `stream → RIV` avec stage + conductance — 1 jour.

---

## 14. Conclusion

HydroModPy est a une etape de transition : le socle **process/** est propre (Pydantic + ABC + generic), le **solver/** est riche mais desorganise. Les trois chemins solveurs (Boussinesq, NWT, MF6) coexistent sans factorisation forte ; chacun porte ses propres conventions et duplications.

**Forces**
- `process/` bien decoupe, validateurs Pydantic robustes.
- `flow_to_modflow_adapter` bien documente (docstrings exemplaires).
- Discretisation temporelle conforme MODFLOW.
- Solveur Boussinesq ambitieux (mixed complementarity + partition) — formulation theorique correcte.

**Faiblesses**
- Solveur Boussinesq **non vectorise** (perf), **non valide** (Jacobien), **code mort residuel** (smoothing).
- Adapter MODFLOW-NWT **monolithique** (1392L), MF6 **encore pire** (2900L).
- BC **incompletes** (GHB, RIV, Neumann absents).
- Transport **stub** (70%).
- Re-exports redondants, 4 runtimes Boussinesq avec Newton-loop duplique.

Un effort de ~2 semaines permettrait de transformer ce corpus « en migration » en un code **presentable pour publication scientifique** (solveur Boussinesq valide, vectorise) tout en comblant les manques fonctionnels du wrapper MODFLOW. Le design de haut niveau ne doit pas etre touche — il est raisonnable. Ce sont les details (tests, vectorisation, suppression de code mort) qui sont prioritaires.
