@echo off
REM One-command launcher for the Siglent SDM web app (Windows).
REM Creates .venv on first run, installs requirements, then launches.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [run] creating .venv ...
    py -3 -m venv .venv
    if errorlevel 1 (
        python -m venv .venv
    )
)

call ".venv\Scripts\activate.bat"

if not exist ".venv\deps-stamp.txt" (
    goto INSTALL
)
for /f %%a in ('powershell -NoProfile -Command "(Get-Item requirements.txt).LastWriteTime -gt (Get-Item .venv/deps-stamp.txt).LastWriteTime"') do (
    if "%%a"=="True" goto INSTALL
)
goto LAUNCH

:INSTALL
echo [run] installing dependencies ...
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo. > .venv\deps-stamp.txt

:LAUNCH
python launch.py %*
