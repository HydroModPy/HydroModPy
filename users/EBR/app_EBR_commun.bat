@echo off
setlocal enabledelayedexpansion

rem Define the folder with scenarios
set scenario_files="D:\Dam_EBR_results\raw\data_Cheze\Reservoir\Scenarios de gestion\*.csv"

rem Get the number of scenarios
set n_scenario=0
for %%i in (%scenario_files%) do (
	set /a n_scenario=n_scenario+1
)

rem Set up the environment and folder
set root=C:\ProgramData\Miniconda3
call %root%\Scripts\activate.bat
call activate hydromodpy
call D:

rem Historic simulation (warm-up)
echo SIMULATION DE L'ETAT INITIAL DU MODELE
echo:
call python .\app_EBR_commun.py -l -t
echo:
echo SIMULATIONS DES 6 PROCHAINS MOIS : %n_scenario% SCENARIOS [nouvelles fenetres]
echo:
timeout /t 2

rem Predictive simulations
set scenar=0
for %%i in (%scenario_files%) do (
	set /a scenar=scenar+1
	start cmd /k ^
	echo SCENARIO !scenar!/%n_scenario% ^& ^
	echo %%i ^& ^
	echo: ^& ^
	call python .\app_EBR_commun_predic.py -l -t
)

cmd /k


rem "echo:" is used for newlines. Alternatives: "echo(" or "echo\"