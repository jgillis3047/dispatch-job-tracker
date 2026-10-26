@echo off
title Dispatch setup
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY goto nopython

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Dispatch. This takes about a minute...
  %PY% -m venv .venv || goto nopython
)
if not exist ".venv\.installed-v2" (
  echo Installing Dispatch's libraries...
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto pipfail
  echo ok> ".venv\.installed-v2"
)
rem Launch without a console window. A "Dispatch" icon is added to your desktop and Start menu.
start "" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
echo Dispatch is opening. Next time, just use the Dispatch icon on your desktop.
timeout /t 4 >nul
goto :eof

:nopython
echo.
echo Python 3 isn't installed on this computer.
echo Install it free from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo then double-click this file again.
echo.
pause
goto :eof

:pipfail
echo.
echo Couldn't download Dispatch's libraries. Check your internet connection and try again.
pause
