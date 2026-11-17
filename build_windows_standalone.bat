@echo off
rem Standalone build: dist\standalone\PneumoLensAI\ with its own WebView2 + Visual C++ runtime,
rem so nothing has to be installed on the target PC (see tools\build_standalone.py).
rem Run run_windows.bat once first. Options:
rem   build_windows_standalone.bat --webview2 C:\path\Microsoft.WebView2.FixedVersionRuntime.xxx.x64.cab
rem   build_windows_standalone.bat --trim-locales --zip
cd /d "%~dp0"
.venv\Scripts\python tools\build_standalone.py %* || goto :error
goto :eof
:error
echo Build failed.
exit /b 1
