Last modification 07052025
Odile de La Rue du Can
------------------------------------------------------------------
GENERAL INFORMATION ABOUT CODE

Currently Useful files:

toolbox_newsFuns_ :
	- (not class)  		: folder and debiasing tools 
	-  class Geo   		: tools to manipulate shp file and geodataframe
	-  class CERRA 		: tools to manipulate Cerra data from netcdf files¨
	-  class WeatherStation : tools to manipulate weather station (should respect WATERWISE data base structure)
	-  class ClimateStats	: tools to manipulate Time serie Statistical data and generate plots from them

toolbox_tester : test most functions proposed in the toolbax and give example on how to use them
main_local_cera : few useful codes using the toolbox to extract local cerra file, generate timeserie files or help inpu files for example


-------------------------------------------------------------------------
DEVELOPPEMENT NOTES

Finalisation pyhelp

- pyhelp_cerra/ method extract_cerra_timeseries
- pyhelp_cerra/ method _load_grid
- create cerra netcdf handler
- cerra netcdf handler / extract catchement area and combine (?)
- cerra netcdf handler / empty year for grid
- utilities gdf
- utilities netcdf
- pyhelp_grid / _empty_grid

Info needed about observation:
- lat/lon
- alt
- timestep 'D' 'H' '3H'

sado/malga sadole
Temperature date - beginning of each month - data points go away from the trend (human action?) 