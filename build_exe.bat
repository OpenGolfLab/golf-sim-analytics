@echo off
echo ==========================================
echo  Building Golf Sim Analytics
echo ==========================================

:: Step 1: Dependencies (PyInstaller is build-only, so it isn't in requirements.txt)
pip install -r requirements.txt
pip install pyinstaller

:: Step 2: Compile the executable
echo Building executable (this can take a few minutes)...
pyinstaller --noconsole --onefile --icon "assets\icon.ico" --add-data "assets;assets" --name "GolfSimAnalytics" app.py
if errorlevel 1 goto :fail

:: Step 3: Ship everything the app looks for NEXT TO the exe, so the packaged
:: app looks exactly like running `python app.py` from the repo — the course
:: photo (landing page + sidebar banner) and both demo datasets for the
:: "Use sample data" setting. The app anchors its data folders to the exe's
:: directory, so the whole dist\ folder is the portable install.
copy /y "course_bg.JPG" "dist\" >nul
xcopy /e /i /y "sample_data" "dist\sample_data" >nul
xcopy /e /i /y "sample_data_progression" "dist\sample_data_progression" >nul

:: Step 4: Cleanup temporary build files
rmdir /s /q build
del /q GolfSimAnalytics.spec

echo ==========================================
echo  Build complete! Ship the whole 'dist' folder.
echo ==========================================
pause
goto :eof

:fail
echo Build FAILED - see the output above.
pause
