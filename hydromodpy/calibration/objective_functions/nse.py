from hydromodpy.calibration.ObjectiveFunction import ObjectiveFunction

import numpy as np
  
class NSE(ObjectiveFunction):
    """
    Nash-Sutcliffe Efficiency (NSE) objective function for hydrological model calibration.
    """
    
    def __init__(self, weight: float = 1.0):
        """Initialize NSE with a weight parameter."""
        super().__init__(weight=weight)
    
    def evaluate(self, obs, sim):
        """
        Calculate the Nash-Sutcliffe Efficiency (NSE) between observed and simulated values.
        
        Args:
            obs: Array of observed values
            sim: Array of simulated values
        
        Returns:
            float: NSE value
        """
        obs, sim = self.check_series_consistency(obs, sim)
        err_var_sum = np.sum((obs - sim) ** 2)
        obs_var_sum = np.sum((obs - np.mean(obs)) ** 2)
        nse = 1 - (err_var_sum / obs_var_sum)

        return nse

    def normalize(self, obs, sim) -> float:
        """
        Normalize NSE to [0, 1] range.
        
        NSE ranges from -∞ to 1, where 1 is optimal.
        Values below 0 indicate poor performance.
        This method clamps NSE to [0, 1] for combining with other objectives.
        """
        nse_value = self.evaluate(obs, sim)
        # Clamp to [0, 1]: values < 0 become 0, values > 1 become 1
        # In practice, NSE rarely exceeds 1 if data is clean
        return max(0.0, min(1.0, nse_value))