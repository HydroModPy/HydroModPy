"""Data transformation strategies for objective functions."""

import numpy as np


class TransformationStrategy:
    """
    Centralized collection of data transformation methods for objective functions.
    
    All transformation methods are static and can be used independently or
    registered in a TransformedObjectiveFunction.
    """
    
    @staticmethod
    def log(data: np.ndarray, epsilon: float = 1e-6) -> np.ndarray:
        """
        Log-transformation: log10(data + epsilon)
        
        Parameters
        ----------
        data : np.ndarray
            Input array to transform
        epsilon : float, optional
            Small value to avoid log(0), by default 1e-6
        
        Returns
        -------
        np.ndarray
            Log-transformed array
        
        Notes
        -----
        Hydrological use case: log(discharge) emphasizes low flows and is useful
        for comprehensive calibration across flow regimes.
        """
        data = np.asarray(data, dtype=float)
        return np.log10(data + epsilon)
    
    @staticmethod
    def sqrt(data: np.ndarray) -> np.ndarray:
        """
        Square-root transformation: sqrt(|data|) * sign(data)
        
        Parameters
        ----------
        data : np.ndarray
            Input array to transform
        
        Returns
        -------
        np.ndarray
            Square-root transformed array
        
        Notes
        -----
        - Preserves sign for potentially negative values
        - Less aggressive than log transformation
        """
        data = np.asarray(data, dtype=float)
        return np.sqrt(np.abs(data)) * np.sign(data)
    
    @staticmethod
    def inverse(data: np.ndarray, epsilon: float = 1e-6) -> np.ndarray:
        """
        Inverse transformation: 1 / (data + epsilon)
        
        Parameters
        ----------
        data : np.ndarray
            Input array to transform
        epsilon : float, optional
            Small value to avoid division by zero, by default 1e-6
        
        Returns
        -------
        np.ndarray
            Inverse transformed array
        
        Notes
        -----
        - Gives more weight to values close to 0
        - Can highlight recession curves and baseflow periods
        - Extreme values become smaller
        """
        data = np.asarray(data, dtype=float)
        return 1.0 / (data + epsilon)
    
    @staticmethod
    def box_cox(data: np.ndarray, lambda_param: float = None) -> np.ndarray:
        """
        Box-Cox transformation: (data^lambda - 1) / lambda
        
        Parameters
        ----------
        data : np.ndarray
            Input array to transform (must be positive)
        lambda_param : float, optional
            Box-Cox lambda parameter. If None, defaults to 0.5 (approximately sqrt).
            Special case: lambda=0 → log transformation
        
        Returns
        -------
        np.ndarray
            Box-Cox transformed array
        """
        data = np.asarray(data, dtype=float)
        
        if lambda_param is None:
            lambda_param = 0.5  # Default: approximately sqrt
        
        if abs(lambda_param) < 1e-10:  # Treat as 0
            return np.log(data)
        else:
            return (np.power(data, lambda_param) - 1) / lambda_param
    
    @staticmethod
    def identity(data: np.ndarray) -> np.ndarray:
        """
        Identity transformation: returns data unchanged.
        
        Parameters
        ----------
        data : np.ndarray
            Input array
        
        Returns
        -------
        np.ndarray
            Same array as input
        
        Notes
        -----
        Used as default when no transformation is specified.
        """
        return np.asarray(data, dtype=float)
    
    # Registry: maps transformation names to their implementations
    _TRANSFORMATIONS = {
        'log': log,
        'sqrt': sqrt,
        'inverse': inverse,
        'box_cox': box_cox,
        'identity': identity,
        None: identity,  # Default transformation
    }
    
    @classmethod
    def get_transformation(cls, name: str | None):
        """
        Retrieve a named transformation function.
        
        Parameters
        ----------
        name : str or None
            Name of the transformation: 'log', 'sqrt', 'inverse', 'box_cox', 'identity', or None
        
        Returns
        -------
        callable
            The transformation function
        
        Raises
        ------
        ValueError
            If transformation name is not recognized
        
        Examples
        --------
        >>> log_func = TransformationStrategy.get_transformation('log')
        >>> sqrt_func = TransformationStrategy.get_transformation('sqrt')
        """
        if name not in cls._TRANSFORMATIONS:
            available = list(cls._TRANSFORMATIONS.keys())
            raise ValueError(
                f"Unknown transformation: '{name}'. "
                f"Available transformations: {available}"
            )
        return cls._TRANSFORMATIONS[name]
    
    @classmethod
    def list_available_transformations(cls):
        """
        List all available Named transformations.
        
        Returns
        -------
        list
            List of available transformation names (excluding None)
        """
        return [name for name in cls._TRANSFORMATIONS.keys() if name is not None]
