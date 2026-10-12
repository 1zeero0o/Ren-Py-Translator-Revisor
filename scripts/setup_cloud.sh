#!/usr/bin/env bash
set -euo pipefail
cd /workspace/Ren-Py-Translator-Revisor
if [ ! -x .venv/bin/python ]; then
    python -m venv .venv
fi
.venv/bin/python -m pip install --no-input --cache-dir /workspace/.cache/renpy-revisor-pip -e '.[dev]'
QT_QPA_PLATFORM=offscreen REVISOR_DATA_DIR=/tmp/renpy-revisor-validation .venv/bin/python -m pytest -q
