# Capture & ingestion - quick playbook

Prereqs:
- active conda env `hmp`
- optional: `pip install psutil duckdb pynvml`

Note:
- `duckdb` is only required when you want to ingest JSONL snapshots into DuckDB.

Package extras:
```bash
pip install -e '.[duckdb]'
pip install -e '.[metrics]'
pip install -e '.[all]'
```

Commands:
- Backup: `scripts/backup_duckdb.sh examples/.../catalog.duckdb`
- Run+ingest orchestrator:
  `scripts/run_and_ingest.sh examples/projects/00_getting_started/project.toml example_run_01`

Notes:
- Use `--reset-data-cache` with `scripts/run_with_capture.py` when migrations bloquent.
- `scripts/validate_capture.py` ensures required fields present and sets `schema_version`.

## Utilisation hors HydroModPy

Exemple minimal d'adaptation pour un modèle externe:

```python
from hydromodpy.validity_frame.auto_capture import RuntimeAutoCapture, ExecutionContext
from hydromodpy.validity_frame.adapters.example_external_adapter import ExampleExternalAdapter

# your_model is any object exposing minimal attributes
adapter = ExampleExternalAdapter(your_model)
ctx = ExecutionContext(run_id="external_run", workspace=".")
cap = RuntimeAutoCapture(context=ctx, probes={"solver": adapter})

def work():
  your_model.run()

cap.run_with_capture(work)
```

L'exemple montre comment injecter un `solver` probe spécifique sans importer HydroModPy.

## Interface minimale `BaseProbe`

Pour intégrer un modèle externe sans modifier le coeur, implémente une classe qui suit l'interface minimale suivante :

- `role(self) -> str` : retourne l'identifiant du rôle (ex. `"solver"`, `"system"`, `"hardware"`, `"runtime"`).
- `collect(self, source: Any = None) -> dict | dataclass` (optionnel) : collecte l'état courant et renvoie un dict ou dataclass serialisable.
- `collect_start(self, start_time: float) -> dict | dataclass` (optionnel) : appelé au démarrage pour obtenir un snapshot initial.
- `collect_end(self, start_time: float) -> dict | dataclass` (optionnel) : appelé à la fin pour obtenir métriques finales.

Exemple minimal :

```python
from hydromodpy.validity_frame.probes.base import BaseProbe

class MyModelProbe(BaseProbe):
  def __init__(self, model):
    self.model = model

  def role(self) -> str:
    return "solver"

  def collect(self, source=None):
    m = source or self.model
    return {"solver_name": getattr(m, "name", "unknown"), "iterations": getattr(m, "n_steps", None)}
```

Ensuite, injecte cette instance dans `RuntimeAutoCapture` via le paramètre `probes` :

```python
cap = RuntimeAutoCapture(context=ctx, probes={"solver": MyModelProbe(my_model)})
cap.run_with_capture(my_callable)
```

Cette interface garde la `validity_frame` totalement découplée du modèle concret.
## Découverte et sélection multi‑modèles (prototype)

