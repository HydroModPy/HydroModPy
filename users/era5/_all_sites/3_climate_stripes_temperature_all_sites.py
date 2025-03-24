import os
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.collections import PatchCollection
from matplotlib.colors import ListedColormap
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

plt.close('all')


def load_data(file_path):
    df = pd.read_csv(file_path, index_col=0)
    df.index = pd.to_datetime(df.index)
    
    return df.resample('Y').mean()


def compute_anomaly(df, start_ref, end_ref):
    mean_ref = df['mean'][(df.index >= start_ref) & (df.index <= end_ref)].mean()
    df['anomaly'] = df['mean'] - mean_ref
    return df


def plot_stripes(df, FIRST, LAST, anomaly, cmap, LIM, fig_folder, variable_name):
    fig = plt.figure(figsize=(10, 1))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()

    col = PatchCollection([
        Rectangle((y, 0), 1, 1) for y in range(FIRST, LAST + 1)
    ])
    col.set_array(anomaly.values)
    col.set_cmap(cmap)
    col.set_clim(-LIM, LIM)
    ax.add_collection(col)

    ax.set_ylim(0, 1)
    ax.set_xlim(FIRST, LAST + 1)

    save_plot(fig, fig_folder, variable_name)


def save_plot(fig, fig_folder, variable_name):
    os.makedirs(fig_folder, exist_ok=True)
    fig_name = os.path.join(fig_folder, 'climate_stripes.png')
    fig.savefig(fig_name, dpi=300, bbox_inches='tight')
    print(f"Plot saved")


# Paths and settings
output_folder = r'Y:/_waterwise_data_process/_climate/_era5'
sites = ["_cont", "_jamt", "_gdsa", "_rech", "_sado", "_zugs", "_peca", "_urse"]

for site in sites:
    print('####################################################################')
    print(f"Processing site: {site}")
    print('')
    site_folder = os.path.join(output_folder, site)
    fig_folder = os.path.join(site_folder, 'fig')

    variable = '2m_temperature'

    file = os.path.join(site_folder,'_hourly', f'{variable}_hourly.csv')

    # Load and process data
    df = load_data(file)
    FIRST, LAST = df.index.year.min(), df.index.year.max()
    
    start_ref = pd.Timestamp('1961-01-01')
    end_ref = pd.Timestamp('2000-12-31')
    if end_ref > df.index.max():
        end_ref = df.index.max()
    
    df = compute_anomaly(df, start_ref, end_ref)
    anomaly = df['anomaly'][(df.index.year >= FIRST) & (df.index.year <= LAST)].dropna()
    
    # Plot settings
    LIM = 2.5
    cmap = ListedColormap([
        '#08306b', '#08519c', '#2171b5', '#4292c6',
        '#6baed6', '#9ecae1', '#c6dbef', '#deebf7',
        '#fee0d2', '#fcbba1', '#fc9272', '#fb6a4a',
        '#ef3b2c', '#cb181d', '#a50f15', '#67000d',
    ])
    
    # Generate and save plot
    plot_stripes(df, FIRST, LAST, anomaly, cmap, LIM, fig_folder, variable)
