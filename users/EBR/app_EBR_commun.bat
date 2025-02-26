@echo off
setlocal enabledelayedexpansion

rem Set up the environment and folder
set root=C:\ProgramData\Miniconda3
call %root%\Scripts\activate.bat
call activate hydromodpy
call D:

rem Fill the folder with selected scenarios
call python .\scenario_selection.py > selected_scenarios.txt

rem Define the folder with selected scenarios
rem set scenario_files="D:\Dam_EBR_results\raw\data_Cheze\Reservoir\Scenarios de gestion\Selection\*.csv"
set scenario_files=selected_scenarios.txt

rem Get the number of scenarios
set n_scenario=0
rem for %%i in (%scenario_files%) do (
for /f "tokens=*" %%i in (selected_scenarios.txt) do (
	set /a n_scenario=n_scenario+1
)

rem Historical simulation (warm-up)
echo SIMULATION DE L'ETAT INITIAL DU MODELE
echo:
call python .\app_EBR_commun.py -l -t
echo:
echo SIMULATIONS DES 6 PROCHAINS MOIS : %n_scenario% SCENARIOS [nouvelles fenetres]
echo:
timeout /t 5

rem Predictive simulations
setlocal
set PYTHONPATH=D:\2- Postdoc\2- Travaux\3_CWatM_EBR\source\Tools_AlexCoche
set PYTHONPATH=D:\2- Postdoc\2- Travaux
set scenar=0
rem for %%i in (%scenario_files%) do (
for /f "tokens=*" %%i in (selected_scenarios.txt) do (
	set /a scenar=scenar+1
	start cmd /k ^
	echo SCENARIO !scenar!/%n_scenario% ^& ^
	echo %%i ^& ^
	echo: ^& ^
	call python .\app_EBR_commun_predic.py "%%i" -l -t
	Set /a _rand=(%RANDOM%*(30+1)/32768)+45
	rem timeout /t 60
	timeout /t %_rand%
)
endlocal

cmd /k


rem "echo:" is used for newlines. Alternatives: "echo(" or "echo\"