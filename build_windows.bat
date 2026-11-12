@echo off
rem Builds dist\XRayAnalyzer\XRayAnalyzer.exe (run run_windows.bat once first).
cd /d "%~dp0"
.venv\Scripts\python tests\test_engine.py || goto :error
.venv\Scripts\pyinstaller --noconfirm --clean --windowed --name XRayAnalyzer ^
    --add-data "ui;ui" --add-data "models;models" ^
    app.py || goto :error
echo.
echo Done: dist\XRayAnalyzer\XRayAnalyzer.exe  (ship the whole dist\XRayAnalyzer folder)
goto :eof
:error
echo Build failed.
exit /b 1
