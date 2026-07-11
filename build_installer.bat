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
set "ISCC="
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" goto :noiscc

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
echo ERROR: Inno Setup 6 isn't installed.
echo Get it from https://jrsoftware.org/isinfo.php and re-run,
echo or install it with: winget install JRSoftware.InnoSetup
goto :fail

:fail
echo.
echo Build FAILED - see the output above.
pause
exit /b 1
