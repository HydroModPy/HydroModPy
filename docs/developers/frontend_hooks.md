# Hooks frontaux

HydroModPy reste une bibliothèque Python pure : pas de serveur HTTP, pas
de FastAPI, pas de WebSocket. Deux points d'intégration stables sont
exposés pour tout frontal (Streamlit, Angular, React, widget Jupyter)
qui n'a pas besoin d'importer le paquet Python.

Liens : [glossary.md](glossary.md),
[design_patterns.md](design_patterns.md), [CLI.md](CLI.md).

## Points d'entrée

1. `hmp schema export --output ./schema/` produit trois fichiers JSON
   qui décrivent la surface de configuration.
2. `hmp schema validate-field <path> <value>` exécute le validateur
   partiel utilisé pour le retour champ par champ dans les formulaires
   (moins de 50 ms par appel).

Les deux sont aussi accessibles côté Python :

```python
from hydromodpy.schema import export_full_schema, validate_field

export_full_schema("./schema/")
result = validate_field("flow.flow_regime", "steady")
assert result.valid is True
```

Modules : `hydromodpy/schema/export.py` et
`hydromodpy/schema/partial_validator.py`.

## Fichiers produits par `hmp schema export`

| Fichier | Rôle |
|---|---|
| `config.json` | JSON Schema complet de `HydroModPyConfig` |
| `config_meta.json` | Sections TOML ordonnées, groupes UI, titres |
| `field_validators.json` | Mapping plat `field_path -> validator_type` |

Chaque champ de `config.json` conserve les annotations
`json_schema_extra` portées par les modèles Pydantic :
`widget_type`, `unit`, `display_name_fr`, `help_text_fr`, `display_min`,
`display_max`. Ces annotations constituent le contrat entre les modèles
Python et l'UI.

## Streamlit (local, Python)

Exemple minimal d'auto-génération d'un formulaire depuis le schema :

```python
import json
from pathlib import Path
import streamlit as st

schema = json.loads(Path("schema/config.json").read_text())
flow = schema["$defs"]["FlowPhysicalProperties"]["properties"]

k = st.slider(
    flow["k_aquifer"]["display_name_fr"],
    min_value=flow["k_aquifer"]["display_min"],
    max_value=flow["k_aquifer"]["display_max"],
    help=flow["k_aquifer"]["help_text_fr"],
)
st.caption(f"Unité : {flow['k_aquifer']['unit']}")
```

Voir `examples/integrations/streamlit_app.py` pour un exemple de bout en bout
qui découvre les sections dynamiquement.

## Angular (repo externe)

Les applications Angular couplent en général JSON Schema et
`ngx-formly` ou `@rjsf/core`. Deux étapes :

```bash
# 1. Produire le schema à chaque release de HydroModPy.
hmp schema export --output ./src/app/api/schema/
```

```ts
// angular: src/app/api/schema.service.ts
import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, shareReplay } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class SchemaService {
  private schema$ = this.http
    .get<object>('/assets/schema/config.json')
    .pipe(shareReplay(1));

  constructor(private http: HttpClient) {}

  get schema(): Observable<object> {
    return this.schema$;
  }
}
```

`ngx-formly` consomme ensuite le schema pour rendre le formulaire. Un
widget custom peut utiliser l'annotation `widget_type` pour distinguer
sliders et text inputs.

## React (repo externe)

```tsx
import Form from '@rjsf/core';
import validator from '@rjsf/validator-ajv8';
import schema from './schema/config.json';

export function SchemaForm() {
  return (
    <Form
      schema={schema}
      validator={validator}
      uiSchema={{
        'flow': {
          'properties': {
            'k_aquifer': { 'ui:widget': 'updown' },
          },
        },
      }}
    />
  );
}
```

La validation champ par champ côté Python est accessible via la CLI
(subprocess) ou tout transport choisi par l'intégrateur. HydroModPy n'en
impose aucun.

## Appel de `validate_field` depuis Python

```python
from hydromodpy.schema import validate_field

def on_change(path, value):
    result = validate_field(path, value)
    if not result.valid:
        show_error(result.error)
```

Le validateur résout le champ sur le modèle racine `HydroModPyConfig`,
sélectionne le `pydantic.TypeAdapter` correspondant et retourne un
`ValidationResult` léger. Les lookups sont mémoïsés : les appels répétés
sur le même path sont gratuits.

## Ce que HydroModPy ne livre pas volontairement

- Pas de dépendance FastAPI, uvicorn ou websockets.
- Pas de génération d'endpoint OpenAPI : le JSON Schema exporté est le
  contrat.
- Pas d'événements server-sent ; à brancher si un flux est nécessaire.

Toute couche HTTP écrite en aval peut s'appuyer sur ces hooks sans
toucher au paquet core.
