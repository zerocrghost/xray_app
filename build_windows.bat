@echo off
rem Builds dist\PneumoLensAI\PneumoLensAI.exe (run run_windows.bat once first).
cd /d "%~dp0"
.venv\Scripts\python tests\test_engine.py || goto :error
.venv\Scripts\pyinstaller --noconfirm --clean --windowed --name PneumoLensAI --icon ui\logo.ico ^
    --add-data "ui;ui" --add-data "models;models" ^
    app.py || goto :error
echo.
echo Done: dist\PneumoLensAI\PneumoLensAI.exe  (ship the whole dist\PneumoLensAI folder)
goto :eof
:error
echo Build failed.
exit /b 1
