@echo off
rem First run: creates .venv with Python 3.14 and installs the packages. Then starts the app.
rem A failed or broken setup (e.g. Python reinstalled) is detected and redone automatically.
cd /d "%~dp0"

rem Setup counts as done if the install finished and the venv's Python still starts
rem (a missing DLL is NOT fixed by reinstalling packages, so don't reinstall for that).
if exist .venv\setup_ok (
    .venv\Scripts\python -c "import sys" >nul 2>&1 && goto :run
    echo The existing .venv is broken. Recreating it...
)
if exist .venv rmdir /s /q .venv

rem Pick Python 3.14 (falls back to 3.13 / 3.12). 3.15+ has no onnxruntime packages yet.
set "PY="
for %%V in (3.14 3.13 3.12) do (
    if not defined PY py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
)
if not defined PY (
    rem No py launcher: accept "python" on PATH if it is 3.12 - 3.14
    python -c "import sys; sys.exit(0 if (3,12) <= sys.version_info[:2] <= (3,14) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Python 3.14 was not found.
    echo Install it from https://www.python.org/downloads/  ^(or run: py install 3.14^)
    goto :error
)
for /f "delims=" %%I in ('%PY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%I"
echo Creating virtual environment with Python %PYVER% ...
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
