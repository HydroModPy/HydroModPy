"""
Example: validity_frame on calibration results (catalog.duckdb).

Run from ANY directory that contains (or has a subdirectory with) catalog.duckdb:
    cd examples/projects/02_nancon_watershed
    python3 /path/to/validity_frame/examples/calibration_example.py

The script automatically finds ALL catalog.duckdb files under the current
working directory, reads calibration_iterations, and applies the validity frame.

Decision rule:
    CVF   if KGE >= tau   (tau defined in aquifer_config.toml)
    INCVF if KGE <  tau
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from validity_frame.semantic_model import (
    ExecutionKnowledgeRecord,
    FidelityLevel,
    UncertaintyDescriptors,
    ValidationStore,
    ValidityDomain,
    load_semantic_model,
)

# ── STEP 1: load semantic model ───────────────────────────────────────────────
config_path = Path(__file__).parent / "aquifer_config.toml"
semantic = load_semantic_model(config_path)
ctx = semantic["context"]

# For calibration we use KGE with threshold 0.70
KGE_THRESHOLD = 0.70

print("=" * 60)
print("Semantic model")
print(f"  system    : {ctx.system_name}")
print(f"  outlet    : ({ctx.outlet_x}, {ctx.outlet_y})  [{ctx.crs}]")
print(f"  thickness : {ctx.aquifer_thickness_m} m")
print(f"  metric    : KGE  (tau={KGE_THRESHOLD})")
print("=" * 60)

# ── STEP 2: find ALL catalog.duckdb under current directory ───────────────────
search_root = Path.cwd()
catalogs = sorted(search_root.rglob("catalog.duckdb"))

if not catalogs:
    print(f"\n[ERROR] No catalog.duckdb found under:\n  {search_root}")
    print("\nRun the calibration first:")
    print("  cd examples/projects/02_nancon_watershed")
    print("  hmp run run_calibration_k.toml")
    sys.exit(1)

print(f"\nFound {len(catalogs)} catalog(s) under {search_root}")


def _process_catalog(catalog_path: Path) -> list[ExecutionKnowledgeRecord]:
    """Apply validity frame to one catalog.duckdb calibration session."""
    try:
        import duckdb
    except ImportError:
        print("[ERROR] duckdb not installed. Run: pip install duckdb")
        return []

    con = duckdb.connect(str(catalog_path), read_only=True)

    # Check calibration_iterations exists and has rows
    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    if "calibration_iterations" not in tables:
        print(f"  [{catalog_path}] no calibration_iterations table — skipping")
        con.close()
        return []

    rows = con.execute("""
        SELECT iteration, sim_id, parameters, objective_value, metrics, status, duration_s
        FROM calibration_iterations
        ORDER BY iteration
    """).fetchall()

    if not rows:
        print(f"  [{catalog_path}] calibration_iterations is empty — skipping")
        con.close()
        return []

    # Read session info for provenance
    session = con.execute("""
        SELECT session_id, project, method, objective_name, n_iterations,
               best_sim_id, best_objective
        FROM calibration_sessions
        LIMIT 1
    """).fetchone()
    con.close()

    session_id, project, method, obj_name, n_iter, best_sim_id, best_obj = session or (
        None,
        None,
        None,
        "kge",
        None,
        None,
        None,
    )

    print(f"\n{'=' * 60}")
    print(f"Catalog  : {catalog_path.parent.name}")
    print(f"  session  : {session_id}")
    print(f"  method   : {method}  objective: {obj_name}")
    print(f"  iterations: {n_iter}")
    if best_obj is not None:
        best_kge = round(1.0 - best_obj, 4)
        print(f"  best KGE : {best_kge}  (tau={KGE_THRESHOLD})")

    records: list[ExecutionKnowledgeRecord] = []

    for iteration, sim_id, params_json, obj_val, _metrics_json, status, duration_s in rows:
        if status != "completed" or obj_val is None:
            print(f"\n  [iter {iteration}] skipped (status={status})")
            continue

        # KGE = 1 - cost  (calibration minimizes 1-KGE)
        kge = round(1.0 - float(obj_val), 4)

        params = json.loads(params_json) if params_json else {}
        K_val = params.get("K", {}).get("value")
        Sy_val = params.get("Sy", {}).get("value")

        # Build ValidationStore for this iteration (KGE-based)
        va = ValidationStore(
            tau=KGE_THRESHOLD,
            metric_name="kge",
            val=kge,
            X_r={},
            P_r={"K": K_val, "Sy": Sy_val},
            incer=UncertaintyDescriptors(),
        )

        record = ExecutionKnowledgeRecord(
            run_id=f"iter_{iteration:03d}",
            validation_store=va,
            validity_domain=ValidityDomain(),
            fidelity=FidelityLevel(P1=True),
            source_adapter="calibration_catalog",
            model_structure=semantic["model_structure"],
            properties_of_interest=semantic["properties_of_interest"],
            influence_factors=semantic["influence_factors"],
            context=semantic["context"],
            metadata={
                "session_id": str(session_id) if session_id else "",
                "sim_id": str(sim_id) if sim_id else "",
                "objective": obj_name or "kge",
                "duration_s": duration_s,
                "catalog_path": str(catalog_path),
            },
        )

        record.delta = kge
        # CVF if KGE >= tau (higher is better → flip comparison)
        from validity_frame.semantic_model.knowledge_record import ValidationDecision

        if kge >= KGE_THRESHOLD:
            record.decision = ValidationDecision.CVF
        else:
            record.decision = ValidationDecision.INCVF

        records.append(record)

        print(f"\n  Iteration {iteration}")
        print(f"    K          = {K_val}")
        print(f"    Sy         = {Sy_val}")
        print(f"    KGE        = {kge}  (tau={KGE_THRESHOLD})")
        print(f"    duration   = {round(duration_s, 1)} s")
        print(f"    --> DECISION: {record.decision.value}")

    if records:
        cvf = [r for r in records if r.decision.value == "CVF"]
        incvf = [r for r in records if r.decision.value == "INCVF"]
        print(f"\n  Summary — {catalog_path.parent.name}")
        print(f"    Total : {len(records)}")
        print(f"    CVF   : {len(cvf)}   {[r.run_id for r in cvf]}")
        print(f"    INCVF : {len(incvf)}  {[r.run_id for r in incvf]}")

    return records


# ── STEP 3: process every catalog found ──────────────────────────────────────
all_records: list[ExecutionKnowledgeRecord] = []
for cp in catalogs:
    all_records.extend(_process_catalog(cp))

# ── STEP 4: global summary ────────────────────────────────────────────────────
if len(catalogs) > 1 and all_records:
    print("\n" + "=" * 60)
    print("Global summary")
    cvf = [r for r in all_records if r.decision.value == "CVF"]
    incvf = [r for r in all_records if r.decision.value == "INCVF"]
    print(f"  Catalogs    : {len(catalogs)}")
    print(f"  Total cases : {len(all_records)}")
    print(f"  CVF         : {len(cvf)}")
    print(f"  INCVF       : {len(incvf)}")
