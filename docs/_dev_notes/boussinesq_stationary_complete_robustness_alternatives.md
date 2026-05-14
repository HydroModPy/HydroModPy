# Boussinesq stationary complete robustness alternatives

Date: 2026-05-14

Statut: investigation experimentale ciblee. Les resultats ci-dessous ne
modifient pas le comportement par defaut de HydroModPy. Les chemins testes sont
des initialiseurs ou solveurs stationnaires exploratoires; seuls les chemins qui
reviennent au modele VI cible non regularise sont consideres comme candidats de
production.

## Executive summary

Cette passe a ajoute une matrice d'investigation stationnaire robuste:

- script: `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py`;
- sorties combinees: `docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_combined/`;
- diagnostics par cas/methode sous les dossiers `diagnostics/<case>/<method>/`;
- tests unitaires: `tests/unit/solver/test_boussinesq_stationary_robust_solver_matrix.py`.

Methodes testees:

- baselines: `vi_obstacle`, `petsc_regularized`, `scipy_sparse_regularized`, `complementarity`, `pseudo_transient_vi_then_steady_vi`, `drainage_continuation_vi`, `recharge_continuation_vi`;
- alternatives: `tspseudo_vi`, `tspseudo_vi_ssls`, `bounded_picard_lscheme`, `bounded_picard_lscheme_then_vi`, `bmin_continuation_vi`, `bmin_continuation_picard_then_vi`, `smooth_threshold_continuation`, `tspseudo_vi_with_bmin_continuation`, `vi_obstacle_ssls`, `saturated_thickness_variable_vi_prototype`.

Conclusion principale: les alternatives plus fondamentales testees ne donnent
pas encore une solution stationnaire completement robuste. Sur `site_01_k_high`,
les meilleurs chemins restent les chemins deja identifies:
`drainage_continuation_vi` et `pseudo_transient_vi_then_steady_vi`. Sur
`site_02_k_low`, le VI direct du code courant converge deja. Sur
`site_02_network`, aucune methode ne converge vers le modele cible final; le
meilleur progres cible est `tspseudo_vi`, qui descend le residu de `9.27` a
`5.43e-4` mais echoue encore par line search.

L'alternative la plus prometteuse pour investigation P1 est donc PETSc
TSPSEUDO + VI, non parce qu'elle converge deja, mais parce qu'elle change la
signature de `site_02_network` sans effondrement massif au fond. Elle doit etre
travaillee comme initialiseur cible avec diagnostics, pas promue telle quelle.

## Problem diagnosis

Les echecs stationnaires naturels restent caracterises par:

- degenerescence au fond: beaucoup de cellules proches de `z_bottom`, avec
  transmissivite tres faible;
- obstacle superieur ou drainage: changement brusque entre cellule libre,
  cellule contrainte et cellule drainee;
- drainage non lisse: terme `max(h - z_top, 0)`;
- active set instable: les cellules changent de regime pendant Newton;
- maillage naturel: petits elements, voisinages irreguliers, interfaces
  geologiques et rivieres contraintes;
- forte sensibilite au chemin d'initialisation.

Le cas `site_02_network` illustre deux signatures opposees:

- VI direct: residu `9.27`, environ `12865` cellules sous le fond;
- PETSc regularise: residu `8.00e-5`, seulement `113` cellules sous le fond,
  mais line search encore en echec et modele non cible.

Cela confirme que l'echec n'est pas seulement un nombre d'iterations insuffisant.
Le chemin vers l'ensemble actif compte autant que le residu stationnaire final.

## Baseline results

| case | method | converged | target final | residual | active bottom | active top | runtime s | usable as IC |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `site_01_k_high d00` | `vi_obstacle` | non | oui | `1.12e-3` | 820 | 0 | 3.1 | non |
| `site_01_k_high d00` | `pseudo_transient_vi_then_steady_vi` | oui | oui | `1.26e-7` | 72 | 32 | 4.2 | oui |
| `site_01_k_high d00` | `drainage_continuation_vi` | oui | oui | `3.90e-10` | 72 | 32 | 1.3 | oui |
| `site_01_k_high d01` | `vi_obstacle` | non | oui | `1.65e-4` | 824 | 0 | 11.0 | non |
| `site_01_k_high d01` | `pseudo_transient_vi_then_steady_vi` | oui | oui | `2.25e-8` | 71 | 0 | 3.8 | oui |
| `site_01_k_high d01` | `drainage_continuation_vi` | oui | oui | `5.30e-9` | 71 | 0 | 0.8 | oui |
| `site_01_k_high d001` | `vi_obstacle` | oui | oui | `1.06e-9` | 67 | 0 | 2.9 | oui |
| `site_02_k_low d00` | `vi_obstacle` | oui | oui | `9.26e-7` | 19 | 1599 | 11.9 | oui |
| `site_02_k_low d001` | `vi_obstacle` | oui | oui | `1.28e-9` | 19 | 0 | 7.4 | oui |
| `site_02_network` | `vi_obstacle` | non | oui | `9.27` | 12865 | 2 | 4.2 | non |
| `site_02_network` | `petsc_regularized` | non | non | `8.00e-5` | 114 | 0 | 147.0 | non |
| `site_02_network` | `pseudo_transient_vi_then_steady_vi` | non | oui | `9.30` | 3 | 2528 | 29.2 | non |
| `site_02_network` | `drainage_continuation_vi` | non | oui | `1.39e-1` | 12865 | 0 | 5.5 | non |

Lecture: les baselines deja presentes restent les seules methodes qui convergent
sur les cas compacts difficiles. Elles ne resolvent pas `site_02_network`.

## Alternative 1: PETSc TSPSEUDO + VI

Implementation:

- `method = "tspseudo_vi"` et `method = "tspseudo_vi_ssls"`;
- PETSc `TS.Type.PSEUDO`;
- formulation RHS experimentale `dh/dtau = -M^-1 R_steady(h)`;
- SNES interne borne avec `SNES.setVariableBounds`;
- variantes `vinewtonrsls` et `vinewtonssls`;
- diagnostics de pseudo-etapes persistants dans `stage_diagnostics.csv`.

Resultats:

| case | method | converged | residual | active bottom | active top |
|---|---|---:|---:|---:|---:|
| `site_01_k_high d00` | `tspseudo_vi` | non | `2.64e-3` | 0 | 0 |
| `site_01_k_high d00` | `tspseudo_vi_ssls` | non | `6.61e-4` | 812 | 0 |
| `site_01_k_high d01` | `tspseudo_vi` | non | `4.09e-5` | 831 | 0 |
| `site_01_k_high d001` | `tspseudo_vi` | non | `6.65e-5` | 831 | 0 |
| `site_02_k_low d00` | `tspseudo_vi` | non | `8.64e-5` | 19 | 1624 |
| `site_02_k_low d001` | `tspseudo_vi` | non | `4.52e-5` | 19 | 0 |
| `site_02_network` | `tspseudo_vi` | non | `5.43e-4` | 33 | 868 |

Forces:

- reduit fortement le residu de `site_02_network` par rapport au VI direct;
- evite l'effondrement massif au fond sur `site_02_network`;
- reste sur une formulation cible VI bornee.

Faiblesses:

- ne converge pas a la tolerance `1e-6`;
- pas meilleur que `drainage_continuation_vi` sur les cas compacts;
- `ssls` n'ameliore pas globalement la situation;
- necessite encore un vrai critere de steady-state TS et probablement une
  strategie de pas pseudo-temporel plus controlee.

## Alternative 2: Bounded Picard / L-scheme

Implementation:

- `method = "bounded_picard_lscheme"`;
- transmissivite figee a l'iteration precedente;
- stabilisation diagonale `L * area * Sy * (h_new - h_old)`;
- projection dans les bornes apres update;
- variante `bounded_picard_lscheme_then_vi` avec controle final VI cible.

Resultats:

| case | method | converged | residual | active bottom | active top |
|---|---|---:|---:|---:|---:|
| `site_01_k_high d00` | Picard -> VI | non | `7.24e-2` | 30 | 65 |
| `site_01_k_high d01` | Picard -> VI | non | `7.70e-3` | 67 | 0 |
| `site_02_k_low d00` | Picard -> VI | non | `9.64e-3` | 11 | 4606 |
| `site_02_k_low d001` | Picard -> VI | non | `9.58e-4` | 8 | 0 |
| `site_02_network` | Picard -> VI | non | `9.39e-2` | 6 | 5383 |

Forces:

- robuste informatiquement: pas d'echec brutal, diagnostics propres;
- peut produire des champs sans violation forte du fond sur certains cas.

Faiblesses:

- n'atteint pas le residu cible;
- la projection cree souvent de grands ensembles actifs au toit;
- ne produit pas encore un warm start qui permette au VI final de converger;
- la version actuelle est trop simple pour etre candidate de production.

## Alternative 3: b_min continuation

Motivation: tester explicitement l'hypothese "degenerescence au fond".

Implementation:

- `method = "bmin_continuation_vi"`;
- schedule `b_min = 5, 2, 1, 0.5, 0.1, 0.01, 0 m`;
- assemblage experimental avec epaisseur effective minimale pendant les etapes
  de continuation;
- controle final attendu a `b_min = 0`.

Resultats:

| case | method | converged | residual | active bottom | note |
|---|---|---:|---:|---:|---|
| `site_01_k_high d00` | `bmin_continuation_vi` | non | `1.13e-3` | 820 | proche VI direct |
| `site_01_k_high d01` | `bmin_continuation_vi` | non | `1.65e-4` | 824 | proche VI direct |
| `site_02_k_low d00` | `bmin_continuation_vi` | non | `1.87` | 12855 | degrade fortement |
| `site_02_k_low d001` | `bmin_continuation_vi` | non | `1.39e-1` | 12845 | degrade fortement |
| `site_02_network` | `bmin_continuation_vi` | non | `9.27` | 12865 | aucun gain |

Conclusion: cette implementation de continuation `b_min` n'aide pas. Elle peut
meme forcer le solveur vers une signature dominee par l'obstacle inferieur. La
degenerescence au fond reste une cause probable, mais ce chemin de continuation
n'est pas le bon remede en l'etat.

## Alternative 4: smooth thresholds

Motivation: tester si les kinks `max(h-z_bottom,0)` et `max(h-z_top,0)` causent
les line-search failures.

Implementation:

- `method = "smooth_threshold_continuation"`;
- smoothplus `0.5 * (x + sqrt(x^2 + eps^2))`;
- schedule `eps = 5, 2, 1, 0.5, 0.1, 0.01, 0 m`;
- modele final cible seulement a `eps = 0`.

Resultats:

| case | converged | residual | active bottom | active top |
|---|---:|---:|---:|---:|
| `site_01_k_high d00` | non | `5.89e-4` | 1219 | 0 |
| `site_01_k_high d01` | non | `4.02e-2` | 1220 | 0 |
| `site_02_k_low d00` | non | `1.37e-4` | 13228 | 0 |
| `site_02_k_low d001` | non | `1.43e-1` | 12845 | 0 |
| `site_02_network` | non | `9.33` | 12865 | 2 |

Conclusion: le smoothing reduit parfois le residu, mais ne permet pas de passer
au modele cible. Il tend souvent a produire une signature dominee par le fond.
Il reste utile comme diagnostic, pas comme initialiseur robuste.

## Alternative 5: saturated thickness variable prototype

Implementation:

- `method = "saturated_thickness_variable_vi_prototype"`;
- variable prototype `s = h - z_bottom`;
- bornes `0 <= s <= H`, avec reconstruction `h = s + z_bottom`;
- assemblage cible reutilise via wrapper `s -> h`.

Resultats:

| case | converged | residual | note |
|---|---:|---:|---|
| `site_01_k_high d00` | non | `1.65e-4` | meilleur que VI direct mais echec |
| `site_01_k_high d01` | oui | `2.30e-7` | seul succes nouveau compact hors baselines |
| `site_01_k_high d001` | non | `1.65e-4` | echec |

Conclusion: piste interessante mais trop partielle. Le succes sur `d01` montre
que le changement de variable peut modifier favorablement la line search, mais
l'echec sur `d00` et `d001` interdit toute promotion.

## Alternative 6: complementarity revisited

Tests:

- `complementarity` direct sur les trois cas compacts;
- `complementarity_then_vi` disponible dans le script historique mais non
  relance dans la matrice robuste principale car les premiers resultats
  compacts etaient deja defavorables.

Resultats compacts:

| case | converged | residual |
|---|---:|---:|
| `site_01_k_high d00` | non | `1.00e-2` |
| `site_01_k_high d01` | non | `1.55e-3` |
| `site_01_k_high d001` | non | `3.49e-4` |

Conclusion: la complementarite reste un outil de diagnostic. Elle n'est pas un
initialiseur robuste general dans l'etat actuel.

## Comparative table

| case | method | converged | target final | residual | active bottom | active top | runtime | usable as IC | recommendation |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `site_01_k_high d00` | `drainage_continuation_vi` | oui | oui | `3.90e-10` | 72 | 32 | `1.3s` | oui | meilleur compact |
| `site_01_k_high d00` | `pseudo_transient_vi_then_steady_vi` | oui | oui | `1.26e-7` | 72 | 32 | `4.2s` | oui | candidat compact |
| `site_01_k_high d00` | `tspseudo_vi_ssls` | non | oui | `6.61e-4` | 812 | 0 | `39.6s` | non | diagnostic |
| `site_01_k_high d01` | `drainage_continuation_vi` | oui | oui | `5.30e-9` | 71 | 0 | `0.8s` | oui | meilleur compact |
| `site_01_k_high d01` | `s_variable_prototype` | oui | oui | `2.30e-7` | 24 | 0 | `3.3s` | oui | piste P2 |
| `site_01_k_high d001` | `vi_obstacle` | oui | oui | `1.06e-9` | 67 | 0 | `2.9s` | oui | controle |
| `site_02_k_low d00` | `vi_obstacle` | oui | oui | `9.26e-7` | 19 | 1599 | `11.9s` | oui | controle courant |
| `site_02_k_low d00` | `drainage_continuation_vi` | oui | oui | `3.10e-7` | 19 | 1600 | `17.2s` | oui | utile |
| `site_02_k_low d001` | `vi_obstacle` | oui | oui | `1.28e-9` | 19 | 0 | `7.4s` | oui | controle courant |
| `site_02_network` | `petsc_regularized` | non | non | `8.00e-5` | 114 | 0 | `147s` | non | meilleur residu non cible |
| `site_02_network` | `tspseudo_vi` | non | oui | `5.43e-4` | 33 | 868 | `136s` | non | meilleur progres cible |
| `site_02_network` | `bounded_picard_lscheme_then_vi` | non | non | `9.39e-2` | 6 | 5383 | `2.1s` | non | echec rapide |
| `site_02_network` | `vi_obstacle` | non | oui | `9.27` | 12865 | 2 | `4.2s` | non | baseline echec |

## Site-specific conclusions

### site_01_k_high

Les cas compacts sont resolus par les chemins existants:

- `drainage_continuation_vi` est le meilleur chemin observe;
- `pseudo_transient_vi_then_steady_vi` est aussi robuste sur `d00` et `d01`;
- `d001` converge deja en VI direct.

Les nouvelles alternatives ne justifient pas un remplacement. `s`-variable est
le seul nouveau signal positif, mais uniquement sur `d01`.

### site_02_k_low

Le code courant converge deja en VI direct sur `d00` et `d001` dans la matrice
bas niveau. Cela confirme que l'ancien artefact d'echec sur `site_02_k_low`
etait au moins en partie un probleme de chemin.

Les nouvelles methodes n'ameliorent pas ce cas. `TSPSEUDO` descend a `1e-4` ou
`5e-5`, mais reste moins bon que le VI direct. Picard et smoothing donnent des
ameliorations partielles mais pas de solution cible.

### site_02_network

`site_02_network` reste le cas bloquant. Aucune methode testee n'atteint le
modele cible final.

Le meilleur residu absolu reste `petsc_regularized` (`8.00e-5`), mais ce n'est
pas le modele cible et il echoue encore par line search. Le meilleur progres sur
une formulation cible bornee est `tspseudo_vi` (`5.43e-4`), avec seulement `33`
cellules actives au fond et sans cellules sous le fond. Cela change la signature
d'echec et merite une suite.

## Operational ranking and distance to convergence

### Methodes qui marchent le mieux maintenant

Le classement operationnel actuel est:

1. `drainage_continuation_vi`: meilleur chemin pratique sur les cas compacts
   `site_01_k_high d00/d01` et utile sur `site_02_k_low`. Il atteint le modele
   VI cible final avec des residus de `3.90e-10` a `3.10e-7`.
2. `pseudo_transient_vi_then_steady_vi`: robuste sur `site_01_k_high d00/d01`
   et sur `site_02_k_low`, avec residus de `2.25e-8` a `6.53e-7`. Il est plus
   couteux que la continuation drainage, mais il atteint aussi le modele cible.
3. `vi_obstacle` direct: excellent quand il converge (`site_01_k_high d001`,
   `site_02_k_low d00/d001`), mais trop fragile sur `site_01_k_high d00/d01`
   et inutilisable tel quel sur `site_02_network`.
4. `petsc_regularized`: souvent tres bon comme diagnostic ou champ candidat,
   mais pas modele cible. Sur `site_02_network`, c'est le meilleur residu brut
   (`8.00e-5`), mais il echoue encore par line search et ne resout pas la VI
   finale.
5. `tspseudo_vi`: meilleure nouvelle piste sur `site_02_network`. Il ne
   converge pas encore, mais il reduit le residu cible et evite l'effondrement
   massif au fond.

Les autres methodes testees ne sont pas de bons candidats court terme:

- `bounded_picard_lscheme`: stable informatiquement, mais residus trop eleves
  et pas de warm start VI fiable;
- `bmin_continuation_vi`: souvent neutre ou degradant, surtout sur `site_02`;
- `smooth_threshold_continuation`: parfois proche en residu, mais signature
  souvent dominee par l'obstacle inferieur;
- `vi_obstacle_ssls`: pas meilleur que RSLS;
- `complementarity`: pas robuste dans cette matrice;
- `saturated_thickness_variable_vi_prototype`: signal interessant mais trop
  ponctuel, avec un seul vrai succes nouveau sur `site_01_k_high d01`.

### Quand ca ne marche pas, est-on loin?

La distance a la convergence depend fortement du cas et de la methode. La
tolérance cible est `1e-6`.

| cas | methode | residu | distance a la tolerance | lecture |
|---|---|---:|---:|---|
| `site_01_k_high d00` | `vi_obstacle` | `1.12e-3` | x1120 | echec net, active set fond trop fort |
| `site_01_k_high d00` | `tspseudo_vi_ssls` | `6.61e-4` | x660 | plus proche, mais moins bon que les baselines qui convergent |
| `site_01_k_high d00` | `smooth_threshold_continuation` | `5.89e-4` | x590 | residu reduit, mais signature fond non cible |
| `site_01_k_high d01` | `vi_obstacle` | `1.65e-4` | x165 | proche en norme, mais line search echoue |
| `site_01_k_high d01` | `tspseudo_vi` | `4.09e-5` | x41 | assez proche, mais inutile car drainage continuation converge |
| `site_02_k_low d00` | `tspseudo_vi` | `8.64e-5` | x86 | proche, mais VI direct converge deja |
| `site_02_k_low d001` | `tspseudo_vi` | `4.52e-5` | x45 | proche, mais VI direct converge deja |
| `site_02_network` | `vi_obstacle` | `9.27` | x9.3e6 | tres loin, effondrement au fond |
| `site_02_network` | `drainage_continuation_vi` | `1.39e-1` | x1.4e5 | loin, encore domine par le fond |
| `site_02_network` | `petsc_regularized` | `8.00e-5` | x80 | proche en residu, mais non cible et line search |
| `site_02_network` | `tspseudo_vi` | `5.43e-4` | x543 | pas proche de la tolerance, mais meilleure signature cible |

Il faut donc distinguer trois niveaux:

- **vraiment proche**: residu entre `1e-6` et `1e-5`. Peu de cas non converges
  entrent clairement dans cette zone; `recharge_continuation_vi` sur
  `site_01_k_high d01/d001` est proche en norme, mais reste peu fiable car ce
  chemin n'aide pas les cas difficiles.
- **intermediaire prometteur**: residu `1e-5` a `1e-3`. C'est la zone de
  `tspseudo_vi` et de certains smoothings. Cela peut justifier un meilleur
  controle de pas, mais ce n'est pas encore une solution.
- **loin**: residu `>1e-2` ou active set physiquement absurde. Picard simple,
  b_min sur `site_02`, VI direct sur `site_02_network` et plusieurs SSLS sont
  dans cette categorie.

### Est-ce qu'augmenter le nombre de pas peut changer les choses?

Oui, mais seulement pour certaines methodes et pas sous la forme "augmenter
aveuglement max_it".

Cas ou cela peut aider:

- `tspseudo_vi`: c'est la meilleure cible pour un travail sur le nombre de pas.
  Il reduit `site_02_network` de `9.27` a `5.43e-4` et garde un active set plus
  raisonnable (`33` cellules au fond, `868` au toit). Augmenter simplement
  `max_steps` ne suffit probablement pas, mais un vrai controle adaptatif de
  pseudo-pas peut aider: pas initial plus petit, limitation de croissance du
  pseudo-dt, rejet/reprise en cas de line search, et monitoring du residu
  stationnaire cible a chaque pseudo-etape.
- `pseudo_transient_vi_then_steady_vi`: sur les cas compacts, cela marche deja.
  Sur `site_02_network`, le calendrier standard echoue tres tot, mais un
  calendrier plus fin passe les petits pas, puis bloque plus tard entre environ
  `730` et `800-1000` jours equivalents. Cela montre que la finesse du debut
  aide a traverser une partie du chemin, mais ne suffit pas a atteindre le
  stationnaire cible.
- continuations: augmenter le nombre de niveaux peut aider seulement si la
  methode echoue entre deux niveaux. Pour `drainage_continuation_vi`, cela
  merite une bissection adaptative sur `site_02_network`. Pour `b_min`, les
  resultats actuels degradent trop souvent la signature, donc raffiner le
  schedule seul n'est pas prioritaire.

Cas ou cela ne devrait pas suffire:

- `vi_obstacle` direct: les echecs principaux sont `SNES_DIVERGED_LINE_SEARCH`,
  pas seulement `MAX_IT`. Plus d'iterations ne corrige pas un pas de Newton qui
  ne trouve pas de descente.
- `vi_obstacle_ssls`: plusieurs cas atteignent `MAX_IT` avec residus encore
  grands ou partent dans une mauvaise signature; augmenter `max_it` risque
  surtout de consommer du temps.
- Picard/L-scheme actuel: les echecs sont des stagnations a residu `1e-3` a
  `1e-1`. Plus d'iterations ne suffit probablement pas sans changer relaxation,
  stabilisation, linearisation du drainage et strategie de projection.
- smoothing et `b_min`: les echecs proches en residu sont souvent accompagnes
  d'un active set domine par le fond. Il faut corriger le chemin, pas seulement
  ajouter des etapes.

Conclusion pratique: le seul endroit ou "augmenter le nombre de pas" parait
vraiment defendable est **TSPSEUDO avec controle adaptatif**, pas les Newton VI
stationnaires directs. La meilleure experience suivante est donc:

`petsc_regularized -> TSPSEUDO VI adaptatif -> VI cible final`

avec diagnostics par pseudo-etape et acceptation uniquement si le modele cible
final `b_min = 0`, `smooth_eps = 0` converge.

### Mise a jour: essais de pas plus fins

Une relance ciblee a ete ajoutee apres la premiere matrice pour tester
explicitement l'effet du nombre de pas et de la finesse des pas. Les nouvelles
methodes d'investigation sont:

- `tspseudo_vi_long`: meme pas initial que `tspseudo_vi`, mais `max_steps = 800`;
- `tspseudo_vi_fine`: pas initial `0.01 s`, `max_steps = 1000`;
- `tspseudo_vi_ultrafine`: pas initial `0.0001 s`, `max_steps = 1500`;
- `tspseudo_vi_then_steady_vi_fine`: TSPSEUDO fin, puis VI stationnaire cible;
- `pseudo_transient_vi_then_steady_vi_fine`: calendrier pseudo-transitoire plus
  progressif;
- `pseudo_transient_vi_then_steady_vi_veryfine`: pas densifies jusque `1000`
  jours;
- `pseudo_transient_vi_730d_then_steady_vi`: arret du warm-up a `730` jours,
  puis VI cible;
- `pseudo_transient_vi_then_steady_vi_superfine`: pas densifies entre `730` et
  `1000` jours;
- `drainage_continuation_vi_fine`: calendrier de drainage plus dense.

Resultats compacts `site_01_k_high`:

| cas | methode | resultat | residu final | lecture |
|---|---|---:|---:|---|
| `d01` | `tspseudo_vi_long` | echec | `4.09e-5` | plus de pas ne depasse pas le plateau TSPSEUDO |
| `d01` | `tspseudo_vi_fine` | echec | `8.62e-5` | pas initial plus petit degrade le residu |
| `d01` | `tspseudo_vi_then_steady_vi_fine` | succes | `1.97e-9` | TSPSEUDO fin est utile comme warm start du VI cible |
| `d01` | `pseudo_transient_vi_then_steady_vi_fine` | succes | `2.23e-8` | confirme que le pseudo-transitoire marche sur compact |
| `d01` | `drainage_continuation_vi_fine` | succes | `1.65e-9` | le raffinement marche en montee vers `0.1` |
| `d00` | `tspseudo_vi_long` | echec | `2.64e-3` | pas mieux que TSPSEUDO standard |
| `d00` | `tspseudo_vi_fine` | echec | `2.89e-3` | pas initial plus petit degrade |
| `d00` | `tspseudo_vi_then_steady_vi_fine` | echec | `1.97e-3` | warm start TSPSEUDO insuffisant pour `drain=0` |
| `d00` | `pseudo_transient_vi_then_steady_vi_fine` | succes | `1.57e-7` | meilleur chemin fin sur `drain=0` |
| `d00` | `drainage_continuation_vi_fine` | echec | `1.65e-4` | un pas plus fin `0.01 -> 0.009` casse alors que le calendrier grossier passait |

Le dernier point est important: une continuation plus fine peut etre moins
robuste si elle force le solveur dans un mauvais changement d'ensemble actif.
Il ne faut donc pas remplacer une continuation par un raffinement uniforme; il
faut une strategie adaptative avec rejet de pas et retour au dernier etat sain.

Resultats `site_02_network`:

| methode | resultat | residu final | etapes utiles | lecture |
|---|---|---:|---:|---|
| `tspseudo_vi_long` | echec | `5.43e-4` | 133 | augmenter `max_steps` seul ne change rien, car l'echec arrive avant |
| `tspseudo_vi_fine` | echec | `1.25e-4` | 190 | meilleur resultat cible obtenu par raffinement du pas initial |
| `tspseudo_vi_ultrafine` | echec | `4.38e-4` | 231 | pas initial trop petit ne continue pas l'amelioration |
| `tspseudo_vi_then_steady_vi_fine` | echec | `9.30` | 191 | le VI final retombe dans l'echec au fond |
| `pseudo_transient_vi_then_steady_vi_fine` | echec | `9.30` | 18 | le calendrier fin passe jusqu'a `100` jours puis casse a `365` jours |
| `pseudo_transient_vi_then_steady_vi_veryfine` | echec | `9.30` | 26 | passe `365`, `500`, `730` jours, casse a `1000` jours |
| `pseudo_transient_vi_730d_then_steady_vi` | echec | `9.30` | 26 | meme depuis un warm-up convergé a `730` jours, le VI cible s'effondre |
| `pseudo_transient_vi_then_steady_vi_superfine` | echec | `9.30` | 26 | densifier `730 -> 1000` casse deja a `800` jours |
| `drainage_continuation_vi_fine` | echec | `1.39e-1` | 1 | echec des le drainage facile `0.01` |

Conclusion de ces essais: augmenter la finesse des pas aide a **avancer plus
loin dans le chemin pseudo-transitoire**, mais ne suffit pas a faire converger
le VI stationnaire final sur `site_02_network`. Le meilleur residu cible obtenu
reste `tspseudo_vi_fine = 1.25e-4`, contre `5.43e-4` pour TSPSEUDO standard et
`9.27` pour VI direct. On gagne donc environ un facteur 4 par rapport au
TSPSEUDO standard et environ un facteur `7e4` par rapport au VI direct, mais on
reste environ `125` fois au-dessus de la tolerance `1e-6`.

La reponse a la question "plus de pas peut-il changer les choses?" est donc:

- oui pour ameliorer un chemin intermediaire, surtout TSPSEUDO et
  pseudo-transitoire;
- non, dans l'etat actuel, pour atteindre automatiquement le modele stationnaire
  cible sur `site_02_network`;
- le prochain levier n'est pas seulement "plus de pas", mais un **controle
  adaptatif de pas avec rejet**, plus un **controle final VI qui ne repart pas
  brutalement vers l'obstacle inferieur**.

### Mise a jour: meilleurs candidats, transitoire et similarite des champs

Une matrice plus restreinte a ensuite ete lancee pour ne garder que les
candidats utiles:

- chemins VI stricts qui convergent deja sur les cas compacts;
- `tspseudo_vi_fine`, meilleur residu cible non converge sur `site_02_network`;
- `pseudo_transient_vi_730d_warm`, etat de warm-up sans controle stationnaire
  final;
- variantes a epaisseur minimale permanente `b_min = 0.01`, `0.05` et `0.10 m`.

Cette matrice ajoute deux controles:

1. un probe transitoire strict de 30 jours depuis le champ candidat;
2. des comparaisons paire-a-paire des champs de charge complets.

#### Candidats compacts

Sur `site_01_k_high / drain_0`, les deux chemins stricts converges sont tous
deux utilisables en transitoire:

| methode | residu | probe transitoire | RMSE vs autre strict |
|---|---:|---:|---:|
| `drainage_continuation_vi` | `3.90e-10` | oui | `9.0e-4 m` |
| `pseudo_transient_vi_then_steady_vi_fine` | `1.57e-7` | oui | `9.0e-4 m` |

Les champs sont donc pratiquement identiques. La variante `b_min = 0.01 m`
converge aussi, passe le probe transitoire, et reste tres proche du VI strict:
RMSE `0.004-0.005 m`, p95 absolu `0.008-0.009 m`, maximum environ `0.034 m`.
La variante `b_min = 0.10 m` converge egalement mais s'eloigne davantage:
RMSE environ `0.05 m`, p95 environ `0.10 m`, maximum environ `0.26 m`.
La variante `b_min = 0.05 m` echoue vers un champ faux, a environ `20 m` RMSE
du champ strict. Cela montre que le plancher d'epaisseur n'est pas monotone et
doit etre traite comme un changement de formulation, pas comme un simple
parametre numerique anodin.

Sur `site_01_k_high / drain_0.1`, les trois chemins stricts converges sont
quasi confondus:

| paire | RMSE |
|---|---:|
| `drainage_continuation_vi_fine` vs `tspseudo_vi_then_steady_vi_fine` | `2.9e-7 m` |
| `pseudo_transient_vi_then_steady_vi_fine` vs `tspseudo_vi_then_steady_vi_fine` | `1.7e-4 m` |
| `drainage_continuation_vi_fine` vs `pseudo_transient_vi_then_steady_vi_fine` | `1.7e-4 m` |

La variante `b_min = 0.10 m` converge et reste proche a l'echelle hydro:
RMSE environ `0.047 m`, p95 environ `0.093 m`, maximum `0.234 m`. En revanche
`b_min = 0.01` et `0.05 m` echouent vers le meme mauvais champ, a environ
`20 m` RMSE du champ strict.

Sur `site_02_k_low / drain_0`, les chemins stricts converges et les variantes
`b_min` convergent tous et passent le probe transitoire:

| paire | RMSE |
|---|---:|
| `drainage_continuation_vi` vs `vi_obstacle` | `2.3e-5 m` |
| `pseudo_transient_vi_then_steady_vi_fine` vs `vi_obstacle` | `1.3e-4 m` |
| `b_min = 0.01 m` vs `vi_obstacle` | `3.5e-4 m` |
| `b_min = 0.05 m` vs `vi_obstacle` | `1.8e-3 m` |

Ici, l'epaisseur minimale permanente est donc presque neutre sur le champ de
charge et ne degrade pas le demarrage transitoire.

#### Cas difficile `site_02_network`

Sur `site_02_network`, aucun candidat ne fournit encore un etat stationnaire VI
cible converge. En revanche, trois familles passent le probe transitoire strict:

| methode | converge stationnaire | probe transitoire | residu stationnaire | lecture |
|---|---:|---:|---:|---|
| `tspseudo_vi_fine` | non | oui | `1.25e-4` | meilleur residu cible non converge |
| `pseudo_transient_vi_730d_warm` | oui en warm-up, non stationnaire | oui | `2.85e-7` sur le dernier pas transitoire | utilisable comme etat de warm-up, pas comme stationnaire |
| `b_min_*_tspseudo` | non | oui | `1.25e-4` | quasi identique a `tspseudo_vi_fine` |

Le champ `pseudo_transient_vi_730d_warm` n'est pas identique au champ
`tspseudo_vi_fine`: RMSE environ `1.57 m`, p95 environ `3.23 m`, maximum
`4.54 m`. Le champ PETSc regularise est encore different: RMSE `1.10 m` avec
le warm-up et `2.17 m` avec TSPSEUDO. Les solveurs VI directs avec `b_min`
echouent vers le meme mauvais champ domine par l'obstacle inferieur:
`12865` cellules au fond et environ `49-51 m` RMSE par rapport aux champs
regularise/TSPSEUDO/warm-up.

L'essai `b_min` permanent ne resout donc pas `site_02_network` par Newton VI
direct. En revanche, `b_min` combine a TSPSEUDO donne presque le meme champ que
TSPSEUDO strict:

| paire | RMSE | p95 abs | max abs |
|---|---:|---:|---:|
| `b_min = 0.01 m` TSPSEUDO vs TSPSEUDO strict | `9.6e-4 m` | `0.0010 m` | `0.031 m` |
| `b_min = 0.05 m` TSPSEUDO vs TSPSEUDO strict | `0.0043 m` | `0.0043 m` | `0.132 m` |
| `b_min = 0.10 m` TSPSEUDO vs TSPSEUDO strict | `0.0085 m` | `0.0090 m` | `0.226 m` |

Interpretation: un plancher de transmissivite de `1 cm` parait marginal sur les
flux et sur le champ de charge lorsque le chemin TSPSEUDO reste dans le bon
bassin. Il ne suffit pas, a lui seul, a rendre le Newton stationnaire direct
robuste sur le grand cas. Le candidat le plus raisonnable pour une suite est
donc:

`TSPSEUDO fin avec eventuel b_min = 0.01 m -> probe transitoire -> pas de
controle stationnaire VI brutal tant que celui-ci retombe au fond`

Ce n'est pas encore un etat stationnaire cible. C'est plutot une strategie de
warm-up transitoire robuste a explorer si l'objectif pratique est de demarrer
une simulation transitoire naturelle difficile.

## Recommended robust initialization architecture

Architecture recommandee apres cette passe:

1. Essayer `vi_obstacle` direct.
2. Si echec et drainage cible different d'un drainage facile, essayer
   `drainage_continuation_vi`.
3. Si echec compact, essayer `pseudo_transient_vi_then_steady_vi`.
4. Sur les cas compacts, terminer par un controle VI cible final.
5. Sur les cas grands ou le controle VI final retombe systematiquement au fond,
   separer explicitement deux objectifs: etat stationnaire cible strict, ou
   warm-up transitoire utilisable.
6. Si tous les chemins echouent, ecrire les diagnostics stationnaires et arreter.
7. Garder `petsc_regularized`, `TSPSEUDO`, Picard, smoothing et complementarite
   comme chemins de diagnostic tant qu'ils ne convergent pas au modele cible.

Pour `site_02_network`, la prochaine investigation devrait cibler une version
plus controlee de TSPSEUDO:

- criteres steady-state TS explicites;
- monitoring du pseudo-pas et du residu cible a chaque etape;
- controle adaptatif de pseudo-dt;
- possibilite de demarrer TSPSEUDO depuis le champ regularise PETSc;
- puis controle final VI cible uniquement s'il ne detruit pas le warm start;
- probe transitoire de verification si l'objectif pratique est seulement de
  demarrer un transitoire naturel difficile.

## What not to promote

Ne pas promouvoir actuellement:

- `regularized -> VI` comme solution de repli robuste;
- `complementarity` comme initialiseur general;
- `recharge_continuation_vi`, qui n'aide pas les cas testes;
- `b_min > 0` ou `smooth eps > 0` comme solution physique finale;
- un champ non stationnaire comme "stationnaire converge", meme s'il demarre le
  transitoire;
- `vi_obstacle_ssls`, qui n'ameliore pas RSLS dans cette matrice;
- Picard/L-scheme simple, qui ne fournit pas encore un warm start VI fiable.

## Implementation recommendations

P0:

- conserver le script d'investigation et les diagnostics persistants;
- ne pas changer le comportement par defaut;
- si l'on veut un correctif court terme, formaliser `drainage_continuation_vi`
  et `pseudo_transient_vi_then_steady_vi` comme initialiseurs experimentaux avec
  controle final VI.

P1:

- reprendre `tspseudo_vi` car il est le seul chemin cible qui ameliore nettement
  la signature de `site_02_network`;
- garder une matrice restreinte des meilleurs candidats avec ecriture des
  champs et probe transitoire;
- tester un demarrage `petsc_regularized -> TSPSEUDO -> VI`, en documentant que
  le champ regularise n'est qu'un warm start;
- ajouter une bissection/adaptation de pseudo-pas et des criteres de steady
  residuel explicites.

P2:

- approfondir le prototype `s = h - z_bottom`, mais seulement apres un test sur
  plusieurs cas compacts;
- revoir Picard/L-scheme avec drainage mieux linearise et relaxation adaptative;
- explorer `b_min = 0.01 m` comme plancher de transmissivite experimental, car
  il est presque neutre sur les champs testes lorsqu'il converge ou lorsqu'il
  est combine a TSPSEUDO. Ne pas le promouvoir sans validation analytique et
  sans version transitoire coherente.

P3:

- explorer TAO, MCP externe ou reformulation plus profonde si `site_02_network`
  reste insoluble au modele cible.

## Commands executed

Smoke tests:

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method tspseudo_vi --method bounded_picard_lscheme_then_vi --method bmin_continuation_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_smoke --max-walltime-soft 600"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method vi_obstacle_ssls --method tspseudo_vi_ssls --method bounded_picard_lscheme --method bmin_continuation_picard_then_vi --method smooth_threshold_continuation --method tspseudo_vi_with_bmin_continuation --method saturated_thickness_variable_vi_prototype --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_smoke2 --max-walltime-soft 900"
```

Matrices principales:

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py --level 1 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_level1 --max-walltime-soft 3600"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py --level 2 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_level2 --max-walltime-soft 5400"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py --case site_02_network__bouss_unstructured_same_mesh --method vi_obstacle --method petsc_regularized --method pseudo_transient_vi_then_steady_vi --method drainage_continuation_vi --method tspseudo_vi --method bounded_picard_lscheme_then_vi --method bmin_continuation_vi --method bmin_continuation_picard_then_vi --method smooth_threshold_continuation --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_site02_network --max-walltime-soft 5400"
```

Essais de raffinement des pas:

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_01 --method tspseudo_vi_long --method tspseudo_vi_fine --method tspseudo_vi_ssls_fine --method tspseudo_vi_then_steady_vi_fine --method pseudo_transient_vi_then_steady_vi_fine --method drainage_continuation_vi_fine --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site01_d01 --max-walltime-soft 1800"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method tspseudo_vi_long --method tspseudo_vi_fine --method tspseudo_vi_then_steady_vi_fine --method pseudo_transient_vi_then_steady_vi_fine --method drainage_continuation_vi_fine --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site01_d00 --max-walltime-soft 1800"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --case site_01_k_high__bouss_tri_irregular_drain_01 --method drainage_continuation_vi_fine --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site01_drainage_fine2 --max-walltime-soft 900"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py --case site_02_network__bouss_unstructured_same_mesh --method tspseudo_vi_long --method tspseudo_vi_fine --method tspseudo_vi_then_steady_vi_fine --method pseudo_transient_vi_then_steady_vi_fine --method drainage_continuation_vi_fine --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site02_network --max-walltime-soft 3600"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py --case site_02_network__bouss_unstructured_same_mesh --method tspseudo_vi_ultrafine --method pseudo_transient_vi_then_steady_vi_veryfine --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site02_network_extra --max-walltime-soft 3600"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py --case site_02_network__bouss_unstructured_same_mesh --method pseudo_transient_vi_730d_then_steady_vi --method pseudo_transient_vi_then_steady_vi_superfine --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site02_network_superfine --max-walltime-soft 3600"
```

Matrice restreinte des meilleurs candidats:

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_site01_d00"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_01 --case site_02_k_low__bouss_tri_irregular_drain_00 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_site01_d01_site02_low_d00"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_02_network__bouss_unstructured_same_mesh --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_site02_network --probe-dt-days 30"
```

Tests et lint:

```powershell
python -m pytest -o addopts='' tests/unit/solver/test_boussinesq_stationary_robust_solver_matrix.py -q
python -m ruff format examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py tests/unit/solver/test_boussinesq_stationary_robust_solver_matrix.py
python -m ruff check examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py tests/unit/solver/test_boussinesq_stationary_robust_solver_matrix.py
python -m ruff format --check examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py tests/unit/solver/test_boussinesq_stationary_robust_solver_matrix.py
python -m py_compile examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py
python -m ruff format examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py
python -m ruff check examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py
```

## Output artifacts

Scripts et tests:

- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py`;
- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py`;
- `tests/unit/solver/test_boussinesq_stationary_robust_solver_matrix.py`.

Sorties principales:

- `docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_level1/stationary_robust_solver_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_level2/stationary_robust_solver_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_site02_network/stationary_robust_solver_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_combined/stationary_robust_solver_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site01_d00/stationary_robust_solver_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site01_d01/stationary_robust_solver_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site01_drainage_fine2/stationary_robust_solver_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site02_network/stationary_robust_solver_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site02_network_extra/stationary_robust_solver_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_robust_solver_matrix_step_refinement_site02_network_superfine/stationary_robust_solver_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_site01_d00/stationary_best_candidate_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_site01_d00/stationary_best_candidate_head_similarity.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_site01_d01_site02_low_d00/stationary_best_candidate_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_site01_d01_site02_low_d00/stationary_best_candidate_head_similarity.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_site02_network/stationary_best_candidate_matrix.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_site02_network/stationary_best_candidate_head_similarity.csv`;
- fichiers JSON correspondants;
- fichiers `head_field.npz` par cas et methode;
- `stage_diagnostics.csv`, `method_summary.json` et diagnostics d'echec dans
  chaque dossier `diagnostics/<case>/<method>/`.

## Remaining open questions

- `site_02_network` a-t-il une solution stationnaire VI utile avec ces
  parametres, ou faut-il un warm-up transitoire plutot qu'un etat stationnaire?
- Les cellules responsables du residu TSPSEUDO sont-elles localisees sur des
  seuils topographiques, interfaces geologiques ou zones de maillage degrade?
- Un demarrage `petsc_regularized -> TSPSEUDO -> VI` peut-il combiner le faible
  residu du regularise avec le modele cible borne?
- Le prototype `s = h - z_bottom` peut-il etre rendu robuste, ou son succes sur
  un seul cas est-il accidentel?
- La ligne de recherche VI echoue-t-elle parce que l'operateur cible est trop
  non lisse, ou parce que la jacobienne experimentale reste insuffisamment
  coherente pres des seuils?
