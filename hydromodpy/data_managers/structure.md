Datamanager folder 
## data list 
`precip`
`etp`
`runoff`
`recharge`
`geology`
`hydrography`
`hydrometry`
`intermittency`
`oceanic`
`piezometry`
`point`
`subbasin`

##DataClass
`Climatic`
`Geology`
`Hydrography`
`Hydrometry`
`Intermittency`
`Oceanic`
`Piezometry`
`Point`
`Subbasin`

## standardization output name 
All outputs should be clip at the catchment scale
`TYPE_PRODUCT_ID_startdate_enddate_freq.extention`
TYPE = folder's name 
PRODUCT = data source 
ID = station's name 
startdate = first day of the simulation period
enddate = Last day of the simulation period
freq = time's discretization ('D' for days, 'ME' for month, 'YE' for year)

Some examples above
        precip_sim2_ID_20010131_20031231_ME.nc 
        precip_meteofrance_saintjacques_20010131_20031231_ME.csv
        runoff_custom_pontdeleglise_20010131_20031231_ME.csv

        geology_BRGM1M_level1.tif

        hydrometry_HUBEAU_LOC.csv # csv file needed to link measurement points to their locations
        hydrometry_HUBEAU_J7214001_20010131_20031231_ME.csv      
        hydrometry_HUBEAU_J7214002_20010131_20031231_ME.csv

        hydrography_BDTOPAGE_COURSDEAU.shp

        intermittency 
        oceanic_SHOM_185_20010131_20031231_ME.csv
        oceanic_SHOM_185_20010131_20031231_ME.nc
        piezometry 
