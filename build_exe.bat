@echo off
echo ==========================================
echo  Building Golf Sim Analytics
echo ==========================================

REM Everything runs through "python -m ..." - bare pip/pyinstaller commands
REM live in Python's Scripts folder, which often isn't on PATH even when
REM python itself is.
python --version >nul 2>&1
if errorlevel 1 goto :nopython

REM Step 1: Dependencies (PyInstaller is build-only, not in requirements.txt)
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail
python -m pip install pyinstaller
if errorlevel 1 goto :fail

REM Step 2: Compile the executable
echo Building executable (this can take a few minutes)...
REM --collect-all tkinterdnd2 bundles its native tkdnd Tcl binaries so
REM drag-and-drop CSV import works in the packaged exe (the app falls back
REM to the file picker if they're ever missing, so this is belt-and-braces).
python -m PyInstaller --noconsole --onefile --icon "assets\icon.ico" --add-data "assets;assets" --collect-all tkinterdnd2 --name "GolfSimAnalytics" app.py
if errorlevel 1 goto :fail

REM Step 3: Ship everything the app looks for NEXT TO the exe, so the
REM packaged app looks exactly like running "python app.py" from the repo -
REM the course photo and both demo datasets for "Use sample data". The app
REM anchors its data folders to the exe's own directory, so the whole dist
REM folder is the portable install.
copy /y "course_bg.JPG" "dist\" >nul
xcopy /e /i /y "sample_data" "dist\sample_data" >nul
xcopy /e /i /y "sample_data_progression" "dist\sample_data_progression" >nul

REM Step 4: Cleanup temporary build files
rmdir /s /q build
del /q GolfSimAnalytics.spec

echo ==========================================
echo  Build complete! Ship the whole 'dist' folder.
echo ==========================================
pause
goto :eof

:nopython
echo ERROR: Python isn't on PATH.
echo Install Python 3.11+ from python.org and check
echo "Add python.exe to PATH" in its installer, then re-run.
goto :fail

:fail
echo.
echo Build FAILED - see the output above.
pause
exit /b 1
