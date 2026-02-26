"""Transformed objective function wrapper for applying data transformations."""

from typing import Callable, Optional

import numpy as np

from hydromodpy.calibration.ObjectiveFunction import ObjectiveFunction
from hydromodpy.calibration.objective_functions.transformations import TransformationStrategy


class TransformedObjectiveFunction(ObjectiveFunction):
    """
    Wrapper (Decorator pattern) that applies a transformation to observed/simulated
    data before evaluating an objective function.
    
    This allows any objective function to work on transformed data without modifying
    the original function. Transformations are composed with objective functions,
    enabling flexible multi-objective optimization with different scales and regimes.
    
    Design Pattern: Decorator - adds transformation capability to any ObjectiveFunction.
    
    Examples
    --------
    >>> # Simple transformation
    >>> nse = NSE()
    >>> nse_log = TransformedObjectiveFunction(nse, transform='log')
    >>> score = nse_log.evaluate(observed, simulated)
    
    >>> # With custom parameters
    >>> nse_log = TransformedObjectiveFunction(
    ...     NSE(),
    ...     transform='log',
    ...     transform_params={'epsilon': 1e-6}
    ... )
    
    >>> # In a weighted combination
    >>> weighted = WeightedObjectiveFunction({
    ...     TransformedObjectiveFunction(NSE(), 'log'): 0.4,
    ...     TransformedObjectiveFunction(KGE(), 'sqrt'): 0.3,
    ...     TransformedObjectiveFunction(RMSE()): 0.3
    ... })
    
    >>> # Custom callable transformation
    >>> custom_transform = lambda x: np.log1p(x) / np.log(10)
    >>> custom_obj = TransformedObjectiveFunction(NSE(), transform=custom_transform)
    """
    
    def __init__(
        self,
        base_objective: ObjectiveFunction,
        transform: str | Callable | None = None,
        transform_params: dict | None = None,
        weight: float = 1.0,
        inverse_transform: bool = False
    ):
        """
        Initialize a transformed objective function.
        
        Parameters
        ----------
        base_objective : ObjectiveFunction
            The objective function to wrap (e.g., NSE(), KGE(), RMSE())
        
        transform : str, callable, or None
            The transformation to apply:
            - str: Named transformation - 'log', 'sqrt', 'inverse', 'box_cox', 'identity', or None
            - callable: Custom transformation function that takes array and returns array
            - None: No transformation (identity)
        
        transform_params : dict, optional
            Parameters to pass to the transformation function.
            Examples:
            - {'epsilon': 1e-6} for 'log' transformation
            - {'lambda_param': 0.3} for 'box_cox' transformation
        
        weight : float, optional
            Weight for this objective function in multi-objective optimization.
            Default is 1.0.
        
        inverse_transform : bool, optional
            If True, apply the inverse transformation to the final score.
            Only supported for 'log' transformation (returns to original scale).
            Default is False.
        
        Raises
        ------
        ValueError
            If named transformation is not recognized
        TypeError
            If base_objective is not an ObjectiveFunction instance
        """
        super().__init__(weight=weight)
        
        if not isinstance(base_objective, ObjectiveFunction):
            raise TypeError(
                f"base_objective must be an ObjectiveFunction instance, "
                f"got {type(base_objective).__name__}"
            )
        
        self.base_objective = base_objective
        self.transform_params = transform_params or {}
        self.inverse_transform = inverse_transform
        
        # Determine and store the transformation function
        if callable(transform):
            self._transform_func = transform
            self._transform_name = "custom_callable"
            self._is_custom = True
        else:
            self._transform_name = transform
            self._transform_func = TransformationStrategy.get_transformation(transform)
            self._is_custom = False
    
    def _apply_transformation(self, data: np.ndarray) -> np.ndarray:
        """
        Apply the transformation to data with stored parameters.
        
        Parameters
        ----------
        data : np.ndarray
            Input data array
        
        Returns
        -------
        np.ndarray
            Transformed data array
        """
        try:
            return self._transform_func(data, **self.transform_params)
        except TypeError:
            # If transformation doesn't accept extra kwargs, call without them
            return self._transform_func(data)
    
    def evaluate(self, observed, simulated) -> float:
        """
        Evaluate the objective function on transformed data.
        
        Process:
        1. Clean data (remove NaN/Inf pairs)
        2. Apply transformation to both observed and simulated
        3. Evaluate the base objective on transformed data
        4. Optionally apply inverse transformation to the result
        
        Parameters
        ----------
        observed : array-like
            Observed data values
        simulated : array-like
            Simulated data values
        
        Returns
        -------
        float
            Objective function score
        """
        # Clean and standardize data
        obs, sim = self.check_series_consistency(observed, simulated)
        
        # Apply transformation to both arrays
        try:
            obs_transformed = self._apply_transformation(obs)
            sim_transformed = self._apply_transformation(sim)
        except Exception as e:
            raise ValueError(
                f"Transformation failed on data. "
                f"Transformation: {self._transform_name}, "
                f"Error: {str(e)}"
            )
        
        # Evaluate base objective on transformed data
        score = self.base_objective.evaluate(obs_transformed, sim_transformed)
        
        # Apply inverse transformation to score if requested
        if self.inverse_transform:
            score = self._apply_inverse_transformation(score)
        
        return score
    
    def normalize(self, observed, simulated) -> float:
        """
        Normalize the objective function score to [0, 1].
        
        Applies transformation, evaluates, and normalizes based on the
        base objective's normalize method.
        
        Parameters
        ----------
        observed : array-like
            Observed data values
        simulated : array-like
            Simulated data values
        
        Returns
        -------
        float
            Normalized score in [0, 1] where 1 is optimal
        """
        obs, sim = self.check_series_consistency(observed, simulated)
        
        # Apply transformation
        obs_transformed = self._apply_transformation(obs)
        sim_transformed = self._apply_transformation(sim)
        
        # Normalize on transformed data
        return self.base_objective.normalize(obs_transformed, sim_transformed)
    
    def _apply_inverse_transformation(self, value: float) -> float:
        """
        Apply inverse transformation to a scalar value.
        
        Parameters
        ----------
        value : float
            Scalar value to inverse transform
        
        Returns
        -------
        float
            Inverse transformed value
        
        Notes
        -----
        Currently only supports 'log' transformation for inverse.
        Other transformations would require additional complexity.
        """
        if self._transform_name == 'log':
            # Inverse of log10 is 10^x
            return 10.0 ** value
        else:
            # For other transformations, warn and return original
            import warnings
            warnings.warn(
                f"Inverse transformation not implemented for '{self._transform_name}'. "
                f"Returning original value."
            )
            return value
    
    def get_base_objective(self) -> ObjectiveFunction:
        """
        Get the wrapped base objective function.
        
        Returns
        -------
        ObjectiveFunction
            The original objective function
        """
        return self.base_objective
    
    def get_transformation_info(self) -> dict:
        """
        Get information about the applied transformation.
        
        Returns
        -------
        dict
            Dictionary containing:
            - 'name': Transformation name
            - 'params': Parameters passed to transformation
            - 'inverse_applied': Whether inverse is applied to score
            - 'base_objective': Name of wrapped objective function
            - 'is_custom': Whether transformation is a custom callable
        """
        return {
            'name': self._transform_name,
            'params': self.transform_params.copy(),
            'inverse_applied': self.inverse_transform,
            'base_objective': type(self.base_objective).__name__,
            'is_custom': self._is_custom
        }
