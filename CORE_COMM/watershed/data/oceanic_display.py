# coding:utf-8

import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.font_manager import FontProperties


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

color_dict = {'RCP2.6':'dodgerblue',
			  'RCP8.5':'red',
			  'RCP4.5':'salmon'}

def display_data(data, figure_folder):
	fig = plt.figure()
	for sce in data:
		d = data[sce].index.values
		data[sce]['median'].plot(c=color_dict[sce], label=sce)
		plt.fill_between(d , data[sce]['std high'], data[sce]['std low'],facecolor=color_dict[sce], alpha=0.2)
		#data[sce]['5th per'].plot(c=color_dict[sce],ls='--', label=sce)
		#data[sce]['95th per'].plot(c=color_dict[sce],ls='--', label=sce)

	plt.legend()
	plt.tight_layout()
	name_out = figure_folder + 'plot'
	fig.savefig(name_out + '.png', dpi=300, bbox_inches='tight')