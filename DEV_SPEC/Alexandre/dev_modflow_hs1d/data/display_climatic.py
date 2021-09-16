# coding:utf-8
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import os
import matplotlib as mpl
import numpy as np
import matplotlib.dates as mdates
from matplotlib.font_manager import FontProperties
import matplotlib.ticker as ticker
from IPython.core.debugger import set_trace as st

# Parameters
# Parameters plot : v2.0 to classic customized
# mpl.style.use('default')
# mpl.rcParams.update(mpl.rcParamsDefault)

# # # Classic
mpl.style.use('classic')
mpl.rcParams["figure.facecolor"] = 'white'
mpl.rcParams['grid.color'] = 'darkgrey'
mpl.rcParams['grid.linestyle'] = '-'
mpl.rcParams['grid.alpha'] = 0.8
mpl.rcParams['axes.axisbelow'] = True
mpl.rcParams['figure.dpi'] = 300
mpl.rcParams['savefig.dpi'] = 300
mpl.rcParams['patch.force_edgecolor'] = True
mpl.rcParams['image.interpolation'] = 'nearest'
mpl.rcParams['image.resample'] = True
mpl.rcParams['axes.autolimit_mode'] = 'data' # 'round_numbers'
# mpl.rcParams['axes.autolimit_mode'] = 'round_numbers' # 'data' 
mpl.rcParams['axes.xmargin'] = 0.1
mpl.rcParams['axes.ymargin'] = 0.1
mpl.rcParams['xtick.direction'] = 'in'
mpl.rcParams['ytick.direction'] = 'in'
mpl.rcParams['xtick.top'] = True
mpl.rcParams['ytick.right'] = True
mpl.rcParams['legend.numpoints'] = 1
mpl.rcParams['legend.scatterpoints'] = 1
mpl.rcParams['legend.edgecolor'] = 'grey'
mpl.rcParams['date.autoformatter.year'] = '%Y'
mpl.rcParams['date.autoformatter.month'] = '%Y-%m'
mpl.rcParams['date.autoformatter.day'] = '%Y-%m-%d'
mpl.rcParams['date.autoformatter.hour'] = '%H:%M'
mpl.rcParams['date.autoformatter.minute'] = '%H:%M:%S'
mpl.rcParams['date.autoformatter.second'] = '%H:%M:%S'

# Parameters size plot
smal = 8
medium = 16
large = 20

plt.rc('font', size=medium)						 # controls default text sizes **font
plt.rc('figure', titlesize=medium)				   # fontsize of the figure title
plt.rc('legend', fontsize=smal)					 # legend fontsize
plt.rc('axes', titlesize=medium, labelpad=8)		# fontsize of the axes title
plt.rc('axes', labelsize=medium, labelpad=12)		# fontsize of the x and y labels
plt.rc('xtick', labelsize=medium)				   # fontsize of the tick labels
plt.rc('ytick', labelsize=medium)				   # fontsize of the tick labels
plt.rcParams["font.family"] = "serif"

# Font label and legend properties
fontprop = FontProperties()
fontprop.set_family('serif') # for x and y label
fontdic = {'family' : 'serif'} # for legend

color_dict = {'ACC1':'dodgerblue',
			  'BCC1':'darkorange',
			  'BNU1':'forestgreen',
			  'CAN1':'red',
			  'CNR1':'purple',
			  'CSI1':'saddlebrown',
			  'IPS1':'olive',
			  'MIR1':'salmon',
			  'NOR1':'grey',
			  'REA':'cyan'}

def display_all_variables(data, figure_folder, mod, start, end):
	#mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5','CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1','REA']
	var_list = ['PPT','ETP','RUN','REC','SNOW']
	sce_list = ['historic','RCP2.6','RCP4.5','RCP8.5']
	couleurs = ['blue','green','orange','red','grey']
	for j, sce in enumerate(sce_list):	
		fig, ax = plt.subplots(figsize=(10,5))
		axb = ax.twinx()
		for i, var in enumerate(var_list):
			try:
				x = data[mod][var][sce].loc[start:end]
				if sce == 'historic':
					x = x[(x.index.year >= 1960) & (x.index.year <= 2010)]
				if var == 'PPT' or var == 'SNOW':
					axb.plot(x['MEAN'], c=couleurs[i], label=var)
					axb.set_ylim(0,75)
					axb.invert_yaxis()
					axb.legend(loc='upper right')
					axb.set_ylabel('PPT / SNOW [mm]')
				else:
					ax.plot(x['MEAN'], c=couleurs[i], label=var)
					ax.set_ylim(-1,15)
					ax.legend(loc='lower left')
					ax.set_ylabel('ETP / RUN / REC [mm]')
				ax.set_xlabel('Date')	
				ax.set_xlim([pd.to_datetime(str(x.first_valid_index().year)), 
							 pd.to_datetime(str(x.last_valid_index().year))])
			except:
				pass
		ax.set_title(mod + ' - ' + sce.upper())
		plt.tight_layout()
		name_out = figure_folder + 'RESUME_' + mod.upper() + '_' + sce.upper()
		fig.savefig(name_out + '.png', dpi=300, bbox_inches='tight')
		plt.close()
        
def display_intermensual_scenarios(data, figure_folder, var):
	mod_list = ['ACC1','BCC1','BNU1','CAN1','CNR1','CSI1','IPS1','MIR1','NOR1','REA']
	var_list = ['TAS','PPT','ETP','RUN','REC','SNOW']
	sce_list = ['historic','RCP2.6','RCP4.5','RCP8.5']
	fig, axs = plt.subplots(2,2, figsize=(8,6))
	axs = axs.ravel()
	minim = []
	maxim = []
	for i, sce in enumerate(sce_list):		
		ax = axs[i]
		for mod in mod_list:
			try:
				color = color_dict[mod]
				x = data[mod][var][sce]
				if sce == 'historic':
					x = x[(x.index.year >= 1960) & (x.index.year <= 2010)]
				else:
					x = x[(x.index.year >= 2090) & (x.index.year <= 2100)]
				mask = x.resample("M").count() >= 25
				idx = np.where((mask==False).all(1))[0]
				for i in idx:
					d = mask.index[i].year
					x = x[(x.index.year != d)]
				first = str(x.first_valid_index())[0:10]
				last = str(x.last_valid_index())[0:10]	 
				if var == 'TAS':
					x = x.resample('M').mean()
				else:
					x = x.resample('M').sum()
				x['month'] = x.index.month
				intm = x.groupby(['month']).mean()
				inter = intm.mean(axis=1)
				ax.plot(inter, lw=1.5, label=mod, color=color)
				ax.tick_params(axis='both', which='major', pad=10)
				x1 = np.arange(1,12+1,1)
				squad = ['J','F','M','A','M','J','J','A','S','O','N','D']
				ax.set_xticks(x1)
				ax.set_xticklabels(squad, minor=False, rotation='horizontal')
				ax.set_xlim(1,12)
				ax.set_title(sce.upper() + ' - ' + first[:4] + ' - ' + last[:4])
				ax.grid(True, zorder=-1, alpha=0.25)	
				minim.append(inter.min())
				maxim.append(inter.max())
			except:
				pass
	if minim and maxim:
		for j in range(4):
			fig.axes[j].set_ylim(np.nanmin(minim), np.nanmax(maxim))

	lines, labels = fig.axes[0].get_legend_handles_labels()
	fig.legend(lines, labels, loc='center left', bbox_to_anchor=(1.0, 0.5), frameon=False)
	if var == 'TAS':
		fig.suptitle(var.upper() + " - [°C/month]")
	else:
		fig.suptitle(var.upper() + ' - [mm/month]')
	plt.tight_layout()
	name_out = figure_folder + 'MULTIMODEL_INTM_' + var.upper()
	fig.savefig(name_out + '.png', dpi=300, bbox_inches='tight')

def display_annual_scenarios(data, figure_folder, var):
	mod_list = ['ACC1','BCC1','BNU1','CAN1','CNR1','CSI1','IPS1','MIR1','NOR1','REA']
	var_list = ['TAS','PPT','ETP','RUN','REC','SNOW']
	sce_list = ['historic','RCP2.6','RCP4.5','RCP8.5']
	fig, axs = plt.subplots(2,2, figsize=(8,6))
	axs = axs.ravel()
	minim = []
	maxim = []
	for i, sce in enumerate(sce_list):
		ax = axs[i]
		for mod in mod_list:
			color = color_dict[mod]
			try:
				x = data[mod][var][sce]
				if sce == 'historic':
					x = x[(x.index.year >= 1960) & (x.index.year <= 2010)]
				else:
					x = x[(x.index.year >= 2010) & (x.index.year <= 2100)]
				mask = x.resample("M").count() >= 25
				idx = np.where((mask==False).all(1))[0]
				for i in idx:
					d = mask.index[i].year
					x = x[(x.index.year != d)]
				first = str(x.first_valid_index())[0:10]
				last = str(x.last_valid_index())[0:10]	  
				if var == 'TAS':
					x = x.resample('Y').mean().mean(axis=1)
					
				else:					
					x = x.resample('Y').sum().mean(axis=1)
				years = mdates.YearLocator(20)   # every year
				yearsmin = mdates.YearLocator(1)
				months = mdates.MonthLocator(6)  # every month
				years_fmt = mdates.DateFormatter('%Y')
				months_fmt = mdates.DateFormatter('%m') #b = name of month ?
				ax.plot(x, lw=1.5, label=mod, color=color)
				ax.tick_params(axis='both', which='major', pad=10)
				ax.xaxis.set_major_locator(years)
				ax.xaxis.set_minor_locator(yearsmin)
				ax.xaxis.set_major_formatter(years_fmt)
				ax.set_title(sce.upper() + ' ' + first[:4] + ' - ' + last[:4])
				ax.grid(True, zorder=-1, alpha=0.25)
				ax.set_xlim([pd.to_datetime(first[0:4]), pd.to_datetime(last[0:4])])	
				minim.append(x.min())
				maxim.append(x.max())
				
			except:
				pass

	if minim and maxim:
		for j in range(4):
			fig.axes[j].set_ylim(min(minim), max(maxim))
	
	lines, labels = fig.axes[0].get_legend_handles_labels()
	fig.legend(lines, labels, loc='center left', bbox_to_anchor=(1.0, 0.5), frameon=False)
	if var == 'TAS':
		fig.suptitle(var.upper() + " - [°C/year]")
	else:
		fig.suptitle(var.upper() + ' - [mm/year]')
	plt.tight_layout()
	
	name_out = figure_folder + 'MULTIMODEL_YEARLY_' + var.upper()
	fig.savefig(name_out + '.png', dpi=300, bbox_inches='tight')  

def display_anomaly(data, figure_folder, mod ,var, per_hist, per_fut):
	df = pd.DataFrame()
	sce = ['RCP2.6','RCP4.5','RCP8.5']
	hist = data[mod][var]['historic']
	hist = hist[(hist.index.year>=per_hist[0]) & (hist.index.year<=per_hist[1])]
	if var == 'TAS':
		hist = hist.resample('M').mean()
	else:
		hist = hist.resample('M').sum()
	hist = hist.groupby([lambda x: x.month]).mean()
				
	lims = []
	for per in per_fut:
		for rcp in sce:
			try:
				fut = data[mod][var][rcp]['MEAN']
				fut = fut[(fut.index.year>=per[0]) & (fut.index.year<=per[1])]
				if var == 'TAS':
					fut = fut.resample('M').mean()
				else:
					fut = fut.resample('M').sum()
				fut = fut.groupby([lambda x: x.month]).mean()
				ano = fut - hist['MEAN']
				lims.append(ano.max())
				lims.append(ano.min())
			
				name = rcp+'_'+str(per[0])+'-'+str(per[1])
				df[name] = ano
			except:
				pass
	horiz = len(per_fut)
	fig, axs = plt.subplots(1, horiz, figsize=(horiz*5, 4))
	axs = axs.ravel()
	vmin = round(np.array(lims).min(),2)
	vmax = round(np.array(lims).max(),2)

	compt=0
		
	for per in per_fut:
		ax = axs[compt]
			
		for rcp in sce:
			name = rcp+'_'+str(per[0])+'-'+str(per[1])
			
			if rcp=='RCP2.6':
				colori = 'dodgerblue'
				space = -0.30
			if rcp=='RCP4.5':
				colori = 'forestgreen'
				space = -0.10
			if rcp=='RCP6.0':
				colori = 'orange'
				space = +0.10
			if rcp=='RCP8.5':
				colori = 'red'
				space = +0.30
			try:
				ax.bar(df.index+(space), df[name], width=0.2, align='center',
				   	color=colori, edgecolor='none', label=rcp)
				
				ax.axhline(y=0, linewidth=0.2, color='k')
			
				x1 = [1,2,3,4,5,6,7,8,9,10,11,12]
				squad = ['J','F','M','A','M','J','J','A','S','O','N','D']
				ax.set_xticks(x1)
				ax.set_xticklabels(squad, minor=False, rotation='horizontal')
				plt.xticks(rotation='horizontal')
				ax.set_xlim(0.5,12.5)
				ax.set_ylim(vmin, vmax)
				minorXlocator = ticker.MultipleLocator(0.5)
				ax.xaxis.set_minor_locator(minorXlocator)
				ax.grid(True, which='minor')
				ax.set_title('Period : '+str(per[0])+'-'+str(per[1]), 
						 fontproperties=fontprop, fontsize=13)				
				ax.set_xlabel('Months', fontproperties=fontprop)

			except:
				pass
			if compt==0:
				if var == 'TAS':
					ax.set_ylabel(var + ' [°C]')
				else:
					ax.set_ylabel(var + ' [mm/mois]')
				ax.legend()
				
		compt+=1
				
	plt.suptitle('MODEL : '+mod+' - '+'ANOMALY HISTORIC : '+str(per_hist[0])+'-'+str(per_hist[1]),
					 fontproperties=fontprop, fontsize=14, y=0.95)
	plt.tight_layout()
		
	out = mod+'_'+var+'_'+'RCPs'+'_'+'I'
	fig.savefig(figure_folder+out+'.jpg', dpi=300, bbox_inches='tight')