# B0 network and transient discharge calibration case

Compares a calibration on a natural drainage network and a transient discharge against a known
truth. The transient config the HTML page reads is `configs/truth_transient_discharge.toml`, and
the real runs it reports on go under `outputs/real_runs/`, which git ignores.

It is exercised by the `tests/unit/validation_cases/test_b0_*.py` files, which also run the two
scripts `run_synthetic_smoke.py` and `score_candidate_table.py`.
