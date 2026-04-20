# 11 — Architecture Frontend-Ready (API REST + Angular)

> **Objectif** : concevoir la couche HTTP qui expose HydroModPy à un frontend
> Angular (ou tout client web) avec validation de configuration en temps réel,
> suivi de simulations, navigation dans le catalogue et streaming de résultats.
> Le package Python reste local-first, pur, indépendant ; l'API est un vernis.
>
> **Analogie** : c'est le modèle JupyterHub/JupyterServer (Python noyau ↔ REST)
> ou Grafana (noyau Go ↔ frontend React via API OpenAPI), ou encore Apache
> Superset (Flask-AppBuilder ↔ React, modèles SQLAlchemy exposés en JSON
> Schema).
>
> **Préfixes de traçabilité** :
> - [NOUVEAU] : n'existe pas aujourd'hui, à créer.
> - [REFACTORE] : existe mais doit changer pour supporter l'API.
> - [RENOMME] : change de nom.
> - [CONSERVE] : tel quel.

---

## 1. Principes directeurs

### 1.1 Local-first, REST-optionnel

Trois postures concurrentes existent dans l'écosystème Python scientifique :

| Projet | Posture | Compromis |
|---|---|---|
| **Streamlit / Panel** | UI Python, WebSocket ad-hoc | Simple mais couple UI & noyau, pas de frontend tiers |
| **Grafana / Superset** | Noyau + REST + frontend JS | Réutilisable, testable indépendamment |
| **Jupyter Server** | Noyau + REST + WebSocket kernel | Compromis : API stable, frontend pluggable |

HydroModPy adopte la **voie Jupyter Server** :

- `hydromodpy` reste un package Python pur, zéro dépendance web.
- `hydromodpy.api` est un sous-package **optionnel** (`pip install hydromodpy[web]`).
- Tout ce que fait l'API, on peut le faire en Python pur (parité stricte).
- Le frontend Angular est un **dépôt séparé** (`hydromodpy-ui`) qui ne voit que
  l'API HTTP et son contrat OpenAPI/JSON Schema.

```
hydromodpy/              (pur Python, feuille)
├── core/
├── data/
├── spatial/
├── physics/
├── solver/
├── simulation/
├── results/
├── analysis/
└── api/                 [NOUVEAU, extra "web"]
    ├── server.py
    ├── routers/
    ├── schemas/
    ├── streaming/
    └── ws.py

hydromodpy-ui/           (dépôt séparé Angular 18, standalone)
├── src/app/...
├── openapi.json         (généré par hydromodpy api dump-openapi)
└── codegen/             (types TS générés depuis openapi.json)
```

### 1.2 Invariants backend ⇄ frontend

1. **Toute réponse identifiant une simulation la désigne par `sim_id` (UUID
   v5, déterministe)**, jamais par index ou nom. Un `sim_id` est stable à
   jamais.
2. **Tout endpoint qui retourne des données immuables émet `ETag` et
   `Cache-Control: immutable`** (les champs Zarr d'une simulation terminée ne
   changent plus).
3. **Toute mutation de config passe par `POST /config/validate-field`**. Le
   backend ne garde aucun état de session ; le frontend est la source de
   vérité de l'état du formulaire.
4. **Tout nommage de champ est en `snake_case`** (cohérent avec Pydantic), y
   compris dans le JSON retourné. Le frontend transpose en `camelCase` dans
   ses types TS si besoin (`quicktype`/`openapi-generator` gère ça).
5. **Pas de magie dans les réponses** : pas de champs qui apparaissent ou
   disparaissent selon le mode. `ParamLevel` filtre la *visibilité* dans le
   JSON Schema, pas dans les payloads.

### 1.3 Authentification

- **Mode local (défaut)** : aucun token. Le serveur n'écoute que sur
  `127.0.0.1:8765`, middleware CORS accepte uniquement `http://localhost:4200`
  (Angular dev server) et l'origine du bundle embarqué.
- **Mode mono-utilisateur distant** : header `X-HydroModPy-Token` comparé à
  `$HYDROMODPY_API_TOKEN` (constant-time compare). Généré par `hmp api token`.
- **Mode multi-utilisateurs** : hors scope v1. Prévu : OAuth2/OpenID Connect
  via middleware FastAPI dédié, non activé par défaut.

---

## 2. Couche API REST/HTTP (FastAPI)

### 2.1 Stack et layout [NOUVEAU]

```
hydromodpy/api/
├── __init__.py              # create_app() -> FastAPI
├── server.py                # uvicorn launcher
├── dependencies.py          # get_workspace, get_catalog (DI FastAPI)
├── settings.py              # ApiSettings (Pydantic BaseSettings)
├── routers/
│   ├── __init__.py
│   ├── health.py            # GET /health, /version
│   ├── config.py            # /config/*
│   ├── workspaces.py        # /workspaces/*
│   ├── simulations.py       # /simulations/*
│   ├── fields.py            # /simulations/{id}/fields/*
│   ├── timeseries.py        # /simulations/{id}/timeseries/*
│   ├── figures.py           # /simulations/{id}/figures/*
│   ├── calibration.py       # /calibration/*
│   ├── data.py              # /data/* (fetch/cache management)
│   └── exports.py           # /simulations/{id}/export
├── schemas/                 # DTO = Pydantic models spécifiques REST
│   ├── envelopes.py         # ApiResponse, ApiError, ApiPage[T]
│   ├── config.py            # ValidateFieldRequest/Response
│   ├── simulation.py        # SimulationSummary, RunRequest
│   ├── catalog.py           # SimulationFilter, SimulationListItem
│   ├── calibration.py       # IterationRecord, ProgressEvent
│   └── fields.py            # FieldRequest (format/timestep/bbox)
├── streaming/
│   ├── arrow.py             # Arrow IPC writer
│   ├── geojson.py           # GeoJSON streaming
│   ├── msgpack.py           # MessagePack fallback
│   └── ndjson.py            # NDJSON pour calibration traces
├── ws.py                    # WebSocket handlers
├── sse.py                   # Server-Sent Events (alternative)
├── progress.py              # ProgressBus (pub/sub inter-process)
└── cli.py                   # hmp api {serve, token, dump-openapi}
```

### 2.2 Dépendances (pyproject)

```toml
[project.optional-dependencies]
web = [
  "fastapi >=0.115",
  "uvicorn[standard] >=0.30",
  "pydantic >=2.8",           # déjà core
  "pyarrow >=16.0",           # Arrow IPC streaming
  "msgpack >=1.1",            # fallback binaire
  "anyio >=4",                # primitives async partagées
  "python-multipart >=0.0.9", # uploads TOML/fichiers
]
```

### 2.3 Principes REST retenus

- **Orienté ressources** : `/workspaces`, `/simulations`, `/calibration-sessions`.
- **Enveloppe minimale** : `{"data": ..., "meta": {...}}` uniquement pour
  listes paginées ; les ressources unitaires retournent l'objet nu (évite
  l'emballage qui force un déballage côté front).
- **Erreurs RFC 7807** (Problem Details) avec extensions maison :
  ```json
  {
    "type": "https://hydromodpy.dev/errors/validation",
    "title": "Validation failed",
    "status": 422,
    "detail": "Sy doit être dans ]0, 1[",
    "pointer": "/flow/param_payload/Sy",
    "locale": "fr"
  }
  ```
- **Versioning via header** : `Accept: application/vnd.hydromodpy.v1+json`.
  Défaut v1. Pas de `/v1/` dans l'URL (évite la migration de chemins).
- **ETag** : calculé à partir de `sim_id + table_version` (invariant après
  completion) ou `config_hash` pour les validations.

### 2.4 Inventaire complet des endpoints

Légende : `R` = ressource unique, `L` = liste, `A` = action, `S` = streaming.

#### Santé et métadonnées

| Méthode | Path | Type | Description |
|---|---|---|---|
| GET | `/health` | R | liveness (toujours 200 si process up) |
| GET | `/ready` | R | readiness (workspace ouvert, DuckDB accessible) |
| GET | `/version` | R | `{version, git_sha, api_version, solvers: {...}}` |
| GET | `/openapi.json` | R | schéma OpenAPI 3.1 généré par FastAPI |

#### Configuration (cœur du formulaire Angular)

| Méthode | Path | Type | Description |
|---|---|---|---|
| GET | `/config/schema` | R | JSON Schema complet, `?profile=user\|dev\|expert` |
| GET | `/config/schema/{section}` | R | JSON Schema d'une section (ex. `flow`) |
| GET | `/config/template` | R | TOML template par défaut, `?profile=user` |
| POST | `/config/validate` | A | valide un **document complet** (TOML ou JSON) |
| POST | `/config/validate-field` | A | valide **un champ** dans le contexte du modèle partiel (§3) |
| POST | `/config/serialize` | A | JSON → TOML canonique (idempotent) |
| POST | `/config/parse` | A | TOML → JSON normalisé (résout alias, chemins) |

#### Workspace

| Méthode | Path | Type | Description |
|---|---|---|---|
| GET | `/workspaces/current` | R | infos du workspace actif |
| GET | `/workspaces/current/inventory` | R | `{n_sims, n_projects, disk_usage, ...}` |
| GET | `/workspaces/current/projects` | L | labels de projets distincts |

*Le serveur sert **un seul workspace à la fois**. Multi-workspace = hors
scope v1 (un utilisateur = un serveur).*

#### Simulations (CRUD + actions)

| Méthode | Path | Type | Description |
|---|---|---|---|
| POST | `/simulations/run` | A | lance une simulation, retourne `run_id` et `sim_id` |
| GET | `/simulations` | L | liste paginée avec filtres (§2.5) |
| GET | `/simulations/{sim_id}` | R | métadonnées + params + métriques agrégées |
| DELETE | `/simulations/{sim_id}` | A | supprime (DuckDB row + Zarr dir) |
| PATCH | `/simulations/{sim_id}` | A | mutations admises : `name`, `tag`, `description` uniquement |
| GET | `/simulations/{sim_id}/config` | R | config TOML/JSON ayant produit la sim |
| GET | `/simulations/{sim_id}/parameters` | L | table `parameters` projetée |
| GET | `/simulations/{sim_id}/metrics` | L | table `metrics` filtrable par station |
| GET | `/simulations/{sim_id}/budget` | L | table `budgets` pivotable |
| GET | `/simulations/{sim_id}/mass-balance` | L | série `mass_balance` |
| GET | `/simulations/{sim_id}/provenance` | L | fingerprints SHA-256 des inputs |

#### Champs spatiaux

| Méthode | Path | Type | Description |
|---|---|---|---|
| GET | `/simulations/{sim_id}/fields` | L | liste des variables (head, watertable, ...) |
| GET | `/simulations/{sim_id}/fields/{name}` | R/S | un champ, §5 |
| GET | `/simulations/{sim_id}/mesh` | R/S | maillage UGRID (Arrow IPC, GeoJSON, ou NetCDF) |
| GET | `/simulations/{sim_id}/geographic/{feature}` | R | watershed/rivers en GeoJSON |

#### Séries temporelles

| Méthode | Path | Type | Description |
|---|---|---|---|
| GET | `/simulations/{sim_id}/timeseries` | L | stations disponibles |
| GET | `/simulations/{sim_id}/timeseries/{station}` | R/S | série JSON ou Arrow, paginable |
| GET | `/simulations/{sim_id}/timeseries/compare` | A | N sim_ids en une requête |

#### Figures (rendu serveur optionnel)

| Méthode | Path | Type | Description |
|---|---|---|---|
| GET | `/simulations/{sim_id}/figures` | L | figures enregistrées (si display a tourné) |
| GET | `/simulations/{sim_id}/figures/{name}` | R | PNG/SVG cached |
| POST | `/simulations/{sim_id}/figures/render` | A | rendu à la volée d'une figure enregistrée |

*Note : le frontend Angular rend lui-même les cartes via Leaflet/MapLibre et
les séries via ECharts/D3. Les figures matplotlib ne sont renvoyées qu'en PNG
pour export rapide.*

#### Calibration

| Méthode | Path | Type | Description |
|---|---|---|---|
| POST | `/calibration/run` | A | lance une session, retourne `session_id` |
| GET | `/calibration/sessions` | L | liste |
| GET | `/calibration/{session_id}` | R | métadonnées session |
| GET | `/calibration/{session_id}/progress` | R | snapshot courant (polling) |
| GET | `/calibration/{session_id}/iterations` | L/S | historique, Arrow IPC ou JSON |
| GET | `/calibration/{session_id}/pareto` | R | front Pareto si multi-obj |
| POST | `/calibration/{session_id}/cancel` | A | interruption gracieuse |

#### Data (cache d'inputs)

| Méthode | Path | Type | Description |
|---|---|---|---|
| GET | `/data/variables` | L | types disponibles (piezometry, geology, …) |
| GET | `/data/cache` | L | entrées du `data/cache.duckdb` |
| POST | `/data/cache/refresh` | A | force refetch d'un dataset |

#### Exports

| Méthode | Path | Type | Description |
|---|---|---|---|
| POST | `/simulations/{sim_id}/export` | A | produit .hmp/.nc/.tif/etc., retourne URL téléchargement |
| GET | `/exports/{token}` | S | download streaming du fichier |

#### Temps réel

| Protocole | Path | Description |
|---|---|---|
| WebSocket | `/ws/simulations/{run_id}/progress` | événements de progression (step, %, logs) |
| WebSocket | `/ws/calibration/{session_id}/progress` | ticks `tell`, métriques courantes |
| SSE | `/sse/simulations/{run_id}/progress` | alternative unidirectionnelle |
| SSE | `/sse/calibration/{session_id}/iterations` | flux NDJSON d'itérations |

*Pourquoi fournir **les deux** WS et SSE ? SSE est plus simple à cacher
derrière un proxy, supporté nativement par `EventSource` en Angular, et suffit
quand le serveur ne reçoit rien du client. WS pour les cas où on veut que le
client envoie aussi (cancel, pause, zoom temporel).*

### 2.5 Paramètres de liste standardisés

Tous les endpoints `L` acceptent la même grammaire :

| Paramètre | Type | Exemple | Notes |
|---|---|---|---|
| `project` | str | `project=canut` | filtre exact |
| `solver` | str | `solver=modflow6` | enum |
| `status` | str | `status=completed` | enum |
| `tag` | str (rep.) | `tag=v2&tag=prod` | AND |
| `created_after` | ISO 8601 | `created_after=2026-01-01T00:00:00Z` | |
| `nse_gt` | float | `nse_gt=0.7` | seuil |
| `limit` | int | `limit=100` | défaut 50, max 1000 |
| `offset` | int | `offset=200` | pagination offset |
| `cursor` | str | `cursor=eyJ...` | pagination cursor (préférée) |
| `sort` | str | `sort=-created_at,nse` | virgule, `-` pour desc |
| `fields` | str | `fields=sim_id,nse,project` | sparse fieldsets |

Réponse paginée :
```json
{
  "data": [...],
  "meta": {
    "total": 1234,
    "limit": 50,
    "next_cursor": "eyJ0IjogMjAyNi0wMS0wMSJ9",
    "prev_cursor": null
  }
}
```

### 2.6 Exemple complet : `POST /simulations/run`

**Requête** :
```http
POST /simulations/run HTTP/1.1
Content-Type: application/json
Idempotency-Key: 7a8f1c...

{
  "config": { ... HydroModPyConfig au format JSON ... },
  "overrides": {"flow.param_payload.K": 5e-4},
  "name": "canut-test-K5",
  "project": "canut",
  "tag": ["ui", "exploratoire"],
  "async": true
}
```

**Réponse 202 Accepted** :
```json
{
  "run_id": "run-01JF...",
  "sim_id": "a7e3b5e6-...",
  "status": "queued",
  "progress_url": "/ws/simulations/run-01JF.../progress",
  "links": {
    "self": "/simulations/a7e3b5e6-...",
    "progress": "/simulations/a7e3b5e6-.../status"
  }
}
```

**Idempotency** : si le même `Idempotency-Key` arrive deux fois en 24h, la
seconde requête renvoie le premier `run_id` sans relancer. Stocké dans une
table `api_idempotency(key, run_id, created_at)` [NOUVEAU] de la DuckDB
workspace.

### 2.7 Squelette `routers/simulations.py`

```python
from fastapi import APIRouter, Depends, status, Response
from hydromodpy.api.dependencies import get_catalog, get_runner_bus
from hydromodpy.api.schemas.simulation import RunRequest, RunAccepted, SimulationSummary
from hydromodpy.api.schemas.catalog import SimulationFilter, SimulationListItem
from hydromodpy.api.schemas.envelopes import ApiPage
from hydromodpy.results import SimulationCatalog
from hydromodpy.simulation import submit_run

router = APIRouter(prefix="/simulations", tags=["simulations"])


@router.post("/run", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED)
def run_simulation(
    req: RunRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    catalog: SimulationCatalog = Depends(get_catalog),
    bus = Depends(get_runner_bus),
) -> RunAccepted:
    sim_id, run_id = submit_run(
        config=req.to_hydromodpy_config(),
        overrides=req.overrides,
        name=req.name,
        project=req.project,
        tag=req.tag,
        catalog=catalog,
        bus=bus,
        idempotency_key=idempotency_key,
    )
    return RunAccepted(
        run_id=run_id,
        sim_id=sim_id,
        status="queued",
        progress_url=f"/ws/simulations/{run_id}/progress",
    )


@router.get("", response_model=ApiPage[SimulationListItem])
def list_simulations(
    filters: SimulationFilter = Depends(),
    catalog: SimulationCatalog = Depends(get_catalog),
) -> ApiPage[SimulationListItem]:
    group = catalog.find(**filters.to_find_kwargs())
    return ApiPage.from_group(group, cursor=filters.cursor, limit=filters.limit)


@router.get("/{sim_id}", response_model=SimulationSummary)
def get_simulation(
    sim_id: UUID,
    response: Response,
    catalog: SimulationCatalog = Depends(get_catalog),
) -> SimulationSummary:
    sim = catalog.get(sim_id)
    etag = f'"{sim.id.hex}-{sim.schema_version}"'
    response.headers["ETag"] = etag
    if sim.status == "completed":
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return SimulationSummary.from_view(sim)
```

---

## 3. Validation champ-par-champ (critique pour l'UX)

C'est le point le plus délicat. Le formulaire Angular doit pouvoir annoncer
une erreur **pendant que l'utilisateur tape**, sans latence perceptible, et
en tenant compte des dépendances inter-champs (par ex. `flow.active_bc`
référence `stream`, or `hydrography` doit être chargée pour cela).

### 3.1 Contrat REST

**Endpoint** : `POST /config/validate-field`

**Requête** :
```json
{
  "path": "flow.param_payload.Sy",
  "value": 1.5,
  "context": {
    "workspace": {...},
    "geographic": {...},
    "flow": {
      "param_list": ["K", "Sy"],
      "param_payload": {"K": 5e-4, "Sy": 0.1}
    }
  },
  "locale": "fr"
}
```

**Réponse 200** (cas d'erreur) :
```json
{
  "valid": false,
  "path": "flow.param_payload.Sy",
  "error": {
    "code": "value_out_of_bounds",
    "message": "Sy doit être dans ]0, 1[",
    "message_fr": "Sy doit être dans ]0, 1[",
    "pointer": "/flow/param_payload/Sy",
    "suggested_value": 0.1
  },
  "warnings": [],
  "dependent_fields_affected": [
    "flow.initial_conditions.steady",
    "solver.packages.storage"
  ],
  "timing_ms": 4.2
}
```

**Réponse 200** (cas valide) :
```json
{
  "valid": true,
  "path": "flow.param_payload.Sy",
  "error": null,
  "warnings": [
    {
      "code": "unusual_value",
      "message_fr": "Valeur inhabituelle pour un sable (attendu 0.15-0.35).",
      "severity": "advisory"
    }
  ],
  "dependent_fields_affected": [],
  "timing_ms": 1.8
}
```

### 3.2 Structure Pydantic pour validation partielle [REFACTORE]

Pydantic v2 est **déjà capable** de `model_validate` sur un dict complet. Le
problème n'est pas là : c'est que les validators `model_validator(mode="after")`
écrits aujourd'hui assument que toutes les sections sont présentes.

**Règle** : tout validator cross-section doit être **tolérant au modèle
partiel**. On introduit un mode de validation explicite :

```python
# hydromodpy/core/config/partial.py   [NOUVEAU]
from contextvars import ContextVar
from enum import Enum

class ValidationMode(str, Enum):
    STRICT = "strict"     # tous les validators, utilisé au chargement TOML et au run
    PARTIAL = "partial"   # cross-field tolérants, utilisé par l'API validate-field
    SCHEMA = "schema"     # génération de JSON Schema, aucun validator custom

_MODE: ContextVar[ValidationMode] = ContextVar("validation_mode", default=ValidationMode.STRICT)

def validation_mode() -> ValidationMode:
    return _MODE.get()

@contextmanager
def partial_validation():
    token = _MODE.set(ValidationMode.PARTIAL)
    try:
        yield
    finally:
        _MODE.reset(token)
```

Chaque validator cross-section observe ce mode :

```python
# hydromodpy/core/config/flow.py   [REFACTORE]
class FlowConfig(HydroModelBase):
    param_list: list[str]
    param_payload: dict[str, float]

    @model_validator(mode="after")
    def _validate_param_payload_consistency(self) -> "FlowConfig":
        if validation_mode() is ValidationMode.PARTIAL:
            # on se contente de valider l'intra-section
            if any(v <= 0 for v in self.param_payload.values()):
                raise ValueError("Paramètres physiques doivent être > 0")
            return self
        # mode STRICT : cohérence complète
        missing = set(self.param_list) - set(self.param_payload)
        if missing:
            raise ValueError(f"Paramètres déclarés mais non fournis : {missing}")
        return self
```

### 3.3 Service de validation [NOUVEAU]

```python
# hydromodpy/api/services/validation.py
from functools import lru_cache
from typing import Any
from pydantic import ValidationError
from hydromodpy.core.config import HydroModPyConfig, PartialHydroModPyConfig
from hydromodpy.core.config.partial import partial_validation
from hydromodpy.api.schemas.config import FieldValidationResult, FieldError, FieldWarning


class FieldValidator:
    """Valide un champ unique dans le contexte d'un modèle partiel."""

    def __init__(self, model_cls: type = HydroModPyConfig):
        self._model_cls = model_cls
        self._partial_cls = _build_partial_model(model_cls)  # cached

    def validate_field(
        self,
        path: str,
        value: Any,
        context: dict,
        locale: str = "fr",
    ) -> FieldValidationResult:
        patched = _patch_dict(context, path, value)
        try:
            with partial_validation():
                # PartialHydroModPyConfig accepte None partout -> tolérant aux absences
                self._partial_cls.model_validate(patched)
        except ValidationError as e:
            return _format_errors(e, path, locale)

        warnings = _physical_bounds_warn(path, value, locale)
        deps = _dependency_graph.affected_by(path)  # statique, calculé au boot
        return FieldValidationResult(
            valid=True, path=path, error=None, warnings=warnings,
            dependent_fields_affected=deps,
        )
```

Points clés :

- **`PartialHydroModPyConfig`** est un modèle généré au démarrage du serveur
  à partir de `HydroModPyConfig` en rendant tout champ `Optional` **en
  profondeur**. Implémentation via `pydantic.create_model` récursif.
  Construit **une fois** au boot, caché ; pas de reconstruction par requête.
- **`_patch_dict(context, path, value)`** applique le delta (dotted path +
  liste d'indices) sur un deepcopy. Implémenté en ~40 lignes de code pur.
- **`_physical_bounds_warn`** consulte une table centralisée
  `PHYSICAL_BOUNDS` (K, Sy, Ss, porosity…) avec domaines « plausibles » et
  retourne des avertissements non-bloquants.
- **`_dependency_graph`** : graphe statique des champs qui s'influencent,
  calculé par introspection du JSON Schema et des `model_validator` ; pas
  recalculé à chaque requête.

### 3.4 Modèle partiel généré

```python
# hydromodpy/core/config/partial_builder.py   [NOUVEAU]
from typing import Any, Optional, get_args, get_origin
from pydantic import BaseModel, create_model

def build_partial(model_cls: type[BaseModel]) -> type[BaseModel]:
    """Crée récursivement une version où tout champ est Optional[...]."""
    fields: dict[str, Any] = {}
    for name, fi in model_cls.model_fields.items():
        ann = _make_optional(fi.annotation)
        fields[name] = (ann, None)
    partial_cls = create_model(
        f"Partial{model_cls.__name__}",
        __base__=model_cls,   # hérite donc des validators
        **fields,
    )
    return partial_cls

def _make_optional(ann):
    if _is_basemodel(ann):
        return Optional[build_partial(ann)]
    if get_origin(ann) in (list, tuple, set, dict):
        inner = tuple(_make_optional(a) if _is_basemodel(a) else a for a in get_args(ann))
        return Optional[get_origin(ann)[inner]]
    return Optional[ann]
```

Héritant de la classe cible, les validators `model_validator(mode="after")`
restent appliqués — mais le mode `PARTIAL` leur permet de passer sans planter.

### 3.5 Budget de latence

Cible **<50 ms p95** par requête `/config/validate-field`. Budget indicatif :

| Étape | Budget | Mesure |
|---|---|---|
| HTTP + JSON parse | 5 ms | uvicorn + orjson |
| `_patch_dict` (deepcopy d'un ~200 champs) | 2 ms | |
| `PartialHydroModPyConfig.model_validate` | 10-25 ms | Pydantic v2 compilé Rust |
| `_physical_bounds_warn` | 0.5 ms | lookup dict |
| `_dependency_graph.affected_by` | 0.1 ms | lookup dict |
| JSON serialize + HTTP | 3 ms | |
| **Total** | **~35 ms** | |

Optimisations si nécessaire :
- **Cache du model_validate** sur hash du context (évite de re-valider si
  l'utilisateur touche plusieurs champs à la suite avec le même contexte).
- **Fallback field-local** : si `path` n'a aucune dépendance connue dans le
  graphe, on ne valide que le sous-modèle contenant ce champ (ex. `FlowConfig`
  seul).
- **Mode « dirty only »** : le client envoie un `context_hash` ; si identique
  au précédent, seul le champ modifié est validé.

### 3.6 Diagnostics i18n

Pydantic v2 n'expose pas nativement de messages localisés. On introduit une
couche de traduction [NOUVEAU] :

```python
# hydromodpy/api/services/i18n.py
_ERROR_CATALOG_FR = {
    "value_error": "Valeur invalide",
    "greater_than": "La valeur doit être strictement supérieure à {gt}",
    "less_than": "La valeur doit être strictement inférieure à {lt}",
    "string_pattern_mismatch": "Format attendu : {pattern}",
    # + codes custom Sy bounds, etc.
}

def translate(err: ErrorDetails, locale: str) -> str:
    if locale == "fr":
        key = err["type"]
        ctx = err.get("ctx", {})
        return _ERROR_CATALOG_FR.get(key, err["msg"]).format(**ctx)
    return err["msg"]
```

Alternative : `pydantic` émet un `type` machine-lisible pour chaque erreur.
Le frontend peut traduire lui-même à partir du `code` si on préfère déporter
l'i18n côté Angular (option retenue : on renvoie les deux, `code` + `message_fr`,
le frontend choisit).

---

## 4. JSON Schema depuis Pydantic

### 4.1 Génération de base

Pydantic v2 retourne un JSON Schema Draft 2020-12 via
`HydroModPyConfig.model_json_schema()`. Cela couvre 80 % du besoin :
`type`, `minimum`, `maximum`, `enum`, `required`, `$ref`.

Ce qui manque pour Angular :
- Étiquettes FR pour les labels de formulaire.
- Unité physique (pour afficher « m/s » à côté du champ).
- `widget_type` (slider, select, file picker, checkbox).
- `help_text_fr` / `placeholder`.
- `step` pour les sliders, `scale` (linéaire/log) pour les valeurs de K, Sy.
- Visibilité par profil (`user`/`dev`/`expert`).
- Groupes visuels (`category`) pour organiser le formulaire en onglets.

### 4.2 Annotations [NOUVEAU] : `ui_meta`

On centralise toutes les annotations UI dans une dataclass injectée via
`json_schema_extra`. Convention unique, évite la dispersion.

```python
# hydromodpy/core/config/ui_meta.py   [NOUVEAU]
from dataclasses import asdict, dataclass, field
from typing import Literal
from pydantic import Field

WidgetType = Literal["input", "slider", "select", "multiselect", "checkbox",
                     "radio", "file", "path", "textarea", "color", "date",
                     "datetime", "duration", "coord", "crs", "bbox"]

Scale = Literal["linear", "log", "symlog"]

@dataclass(frozen=True)
class UiMeta:
    label_fr: str
    label_en: str | None = None
    help_fr: str | None = None
    help_en: str | None = None
    unit: str | None = None              # "m/s", "m", "days", "kg/m³", "-"
    widget: WidgetType = "input"
    placeholder: str | None = None
    step: float | None = None            # pour sliders
    scale: Scale = "linear"
    group: str | None = None             # ex. "Hydraulique", "Conditions initiales"
    order: int = 0                       # tri intra-groupe
    profile: Literal["user", "dev", "expert"] = "user"
    examples: list = field(default_factory=list)
    readonly: bool = False
    deprecated: bool = False

    def to_schema_extra(self) -> dict:
        d = asdict(self)
        return {f"x-{k.replace('_', '-')}": v for k, v in d.items() if v not in (None, [], "")}


def ui(**kw):
    """Helper pour annoter un champ Pydantic."""
    return Field(json_schema_extra=UiMeta(**kw).to_schema_extra())
```

### 4.3 Exemple annoté : `FlowConfig` [REFACTORE]

```python
# hydromodpy/core/config/flow.py (extrait)
from typing import Annotated
from pydantic import Field, PositiveFloat
from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.ui_meta import ui, UiMeta

class FlowInitialConditions(HydroModelBase):
    steady: bool = ui(
        label_fr="Régime permanent initial",
        help_fr="Démarre la simulation en régime permanent (recommandé).",
        widget="checkbox",
        group="Conditions initiales",
        order=1,
    )
    steady_recharge_mm_yr: Annotated[float, Field(gt=0, le=3000)] = ui(
        label_fr="Recharge moyenne (mm/an)",
        help_fr="Utilisée pour calculer la condition initiale permanente.",
        unit="mm/yr",
        widget="input",
        step=10.0,
        group="Conditions initiales",
        order=2,
        examples=[250.0, 400.0, 650.0],
    )


class FlowConfig(HydroModelBase):
    active_bc: list[str] = ui(
        label_fr="Conditions aux limites actives",
        help_fr="Sélectionnez les BC à activer. `stream` nécessite l'hydrographie.",
        widget="multiselect",
        group="Conditions aux limites",
        order=1,
        examples=[["stream"], ["stream", "ocean"]],
    )
    param_list: list[str] = ui(
        label_fr="Paramètres calibrables",
        widget="multiselect",
        group="Paramétrisation",
        profile="dev",
        order=1,
    )
    param_payload: dict[str, PositiveFloat] = ui(
        label_fr="Valeurs des paramètres",
        widget="input",
        group="Paramétrisation",
        order=2,
    )
    hydraulic_conductivity_m_s: Annotated[float, Field(gt=1e-12, lt=1e-1)] = ui(
        label_fr="Conductivité hydraulique (K)",
        help_fr="Valeur typique : sable 1e-4 à 1e-2 m/s, argile 1e-10 à 1e-7 m/s.",
        unit="m/s",
        widget="slider",
        scale="log",
        step=0.1,
        group="Hydraulique",
        order=1,
        examples=[1e-5, 1e-4, 1e-3],
    )
    specific_yield: Annotated[float, Field(gt=0, lt=1)] = ui(
        label_fr="Porosité efficace (Sy)",
        help_fr="Valeur typique : 0.01 (argile) à 0.35 (sable grossier).",
        unit="-",
        widget="slider",
        scale="linear",
        step=0.005,
        group="Hydraulique",
        order=2,
    )
```

### 4.4 JSON Schema généré (extrait)

```json
{
  "$defs": {
    "FlowConfig": {
      "type": "object",
      "title": "FlowConfig",
      "properties": {
        "hydraulic_conductivity_m_s": {
          "type": "number",
          "exclusiveMinimum": 1e-12,
          "exclusiveMaximum": 0.1,
          "x-label-fr": "Conductivité hydraulique (K)",
          "x-help-fr": "Valeur typique : sable 1e-4 à 1e-2 m/s, argile 1e-10 à 1e-7 m/s.",
          "x-unit": "m/s",
          "x-widget": "slider",
          "x-scale": "log",
          "x-step": 0.1,
          "x-group": "Hydraulique",
          "x-order": 1,
          "x-profile": "user",
          "x-examples": [1e-5, 1e-4, 1e-3]
        },
        "specific_yield": {
          "type": "number",
          "exclusiveMinimum": 0,
          "exclusiveMaximum": 1,
          "x-label-fr": "Porosité efficace (Sy)",
          "x-unit": "-",
          "x-widget": "slider",
          "x-scale": "linear",
          "x-step": 0.005,
          "x-group": "Hydraulique",
          "x-order": 2
        }
      },
      "required": ["active_bc", "param_list", "param_payload",
                   "hydraulic_conductivity_m_s", "specific_yield"]
    }
  }
}
```

Convention `x-*` : préfixe standardisé JSON Schema pour extensions
vendor-specific. Les générateurs TypeScript (`quicktype`, `openapi-generator`)
les préservent tels quels ; le frontend les consomme via un service
`SchemaUiMeta`.

### 4.5 Filtre par profil

`GET /config/schema?profile=user` : le serveur retourne un schéma où tous
les champs avec `x-profile=dev` ou `x-profile=expert` sont supprimés du
`properties` et du `required`. Implémentation :

```python
# hydromodpy/api/services/schema.py
def filter_schema_by_profile(schema: dict, profile: Literal["user", "dev", "expert"]) -> dict:
    allowed = {"user", "dev", "expert"}
    if profile == "user":
        allowed = {"user"}
    elif profile == "dev":
        allowed = {"user", "dev"}
    return _walk_filter(schema, lambda prop: prop.get("x-profile", "user") in allowed)
```

### 4.6 Pipeline Angular → JSON Schema

Côté frontend, deux briques existantes consomment ce schéma :
- `ajv` pour la validation locale instantanée (doublon du serveur, utilisé
  quand la latence réseau est perceptible).
- `ngx-formly` ou `@rjsf/core` (React JSON Schema Form, porté en Angular)
  pour rendre automatiquement le formulaire, en fournissant un mapping
  `x-widget` → composant Angular.

---

## 5. Streaming des résultats

### 5.1 Problème

Un champ spatial (ex. `head`) sur une maille de 100 000 cellules × 10
couches × 1000 pas de temps = 1 Go non compressé. En JSON brut, c'est
impraticable. On a besoin de formats binaires efficaces ET de pagination/
crop.

### 5.2 Matrice des formats

| Format | Cas d'usage | Négociation | Taille |
|---|---|---|---|
| **JSON** | petite série temporelle, métriques | `Accept: application/json` | baseline |
| **GeoJSON** | vecteurs (rivières, bassin, points) | `Accept: application/geo+json` | idem |
| **Arrow IPC** | champs, longues séries | `Accept: application/vnd.apache.arrow.stream` | ~5-10× JSON |
| **MessagePack** | structures arbitraires | `Accept: application/msgpack` | ~3× JSON |
| **NetCDF** | export scientifique | `Accept: application/x-netcdf` | CF-compliant |
| **GeoTIFF** | rasters | `Accept: image/tiff` | géo-référencé |
| **PNG/WebP** | visuel direct map | `Accept: image/png` | thumbnail |

Le frontend Angular privilégie **Arrow IPC** pour les champs (via
`apache-arrow` npm) et **GeoJSON** pour les vecteurs (via
`leaflet`/`maplibre-gl`).

### 5.3 Endpoint `/fields/{name}` [NOUVEAU]

**Paramètres** :

| Paramètre | Type | Description |
|---|---|---|
| `timestep` | int | index temporel (-1 = dernier) |
| `timestep_from`, `timestep_to` | int | range |
| `layer` | int | couche (défaut 0) |
| `bbox` | str | `xmin,ymin,xmax,ymax` (filtrage spatial) |
| `cells` | str | liste d'IDs de cellules (sparse) |
| `decimate` | int | facteur de sous-échantillonnage cellulaire |
| `format` | str | override `Accept` header |

**Réponse Arrow IPC** :
```
HTTP/1.1 200 OK
Content-Type: application/vnd.apache.arrow.stream
ETag: "a7e3b5e6-head-v3-ts5"
Cache-Control: public, max-age=31536000, immutable

<Arrow IPC stream :
  schema {cell_id: int64, x: float64, y: float64, value: float64}
  + N record batches de 10_000 lignes
>
```

**Squelette serveur** :

```python
# hydromodpy/api/routers/fields.py
import pyarrow as pa
import pyarrow.ipc as ipc
from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse

router = APIRouter()

@router.get("/simulations/{sim_id}/fields/{name}")
def get_field(sim_id: UUID, name: str, timestep: int = -1, layer: int = 0,
              bbox: str | None = None, accept: str = Header(default="application/json")):
    sim = catalog.get(sim_id)
    arr = sim.field(name, timestep=timestep, layer=layer)
    if bbox:
        arr = _crop_bbox(arr, _parse_bbox(bbox))
    if "arrow" in accept:
        return StreamingResponse(
            _stream_arrow(arr),
            media_type="application/vnd.apache.arrow.stream",
            headers={"ETag": _etag(sim, name, timestep, layer),
                     "Cache-Control": "public, max-age=31536000, immutable"},
        )
    if "geo+json" in accept:
        return _geojson_response(arr, sim.mesh)
    return _json_response(arr)


def _stream_arrow(arr, batch_size: int = 10_000):
    table = pa.Table.from_pydict({
        "cell_id": arr.cell_id.values,
        "x": arr.x.values, "y": arr.y.values,
        "value": arr.values.astype("float64"),
    })
    buf = io.BytesIO()
    with ipc.new_stream(buf, table.schema) as writer:
        for batch in table.to_batches(max_chunksize=batch_size):
            writer.write_batch(batch)
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)
```

### 5.4 Séries temporelles : pagination

Endpoint `/simulations/{sim_id}/timeseries/{station}` accepte :
- `variable=head`
- `from=2020-01-01`, `to=2023-12-31`
- `step=1D` (resample côté serveur via pandas)
- `limit=10000`, `cursor=...` pour paginer
- `format=arrow` ou `format=json`

Réponse JSON paginée :
```json
{
  "station": "P01",
  "variable": "head",
  "unit": "m",
  "data": [["2020-01-01T00:00:00Z", 42.15], ...],
  "meta": {"total": 87650, "next_cursor": "eyJ0IjogIjIwMjEtMDEtMDEifQ=="}
}
```

Réponse Arrow : deux colonnes `time: timestamp[ns]`, `value: float64`.

### 5.5 Cache HTTP et versioning

- **Champs d'une simulation `completed`** : `Cache-Control: public,
  max-age=31536000, immutable`. Le frontend peut cacher éternellement.
- **ETag** : `"{sim_id}-{resource}-{schema_version}"`. Schema_version change
  quand on migre le Zarr.
- **Simulation `running`** : `Cache-Control: no-store`. Re-lecture à chaque
  fois.
- **JSON Schema** : `Cache-Control: public, max-age=3600` (change rarement),
  ETag = git_sha du paquet.
- **Vary: Accept** pour que les caches distinguent Arrow/JSON/GeoJSON.

### 5.6 Compression

`uvicorn` avec middleware `GZipMiddleware(minimum_size=1024)` pour les
réponses JSON. Pour Arrow IPC, **pas de gzip HTTP** (Arrow a son propre
compressage LZ4/ZSTD au niveau batch) ; si on veut compresser en plus, on
utilise `Content-Encoding: zstd`.

### 5.7 Tuiles vectorielles pour les champs denses

Pour un champ de >1M cellules, l'approche Arrow d'un seul coup devient
lourde. Alternative [NOUVEAU] inspirée de `titiler` et `martin` :

- `GET /simulations/{sim_id}/fields/{name}/tiles/{z}/{x}/{y}.pbf` retourne
  une tuile vectorielle MVT (Mapbox Vector Tile).
- Généré à la demande par `rasterio` + `mapbox-vector-tile`.
- Le frontend utilise `maplibre-gl` pour le rendu.

Hors scope v1, recommandé v2 dès que la taille de maille dépasse ~500k.

---

## 6. Temps réel : progression des simulations et calibration

### 6.1 ProgressBus [NOUVEAU]

Les simulations tournent dans un ProcessPoolExecutor détaché du serveur
FastAPI. Elles publient leurs événements dans un bus partagé lisible par
le serveur.

```
simulation worker (process)        FastAPI process
──────────────────────────          ────────────────
progress_callback(event)  ────►     ProgressBus.subscribe(run_id)
                          redis/                        │
                          file/IPC                       ▼
                                        WebSocket /ws/.../progress
                                        SSE        /sse/.../progress
```

**Implémentation v1** : fichier NDJSON append-only par run dans
`workspace/.hmp/progress/{run_id}.ndjson`, lu côté FastAPI avec `inotify`
(Linux) ou polling 100ms (fallback). Léger, zéro dépendance, observable
en CLI (`tail -f`).

**Implémentation v2** (si multi-worker) : Redis pub/sub.

### 6.2 Schéma d'événement

Un seul type de message, union discriminée sur `event` :

```python
# hydromodpy/api/schemas/progress.py
from typing import Literal, Union
from pydantic import BaseModel, Field

class StepStarted(BaseModel):
    event: Literal["step_started"] = "step_started"
    run_id: str
    step: str                    # "validate", "mesh", "solve", ...
    step_index: int
    started_at: datetime

class StepProgress(BaseModel):
    event: Literal["step_progress"] = "step_progress"
    run_id: str
    step: str
    progress: float              # 0..1
    message: str | None = None

class StepCompleted(BaseModel):
    event: Literal["step_completed"] = "step_completed"
    run_id: str
    step: str
    duration_ms: int

class SolverIteration(BaseModel):
    event: Literal["solver_iteration"] = "solver_iteration"
    run_id: str
    iteration: int
    residual: float
    current_time_step: int

class RunCompleted(BaseModel):
    event: Literal["run_completed"] = "run_completed"
    run_id: str
    sim_id: UUID
    status: Literal["completed", "failed", "cancelled"]
    error: str | None = None

ProgressEvent = Annotated[
    Union[StepStarted, StepProgress, StepCompleted, SolverIteration, RunCompleted],
    Field(discriminator="event"),
]
```

### 6.3 WebSocket handler

```python
# hydromodpy/api/ws.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from hydromodpy.api.progress import ProgressBus

router = APIRouter()

@router.websocket("/ws/simulations/{run_id}/progress")
async def simulation_progress(websocket: WebSocket, run_id: str, bus: ProgressBus = Depends(get_bus)):
    await websocket.accept()
    try:
        async for event in bus.subscribe(run_id):
            await websocket.send_json(event.model_dump(mode="json"))
            if event.event == "run_completed":
                break
    except WebSocketDisconnect:
        pass
```

### 6.4 Calibration : historique + flux

- `GET /calibration/{session_id}/iterations?format=arrow` : retourne tout
  l'historique en un coup (Arrow IPC). Utilisé au premier chargement du
  dashboard.
- `GET /sse/calibration/{session_id}/iterations` : SSE qui diffuse chaque
  nouvelle itération au fur et à mesure. Utilisé ensuite (stream
  incrémental).
- `GET /calibration/{session_id}/progress` : snapshot courant `{n_done,
  n_budget, best_metric, elapsed_s, eta_s}`.

Le frontend Angular :
1. Charge l'historique complet (cache local).
2. Branche SSE pour les nouvelles itérations.
3. À la déconnexion/reconnexion, rejoue depuis `last_event_id` (SSE le gère
   nativement via header `Last-Event-ID`).

---

## 7. Séparation backend ⇄ frontend

### 7.1 Organisation des dépôts

```
hydromodpy/                  (monorepo Python actuel)
├── pyproject.toml           (extra "web")
├── hydromodpy/              (noyau pur)
└── hydromodpy/api/          (extra, zéro dépendance obligatoire)

hydromodpy-ui/               (dépôt séparé Angular, NOUVEAU)
├── angular.json
├── package.json
├── openapi.json             (artefact généré par hmp api dump-openapi)
├── src/
│   ├── app/
│   │   ├── core/            (services HTTP, WS, SSE, schema)
│   │   ├── shared/          (form widgets, charts)
│   │   ├── features/
│   │   │   ├── config-editor/
│   │   │   ├── catalog-browser/
│   │   │   ├── simulation-runner/
│   │   │   ├── field-viewer/
│   │   │   ├── timeseries-plotter/
│   │   │   ├── calibration-dashboard/
│   │   │   └── comparison-workbench/
│   │   └── app.config.ts
│   └── environments/
└── scripts/
    └── codegen.sh           (openapi-generator-cli -> src/app/api/generated/)
```

### 7.2 Génération de types TS

```bash
# dans hydromodpy-ui/
hmp api dump-openapi --output ./openapi.json
npx openapi-typescript ./openapi.json --output src/app/api/generated/schema.ts
npx quicktype --src openapi.json --src-lang schema --lang typescript \
  --out src/app/api/generated/models.ts
```

CI :  
- HydroModPy publie un artefact `openapi.json` signé à chaque tag.
- `hydromodpy-ui` a un job qui compare `openapi.json` courant vs produit
  par le serveur tag-local ; PR échoue si l'API a dérivé sans bump.

### 7.3 Parité API Python ⇄ HTTP

Chaque endpoint HTTP correspond 1:1 à une fonction Python publique. On le
formalise par un tableau de correspondance (testé en CI) :

| Python (hmp) | HTTP |
|---|---|
| `catalog.find(**filters)` | `GET /simulations` |
| `catalog.get(sim_id)` | `GET /simulations/{sim_id}` |
| `sim.field(name, timestep, layer)` | `GET /simulations/{sim_id}/fields/{name}` |
| `sim.timeseries(var, station)` | `GET /simulations/{sim_id}/timeseries/{station}` |
| `sim.metrics(station)` | `GET /simulations/{sim_id}/metrics` |
| `Simulation(config).run()` | `POST /simulations/run` |
| `hmp.compare([a, b])` | `POST /simulations/compare` |

**Test de parité** [NOUVEAU] : `tests/api/test_parity.py` exécute
chaque appel Python et son pendant HTTP sur un workspace de fixture et
compare les résultats (tolérance float sur Arrow ↔ DataFrame).

### 7.4 CORS et sécurité

```python
# hydromodpy/api/server.py
def create_app(settings: ApiSettings) -> FastAPI:
    app = FastAPI(
        title="HydroModPy API",
        version=hydromodpy.__version__,
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,         # ["http://localhost:4200"]
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Accept",
                       "X-HydroModPy-Token", "Idempotency-Key"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    if settings.api_token:
        app.add_middleware(SimpleTokenAuthMiddleware, token=settings.api_token)
    _register_routers(app)
    _register_exception_handlers(app)
    return app
```

### 7.5 Commande CLI

```bash
hmp api serve [--host 127.0.0.1] [--port 8765] [--workspace PATH]
              [--cors http://localhost:4200] [--token-env HYDROMODPY_API_TOKEN]
              [--reload]   # dev
hmp api token [--rotate]
hmp api dump-openapi [--output openapi.json]
```

---

## 8. Impact sur les phases précédentes

### 8.1 Modifications minimales des modèles Pydantic (phase 02)

| Élément | Action | Raison |
|---|---|---|
| `HydroModelBase.model_config` | [REFACTORE] ajouter `extra="forbid"` de façon globale, `populate_by_name=True`, `ser_json_bytes="base64"` | API REST strict |
| `ParamLevel` → `UiMeta` | [RENOMME] intégrer tous les métadonnées UI dans `UiMeta`, `ParamLevel` devient champ `profile` | Un seul endroit pour les métadonnées UI |
| `FlowConfig`, `TransportConfig`, etc. | [REFACTORE] ajouter `ui(...)` sur chaque champ | JSON Schema riche |
| Validators `model_validator(mode="after")` | [REFACTORE] consulter `validation_mode()` pour supporter partiel | `/config/validate-field` |
| `HydroModPyConfig` | [REFACTORE] aucun champ ne doit dépendre de l'ordre de parsing TOML | JSON input |
| `PartialHydroModPyConfig` | [NOUVEAU] généré via `build_partial` | Validation champ |

**Conséquence sur les noms de champs** : aucun changement de nom requis, le
`snake_case` actuel est REST-compatible. La sérialisation JSON sort
naturellement en `snake_case`.

### 8.2 Storage (phase 04)

| Élément | Action | Raison |
|---|---|---|
| PK manquantes (`timeseries`, `budgets`, `mass_balance`) | [REFACTORE] ajouter | Unicité garantie en API |
| FK manquantes | [REFACTORE] déclarer `ON DELETE CASCADE` | Suppression propre via `DELETE /simulations/{id}` |
| `period_start/end` VARCHAR | [REFACTORE] → `TIMESTAMPTZ` | Filtres temporels API |
| `api_idempotency(key, run_id, created_at)` | [NOUVEAU] table | Idempotence `POST /simulations/run` |
| `progress_log(run_id, ts, event JSON)` | [NOUVEAU] table optionnelle | Historique WS si besoin rejeu |
| `api_exports(token, sim_id, format, path, expires_at)` | [NOUVEAU] table | `GET /exports/{token}` |
| `SimulationCatalog.get(sim_id) -> SimulationView` | [NOUVEAU méthode publique] | déjà dans phase 10, confirmer |
| `SimulationView.etag()` | [NOUVEAU] | calcul ETag cohérent |

### 8.3 Pipeline d'exécution (phase 06)

| Élément | Action | Raison |
|---|---|---|
| Step `progress_callback` | [REFACTORE] formaliser la signature : `Callable[[ProgressEvent], None]` | WS/SSE |
| `submit_run(...)` | [NOUVEAU] fonction de haut niveau qui accepte une config, démarre un worker et retourne `(sim_id, run_id)` sans attendre | `POST /simulations/run` asynchrone |
| `SimulationRunner.cancel(run_id)` | [NOUVEAU] | `POST /simulations/{id}/cancel` |
| Writer NDJSON progression | [NOUVEAU] `hydromodpy/simulation/progress_writer.py` | sous-jacent au bus |

### 8.4 Calibration (phase 07)

| Élément | Action | Raison |
|---|---|---|
| `CalibrationEngine.on_iteration(callback)` | [NOUVEAU] | SSE iterations |
| `CalibrationSession.cancel()` | [NOUVEAU] | `POST /calibration/{id}/cancel` |
| Colonne `status` dans `calibration_sessions` | [REFACTORE] enum complet (`running`, `completed`, `cancelled`, `failed`) | |

### 8.5 Postprocess et display (phase 08)

| Élément | Action | Raison |
|---|---|---|
| Figure Protocol → `.to_png_bytes()` | [NOUVEAU méthode] | `GET /figures/{name}` serveur |
| Figure Protocol → `.serialize_spec()` | [NOUVEAU] retourne le FigureSpec JSON | frontend peut re-rendre côté client |
| Colormaps registre | [CONSERVE] déjà présent, simplement exposé via `GET /config/colormaps` | |

### 8.6 Tests (phase 09)

Nouveaux fichiers :

```
tests/api/
├── conftest.py                    # fixture FastAPI TestClient + workspace temporaire
├── test_config_schema.py           # GET /config/schema -> snapshots
├── test_validate_field.py          # latence + cas limites
├── test_simulations_crud.py
├── test_fields_streaming.py        # Arrow IPC round-trip
├── test_timeseries_pagination.py
├── test_progress_ws.py             # WS mock
├── test_calibration_sse.py
├── test_parity_python_http.py      # parité API Python vs HTTP
└── test_auth.py                    # token, CORS
```

Marqueurs : `pytest -m api`. Tous les tests API utilisent un workspace
temp et ne nécessitent aucun solveur (mocké au niveau `submit_run`).

### 8.7 Documentation

Ajouter dans `docs/readthedocs/` :
- `api_http.rst` : guide complet des endpoints.
- `frontend_ready.rst` : pointer vers `hydromodpy-ui`.
- `jsonschema_annotations.rst` : cookbook `ui()`.

---

## 9. Pratiques de référence (comparaison)

| Projet | Ce qu'on emprunte |
|---|---|
| **Jupyter Server** | Noyau + REST + WS clair, workspace unique par serveur |
| **JupyterHub** | Auth modulable (hors scope v1 mais prévu) |
| **Grafana** | OpenAPI strict, stabilité du contrat, headers de version |
| **Apache Superset** | JSON Schema piloté, édition par sections |
| **MLflow** | Artifacts serving par URI, catalog + runs model |
| **titiler** | Arrow + tuiles vectorielles pour données géospatiales |
| **fiftyone** | Dataset catalog exposé REST + WS temps réel |
| **GeoServer / pygeoapi** | OGC API Features (à terme, compatibilité CRS) |
| **OpenDAP / ERDDAP** | Pagination de Dataset, subset via query params |
| **Pangeo / xpublish** | xarray → REST (inspiration pour `/fields`) |

Notamment, **xpublish** (https://xpublish.readthedocs.io/) fournit déjà une
couche FastAPI qui expose un xarray.Dataset en REST avec Zarr/NetCDF. On
peut **s'en inspirer** pour les endpoints `/fields` (mais pas l'importer :
on veut contrôler les formats et garder l'API cohérente avec le reste).

---

## 10. Checklist d'implémentation (ordre suggéré)

1. **[core/config]** introduire `UiMeta`, annoter progressivement les
   modèles Pydantic, activer `extra="forbid"` partout. *Effort : 1 semaine.*
2. **[core/config]** `build_partial`, `ValidationMode`, refactor des
   validators cross-field pour tolérer le mode PARTIAL. *Effort : 3-4 jours.*
3. **[results]** ajouter PKs, FKs, TIMESTAMPTZ ; migration
   `_schema_version` v2→v3. *Effort : 3 jours.*
4. **[simulation]** formaliser `submit_run`, `ProgressEvent`, writer NDJSON.
   *Effort : 3-4 jours.*
5. **[api]** scaffold FastAPI, routers health/version/config/schema,
   validator service (§3). *Effort : 1 semaine.*
6. **[api]** routers simulations, catalog, metrics, budget. *Effort : 1
   semaine.*
7. **[api]** routers fields (Arrow IPC), timeseries, streaming. *Effort : 1
   semaine.*
8. **[api]** WS/SSE progression + calibration. *Effort : 3-4 jours.*
9. **[api]** tests parité Python ⇄ HTTP + tests de latence
   `validate-field`. *Effort : 3 jours.*
10. **[ui]** bootstrap `hydromodpy-ui` (Angular 18 standalone), codegen
    OpenAPI, premier formulaire piloté par JSON Schema. *Effort :
    parallèle, 2 semaines.*
11. **[doc]** `api_http.rst`, `jsonschema_annotations.rst`, exemple curl/HTTPie.

**Durée cible totale backend** : ~6 semaines à temps plein pour atteindre
la v1 frontend-ready.

---

## 11. Ce que l'on NE fait PAS en v1

Liste explicite pour éviter les dérives :

- **Pas** d'authentification multi-utilisateurs (OAuth2).
- **Pas** de base de données autre que DuckDB (pas de Postgres).
- **Pas** de queue externe (Celery, RQ) ; `ProcessPoolExecutor` suffit en
  local.
- **Pas** de GraphQL ; REST + JSON Schema est plus simple à outiller.
- **Pas** de gRPC ; Arrow IPC via HTTP fait le job binaire.
- **Pas** de SSE bidirectionnel (contradictoire) — on choisit WS pour
  bidir, SSE pour unidir.
- **Pas** de cache Redis ; cache in-process FastAPI (`@lru_cache`) + cache
  HTTP.
- **Pas** de multi-workspace simultané ; un workspace par process.
- **Pas** de tenant/isolation ; local-first.
- **Pas** de hot-reload du schéma Pydantic ; changement de schéma = redémarrer
  le serveur.

---

## 12. Résumé

Ce document pose les fondations d'une exposition HTTP propre de HydroModPy,
sans trahir le principe local-first :

- **API REST FastAPI** dans `hydromodpy/api/`, extra `[web]`, aucun impact
  sur le noyau.
- **Validation champ-par-champ < 50 ms** via `PartialHydroModPyConfig`
  généré, `ValidationMode` contextuel, graphe statique de dépendances.
- **JSON Schema enrichi** via `UiMeta` et `ui()` — labels FR, unités,
  widget_type, profil, help_text — directement consommable par
  `ngx-formly` ou `@rjsf/core`.
- **Streaming** : Arrow IPC pour champs et séries longues, GeoJSON pour
  vecteurs, cache HTTP immutable sur ressources finalisées.
- **Temps réel** : WebSocket + SSE alimentés par un `ProgressBus` NDJSON
  partagé entre worker et serveur.
- **Frontend Angular séparé** (`hydromodpy-ui`), typage généré depuis
  `openapi.json`, parité stricte testée en CI.

Le design **conserve** la forme de l'architecture déjà spécifiée dans les
phases 01-10 : le noyau reste le même, on ajoute une peau HTTP qui parle
la même langue. Les seules modifications requises sont ciblées
(`extra="forbid"`, `UiMeta`, mode `PARTIAL`, PKs DuckDB, `submit_run`
async) et n'introduisent aucune régression.
