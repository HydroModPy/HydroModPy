# -*- coding: utf-8 -*-
"""
Created on Wed Apr 27 17:16:52 2022

@author: ronan
"""

type_obs = 'streams_fr'

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

# Init
df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)
area = BV.geographic.area
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce = 'historic',
                                  first_year = 1960, last_year=2019, time_step = 'D',
                                  sim_state = 'steady') #
BV.hydrodynamic.update_thickness(30)
# BV.hydrodynamic.update_porosity(0.1)
# BV.hydrodynamic.update_hyd_cond(2)
params_df = pd.DataFrame(columns=['params',
                                  'init_values','lower_bounds','higher_bounds',
                                  'units','scale'])
params_df.loc[0] = ['k1',8.64e-01,8.64e-03,8.64e+01,'m/j','lin']
params_file = 'calib_dicot_hom_1v_k1'
params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
calib = calib_root.Calibration(params_file, BV, observations = ['streams'])

# Launch dichotomy
dicot = calib.dichotomy(gap=1)

# Extract
typ_calib = 'streams_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                   key=os.path.getmtime)
name_file = list_path[-1].split('\\')[-1]
calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
test = calib_analysis.CalibAnalysis(calib_file)
test.display_objective_function(save=None)

koptim = test.calib['params_values'][-1]
kr = koptim / test.calib['recharge']
obj_func = test.calib['objective_function'][-1]

df.loc[0,type_obs] = koptim / 24 / 3600
df.loc[1,type_obs] = kr
df.loc[2,type_obs] = obj_func
    
df.to_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
