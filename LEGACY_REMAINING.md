# Legacy Remaining

Après le nettoyage v0.6 et les passes de suivi, la base de code ne porte
plus de shim mort ni d'alias redondant. Trois éléments subsistent de
façon légitime et sont documentés ici pour que les futurs contributeurs
sachent pourquoi.

## 1. Façade `CatchmentDelineation`

Objet runtime public exposé sous `hydromodpy.spatial.geographic.CatchmentDelineation`.

**Conservé parce que :**
- C'est l'API publique canonique : les utilisateurs appellent
  `from hydromodpy.spatial.geographic import CatchmentDelineation` puis
  `CatchmentDelineation(config, workspace)`.
- Les internes ont été migrés vers la disposition v0.6 : la classe délègue
  désormais à `build_geographic_runtime_context()` et hydrate ses attributs
  via `runtime_attributes()` (plus aucun symbole `legacy_*`).
- Retirer la façade casserait chaque script utilisateur en aval et chaque
  exemple.

**Statut :** c'est le design actuel, pas un shim.

## 2. `DataStore.workspace_root`

Paramètre constructeur de `hydromodpy.data.DataStore(workspace_root=...)`.

**Conservé parce que :**
- C'est un argument nommé public documenté dans toute la couche data.
- Renommer en `root` n'apporte aucune amélioration sémantique et casse
  chaque utilisateur de la façade data.
- L'attribut est descriptif (il *est* la racine du workspace que le store
  utilise pour le cache data partagé et les dossiers par variable) et
  distinct de `WorkspaceConfig.root` côté simulation.

**Statut :** API publique légitime, conservée telle quelle.

## 3. Docstrings « Ported from legacy X »

Docstrings de traçabilité dans :

- `hydromodpy/calibration/adapters/da_mh_gp_adapter.py`
- `hydromodpy/calibration/adapters/gp_mapping_adapter.py`
- `hydromodpy/calibration/cases/__init__.py`
- `hydromodpy/calibration/cases/recession_brutsaert.py`

**Conservées parce que :**
- Elles documentent l'origine scientifique de chaque algorithme porté
  (quelle implémentation de référence le comportement numérique reproduit,
  quel papier ou module legacy le code réplique).
- Critiques pour la reproductibilité : quand un golden de validation
  diverge, la première question est « qu'est-ce que la version pré-port
  faisait exactement ? », et les docstrings répondent.
- Elles sont descriptives, pas actionnables : pas de shim, pas d'alias,
  pas d'import mort.

**Statut :** documentation de provenance scientifique, conservée telle quelle.

## 4. Interface `[method_comparison]`

Ancienne interface TOML supprimee.

**Decision :**
- La seule section runtime acceptee est `[comparison]`.
- Les comparaisons de simulations declarent `[[comparison.simulation]]`.
- Les comparaisons de variantes ou de dossiers existants declarent
  `[[comparison.variant]]`.
- Les noms `MethodComparison*`, le workflow `method-comparison`, la commande
  `compare-methods`, et le relais `run_method_comparison.py` ne font plus partie
  du contrat public.
- Les chemins statiques de galerie qui contiennent `method_comparison` restent
  des identifiants documentaires, pas des interfaces runtime.

**Statut :** compatibilite runtime supprimee.
