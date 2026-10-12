$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
py -3 scripts/setup_windows.py --build
if ($LASTEXITCODE -ne 0) { throw "Falha na instalação" }
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name RenPyTranslator --collect-data renpy_revisor --onedir main.py
if ($LASTEXITCODE -ne 0) { throw "Falha na compilação" }
Write-Host "Programa gerado em dist\RenPyTranslator\RenPyTranslator.exe. Distribua a pasta completa."
