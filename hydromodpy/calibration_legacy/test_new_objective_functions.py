"""
Test script for the new ObjectiveFunction classes.

This script tests the newly implemented NSE, KGE, MAE, RMSE, 
WeightedObjectiveFunction, and TransformedObjectiveFunction classes
in the context of the calibration workflow.

Starting with a simple NSE (no weighting, no transformation) to verify
that the objective functions work correctly with the existing calibration engine.
"""

from hydromodpy.calibration import calibration_engine
from hydromodpy.calibration.objective_functions import NSE, KGE, MAE, RMSE
import pandas as pd
import numpy as np


# ============================================================================
# SETUP DATA
# ============================================================================

# Create a synthetic monthly recharge time series
# to replace by: user path or automatic data retrieving
time = list(range(1, 13))  # 1 à 12
rech = [40, 30, 25, 20, 18, 19, 22, 26, 31, 37, 40, 43]
rech_ts = pd.Series(rech, index=time, name='rech')
rech_ts.index.name = 'time'

print("=" * 70)
print("Testing New Objective Functions")
print("=" * 70)
print("\nTest Data (Recharge time series):")
print(rech_ts)

# ============================================================================
# TEST 1 : SIMPLE NSE (No weighting, no transformation)
# ============================================================================

print("\n" + "=" * 70)
print("TEST 1: Simple NSE (No weighting, no transformation)")
print("=" * 70)

# Define parameters to calibrate and their bounds
params_to_calibrate = {
    'K': [1e-5, 1e-1],
    'Sy': [0.03, 0.07]
}

# Define maximum number of simulations
max_nb_sim = 512

# Create an instance of NSE objective function
obj_func = NSE(weight=1.0)

print(f"\nObjective Function: {type(obj_func).__name__}")
print(f"  Weight: {obj_func.weight}")
print(f"  Parameters to calibrate: {list(params_to_calibrate.keys())}")
print(f"  Max simulations: {max_nb_sim}")

# Define the calibration method to use
calib_method = 'regular_exploration'

# Visualization of results if number of parameters is 3 or less
visualization = True

# Proceed to calibration via calibration_engine
print("\nRunning calibration with new NSE objective function...")
try:
    calib_results_dict, calib_results_df = calibration_engine.Calibration(
        params_to_calibrate, 
        max_nb_sim, 
        rech_ts, 
        obj_func,  # ← Now using NSE instance instead of string
        calib_method, 
        visualization, 
        solver='Modflow'
    )
    
    print("\n✓ Calibration SUCCESS!")
    print("\nCalibration Results (top 5):")
    print(calib_results_df.head())
    
except Exception as e:
    print(f"\n✗ Calibration FAILED!")
    print(f"Error: {str(e)}")
    import traceback
    traceback.print_exc()

# ============================================================================
# TEST 2: Simple test of NSE class methods
# ============================================================================

print("\n" + "=" * 70)
print("TEST 2: Unit tests for NSE class methods")
print("=" * 70)

# Create synthetic observed and simulated data
np.random.seed(42)
observed = np.array([10, 20, 15, 25, 30, 22, 18, 28, 35, 32])
simulated = np.array([12, 19, 16, 24, 31, 21, 19, 27, 34, 33])

nse = NSE(weight=0.8)

print(f"\nTest data:")
print(f"  Observed:  {observed}")
print(f"  Simulated: {simulated}")

# Test evaluate method
try:
    score = nse.evaluate(observed, simulated)
    print(f"\n✓ evaluate() SUCCESS")
    print(f"  NSE score: {score:.4f}")
except Exception as e:
    print(f"\n✗ evaluate() FAILED: {e}")

# Test normalize method
try:
    normalized_score = nse.normalize(observed, simulated)
    print(f"\n✓ normalize() SUCCESS")
    print(f"  Normalized score (0-1): {normalized_score:.4f}")
except Exception as e:
    print(f"\n✗ normalize() FAILED: {e}")

# Test weight property
try:
    print(f"\n✓ weight property SUCCESS")
    print(f"  Initial weight: {nse.weight}")
    nse.weight = 0.5
    print(f"  After modification: {nse.weight}")
except Exception as e:
    print(f"\n✗ weight property FAILED: {e}")

print("\n" + "=" * 70)
print("Tests completed!")
print("=" * 70)
