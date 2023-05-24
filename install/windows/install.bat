@echo off
:: Removes prompt at the beginning of the line
SETLOCAL ENABLEDELAYEDEXPANSION

echo NOTE: when a default value is proposed : press Enter to confirm this value, otherwise enter your own value.
echo.

set argC=0
for %%x in (%*) do Set /A argC+=1

:: Current directory
set INSTALL_DIR=%CD%
::ligne a changer si le batch n'est pas sur HydroModPy\install\windows\install.bat :
cd ..\..\..


::::::::::::::::::::::: ENVIRONMENT VARIABLES :::::::::::::::::::::::::::
echo Definition of user-defined environnement variables...
IF exist "%HYDROMODPY_ROOT%" echo INFO: the fomer value of HYDROMODPY_ROOT will be erased.
set HYDROMODPY_ROOT=%CD%
setx HYDROMODPY_ROOT "%HYDROMODPY_ROOT%"
echo HYDROMODPY_ROOT = %HYDROMODPY_ROOT%
echo.


IF NOT "!HYDROMODPY_RESULTS!"=="" GOTO hydromodpy_results_ok
echo Enter the path to the Results of HydroModPy (will be created if non-existant): (Default: D:\results\HydroModPy)
set /P HYDROMODPY_RESULTS=
IF "!HYDROMODPY_RESULTS!"=="" set HYDROMODPY_RESULTS=D:\results\HydroModPy
IF NOT exist "!HYDROMODPY_RESULTS!" mkdir "!HYDROMODPY_RESULTS!"
setx HYDROMODPY_RESULTS "!HYDROMODPY_RESULTS!"
echo HYDROMODPY_RESULTS = !HYDROMODPY_RESULTS!
echo.
:hydromodpy_results_ok


IF NOT "!ANACONDA!"=="" GOTO anaconda_ok
echo Enter the path to the Anaconda Scripts: (Default: C:\ProgramData\Anaconda3\Scripts)
set /P ANACONDA=
IF "!ANACONDA!"=="" set ANACONDA=C:\ProgramData\Anaconda3\Scripts
IF NOT exist "!ANACONDA!" mkdir "!ANACONDA!"
setx ANACONDA "!ANACONDA!"
echo ANACONDA = !ANACONDA!
echo.
:anaconda_ok



echo 


echo.
echo Script completed. 
echo Please logout you Windows session and relog it.
echo Then, to finish, continue the installation procedure described in the "installation.htm" document.

pause