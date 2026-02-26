from hydromodpy.calibration.ObjectiveFunction import ObjectiveFunction

import numpy as np
  
class NSE(ObjectiveFunction):
    """
    Nash-Sutcliffe Efficiency (NSE) objective function for hydrological model calibration.
    """
    
    def __init__(self, weight: float = 1.0):
        """Initialize NSE with a weight parameter."""
        super().__init__(weight=weight)
    
    def evaluate(self, observed, simulated) -> float:
        """
        Calculate the Nash-Sutcliffe Efficiency (NSE) between observed and simulated values.
        
        Args:
            observed: Array of observed values
            simulated: Array of simulated values
        
        Returns:
            float: NSE value
        """
        observed, simulated = self.check_series_consistency(observed, simulated)
        err_var_sum = np.sum((observed - simulated) ** 2)
        obs_var_sum = np.sum((observed - np.mean(observed)) ** 2)
        nse = 1 - (err_var_sum / obs_var_sum)

        return nse

    def normalize(self, observed, simulated) -> float:
        """
        Normalize NSE to [0, 1] range.
        
        NSE ranges from -∞ to 1, where 1 is optimal.
        Values below 0 indicate poor performance.
        This method clamps NSE to [0, 1] for combining with other objectives.
        """
        nse_value = self.evaluate(observed, simulated)
        # Clamp to [0, 1]: values < 0 become 0, values > 1 become 1
        # In practice, NSE rarely exceeds 1 if data is clean
        return max(0.0, min(1.0, nse_value))