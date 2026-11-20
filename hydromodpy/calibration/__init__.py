"""Calibration sub-system.

Public surface:
    - CalibrationEngine: the orchestrator
    - Optimizer / Objective / Evaluator: Protocol contracts
    - Calibrable: Pydantic-field annotation marking a calibrable parameter
    - build_optimizer: adapter registry lookup
"""
