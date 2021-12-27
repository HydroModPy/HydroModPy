load = True
print('##### '+watershed_name.upper()+' #####')

# try:
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              surfex_path=surfex_path, 
                              geology_path = geology_path, 
                              hydrology_path=hydrology_path,
                              oceanic_path=oceanic_path, 
                              piezometry_path=piezometry_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              types_obs=types_obs,
                              fields_obs=fields_obs)
# except:
#     print('There is a problem to generate the watershed object')

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)