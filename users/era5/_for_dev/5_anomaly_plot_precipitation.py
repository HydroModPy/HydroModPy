import os
import pandas as pd
import matplotlib.pyplot as plt

### NOT UP TO DATE YET ##########

# Load your hourly Precipitation data 
folder_path = './tp'
name = 'tp_hourly.csv'
file = os.path.join(folder_path, name)
hourly_df = pd.read_csv(file, index_col=0)
hourly_df.index = pd.to_datetime(hourly_df.index)

# Calculate the anomalies relative to a reference period (e.g., 2000-2010)
start_ref = '1960-01-01'
end_ref = '2000-01-01'
mean_ref = hourly_df.loc[(hourly_df.index >= start_ref) & (hourly_df.index < end_ref), 'tp'].mean()
hourly_df['anomaly'] = hourly_df['tp'] - mean_ref

# Group the data by month to create monthly anomalies
monthly_anomalies = hourly_df.resample('M').mean()

# Calculate the rolling 12-month average
rolling_12m_avg = monthly_anomalies['anomaly'].rolling(window=12, min_periods=1).mean()

#%% Plot the anomalies with custom styling
fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

# Set background color
fig.patch.set_facecolor('white')

# Plot monthly anomalies
axes[0].bar(monthly_anomalies.index, monthly_anomalies['anomaly'], 
            color=['red' if anomaly <= 0 else 'blue' for anomaly in monthly_anomalies['anomaly']],
            width = 50)

#axes[0].grid(axis='y', linestyle='--', linewidth=0.5, color='gray')
axes[0].set_ylabel('Anomaly [mm/d]', fontsize=14, labelpad=15)
axes[0].set_title('Monthly Precipitation Anomalies [mm/d]', fontsize=12, pad=20)
axes[0].set_ylim(monthly_anomalies['anomaly'].min() - 0.01, monthly_anomalies['anomaly'].max() + 0.01)

# Plot rolling 12-month average excluding first and last 12 months
rolling_12m_avg_trimmed = rolling_12m_avg.iloc[12:-12]
axes[1].plot(rolling_12m_avg_trimmed.index, rolling_12m_avg_trimmed, color='black')
axes[1].fill_between(rolling_12m_avg_trimmed.index, rolling_12m_avg_trimmed, 0, where=rolling_12m_avg_trimmed >= 0, facecolor='blue', interpolate=True)
axes[1].fill_between(rolling_12m_avg_trimmed.index, rolling_12m_avg_trimmed, 0, where=rolling_12m_avg_trimmed <= 0, facecolor='red', interpolate=True)
axes[1].grid(axis='y', linestyle='--', linewidth=0.5, color='gray')
axes[1].set_ylabel('Anomaly [mm/d]', fontsize=14, labelpad=15)
axes[1].set_title('12-Month Rolling Average Precipitation Anomalies [mm/d]', fontsize=12, pad=20)
axes[1].set_ylim(rolling_12m_avg_trimmed.min() - 0.01, rolling_12m_avg_trimmed.max() + 0.01)

# Customize tick marks and labels
for ax in axes:
    ax.set_xticks(monthly_anomalies.index[::24])  # Display every other year
    ax.set_xticklabels(monthly_anomalies.index.year.unique()[::2], rotation=45, ha='right', fontsize=8)
    # ax.set_yticks(range(int(ax.get_ylim()[0]), int(ax.get_ylim()[1]) + 0.1, 0.1))
    # ax.set_yticklabels(['{:+d}'.format(y) for y in range(int(ax.get_ylim()[0]), int(ax.get_ylim()[1]) + 0.1, 0.1)], fontsize=8)

# Add horizontal line at 0 for both subplots
for ax in axes:
    ax.axhline(0, color='black', linewidth=1)

plt.xticks(fontsize=12)
plt.yticks(fontsize=12)

plt.tight_layout()
plt.show()

fig.savefig('./figures/tp_anomaly.png')