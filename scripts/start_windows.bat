@echo off
setlocal
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv
    if errorlevel 1 goto fail
)
.venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m renpy_revisor
if errorlevel 1 goto fail
exit /b 0
:fail
echo Nao foi possivel iniciar. Verifique a mensagem acima e instale Python 3.11 ou superior.
pause
exit /b 1
