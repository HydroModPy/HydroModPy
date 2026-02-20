from hydromodpy.calibration.ObjectiveFunction import ObjectiveFunction

import numpy as np


class WeightedObjectiveFunction(ObjectiveFunction):
    """
    Combine multiple objective functions with user-defined weights.
    
    This class enables flexible multi-objective optimization by combining
    different objective functions (NSE, KGE, RMSE, MAE) with custom weights.
    Each objective is normalized to [0, 1] before combination, so different
    scales (e.g., NSE optimal=1 vs RMSE optimal=0) are handled automatically.
    """
    
    def __init__(self, objectives: dict, weight: float = 1.0):
        """
        Initialize weighted combination of objective functions.
        
        Parameters
        ----------
        objectives : dict
            Dictionary mapping ObjectiveFunction instances to their weights.
            Example: {NSE(): 0.4, KGE(): 0.6}
            Weights must be non-negative and sum to 1.0.
        
        weight : float, optional
            Weight for this combined objective function in case it's used
            as part of a larger multi-objective optimization. Default is 1.0.
        
        Raises
        ------
        ValueError
            If the sum of weights is not approximately 1.0 (within tolerance).
        TypeError
            If objectives is not a dictionary or keys are not ObjectiveFunction instances.
        """
        super().__init__(weight=weight)
        
        # Validate input
        if not isinstance(objectives, dict):
            raise TypeError("objectives must be a dictionary")
        
        if not objectives:
            raise ValueError("objectives dictionary cannot be empty")
        
        # Validate that all keys are ObjectiveFunction instances
        for obj_func in objectives.keys():
            if not isinstance(obj_func, ObjectiveFunction):
                raise TypeError(
                    f"All keys in objectives must be ObjectiveFunction instances, "
                    f"got {type(obj_func).__name__}"
                )
        
        # Check that weights are non-negative
        for weight_val in objectives.values():
            if weight_val < 0:
                raise ValueError(f"All weights must be non-negative, got {weight_val}")
        
        # Validate that weights sum to 1.0 (with numerical tolerance)
        total_weight = sum(objectives.values())
        tolerance = 1e-6
        if not (1.0 - tolerance < total_weight < 1.0 + tolerance):
            raise ValueError(
                f"Sum of weights must be 1.0, got {total_weight}. "
                f"Current weights: {objectives}"
            )
        
        self.objectives = objectives
    
    def evaluate(self, observed, simulated) -> float:
        """
        Calculate weighted combination of normalized objective functions.
        
        Each objective function is normalized to [0, 1] independently,
        then combined using the specified weights.
        
        Parameters
        ----------
        observed : array-like
            Observed data values
        simulated : array-like
            Simulated data values
        
        Returns
        -------
        float
            Weighted combination score in [0, 1], where 1 is optimal.
        """
        weighted_sum = 0.0
        
        for obj_func, weight_coeff in self.objectives.items():
            # Get normalized performance (already in [0, 1])
            normalized_performance = obj_func.normalize(observed, simulated)
            # Add weighted contribution
            weighted_sum += weight_coeff * normalized_performance
        
        return weighted_sum
    
    def normalize(self, observed, simulated) -> float:
        """
        Normalize the weighted objective function result.
        
        Since evaluate() already returns a value in [0, 1],
        normalize() simply returns the same value.
        
        Parameters
        ----------
        observed : array-like
            Observed data values
        simulated : array-like
            Simulated data values
        
        Returns
        -------
        float
            Score in [0, 1], where 1 is optimal.
        """
        return self.evaluate(observed, simulated)
    
    def get_objectives(self) -> dict:
        """
        Get the objectives and their weights.
        
        Returns
        -------
        dict
            Dictionary mapping ObjectiveFunction instances to weights.
        """
        return self.objectives.copy()
    
    def set_objective_weights(self, weights_update: dict[ObjectiveFunction, float]) -> None:
        """
        Update multiple objective function weights at once.
        
        This method allows updating several weights simultaneously while maintaining
        the constraint that all weights must sum to 1.0. Validation happens only
        after all updates, allowing for complex weight redistribution.
        
        Parameters
        ----------
        weights_update : dict
            Dictionary mapping ObjectiveFunction instances to their new weights.
            Example: {nse: 0.3, kge: 0.7}
            Only specified objectives are updated; others remain unchanged.
            The sum of all weights (updated + unchanged) must equal 1.0.
        
        Raises
        ------
        ValueError
            If any objective is not in the weighted combination, has invalid weight,
            or if the total sum doesn't equal 1.0 after update.
        TypeError
            If weights_update is not a dictionary or contains invalid keys.
        
        Notes
        -----
        If the update fails validation, NO weights are modified (atomic operation).
        """
        if not isinstance(weights_update, dict):
            raise TypeError("weights_update must be a dictionary")
        
        if not weights_update:
            raise ValueError("weights_update dictionary cannot be empty")
        
        # Validate all input objectives and weights before making any changes
        for obj_func, new_weight in weights_update.items():
            if obj_func not in self.objectives:
                raise ValueError(
                    f"Objective function {type(obj_func).__name__} not in this weighted combination"
                )
            if new_weight < 0:
                raise ValueError(f"All weights must be non-negative, got {new_weight}")
        
        # Store old state in case we need to rollback
        old_objectives = self.objectives.copy()
        
        try:
            # Apply all updates
            for obj_func, new_weight in weights_update.items():
                self.objectives[obj_func] = new_weight
            
            # Validate that sum equals 1.0
            total_weight = sum(self.objectives.values())
            tolerance = 1e-6
            if not (1.0 - tolerance < total_weight < 1.0 + tolerance):
                raise ValueError(
                    f"Sum of all weights must be 1.0, got {total_weight}. "
                    f"Updated weights: {weights_update}, "
                    f"All weights now: {self.objectives}"
                )
        except ValueError:
            # Rollback on any validation error
            self.objectives = old_objectives
            raise
    
    def __repr__(self) -> str:
        """String representation of the weighted objective function."""
        lines = ["WeightedObjectiveFunction("]
        for obj_func, weight_val in self.objectives.items():
            obj_name = type(obj_func).__name__
            lines.append(f"    {obj_name}: {weight_val:.4f}")
        lines.append(")")
        return "\n".join(lines)
