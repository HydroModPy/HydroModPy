# Refactor: passer la configuration HydroModPy en Pydantic v2 natif

## Contexte et problème

La configuration HydroModPy s'expose en TOML, validée par `HydroModPyConfig`
(`hydromodpy/config/__init__.py`). Aujourd'hui une partie des sections critiques
(`[flow.bc]`, `[flow.param.<id>]`) suit un pattern hybride :

- le champ Pydantic est typé en `dict[str, object]` ou `dict[str, dict[str, object]]`,
- la validation passe par une fonction externe (`normalize_flow_boundary_conditions`,
  `parse_flow_param_sections`, `get_field_param_payload_resolver`),
- le payload final est stocké en `dict[str, object]` non typé.

Ce pattern empêche :

1. Le **JSON Schema** exporté de refléter la vraie structure (Stoplight,
   validateur browser, IDE plugins voient `dict[str, object]`).
2. L'**auto-completion IDE** dans le code Python qui consomme ces payloads.
3. La **génération automatique** de la doc, qui doit lire une table
   `tools/doc_config/dispatchers.py` maintenue à la main pour découvrir
   le vrai schéma derrière les `dict[str, object]`.
4. Le filtrage `Profile.USER/DEV/EXPERT` de remonter sur les sous-payloads.

Le reste du codebase (les `~26` `data/variables/<x>/config.py`,
`FlowBoundaryForcingConfig`, `FlowWellConfig`, `FieldBaseSection`,
`FieldHomogeneousSection`, etc.) utilise déjà le pattern Pydantic v2 natif
attendu (BaseModel typé, parfois discriminated union). Le bricolage est
concentré sur deux sous-systèmes.

## Solution cible

Tous les payloads dynamiques deviennent des `BaseModel` typés (avec
`discriminator` quand il y a plusieurs variantes). La canonicalisation
TOML qu'effectuent aujourd'hui les normalizers externes passe en
`@model_validator(mode="before")` interne au modèle. Aucune fonction
de normalisation hors classe Pydantic ne survit.

La règle :

> Tout `dict[str, object]` ou `dict[str, dict[str, object]]` dans le
> tree `HydroModPyConfig` est interdit, sauf déclaration explicite dans
> `INTENTIONALLY_OPAQUE_PATHS` (free-form key/value mappings).

Avantages directs :

- **`tools/doc_config/dispatchers.py` disparaît**.
- La doc devient 100% dérivée de `model_fields` sans table externe.
- Le JSON Schema export est correct, le validateur browser détecte les
  payloads invalides, l'IDE auto-complete les structures.
- Le filtre Profile fonctionne sur tous les sous-payloads.

**La compatibilité du format `project.toml` côté utilisateur doit être
totale**: aucun fichier sous `examples/projects/` ne doit casser. Le
`@model_validator(mode="before")` accepte la même grammaire TOML qu'avant
et la transforme en payload typé.

## Inventaire exhaustif des cas

### Cas à migrer (le vrai chantier)

| # | Path TOML | Classe parente | Fonction normalizer à supprimer | Modèles cibles | Discriminator |
|---|---|---|---|---|---|
| 1 | `[flow.bc.dirichlet.<id>]` (ids: ocean, stream, north_side, south_side, east_side, west_side) | `FlowConfig.bc` | `normalize_flow_boundary_conditions` (`hydromodpy/physics/flow/boundary_conditions_config.py`) | `DirichletBC`, `CauchyBC`, `RobinBC` (à créer ou dériver de `FlowBoundaryConditionConfig`) | `type: Literal["dirichlet","cauchy","robin"]` |
| 2 | `[flow.bc.cauchy.drainage]`, `[flow.bc.robin.drainage]` | `FlowConfig.bc` | idem | idem (`type="cauchy"`, `type="robin"`) | idem |
| 3 | `[flow.param.<id>.field]` + `[flow.param.<id>.field_homogeneous]` + `[flow.param.<id>.field_heterogeneous]` + `[flow.param.<id>.field_vertical_profile]` | `FlowConfig.param` | `parse_flow_param_sections`, `normalize_flow_param_payloads`, `get_field_param_payload_resolver` (`hydromodpy/physics/flow/param_config.py`, `hydromodpy/spatial/field/core/_field_param_resolution.py`) | Réutiliser `FieldBaseSection`, `FieldHomogeneousSection`, `FieldHeterogeneousSection`, `FieldVerticalProfileSection` qui existent déjà dans `hydromodpy/spatial/field/core/_field_param_sections.py`. Cible: `class FlowParam(BaseModel): field: FieldBaseSection; field_homogeneous: FieldHomogeneousSection \| None; ...` | implicite par sous-section + `kind` dans `FieldBaseSection` |

### Cas déjà natifs (rien à faire, juste vérifier)

- `[[data.<variable>.sources]]` pour les 16 variables (`recharge`,
  `precipitation`, `dem`, `etp`, `geology`, `humidity`, `hydrography`,
  `hydrometry`, `intermittency`, `oceanic`, `piezometry`, `radiation`,
  `runoff`, `soil_moisture`, `temperature`, `water_quality`, `wind`).
  Tous déjà typés `list[<Variable>SourceConfig]` avec
  `source: Literal[...]`.
- `[flow.bc.<id>.forcing]` (`mode: Literal["constant", "csv"]`) : déjà
  une union discriminée native via `FlowBoundaryForcingConfig`.
- `[flow.sinks_sources.wells.<id>]` -> `FlowWellConfig` typé.
- `[flow.ic]` -> `FlowInitialConditions(h=FlowInitialCondition)` typé.
- `[flow.sinks_sources.recharge]` -> `FlowRechargeConfig` typé.
- `[flow.sinks_sources.etp]` -> `FlowEtpConfig` typé.

### Cas intentionnellement opaques (whitelist)

Sont déjà gérés via `tools/doc_config/coverage.py:INTENTIONALLY_OPAQUE_PATHS`:

- `mesh_catchment.hydraulic_properties.conductivity.values` (zone_key -> scalar)
- `mesh_catchment.hydraulic_properties.storage_coefficient.values` (zone_key -> scalar)

Garder ces entrées telles quelles. Si la migration introduit un nouveau
`dict[str, scalar]` libre, l'ajouter à cette liste plutôt qu'à `dispatchers.py`.

### Cas génériques par héritage (aucun changement)

- `ProcessSpatialConfig.{param, bc, sinks_sources}` reste `dict[str, object]`
  comme contrat hérité abstrait. Les sous-classes concrètes (`FlowConfig`,
  `TransportConfig`) doivent **soit** override avec un type concret,
  **soit** marquer `exclude=True`.
- `TransportConfig.{param, bc, sinks_sources}` : `exclude=True` (déjà fait,
  ne pas toucher).

## Plan d'implémentation

Procéder section par section, chaque étape autonome (commit atomique).
Conventions: branche actuelle `dev-docs`, format de commit
`[refactor] - <imperative sentence>`, pas d'amend, pas de push.

### Étape 0 : préparation

1. Créer `tests/unit/config/test_native_dispatch.py` avec un test
   `test_no_opaque_dicts_in_root_schema`:
   - parcourt récursivement `HydroModPyConfig.model_fields`,
   - applique `tools.doc_config.coverage._walk_opaque_fields`,
   - filtre `INTENTIONALLY_OPAQUE_PATHS` et les fields `exclude=True`,
   - assert que la liste résultante est **vide**.

   Au début ce test échoue (cas 1, 2, 3). Il devient la spec d'arrivée.

2. Lancer la suite existante pour ces sections pour avoir une baseline:
   ```
   mamba activate hmp_refact
   pytest tests/unit -k "flow or boundary or field_param" -x
   pytest tests/integration -k "flow" -x
   pytest tests/regression -k "flow" -x
   ```
   Noter les tests qui passent actuellement comme baseline anti-régression.

### Étape 1 : migrer `[flow.bc]`

1. Créer dans `hydromodpy/physics/flow/boundary_conditions.py` les modèles
   typés `DirichletBC`, `CauchyBC`, `RobinBC` qui héritent de
   `HydroModelBase` et exposent `type: Literal[...]` comme discriminateur.
   Conserver les contraintes existantes (`application_domain`, `value`,
   `units`, `forcing`, etc.) telles quelles, à l'identique de ce que
   produit aujourd'hui `FlowBoundaryConditionConfig` selon `type`.
2. Définir l'alias :
   ```python
   BCEntry = Annotated[
       DirichletBC | CauchyBC | RobinBC,
       Field(discriminator="type"),
   ]
   ```
3. Dans `FlowConfig` (`hydromodpy/physics/flow/flow_config.py`):
   ```python
   bc: Annotated[dict[str, BCEntry], Profile.USER] = Field(
       default_factory=dict,
       description="...",
   )
   ```
4. Ajouter un `@model_validator(mode="before")` sur `FlowConfig` qui
   reçoit le payload TOML brut et l'aplatit:
   - `[flow.bc.dirichlet.<id>]` -> entrée `<id>` avec `type="dirichlet"`,
   - `[flow.bc.cauchy.drainage]` -> entrée `drainage` avec `type="cauchy"`,
   - `[flow.bc.robin.drainage]` -> entrée `drainage` avec `type="robin"`,
   - `[flow.bc.<custom_id>]` direct (sans la couche `dirichlet/cauchy/robin`)
     reste accepté avec `type` explicite ou inféré.
   - canonicalisation des keys (`west_side` -> `application_domain="west side"`),
   - contraintes croisées (`application_domain` requis pour cauchy/robin),
   - cohérence side-id ↔ domaine (cf. `DIRICHLET_BC_CANONICAL_DOMAINS`).

   Cette logique vient quasi telle quelle de
   `_parse_flow_bc_sections` et `_normalize_dirichlet_boundary_payload`.
5. Adapter les call-sites runtime qui consomment `FlowConfig.bc`. Ils
   reçoivent maintenant des `BCEntry` typés au lieu de dicts. Grep
   `flow_config.bc`, `cfg.flow.bc`, `flow.bc[`, `bc.values()`, `bc.items()`
   et `FlowBoundaryConditionConfig` pour propager le typage.
6. Supprimer `boundary_conditions_config.py` (les normalizers) sauf si
   un sous-helper a une vie autonome. Supprimer
   `_resolve_boundary_condition_forcing_paths` du `from_toml_section` ou
   le déplacer dans le `model_validator` (résolution chemin CSV).
7. Supprimer la fonction `from_toml_section` si elle ne fait plus que
   dispatcher vers la validation Pydantic standard.
8. Lancer les tests:
   ```
   pytest tests/unit -k "boundary or flow_bc or flow_config" -x
   pytest tests/integration -k "flow" -x
   pytest tests/regression -k "flow" -x
   pytest tests/validation -k "flow" -x
   ```
9. Vérifier que tous les `examples/projects/*/project.toml` chargent
   sans erreur:
   ```
   for f in examples/projects/*/project.toml; do
       python -c "import tomllib; from hydromodpy.config import HydroModPyConfig; HydroModPyConfig.model_validate(tomllib.load(open('$f','rb')))"
   done
   ```
10. Supprimer l'entrée correspondante dans
    `tools/doc_config/dispatchers.py` (`flow.bc.dirichlet.<id>`,
    `flow.bc.cauchy.drainage`, `flow.bc.robin.drainage`,
    `flow.bc.<id>.forcing`).
11. Lancer `python -m tools.doc_config` puis `make -C docs html`,
    vérifier 0 warning et que la page `flow.html` montre maintenant
    la sous-grammaire BC nativement.
12. Commit `[refactor] - native discriminated union for flow.bc`.

### Étape 2 : migrer `[flow.param.<id>]`

1. Créer `class FlowParam(BaseModel)` qui regroupe les 4 sections existantes:
   ```python
   class FlowParam(HydroModelBase):
       field: FieldBaseSection
       field_homogeneous: FieldHomogeneousSection | None = None
       field_heterogeneous: FieldHeterogeneousSection | None = None
       field_vertical_profile: FieldVerticalProfileSection | None = None
   ```
   `FieldParamConfig` dans `hydromodpy/spatial/field/core/field_param_config.py`
   définit déjà cette structure: la réutiliser ou en faire l'alias canonique.
2. Dans `FlowConfig`:
   ```python
   param: Annotated[dict[str, FlowParam], Profile.USER] = Field(default_factory=dict, ...)
   ```
3. Ajouter ou étendre le `@model_validator(mode="before")` de `FlowConfig`
   pour intégrer la résolution actuellement faite par
   `parse_flow_param_sections` / `get_field_param_payload_resolver`:
   - lecture des `[flow.param.<id>.field*]` sub-tables,
   - dispatch sur `kind` (`homogeneous`, `heterogeneous`, ...),
   - résolution des chemins CSV via `base_dir`.
4. Supprimer `param_config.py` du module flow (les fonctions
   `normalize_flow_param_payloads`, `parse_flow_param_sections`,
   `field_param_config_from_flow_payload`).
5. Adapter le validateur `_validate_param_consistency` (déjà sur `FlowConfig`)
   pour fonctionner sur le nouveau type.
6. Lancer la suite de tests `flow.param`:
   ```
   pytest tests/unit -k "field_param or flow_param" -x
   pytest tests/integration -k "flow" -x
   pytest tests/regression -k "flow" -x
   ```
7. Vérifier les `examples/projects/*` (commande de l'étape 1.9).
8. Supprimer les 4 entrées `flow.param.<id>.*` de `dispatchers.py`.
9. Rebuild docs, 0 warning attendu.
10. Commit `[refactor] - native typed dict for flow.param payloads`.

### Étape 3 : élaguer les entrées déjà natives de `dispatchers.py`

Vérifier que la doc est correctement générée sans elles, puis retirer:

- `[flow.sinks_sources.wells.<id>]` (déjà via `FlowWellConfig`),
- `[[data.recharge.sources]]` (déjà via `RechargeSourceConfig` + Literal).

Si le générateur ne produit plus la "Dynamic sub-tables" pour ces paths
parce que les inner_models sont rendus en dropdown classiques, l'entrée
peut être supprimée. Sinon, modifier le générateur pour qu'il rende
toujours les sub-tables dynamiques `dict[str, BaseModel]` et `list[BaseModel]`
sans avoir besoin d'une entrée dispatchers.

Commit `[cleanup] - drop redundant dispatcher entries now covered by native types`.

### Étape 4 : suppression définitive de `dispatchers.py`

Une fois toutes les entrées migrées et la doc validée comme complète:

1. Adapter le générateur (`tools/doc_config/generate.py`):
   - retirer l'import de `dispatchers_for_section`,
   - retirer l'appel à `_render_dispatcher_section`,
   - retirer la section `Dynamic sub-tables` du rendu Couche 2,
   - le rendu déjà existant des inner BaseModels (via les dropdowns
     `Fields of <Model>`) couvre maintenant tous les cas,
   - garder `coverage.py` (avec `INTENTIONALLY_OPAQUE_PATHS`) comme
     filet de sécurité.
2. Supprimer `tools/doc_config/dispatchers.py`.
3. Supprimer la documentation correspondante dans
   `tools/doc_config/README.md`.
4. Mettre à jour `coverage.py` pour ne plus dépendre de `dispatchers.py`:
   maintenant la couverture se fait uniquement avec les inner_models
   accessibles via `_get_inner_basemodels`. Si aucun BaseModel n'est
   trouvé pour un `dict[str, ...]`, c'est forcément un opaque non couvert
   (ou whitelisté).
5. Mettre à jour `docs/source/user_guide/config_reference/recipes.rst`
   et le pointer vers les modèles natifs.
6. Mettre à jour `tools/doc_config/README.md` pour refléter le nouvel
   état:
   - section "What requires a one-line addition: dispatchers" -> supprimée,
   - mention que toute la doc dérive maintenant de `model_fields`
     uniquement,
   - section "Coverage check" devient simplement "garde-fou anti-bricolage".
7. Vérifier que `tests/unit/config/test_native_dispatch.py` passe.
8. Rebuild docs, vérifier 0 warning.
9. Commit `[cleanup] - drop dispatchers table after Pydantic v2 native migration`.

## Tests à adapter

### Tests unitaires existants

Dans `tests/unit/`, identifier et adapter:

- les tests qui asssertent que `FlowConfig.bc` est `dict[str, dict]` (forme post-normalize).
  Maintenant `dict[str, BCEntry]` typé;
- les tests qui appellent directement `normalize_flow_boundary_conditions`,
  `parse_flow_param_sections`, etc. : remplacer par
  `FlowConfig.model_validate({...})`;
- les tests qui dump en `model_dump()` : la sortie peut différer
  marginalement (champs typés vs object). Mettre à jour les assertions.

### Tests d'intégration

`tests/integration/` consomme les `FlowConfig` via le launcher. Vérifier:

- les paths d'erreur (TOML invalide doit toujours produire le même
  type d'erreur, idéalement avec un message Pydantic plus précis);
- les golden TOML existants des fixtures (`tests/regression/fixtures/projects/*/project.toml`)
  chargent sans erreur.

### Nouveaux tests

1. `tests/unit/config/test_native_dispatch.py::test_no_opaque_dicts_in_root_schema`:
   garde-fou structurel.
2. `tests/unit/config/test_flow_bc_native.py`: round-trip
   TOML -> `FlowConfig.model_validate` -> `model_dump_json` -> reload
   pour les 6 ids Dirichlet + cauchy + robin.
3. `tests/unit/config/test_flow_param_native.py`: pareil pour
   les 4 sections par id.
4. `tests/unit/config/test_examples_projects_load.py`: parcourt
   `examples/projects/*/project.toml` et appelle
   `HydroModPyConfig.model_validate`.

## Mise à jour `docs/`

### `docs/source/user_guide/config_reference/`

Le contenu est régénéré automatiquement à chaque build via le hook
`builder-inited`. Aucune édition manuelle des `.rst` générés.

À adapter manuellement:

- `recipes.rst` : si la grammaire TOML utilisateur reste identique,
  zéro changement nécessaire. Sinon, mettre à jour les exemples.
- `validate.rst` : si le contrat reste identique, zéro changement.

### `tools/doc_config/`

- `generate.py` : voir Étape 4.
- `dispatchers.py` : supprimé.
- `coverage.py` : conservé, simplifié, ne dépend plus de `dispatchers.py`.
- `README.md` : reformulé pour décrire un système 100% auto.

### `docs/developers/`

Ajouter un fichier `docs/developers/architecture_config.md` (s'il
n'existe pas) ou amender l'existant pour acter la nouvelle règle:

> Tout payload validé doit être un `BaseModel` typé. `dict[str, object]`
> est interdit en dehors de la whitelist `INTENTIONALLY_OPAQUE_PATHS`.
> Toute grammaire TOML hiérarchique (genre `[a.b.<kind>.<id>]`) se
> traduit en `dict[str, Annotated[Union[...], Field(discriminator=...)]]`
> et la canonicalisation se fait dans un `@model_validator(mode="before")`
> du modèle parent.

## Critères de succès

Le refactor est terminé quand toutes les conditions suivantes sont vraies:

1. `python -m tools.doc_config` n'émet aucun warning de couverture.
2. `pytest tests/unit/config/test_native_dispatch.py` passe.
3. La suite complète `pytest -m fast` passe sans nouvelle régression.
4. `make -C docs html` produit `build succeeded` avec 0 warning Sphinx
   dans `docs/source/user_guide/config_reference/`.
5. Tous les `examples/projects/*/project.toml` chargent via
   `HydroModPyConfig.model_validate` sans erreur.
6. `tools/doc_config/dispatchers.py` n'existe plus.
7. Le grep suivant ne retourne **aucun** résultat dans
   `hydromodpy/`:
   ```
   grep -rE "dict\[str,\s*object\]|dict\[str,\s*dict\[str,\s*object\]\]" hydromodpy/
   ```
   sauf dans `physics/base.py` (contrat abstrait) et les fields marqués
   `exclude=True`.
8. `dispatchers_for_section` n'est plus appelé dans `tools/doc_config/generate.py`.
9. Les fonctions `normalize_flow_boundary_conditions`,
   `parse_flow_param_sections`, `normalize_flow_param_payloads`,
   `field_param_config_from_flow_payload` ne sont plus définies ni
   importées nulle part.
10. La doc HTML générée pour `flow.html` montre les variants BC
    (`Dirichlet`, `Cauchy`, `Robin`) comme des sous-modèles natifs avec
    leurs champs filtrables par profil, sans passer par la section
    "Dynamic sub-tables".

## Conventions à respecter

- Code en anglais, commentaires courts, docstrings simples.
- Ruff lint + format avant chaque commit.
- Format de commit: `[tag] - imperative sentence`. Tags pertinents:
  `refactor`, `cleanup`, `tests`, `docs`.
- Stay sur la branche `dev-docs`. Ne pas push, ne pas amend, ne pas
  ouvrir de PR.
- Aucun shim de compat, aucun alias de retour, aucun re-export.
- Si une migration introduit une rupture inévitable, mettre à jour la
  doc et un test plutôt que d'ajouter un fallback.
- En cas de doute sur une logique de canonicalisation TOML, vérifier
  d'abord que les `examples/projects/*/project.toml` continuent à
  charger, puis seulement après les tests unitaires.
