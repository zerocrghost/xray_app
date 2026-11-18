@echo off
rem First run: creates .venv with Python 3.14 and installs the packages. Then starts the app.
rem A failed or broken setup (e.g. Python reinstalled) is detected and redone automatically.
cd /d "%~dp0"

rem Setup counts as done if the install finished and the venv's Python still starts
rem (a missing DLL is NOT fixed by reinstalling packages, so don't reinstall for that).
if exist .venv\setup_ok (
    .venv\Scripts\python -c "import sys" >nul 2>&1 && goto :update
    echo The existing .venv is broken. Recreating it...
)
if exist .venv rmdir /s /q .venv

rem Pick 64-bit Python 3.14 (falls back to 3.13 / 3.12). 3.15+ has no onnxruntime packages yet, and
rem onnxruntime has NO 32-bit Windows packages at all (pip then says "from versions: none").
set "PY="
set "FOUND32="
set "IS64=import struct, sys; sys.exit(0 if struct.calcsize('P') == 8 else 1)"
for %%V in (3.14 3.13 3.12) do (
    if not defined PY py -%%V-64 -c "%IS64%" >nul 2>&1 && set "PY=py -%%V-64"
    if not defined PY py -%%V -c "import sys" >nul 2>&1 && set "FOUND32=%%V"
)
if not defined PY (
    rem No py launcher: accept "python" on PATH if it is a 64-bit 3.12 - 3.14
    python -c "import struct, sys; sys.exit(0 if (3,12) <= sys.version_info[:2] <= (3,14) and struct.calcsize('P') == 8 else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    python -c "import struct, sys; sys.exit(0 if struct.calcsize('P') == 4 else 1)" >nul 2>&1 && set "FOUND32=on PATH"
)
if not defined PY (
    if defined FOUND32 (
        echo Only a 32-bit Python was found ^(%FOUND32%^). onnxruntime needs 64-bit Python.
        echo Install the "Windows installer ^(64-bit^)" of Python 3.12 - 3.14 from https://www.python.org/downloads/
    ) else (
        echo 64-bit Python 3.12 - 3.14 was not found.
        echo Install it from https://www.python.org/downloads/  ^(or run: py install 3.14^)
    )
    goto :error
)
for /f "delims=" %%I in ('%PY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%I"
echo Creating virtual environment with Python %PYVER% ...
%PY% -m venv .venv || goto :error
rem longer timeout and more retries: slow or filtered connections to pypi.org otherwise end in
rem "Could not find a version ... (from versions: none)"
set "PIPNET=--timeout 120 --retries 10"
.venv\Scripts\python -m pip install %PIPNET% --upgrade pip || goto :error
.venv\Scripts\python -m pip install %PIPNET% -r requirements.txt || goto :net
copy /y requirements.txt .venv\requirements.installed >nul
echo ok> .venv\setup_ok
goto :run

:update
rem requirements.txt changed since the last install (e.g. a new package such as python-docx): install the difference
fc /b requirements.txt .venv\requirements.installed >nul 2>&1 && goto :run
echo Updating packages for the new version...
.venv\Scripts\python -m pip install --timeout 120 --retries 10 -r requirements.txt || goto :updfail
copy /y requirements.txt .venv\requirements.installed >nul
goto :run

:updfail
rem never delete a working .venv because an update failed (e.g. no internet): start with what is installed
echo.
echo WARNING: the package update failed. Starting with the installed packages; it is retried next time.
echo.

:run
.venv\Scripts\python app.py %*
goto :eof

:net
echo.
echo Installing the packages failed. If the messages above show "Read timed out" or
echo "from versions: none", this PC cannot reach pypi.org reliably:
echo   - check the internet connection / proxy  (behind a proxy: set HTTPS_PROXY=http://proxy:port)
echo   - or install offline: put the wheel files in a "wheels" folder next to this file and run
echo       .venv\Scripts\python -m pip install --no-index --find-links wheels -r requirements.txt
goto :error

:error
echo.
echo Setup failed - see the messages above.
if exist .venv rmdir /s /q .venv
pause
exit /b 1
