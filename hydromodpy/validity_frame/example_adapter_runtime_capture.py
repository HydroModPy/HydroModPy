from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

from hydromodpy.validity_frame.auto_capture.context import ExecutionContext
from hydromodpy.validity_frame.auto_capture.runtime_capture import RuntimeAutoCapture
from hydromodpy.validity_frame.probes.runtime import RuntimeProbe


class FakeExternalModel:
    """Exemple de modèle externe dont les attributs ne correspondent pas
    exactement à ceux attendus par `SolverProbe`.
    """

    def __init__(self, name: str, steps: int = 5):
        self.model_name = name
        self.n_steps = steps
        self.has_converged = False
        self.status = "not_started"

    def run(self):
        self.status = "running"
        for i in range(1, self.n_steps + 1):
            # Simule du travail
            time.sleep(0.1)
            self.current_step = i
        self.has_converged = True
        self.status = "completed"
        return {"result": "ok", "steps": self.n_steps}


class MySolverProbe:
    """Adapter qui mappe l'API du modèle externe au contrat attendu.

    Le collector appellera `collect(source)` avec `solver_source` passé
    depuis `RuntimeAutoCapture`.
    """

    def __init__(self, model=None):
        self.model = model

    def collect(self, source: object | None = None) -> dict:
        m = source or self.model
        if m is None:
            return {}
        return {
            "solver_name": getattr(m, "model_name", getattr(m, "name", None)),
            "iterations": getattr(m, "current_step", getattr(m, "n_steps", None)),
            "converged": getattr(m, "has_converged", None),
            "solver_status": getattr(m, "status", None),
        }


class MyRuntimeProbe(RuntimeProbe):
    """Sous-classe qui permet de passer une liste personnalisée `env_keys`.

    Vous pouvez soit fournir `env_keys` à `collect_start`, soit instancier
    ce probe et l'injecter dans le mapping `probes`.
    """

    @staticmethod
    def collect_start(start_time: float, *, env_keys: list[str] | None = None):
        keys = env_keys or [
            "HMP_WORKSPACE",
            "PYTHONPATH",
            "CONDA_DEFAULT_ENV",
            "CUDA_VISIBLE_DEVICES",
            "MY_APP_SETTING",
        ]
        # appelle l'implémentation parent en lui passant nos clés
        return super().collect_start(start_time, env_keys=keys)


def main():
    outdir = Path("examples/captures/run_example")
    outdir.mkdir(parents=True, exist_ok=True)

    # modèle externe
    model = FakeExternalModel("demo_model", steps=3)

    # probes personnalisées
    solver_probe = MySolverProbe(model)
    runtime_probe = MyRuntimeProbe()

    ctx = ExecutionContext(run_id="example_run", workspace=str(Path.cwd()))
    cap = RuntimeAutoCapture(
        context=ctx, output_dir=outdir, probes={"solver": solver_probe, "runtime": runtime_probe}
    )

    # exécution avec capture; `solver_source` permet au SolverProbe de
    # récupérer les états (itérations, status, ...)
    result, snapshot = cap.run_with_capture(lambda: model.run(), solver_source=model)

    print("Result:", result)
    print("Snapshot (dict):")
    print(asdict(snapshot))
    print("Fichiers créés dans:", outdir)


if __name__ == "__main__":
    main()
