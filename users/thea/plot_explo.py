#%%
"""
Enhanced Calibration Grid Analyzer - Improved Version

This module provides tools for visualizing hydrological model calibration results
as pixel grids, where each pixel represents a unique parameter combination colored
by performance statistics.

Authors: Enhanced version for HydroModPy calibration analysis
"""

import os
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, Normalize, SymLogNorm
from matplotlib.patches import Circle, RegularPolygon, Patch
from typing import Tuple, Optional, Dict, List
import warnings
warnings.filterwarnings('ignore')

plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams.update({
    'font.size': 10,
    'axes.titlesize': 12,
    'axes.labelsize': 11,
    'xtick.labelsize': 9,
    'ytick.labelsize': 9,
    'legend.fontsize': 9,
    'figure.titlesize': 14,
    'font.family': 'sans-serif',
    'font.sans-serif': ['DejaVu Sans', 'Arial', 'Helvetica', 'Liberation Sans'],
    'axes.grid': True,
    'grid.alpha': 0.3
})

# Statistical metrics definitions and explanations
METRIC_DEFINITIONS = {
    # Streamflow metrics
    'NSE': {
        'name': 'Nash-Sutcliffe Efficiency',
        'description': 'Measures model performance relative to mean observed flow',
        'formula': '1 - (SS_res / SS_tot)',
        'range': '(-∞, 1]',
        'optimal': '1.0',
        'interpretation': 'NSE > 0.75: Very good; 0.65-0.75: Good; 0.5-0.65: Satisfactory; <0.5: Unsatisfactory',
        'color_scale': 'normal'
    },
    'NSElog': {
        'name': 'Log Nash-Sutcliffe Efficiency',
        'description': 'NSE applied to logarithm of flows, emphasizes low flows',
        'formula': 'NSE(log(Q_sim), log(Q_obs))',
        'range': '(-∞, 1]',
        'optimal': '1.0',
        'interpretation': 'Similar to NSE but gives more weight to low flow periods',
        'color_scale': 'normal'
    },
    'KGE': {
        'name': 'Kling-Gupta Efficiency',
        'description': 'Composite metric combining correlation, bias, and variability',
        'formula': '1 - √[(r-1)² + (α-1)² + (β-1)²]',
        'range': '(-∞, 1]',
        'optimal': '1.0',
        'interpretation': 'KGE > 0.9: Excellent; 0.75-0.9: Good; 0.5-0.75: Satisfactory; <0.5: Poor',
        'color_scale': 'normal'
    },
    'RMSE': {
        'name': 'Root Mean Square Error',
        'description': 'Average magnitude of prediction errors',
        'formula': '√[mean((Q_sim - Q_obs)²)]',
        'range': '[0, +∞)',
        'optimal': '0.0',
        'interpretation': 'Lower values indicate better performance, units same as observed data',
        'color_scale': 'log_if_large_range'
    },
    
    # Spatial matching metrics
    'FA': {
        'name': 'Frequency Agreement',
        'description': 'Measures agreement in drainage network density between simulated and observed',
        'formula': '1/(1+(abs(np.log(sim_distance/obs_distance)))))',
        'range': '[0, 1)',
        'optimal': '1',
        'interpretation': 'Compares simulated vs observed drainage density. 1 = perfect match',
        'color_scale': 'normal'  # Special scale for FA to see small differences
    },
    # 'Dmean': {
    #     'name': 'Mean Distance',
    #     'description': 'Average spatial distance between simulated and observed drainage networks',
    #     'formula': '(D_sim_to_obs + D_obs_to_sim) / 2',
    #     'range': '[0, +∞)',
    #     'optimal': '0.0',
    #     'interpretation': 'Mean distance in meters between networks. Lower values indicate better spatial agreement',
    #     'color_scale': 'log_if_large_range'
    # },
    'FQA': {
        'name': 'Flow-Spatial Combined Metric',
        'description': 'Combined metric incorporating both flow performance and spatial agreement',
        'formula': '(FQ + FA)/2, where FQ = NSElog',
        'range': '[0, 1)',
        'optimal': '1',
        'interpretation': 'higher values better. Combines streamflow accuracy with spatial network matching',
        'color_scale': 'normal'
    },
    # 'Dd_sim': {
    #     'name': 'Simulated Drainage Density',
    #     'description': 'Density of simulated drainage network points per unit area',
    #     'formula': 'N_points_sim / Area',
    #     'range': '[0, +∞)',
    #     'optimal': 'Match Dd_obs',
    #     'interpretation': 'Points per km². Should match observed drainage density for good spatial performance',
    #     'color_scale': 'normal'
    # },
    # 'Dd_obs': {
    #     'name': 'Observed Drainage Density',
    #     'description': 'Density of observed drainage network points per unit area',
    #     'formula': 'N_points_obs / Area',
    #     'range': '[0, +∞)',
    #     'optimal': 'Reference value',
    #     'interpretation': 'Reference drainage density from field observations or high-resolution data',
    #     'color_scale': 'normal'
    # }
}

def get_metric_info(metric_name: str) -> Dict[str, str]:
    """
    Get information about a specific performance metric.
    
    Parameters
    ----------
    metric_name : str
        Name of the metric to look up
        
    Returns
    -------
    dict
        Dictionary containing metric information, or basic info if not found
    """
    return METRIC_DEFINITIONS.get(metric_name, {
        'name': metric_name,
        'description': 'Performance metric',
        'interpretation': 'See documentation for details',
        'color_scale': 'normal'
    })

def combine_metrics(df: pd.DataFrame, 
                   metrics: List[str], 
                   weights: Optional[List[float]] = None,
                   method: str = 'weighted_sum',
                   normalize: bool = True) -> Tuple[pd.Series, str]:
    """
    Combine multiple performance metrics into a single composite metric.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing the metrics
    metrics : list of str
        List of metric column names to combine
    weights : list of float, optional
        Weights for each metric (default: equal weights)
    method : str, default='weighted_sum'
        Combination method: 'weighted_sum', 'weighted_mean', 'product', 'geometric_mean'
    normalize : bool, default=True
        Whether to normalize metrics to [0,1] before combining
        
    Returns
    -------
    tuple
        (combined_series, description_string)
    """
    
    # Validate inputs
    available_metrics = [m for m in metrics if m in df.columns]
    if not available_metrics:
        raise ValueError(f"None of the specified metrics found in dataframe: {metrics}")
    
    if weights is None:
        weights = [1.0] * len(available_metrics)
    elif len(weights) != len(available_metrics):
        raise ValueError(f"Number of weights ({len(weights)}) must match number of available metrics ({len(available_metrics)})")
    
    # Prepare data
    metric_data = {}
    descriptions = []
    metric_arrays = []  # For mask
    
    for i, metric in enumerate(available_metrics):
        data = df[metric].copy()
        
        # Handle missing values
        if data.isna().all():
            continue
            
        # Get metric info to determine if higher is better
        metric_info = get_metric_info(metric)
        higher_is_better = metric_info.get('optimal') not in ['0.0', 'Lower']
        
        # Normalize if requested
        if normalize and len(data.dropna()) > 0:
            data_clean = data.dropna()
            data_min, data_max = data_clean.min(), data_clean.max()
            
            if data_max != data_min:  # Avoid division by zero
                if higher_is_better:
                    data = (data - data_min) / (data_max - data_min)
                else:
                    data = 1 - (data - data_min) / (data_max - data_min)
            else:
                data = data * 0 + 0.5  # All values the same, set to middle
        
        metric_data[metric] = data
        metric_arrays.append(data)
        
        # Create description
        weight_str = f"{weights[i]:.2f}" if weights[i] != 1.0 else "1"
        norm_str = " (norm)" if normalize else ""
        inv_str = " (inv)" if normalize and not higher_is_better else ""
        descriptions.append(f"{weight_str}×{metric}{norm_str}{inv_str}")
    
    if not metric_data:
        raise ValueError("No valid metric data found after processing")
    
    # Mask: True si toutes les métriques sont non-NaN, False sinon
    if len(metric_arrays) > 1:
        valid_mask = ~pd.concat(metric_arrays, axis=1).isnull().any(axis=1)
    else:
        valid_mask = ~metric_arrays[0].isnull()
    
    # Combine metrics
    if method == 'weighted_sum':
        combined = pd.Series(np.nan, index=df.index)
        total_weight = 0
        for i, (metric, data) in enumerate(metric_data.items()):
            if i == 0:
                combined = weights[i] * data
            else:
                combined += weights[i] * data
            total_weight += weights[i]
        description = f"Weighted sum: {' + '.join(descriptions)}"
        
    elif method == 'weighted_mean':
        combined = pd.Series(np.nan, index=df.index)
        total_weight = 0
        for i, (metric, data) in enumerate(metric_data.items()):
            if i == 0:
                combined = weights[i] * data
            else:
                combined += weights[i] * data
            total_weight += weights[i]
        combined = combined / total_weight if total_weight > 0 else combined
        description = f"Weighted mean: ({' + '.join(descriptions)}) / {total_weight:.2f}"
        
    elif method == 'product':
        combined = pd.Series(1.0, index=df.index)
        for i, (metric, data) in enumerate(metric_data.items()):
            # Add small epsilon to avoid zero products
            data_safe = data.fillna(0.001) + 0.001
            combined *= data_safe ** weights[i]
        description = f"Product: {' × '.join(descriptions)}"
        
    elif method == 'geometric_mean':
        combined = pd.Series(1.0, index=df.index)
        total_weight = sum(weights)
        for i, (metric, data) in enumerate(metric_data.items()):
            data_safe = data.fillna(0.001) + 0.001
            combined *= data_safe ** (weights[i] / total_weight)
        description = f"Geometric mean: {' ∘ '.join(descriptions)}"
        
    else:
        raise ValueError(f"Unknown combination method: {method}")
    
    # Appliquer le masque : NaN si une des métriques est NaN
    combined[~valid_mask] = np.nan
    
    return combined, description

def determine_color_normalization(data: np.ndarray, metric_name: str, 
                                color_log: Optional[bool] = None) -> Tuple[Normalize, str]:
    """
    Determine the best color normalization for a given metric and data.
    
    Parameters
    ----------
    data : np.ndarray
        The data values to normalize
    metric_name : str
        Name of the metric
    color_log : bool, optional
        Force logarithmic scale if True, force linear if False, auto-detect if None
        
    Returns
    -------
    tuple
        (normalization object, description string)
    """
    data_clean = data[np.isfinite(data)]
    if len(data_clean) == 0:
        return Normalize(), "No valid data"
    
    data_min, data_max = np.min(data_clean), np.max(data_clean)
    data_range = data_max - data_min
    
    # Get metric info
    metric_info = get_metric_info(metric_name)
    recommended_scale = metric_info.get('color_scale', 'normal')
    
    # If user explicitly requested log or linear
    if color_log is not None:
        if color_log and data_min > 0:
            return LogNorm(vmin=data_min, vmax=data_max), "Logarithmic (user-requested)"
        else:
            return Normalize(vmin=data_min, vmax=data_max), "Linear (user-requested)"
    
    # Auto-detection based on metric type and data characteristics
    if recommended_scale == 'symlog':
        # For metrics like FA where we want to see small differences near zero
        if data_min >= 0:
            # Use symlog with appropriate threshold
            linthresh = max(data_range * 0.01, 0.1)  # 1% of range or 0.1, whichever is larger
            return SymLogNorm(linthresh=linthresh, vmin=data_min, vmax=data_max), f"Symlog (threshold: {linthresh:.2f})"
        else:
            return Normalize(vmin=data_min, vmax=data_max), "Linear"
    
    elif recommended_scale == 'log_if_large_range':
        # Use log if range is large and all values positive
        if data_min > 0 and (data_max / data_min) > 10:
            return LogNorm(vmin=data_min, vmax=data_max), "Logarithmic (large range)"
        else:
            return Normalize(vmin=data_min, vmax=data_max), "Linear"
    
    else:  # 'normal'
        return Normalize(vmin=data_min, vmax=data_max), "Linear"

def create_legend_markers(ax, best_idx: Tuple[int, int], worst_idx: Tuple[int, int],
                         best_value: float, worst_value: float, 
                         metric_name: str, higher_is_better: bool) -> None:
    """
    Create legend markers for best performing points using a cross marker and do not display worst points.
    
    Parameters
    ----------
    ax : matplotlib.axes.Axes
        The axes to add markers to
    best_idx, worst_idx : tuple
        Indices of best and worst performing points
    best_value, worst_value : float
        Values at best and worst points
    metric_name : str
        Name of the performance metric
    higher_is_better : bool
        Whether higher values are better for this metric
    """
    if metric_name == 'FA' : 
        best_idx, worst_idx = best_idx,worst_idx  # Swap for FA since lower is better
        best_value, worst_value = best_value, worst_value  # Swap values too
        
    # Define marker styles
    if higher_is_better:
        # Best: Green cross
        best_label = f'Best: {best_value:.3f}'
    else:
        # Best (lowest): Green cross
        best_label = f'Best (lowest): {best_value:.3f}'
    
    # Add marker for best point
    ax.scatter([best_idx[1]], [best_idx[0]], s=300, marker='x', 
               color='limegreen', linewidth=3, zorder=10)
    
    return best_label, None

def analyze_calibration_grid(folder_path: str, 
                           x_column: str, 
                           y_column: str, 
                           color_column,  # Can be str or dict for combined metrics
                           x_log: bool = False,
                           y_log: bool = False,
                           color_log: Optional[bool] = None,  # Changed to Optional for auto-detection
                           colormap: str = 'Spectral',
                           figsize: Tuple[int, int] = (12, 10),
                           title: Optional[str] = None,
                           save_path: Optional[str] = None,
                           dpi: int = 300,
                           show_values: bool = False,
                           font_size: int = 8,
                           show_metric_info: bool = True) -> Tuple[plt.Figure, plt.Axes, pd.DataFrame]:
    """
    Visualize calibration results as a pixel grid with improved legends and color scaling.
    
    Each pixel represents one exact parameter combination, colored by a performance
    statistic. This provides a comprehensive view of the parameter space exploration
    and identifies optimal parameter regions.
    
    Parameters
    ----------
    folder_path : str
        Path to folder containing parameters_*.csv files
    x_column : str
        Column name for X-axis parameter (e.g., 'hk')
    y_column : str
        Column name for Y-axis parameter (e.g., 'sy')
    color_column : str or dict
        Column name for the performance statistic to color pixels, OR
        Dictionary for combined metrics: 
        {'metrics': ['NSElog', 'FA'], 'weights': [1, 0.5], 'method': 'weighted_sum'}
    x_log : bool, default=False
        Use logarithmic scale for X-axis
    y_log : bool, default=False
        Use logarithmic scale for Y-axis
    color_log : bool, optional
        Use logarithmic scale for colorbar (None for auto-detection)
    colormap : str, default='Spectral'
        Matplotlib colormap name
    figsize : tuple, default=(12, 10)
        Figure size in inches (width, height)
    title : str, optional
        Custom title for the plot
    save_path : str, optional
        Path to save the figure
    dpi : int, default=300
        Resolution for saved figure
    show_values : bool, default=False
        Display numeric values in each pixel
    font_size : int, default=8
        Font size for pixel values (if show_values=True)
    show_metric_info : bool, default=True
        Display information box about the metric
        
    Returns
    -------
    fig : matplotlib.figure.Figure
        The created figure object
    ax : matplotlib.axes.Axes
        The main axes object
    df_combined : pandas.DataFrame
        Combined dataframe with all calibration results
    """
    
    print(f"Analyzing calibration grid from: {folder_path}")
    
    # Step 1: Read and combine CSV files
    pattern = os.path.join(folder_path, "parameters_*.csv")
    csv_files = glob.glob(pattern)
    
    if not csv_files:
        raise FileNotFoundError(f"No parameters_*.csv files found in {folder_path}")
    
    print(f"Found {len(csv_files)} CSV files")
    
    # Read and combine all CSV files
    dataframes = []
    for file_path in csv_files:
        try:
            df = pd.read_csv(file_path)
            df['source_file'] = os.path.basename(file_path)
            dataframes.append(df)
            print(f"  Loaded {os.path.basename(file_path)}: {len(df)} rows")
        except Exception as e:
            print(f"  Error reading {os.path.basename(file_path)}: {e}")
    
    if not dataframes:
        raise ValueError("No valid CSV files found")
    
    # Combine all DataFrames
    df_combined = pd.concat(dataframes, ignore_index=True)
    print(f"Combined dataset: {len(df_combined)} rows, {len(df_combined.columns)} columns")
    
    # Step 2: Data validation and cleaning
    required_columns = [x_column, y_column]
    missing_columns = [col for col in required_columns if col not in df_combined.columns]
    
    if missing_columns:
        available_cols = list(df_combined.columns)
        raise ValueError(f"Missing columns: {missing_columns}. Available: {available_cols}")
    
    # Clean and convert data types
    df_clean = df_combined.copy()
    
    # Convert parameter columns to numeric
    for col in required_columns:
        df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce')
    
    # --- FIX: Handle combined metrics before using color_column as a string ---
    combined_metric_description = None
    if isinstance(color_column, dict):
        # Extract combination parameters
        metrics = color_column.get('metrics', [])
        weights = color_column.get('weights', None)
        method = color_column.get('method', 'weighted_sum')
        normalize = color_column.get('normalize', True)
        print(f"Combining metrics: {metrics} with method: {method}")
        # Combine the metrics
        combined_series, combined_metric_description = combine_metrics(
            df_clean, metrics, weights, method, normalize
        )
        # Add combined metric to dataframe
        combined_name = f"Combined_{method}"
        df_clean[combined_name] = combined_series
        color_column = combined_name
        print(f"Combined metric created: {combined_metric_description}")
    # --- END FIX ---
    
    # Handle color column (may be missing or contain NaN)
    if color_column not in df_clean.columns:
        df_clean[color_column] = np.nan
        print(f"Warning: Color column '{color_column}' not found, will show as gray pixels")
    else:
        df_clean[color_column] = pd.to_numeric(df_clean[color_column], errors='coerce')
    
    # Remove rows with missing parameter values
    df_clean = df_clean.dropna(subset=required_columns)
    
    if len(df_clean) == 0:
        raise ValueError("No valid data found after cleaning")
    
    print(f"Clean dataset: {len(df_clean)} valid points")
    
    # Step 3: Create parameter grid
    x_values = sorted(df_clean[x_column].unique())
    y_values = sorted(df_clean[y_column].unique())
    
    print(f"Grid structure:")
    print(f"  {x_column}: {len(x_values)} unique values")
    print(f"  {y_column}: {len(y_values)} unique values")
    print(f"  Theoretical grid: {len(x_values)}×{len(y_values)} = {len(x_values)*len(y_values)} pixels")
    print(f"  Data points: {len(df_clean)}")
    
    # Step 4: Create data matrix
    grid_matrix = np.full((len(y_values), len(x_values)), np.nan)
    
    # Fill matrix with performance data
    points_placed = 0
    for _, row in df_clean.iterrows():
        try:
            x_idx = x_values.index(row[x_column])
            y_idx = y_values.index(row[y_column])
            val = row[color_column] if pd.notnull(row[color_column]) else np.nan
            grid_matrix[y_idx, x_idx] = val
            points_placed += 1
        except ValueError:
            continue
    
    print(f"Successfully placed {points_placed} points in grid")
    
    # Calculate grid statistics
    valid_pixels = np.sum(~np.isnan(grid_matrix))
    total_pixels = grid_matrix.size
    coverage = 100 * valid_pixels / total_pixels
    print(f"Grid coverage: {valid_pixels}/{total_pixels} pixels ({coverage:.1f}%)")
    
    # Step 5: Create the visualization with more space for legends
    fig = plt.figure(figsize=figsize, facecolor='white', dpi=100)
    
    # Create main plot area (leaving space at bottom for legends)
    ax = fig.add_subplot(111)
    
    # Configure color normalization with improved auto-detection
    norm = None
    norm_description = "No data"
    if color_column in df_clean.columns:
        z_data = df_clean[color_column].dropna()
        if len(z_data) > 0:
            norm, norm_description = determine_color_normalization(z_data.values, color_column, color_log)
            print(f"Color normalization: {norm_description}")
    
    # Configure colormap with gray for NaN values
    cmap = plt.get_cmap(colormap).copy()
    cmap.set_bad(color='lightgray', alpha=0.8)
    
    # Create equally spaced pixel grid
    x_edges = np.arange(len(x_values) + 1) - 0.5
    y_edges = np.arange(len(y_values) + 1) - 0.5
    
    # Create the heatmap
    X_edges, Y_edges = np.meshgrid(x_edges, y_edges)
    im = ax.pcolormesh(X_edges, Y_edges, grid_matrix, 
                      cmap=cmap, norm=norm, 
                      shading='flat', alpha=0.9,
                      edgecolors='white', linewidth=0.1)
    
    # Add numeric values to pixels if requested
    if show_values and color_column in df_clean.columns:
        z_data_valid = df_clean[color_column].dropna()
        if len(z_data_valid) > 0:
            z_median = np.median(z_data_valid)
            for i in range(len(y_values)):
                for j in range(len(x_values)):
                    if not np.isnan(grid_matrix[i, j]):
                        # Choose text color based on value relative to median
                        text_color = 'white' if grid_matrix[i, j] < z_median else 'black'
                        ax.text(j, i, f'{grid_matrix[i, j]:.3f}',
                               ha='center', va='center', 
                               fontsize=font_size, color=text_color, 
                               weight='bold', alpha=0.8)
    
    # Step 6: Configure axes with proper parameter values
    def format_tick_labels(values: List[float], is_log: bool) -> List[str]:
        """Format tick labels based on value range and log scale."""
        labels = []
        for val in values:
            if is_log:
                if val >= 1e-3 and val < 1e3:
                    labels.append(f"{val:.3g}")
                else:
                    labels.append(f"{val:.2e}")
            else:
                # Smart formatting based on value magnitude
                if abs(val) >= 1e3 or (abs(val) < 1e-2 and abs(val) > 0):
                    labels.append(f"{val:.2e}")
                elif abs(val) < 0.1:
                    labels.append(f"{val:.4f}")
                else:
                    labels.append(f"{val:.3g}")
        return labels
    
    # X-axis configuration
    n_ticks_x = min(10, len(x_values))
    x_tick_indices = np.linspace(0, len(x_values)-1, n_ticks_x, dtype=int)
    x_tick_values = [x_values[i] for i in x_tick_indices]
    x_tick_labels = format_tick_labels(x_tick_values, x_log)
    
    ax.set_xticks(x_tick_indices)
    ax.set_xticklabels(x_tick_labels, rotation=45, ha='right')
    
    # Y-axis configuration
    n_ticks_y = min(10, len(y_values))
    y_tick_indices = np.linspace(0, len(y_values)-1, n_ticks_y, dtype=int)
    y_tick_values = [y_values[i] for i in y_tick_indices]
    y_tick_labels = format_tick_labels(y_tick_values, y_log)
    
    ax.set_yticks(y_tick_indices)
    ax.set_yticklabels(y_tick_labels)
    
    # Axis labels
    x_label = f"{x_column}" + (" (log scale)" if x_log else "")
    y_label = f"{y_column}" + (" (log scale)" if y_log else "")
    ax.set_xlabel(x_label, fontsize=12, fontweight='bold')
    ax.set_ylabel(y_label, fontsize=12, fontweight='bold')
    
    # Step 7: Add colorbar with enhanced information
    if norm is not None:
        cbar = plt.colorbar(im, ax=ax, shrink=0.8, aspect=25, pad=0.02)
        
        # Get metric information
        if combined_metric_description:
            cbar_label = "Combined Metric"
        else:
            metric_info = get_metric_info(color_column)
            cbar_label = f"{metric_info['name']}"
            
        if norm_description != "Linear":
            cbar_label += f" ({norm_description})"
        
        cbar.set_label(cbar_label, fontsize=11, fontweight='bold')
        cbar.ax.tick_params(labelsize=9)
    
    # Step 8: Mark extreme values with improved markers
    best_label = worst_label = None
    if color_column in df_clean.columns and len(z_data) > 0:
        # Find best and worst performing pixels
        best_idx = np.unravel_index(np.nanargmax(grid_matrix), grid_matrix.shape)
        worst_idx = np.unravel_index(np.nanargmin(grid_matrix), grid_matrix.shape)
        
        best_value = grid_matrix[best_idx]
        worst_value = grid_matrix[worst_idx]
        
        # Determine if higher is better based on metric type
        metric_info = get_metric_info(color_column)
        higher_is_better = metric_info.get('optimal') not in ['0.0', 'Lower']
        
        # Create legend markers
        best_label, worst_label = create_legend_markers(
            ax, best_idx, worst_idx, best_value, worst_value, 
            color_column, higher_is_better
        )
    
    # Configure title
    if title is None:
        if combined_metric_description:
            title = f"Calibration Grid Analysis: Combined Metric\n"
            title += f"{combined_metric_description}\n"
            title += f"Parameter Space: {x_column} vs {y_column}"
        else:
            metric_info = get_metric_info(color_column)
            title = f"Calibration Grid Analysis: {metric_info['name']}\n"
            title += f"Parameter Space: {x_column} vs {y_column}"
    
    ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
    
    # Step 9: Add information panels in the plot area
    # Grid statistics panel (top right)
    """
    stats_text = f"Grid: {len(x_values)}×{len(y_values)}\n"
    stats_text += f"Simulations: {valid_pixels}/{total_pixels}\n"
    stats_text += f"Coverage: {coverage:.1f}%"
    
    ax.text(0.98, 0.98, stats_text, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9,
                     edgecolor='gray', linewidth=1))
    """
    # Metric information panel (top left)
    """
    if show_metric_info and color_column in df_clean.columns:
        if combined_metric_description:
            info_text = "Combined Metric\n"
            info_text += f"Formula: {combined_metric_description}\n"
            info_text += "Higher values = better performance"
        else:
            metric_info = get_metric_info(color_column)
            info_text = f"{metric_info['name']}\n"
            info_text += f"Range: {metric_info.get('range', 'N/A')}\n"
            info_text += f"Optimal: {metric_info.get('optimal', 'N/A')}"
        
        ax.text(0.02, 0.98, info_text, transform=ax.transAxes, fontsize=8,
                verticalalignment='top', horizontalalignment='left',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='lightblue', alpha=0.8,
                         edgecolor='blue', linewidth=1))
    """
    # Step 10: Create legends outside the plot area
    plt.tight_layout()
    
    # Adjust layout to make room for legends at bottom
    plt.subplots_adjust(bottom=0.15)
    
    # Create legends below the plot
    legend_elements = []
    
    # Add extreme values legend
    if best_label and worst_label:
        legend_elements.extend([
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='dark', 
                      markeredgecolor='dark', markersize=10, label=best_label, linewidth=0),
            plt.Line2D([0], [0], marker='^', color='w', markerfacecolor='red', 
                      markeredgecolor='darkred', markersize=10, label=worst_label, linewidth=0)
        ])
    
    # Add legend for gray pixels if needed
    if valid_pixels < total_pixels:
        legend_elements.append(
            Patch(facecolor='lightgray', edgecolor='black', alpha=0.8, 
                  label='Not simulated/Failed')
        )
    
    # Place legend below the plot
    if legend_elements:
        legend = fig.legend(handles=legend_elements, loc='lower center', 
                           bbox_to_anchor=(0.5, 0.02), ncol=len(legend_elements),
                           fontsize=10, frameon=True, fancybox=True, shadow=True)
        if legend:
            legend.get_frame().set_facecolor('white')
            legend.get_frame().set_alpha(0.9)
    
    # Step 11: Final formatting
    ax.grid(True, alpha=0.2, linestyle='-', linewidth=0.5)
    ax.set_aspect('equal', adjustable='box')
    
    # Save figure if path provided
    if save_path:
        plt.savefig(save_path, dpi=dpi, bbox_inches='tight', 
                   facecolor='white', edgecolor='none')
        print(f"Figure saved to: {save_path}")
    
    # Print summary and save to CSV
    if color_column in df_clean.columns and len(z_data) > 0:
        print(f"\nCalibration Grid Summary:")
        print(f"  Grid dimensions: {len(x_values)}×{len(y_values)} pixels")
        print(f"  Valid simulations: {valid_pixels}/{total_pixels} ({coverage:.1f}%)")
        print(f"  {color_column} range: {z_data.min():.3f} to {z_data.max():.3f}")
        print(f"  Color normalization: {norm_description}")
        
        # Best parameter combination
        best_idx = np.unravel_index(np.nanargmax(grid_matrix), grid_matrix.shape)
        best_x = x_values[best_idx[1]]
        best_y = y_values[best_idx[0]]
        best_z = grid_matrix[best_idx]
        print(f"  Best performance: {x_column}={best_x:.3e}, {y_column}={best_y:.3e} → {best_z:.3f}")
        
        # Save summary to CSV
        summary_data = {
            "Grid Dimensions": [f"{len(x_values)}×{len(y_values)}"],
            "Valid Simulations": [f"{valid_pixels}/{total_pixels} ({coverage:.1f}%)"],
            f"{color_column} Range": [f"{z_data.min():.3f} to {z_data.max():.3f}"],
            "Color Normalization": [norm_description],
            "Best Performance": [f"{x_column}={best_x:.3e}, {y_column}={best_y:.3e} → {best_z:.3f}"]
        }
        summary_df = pd.DataFrame(summary_data)
        csv_path = os.path.join(folder_path, "calibration_grid_summary.csv")
        summary_df.to_csv(csv_path, index=False)
        print(f"Summary saved to: {csv_path}")
    
    return fig, ax, df_combined

def explore_parameter_grid(folder_path: str) -> Optional[pd.DataFrame]:
    """
    Explore the structure of parameter grid data.
    
    This function analyzes the CSV files to understand the parameter space
    and available metrics, providing guidance for visualization.
    
    Parameters
    ----------
    folder_path : str
        Path to folder containing parameters_*.csv files
        
    Returns
    -------
    pandas.DataFrame or None
        Combined dataframe if successful, None if no data found
    """
    
    print("Exploring parameter grid structure")
    print("="*40)
    
    # Find and read CSV files
    pattern = os.path.join(folder_path, "parameters_*.csv")
    csv_files = glob.glob(pattern)
    
    if not csv_files:
        print(f"No parameter files found in {folder_path}")
        return None
    
    # Read first few files for exploration
    dataframes = []
    for file_path in csv_files[:3]:  # Sample first 3 files
        try:
            df = pd.read_csv(file_path)
            dataframes.append(df)
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            continue
    
    if not dataframes:
        return None
    
    df_combined = pd.concat(dataframes, ignore_index=True)
    
    print(f"Sample data: {len(df_combined)} rows, columns: {list(df_combined.columns)}")
    
    # Identify parameter and metric columns
    param_keywords = ['hk', 'sy', 'k', 'conductivity', 'porosity', 'storage', 'thick']
    metric_keywords = ['NSE', 'RMSE', 'KGE', 'SMPI', 'R2', 'bias', 'FA', 'Dmean', 'FQA']
    
    found_params = [col for col in df_combined.columns 
                   if any(keyword.lower() in col.lower() for keyword in param_keywords)]
    found_metrics = [col for col in df_combined.columns 
                    if any(keyword in col.upper() for keyword in metric_keywords)]
    
    print(f"\nDetected parameters: {found_params}")
    print(f"Detected metrics: {found_metrics}")
    
    # Analyze parameter value ranges
    for param in found_params[:3]:  # Analyze first 3 parameters
        if param in df_combined.columns:
            values = sorted(df_combined[param].dropna().unique())
            print(f"\n{param} analysis:")
            print(f"  Unique values: {len(values)}")
            if len(values) > 0:
                print(f"  Range: {values[0]:.3e} to {values[-1]:.3e}")
                if len(values) <= 10:
                    print(f"  All values: {[f'{v:.3e}' for v in values]}")
                else:
                    print(f"  Sample: {[f'{v:.3e}' for v in values[:3]]} ... {[f'{v:.3e}' for v in values[-2:]]}")
    
    return df_combined

def create_combined_metric(metrics: List[str], 
                          weights: Optional[List[float]] = None,
                          method: str = 'weighted_sum',
                          normalize: bool = True) -> Dict:
    """
    Create a combined metric configuration dictionary.
    
    Parameters
    ----------
    metrics : list of str
        List of metric names to combine (e.g., ['NSElog', 'FA'])
    weights : list of float, optional
        Weights for each metric (default: equal weights)
    method : str, default='weighted_sum'
        Combination method:
        - 'weighted_sum': Sum of weighted normalized metrics
        - 'weighted_mean': Mean of weighted normalized metrics  
        - 'product': Product of weighted normalized metrics
        - 'geometric_mean': Geometric mean of weighted normalized metrics
    normalize : bool, default=True
        Whether to normalize metrics to [0,1] before combining
        
    Returns
    -------
    dict
        Configuration dictionary for use with analyze_calibration_grid
        
    Examples
    --------
    >>> # Combine NSElog and FA with equal weights
    >>> combined = create_combined_metric(['NSElog', 'FA'])
    >>> fig, ax, df = analyze_calibration_grid(path, 'hk', 'sy', combined)
    
    >>> # Combine with custom weights (NSElog twice as important as FA)
    >>> combined = create_combined_metric(['NSElog', 'FA'], weights=[1, 1])
    >>> fig, ax, df = analyze_calibration_grid(path, 'hk', 'sy', combined)
    """
    return {
        'metrics': metrics,
        'weights': weights,
        'method': method,
        'normalize': normalize
    }

def quick_combined_plot(folder_path: str,
                       metrics: List[str],
                       x_column: str = 'hk', 
                       y_column: str = 'sy',
                       weights: Optional[List[float]] = None,
                       method: str = 'weighted_sum') -> Tuple[plt.Figure, plt.Axes, pd.DataFrame]:
    """
    Create a quick plot with combined metrics.
    
    Parameters
    ----------
    folder_path : str
        Path to folder containing parameters_*.csv files
    metrics : list of str
        List of metrics to combine (e.g., ['NSElog', 'FA'])
    x_column, y_column : str
        Parameter columns for axes
    weights : list of float, optional
        Weights for each metric
    method : str, default='weighted_sum'
        Combination method
        
    Returns
    -------
    tuple
        Figure, axes, and dataframe objects
        
    Examples
    --------
    >>> # Quick plot combining NSElog and FA
    >>> fig, ax, df = quick_combined_plot(path, ['NSElog', 'FA'])
    
    >>> # With custom weights
    >>> fig, ax, df = quick_combined_plot(path, ['NSElog', 'FA'], weights=[1, 1])
    """
    
    print(f"Creating combined metric plot: {metrics}")
    print(f"Method: {method}, Weights: {weights}")
    
    # Create combined metric configuration
    combined_config = create_combined_metric(metrics, weights, method, normalize=True)
    
    # Auto-detect parameter scales
    df = explore_parameter_grid(folder_path)
    if df is None:
        return None, None, None
    
    x_log = False
    y_log = False
    
    if x_column in df.columns:
        x_values = df[x_column].dropna()
        if len(x_values) > 1 and x_values.min() > 0:
            x_ratio = x_values.max() / x_values.min()
            if x_ratio > 100:
                x_log = True
                print(f"Using log scale for {x_column} (range factor: {x_ratio:.1f})")
    
    if y_column in df.columns:
        y_values = df[y_column].dropna()
        if len(y_values) > 1 and y_values.min() > 0:
            y_ratio = y_values.max() / y_values.min()
            if y_ratio > 100:
                y_log = True
                print(f"Using log scale for {y_column} (range factor: {y_ratio:.1f})")
    
    # Use a suitable colormap for combined metrics (higher = better)
    colormap = 'Spectral' # Red-Yellow-Green 
    
    # Create the plot
    fig, ax, df = analyze_calibration_grid(
        folder_path=folder_path,
        x_column=x_column,
        y_column=y_column,
        color_column=combined_config,
        x_log=x_log,
        y_log=y_log,
        color_log=None,  # Auto-detect
        colormap=colormap,
        figsize=(12, 10),
        show_values=False,
        show_metric_info=True
    )
    
    return fig, ax, df

def quick_grid_plot(folder_path: str, 
                   x_column: str = 'hk', 
                   y_column: str = 'sy', 
                   color_column = 'NSE') -> Tuple[plt.Figure, plt.Axes, pd.DataFrame]:
    """
    Create a quick calibration grid plot with automatic scale detection.
    
    Parameters
    ----------
    folder_path : str
        Path to folder containing parameters_*.csv files
    x_column : str, default='hk'
        Parameter for X-axis
    y_column : str, default='sy'
        Parameter for Y-axis  
    color_column : str or dict, default='NSE'
        Metric for pixel coloring, or combined metric configuration
        
    Returns
    -------
    tuple
        Figure, axes, and dataframe objects
    """
    
    print("Creating quick calibration grid plot")
    print("="*35)
    
    # Explore data first
    df = explore_parameter_grid(folder_path)
    if df is None:
        return None, None, None
    
    # Auto-detect logarithmic scales
    x_log = False
    y_log = False
    
    if x_column in df.columns:
        x_values = df[x_column].dropna()
        if len(x_values) > 1 and x_values.min() > 0:
            x_ratio = x_values.max() / x_values.min()
            if x_ratio > 100:
                x_log = True
                print(f"Using log scale for {x_column} (range factor: {x_ratio:.1f})")
    
    if y_column in df.columns:
        y_values = df[y_column].dropna()
        if len(y_values) > 1 and y_values.min() > 0:
            y_ratio = y_values.max() / y_values.min()
            if y_ratio > 100:
                y_log = True
                print(f"Using log scale for {y_column} (range factor: {y_ratio:.1f})")
    
    # Choose appropriate colormap based on metric
    if any(keyword in color_column.upper() for keyword in ['NSE', 'KGE']):
        colormap = 'RdYlGn'  # Red-Yellow-Green (bad to good)
    elif any(keyword in color_column.upper() for keyword in ['RMSE', 'FA', 'DMEAN', 'FQA']):
        colormap = 'RdYlBu'  # Red-Yellow-Blue (high values bad)
    else:
        colormap = 'Spectral'  # Default
    
    # Create the plot with auto color scaling
    fig, ax, df = analyze_calibration_grid(
        folder_path=folder_path,
        x_column=x_column,
        y_column=y_column,
        color_column=color_column,
        x_log=x_log,
        y_log=y_log,
        color_log=None,  # Auto-detect based on metric
        colormap=colormap,
        figsize=(12, 10),
        show_values=False,
        show_metric_info=True
    )
    
    return fig, ax, df

def print_metric_definitions():
    """Print detailed definitions of all available performance metrics."""
    
    print("HYDROLOGICAL MODEL PERFORMANCE METRICS")
    print("="*50)
    
    categories = {
        'Streamflow Metrics': ['NSE', 'NSElog', 'KGE', 'RMSE'],
        'Spatial Network Metrics': ['FA', 'Dmean', 'FQA', 'Dd_sim', 'Dd_obs']
    }
    
    for category, metrics in categories.items():
        print(f"\n{category}:")
        print("-" * len(category))
        
        for metric in metrics:
            if metric in METRIC_DEFINITIONS:
                info = METRIC_DEFINITIONS[metric]
                print(f"\n{metric} - {info['name']}")
                print(f"  Description: {info['description']}")
                print(f"  Formula: {info['formula']}")
                print(f"  Range: {info['range']}")
                print(f"  Optimal value: {info['optimal']}")
                print(f"  Interpretation: {info['interpretation']}")
                print(f"  Color scale: {info['color_scale']}")
#%%
if __name__ == "__main__":
    folder_path = r"C:\Users\theat\Documents\Python\02_Output_HydroModPy\LA_FLUME\last_FA_LOG\parameters"
    if os.path.exists(folder_path):
        print_metric_definitions()
        
        df = explore_parameter_grid(folder_path)
        if df is not None:
            fig1, ax1, df1 = quick_grid_plot(folder_path, 'hk', 'sy', 'NSElog')
            fig2, ax2, df2 = quick_combined_plot(folder_path, ['NSElog', 'FA'], weights=[1, 1], method='weighted_mean')
            plt.show()
        else:
            print("No data found for visualization")
    else:
        print(f"Test path does not exist: {folder_path}")
        print("Please update the path to your calibration results folder")

# %%
