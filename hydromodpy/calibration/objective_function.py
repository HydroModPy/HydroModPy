import numpy as np

def check_series_consistency(observed, simulated):
    """
    Prepare observed/simulated arrays with common finite-value masking.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (obs, sim) masked to finite pairs.

    Notes
    -----
    - Keeps only paired finite values to avoid NaN/Inf propagation.
    - Preserves 1-to-1 comparison after masking.
    """
    obs = np.asarray(observed, dtype=float)
    sim = np.asarray(simulated, dtype=float)

    if obs.shape != sim.shape:
        raise ValueError("Observed and simulated data must have the same shape")

    # Keep only entries where both observed and simulated are finite.
    mask = np.isfinite(obs) & np.isfinite(sim)
    obs = obs[mask]
    sim = sim[mask]

    if obs.size == 0:
        raise ValueError("No common valid finite values in observed and simulated data")

    return obs, sim

def RMSE(obs, sim):
    """
    Calculate the Root Mean Square Error (RMSE) between observed and simulated values.
    
    Args:
        obs: Array of observed values
        sim: Array of simulated values
    
    Returns:
        float: RMSE value
    """
    obs, sim = check_series_consistency(obs, sim)
    rmse = np.sqrt(np.mean((obs - sim) ** 2))

    return rmse

def NSE(obs, sim):
    """
    Calculate the Nash-Sutcliffe Efficiency (NSE) between observed and simulated values.
    
    Args:
        obs: Array of observed values
        sim: Array of simulated values
    
    Returns:
        float: NSE value
    """
    obs, sim = check_series_consistency(obs, sim)
    err_var_sum = np.sum((obs - sim) ** 2)
    obs_var_sum = np.sum((obs - np.mean(obs)) ** 2)
    nse = 1 - (err_var_sum / obs_var_sum)

    return nse

def KGE(obs, sim):
    """
    Calculate the Kling-Gupta Efficiency (KGE) between observed and simulated values.
    
    Args:
        obs: Array of observed values
        sim: Array of simulated values
    
    Returns:
        float: KGE value
    """
    obs, sim = check_series_consistency(obs, sim)
    correlation = np.corrcoef(obs, sim)[0, 1]
    bias = np.mean(sim) / np.mean(obs)
    variability = (np.std(sim) / np.std(obs))
    kge = 1 - np.sqrt((correlation - 1) ** 2 + (bias - 1) ** 2 + (variability - 1) ** 2)
    
    return kge

def MAE(obs, sim):
    """
    Calculate the Mean Absolute Error (MAE) between observed and simulated values.
    
    Args:
        obs: Array of observed values
        sim: Array of simulated values
    
    Returns:
        float: MAE value
    """
    obs, sim = check_series_consistency(obs, sim)
    mae = np.mean(np.abs(obs - sim))
    
    return mae

def objective_function(obs, sim, metric='RMSE'):
    """
    Calculate the objective function value based on a specified metric.
    
    Args:
        obs: Array of observed values
        sim: Array of simulated values
        metric: String specifying the metric to use ('RMSE', 'NSE', 'KGE', 'MAE')
    
    Returns:
        float: Objective function value
    """
    if metric == 'RMSE':
        return RMSE(obs, sim)
    elif metric == 'NSE':
        return NSE(obs, sim)
    elif metric == 'KGE':
        return KGE(obs, sim)
    elif metric == 'MAE':
        return MAE(obs, sim)
    else:
        raise ValueError(f"Unsupported metric: {metric}. Choose from 'RMSE', 'NSE', 'KGE', 'MAE'.")
    
