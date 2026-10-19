@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHON_EXE=%~dp0data\v5-web-venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  echo RepoLens Python environment was not found:
  echo %PYTHON_EXE%
  echo Please read docs\v5-workbench.md and prepare the environment first.
  pause
  exit /b 1
)

echo Starting RepoLens V6. The browser will open automatically.
"%PYTHON_EXE%" -m repolens.workbench.launcher --data-dir "%~dp0data\v5-workbench"
if errorlevel 1 (
  echo.
  echo RepoLens failed to start. The error above is the diagnostic.
  pause
)
