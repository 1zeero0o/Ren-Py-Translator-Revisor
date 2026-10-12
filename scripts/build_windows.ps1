$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o ambiente Python" }
}
& .venv\Scripts\python.exe -m pip install -e ".[build]"
if ($LASTEXITCODE -ne 0) { throw "Falha na instalação" }
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name RenPyTranslator --collect-data renpy_revisor --onedir main.py
if ($LASTEXITCODE -ne 0) { throw "Falha na compilação" }
Write-Host "Programa gerado em dist\RenPyTranslator\RenPyTranslator.exe. Distribua a pasta completa."
