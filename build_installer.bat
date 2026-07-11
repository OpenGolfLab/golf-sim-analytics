@echo off
echo ==========================================
echo  Building Golf Sim Analytics Installer
echo ==========================================

python --version >nul 2>&1
if errorlevel 1 goto :nopython

echo Step 1 of 2: Building the app...
call "%~dp0build_exe.bat" < NUL
if errorlevel 1 goto :fail

echo.
echo Step 2 of 2: Compiling the installer...
rem Search each common install root for any "Inno Setup *" folder rather
rem than a hardcoded version number, so a newer (or older) release than
rem whatever this script was last touched for still gets found. Later
rem matches overwrite ISCC, so the highest version number wins when more
rem than one is installed.
set "ISCC="
for %%R in ("%LocalAppData%\Programs" "%ProgramFiles(x86)%" "%ProgramFiles%") do (
    for /d %%D in ("%%~R\Inno Setup*") do (
        if exist "%%D\ISCC.exe" set "ISCC=%%D\ISCC.exe"
    )
)
if "%ISCC%"=="" goto :noiscc
echo Using: %ISCC%

"%ISCC%" "%~dp0installer\GolfSimAnalytics.iss"
if errorlevel 1 goto :fail

echo ==========================================
echo  Installer built! See installer\Output\GolfSimAnalytics-Setup.exe
echo ==========================================
pause
goto :eof

:nopython
echo ERROR: Python isn't on PATH.
echo Install Python 3.11+ from python.org and check
echo "Add python.exe to PATH" in its installer, then re-run.
goto :fail

:noiscc
echo ERROR: Inno Setup isn't installed.
echo Get it from https://jrsoftware.org/isinfo.php and re-run,
echo or install it with: winget install JRSoftware.InnoSetup
goto :fail

:fail
echo.
echo Build FAILED - see the output above.
pause
exit /b 1
