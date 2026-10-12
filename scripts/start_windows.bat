@echo off
setlocal
cd /d "%~dp0.."
py -3 scripts\setup_windows.py
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m renpy_revisor
if errorlevel 1 goto fail
exit /b 0
:fail
echo Nao foi possivel iniciar. Verifique a mensagem acima. Recomendado: Python 3.12 de 64 bits.
pause
exit /b 1
