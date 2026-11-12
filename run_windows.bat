@echo off
rem First run: creates .venv with Python 3.12 and installs the packages. Then starts the app.
rem A failed or broken setup (e.g. Python reinstalled) is detected and redone automatically.
cd /d "%~dp0"

rem Setup counts as done only if the venv's Python runs AND the install finished.
if exist .venv\setup_ok (
    .venv\Scripts\python -c "import webview, onnxruntime" >nul 2>&1 && goto :run
    echo The existing .venv is broken. Recreating it...
)
if exist .venv rmdir /s /q .venv

rem Pick Python 3.12 (or 3.13). Newer versions may not have onnxruntime packages yet.
set "PY="
py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if not defined PY py -3.13 -c "import sys" >nul 2>&1 && set "PY=py -3.13"
if not defined PY (
    echo Python 3.12 was not found.
    echo Install it from https://www.python.org/downloads/  ^(or run: py install 3.12^)
    goto :error
)
echo Creating virtual environment with %PY% ...
%PY% -m venv .venv || goto :error
.venv\Scripts\python -m pip install --upgrade pip || goto :error
.venv\Scripts\python -m pip install -r requirements.txt || goto :error
echo ok> .venv\setup_ok

:run
.venv\Scripts\python app.py %*
goto :eof

:error
echo.
echo Setup failed - see the messages above.
if exist .venv rmdir /s /q .venv
pause
exit /b 1
