"""
Example: using validity_frame semantic model with testbed results.

Run from the HydroModPy root directory:
    python3 validity_frame/examples/testbed_example.py

What this example does:
  1. Loads the semantic model from aquifer_config.toml (metric + threshold)
  2. Simulates a testbed manifest with two cases (low_K and high_K)
  3. Builds one ExecutionKnowledgeRecord per case
  4. Makes an automatic CVF / INCVF decision for each case
  5. Optionally adds an expert annotation
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

# Make validity_frame importable without installing it
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from validity_frame.semantic_model import (
    ExecutionKnowledgeRecord,
    ExpertAnnotation,
    ExpertVerdict,
    FidelityLevel,
    ValidityDomain,
    load_semantic_model,
)

# ── STEP 1: load semantic model from TOML ─────────────────────────────────────
# metric name and threshold (tau) come from the TOML, not hardcoded here
config_path = Path(__file__).parent / "aquifer_config.toml"
semantic = load_semantic_model(config_path)

va_template     = semantic["validation_store"]
ctx = semantic["context"]
print("=" * 60)
print("Semantic model loaded")
print(f"  system            : {ctx.system_name}")
print(f"  catchment         : {ctx.family}")
print(f"  outlet (x, y)     : ({ctx.outlet_x}, {ctx.outlet_y})  [{ctx.crs}]")
print(f"  aquifer thickness : {ctx.aquifer_thickness_m} m")
print(f"  lithology         : {ctx.geo_nature}")
print(f"  SM inputs         : {semantic['model_structure'].inputs}")
print(f"  SM parameters     : {semantic['model_structure'].parameters}")
print(f"  PoI known         : {[p.id for p in semantic['properties_of_interest'].known]}")
print(f"  Gamma meas        : {[f.id for f in semantic['influence_factors'].measurable]}")
print(f"  Gamma non-meas    : {[f.id for f in semantic['influence_factors'].non_measurable]}")
print(f"  metric            : {va_template.metric_name}")
print(f"  tau               : {va_template.tau} %")
print("=" * 60)

# ── STEP 2: simulate a testbed manifest (two cases) ───────────────────────────
# In real use this comes from testbed_manifest.json written by the testbed runner.
# The field names match what testbed/pipeline.py writes into flow_metrics.
FAKE_MANIFEST = {
    "testbed_id":  "flow_k_sensitivity",
    "subject":     "flow",
    "runner":      "simulation",
    "base_config": "examples/projects/10_testbed_workflow/base_armorican_nwt_flux_transient.toml",
    "purpose":     "robustness",
    "cases": [
        {
            "case_id": "low_K",
            "status":  "ok",
            "flow_metrics": {
                # mass balance error: below threshold → should be CVF
                "max_abs_mass_balance_percent_error": 2.3,
                "head_range_m":        8.3,
                "budget_chd_total_out": 12.5,
                "param_K":  1e-5,
                "param_Sy": 0.15,
            },
        },
        {
            "case_id": "high_K",
            "status":  "ok",
            "flow_metrics": {
                # mass balance error: above threshold → should be INCVF
                "max_abs_mass_balance_percent_error": 7.8,
                "head_range_m":        1.2,
                "budget_chd_total_out": 87.4,
                "param_K":  1e-3,
                "param_Sy": 0.20,
            },
        },
        {
            # failed case: skipped
            "case_id": "bad_case",
            "status":  "failed",
            "flow_metrics": {},
        },
    ],
}

# ── STEP 3: build one ExecutionKnowledgeRecord per case ───────────────────────
records: list[ExecutionKnowledgeRecord] = []

for case in FAKE_MANIFEST["cases"]:

    if case["status"] != "ok":
        print(f"\n  [{case['case_id']}] skipped (status={case['status']})")
        continue

    flow = case["flow_metrics"]

    # Copy the ValidationStore template (keeps tau and metric_name from TOML)
    # then fill in the actual results from this case
    va = copy.copy(va_template)
    va.val = flow.get(va.metric_name)        # the actual metric value
    va.X_r = {
        "debit":      flow.get("budget_chd_total_out"),
        "head_range": flow.get("head_range_m"),
    }
    va.P_r = {
        "K":  flow.get("param_K"),
        "Sy": flow.get("param_Sy"),
    }

    # Build the record (semantic model fields come from the TOML via **semantic)
    record = ExecutionKnowledgeRecord(
        run_id                  = case["case_id"],
        validation_store        = va,
        validity_domain         = ValidityDomain(),
        fidelity                = FidelityLevel(P1=True),
        source_adapter          = "testbed_manifest",
        metadata                = {
            "base_config": FAKE_MANIFEST.get("base_config"),
            "runner":      FAKE_MANIFEST.get("runner"),
            "subject":     FAKE_MANIFEST.get("subject"),
            "purpose":     FAKE_MANIFEST.get("purpose"),
        },
        model_structure         = semantic["model_structure"],
        properties_of_interest  = semantic["properties_of_interest"],
        influence_factors       = semantic["influence_factors"],
        context                 = semantic["context"],
    )

    # Automatic decision: val <= tau → CVF, else INCVF
    record.delta = va.val
    decision = record.make_decision()
    record.fidelity.P0 = False   # no field observations yet
    record.fidelity.P1 = True    # simulation results available
    record.fidelity.P2 = False   # expert not consulted yet

    records.append(record)

    print(f"\nCase : {record.run_id}")
    print(f"  K             = {va.P_r['K']:.1e}  m/s")
    print(f"  Sy            = {va.P_r['Sy']}")
    print(f"  debit         = {va.X_r['debit']} m3/s")
    print(f"  head_range    = {va.X_r['head_range']} m")
    print(f"  {va.metric_name}")
    print(f"    val = {va.val} %   tau = {va.tau} %")
    print(f"  --> DECISION  : {decision.value}")
    print(f"  --> fidelity  : P0={record.fidelity.P0}  P1={record.fidelity.P1}  P2={record.fidelity.P2}")

# ── STEP 4 (optional): expert adds annotation on the first record ──────────────
print("\n" + "=" * 60)
print("Expert review (optional)")

first = records[0]
first.apply_expert(ExpertAnnotation(
    verdict    = ExpertVerdict.ACCEPT,
    reason     = "Mass balance and head range are physically consistent",
    annotator  = "Dr. Martin",
    confidence = 0.95,
))
print(f"  Case '{first.run_id}' after expert review:")
print(f"  decision   = {first.decision.value}")
print(f"  verdict    = {first.expert_annotation.verdict.value}")
print(f"  reason     = {first.expert_annotation.reason}")
print(f"  fidelity   : P0={first.fidelity.P0}  P1={first.fidelity.P1}  P2={first.fidelity.P2}")
print(f"  global f(m): {first.fidelity.global_fidelity()}")

# ── STEP 5: summary ───────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Summary")
for r in records:
    print(f"  {r.run_id:10s}  delta={r.delta}%  decision={r.decision.value}")
