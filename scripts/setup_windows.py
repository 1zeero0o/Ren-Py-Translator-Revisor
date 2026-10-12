"""Select a supported Windows Python and install wheels without a C++ compiler.

This bootstrap uses only the standard library, so even Python 3.15 can run it.
The application itself runs inside the compatible virtual environment it finds.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PREFERRED_VERSIONS = ("3.12", "3.13", "3.14", "3.11")
PROBE = (
    "import json,sys,struct,sysconfig;"
    "print(json.dumps({'version':list(sys.version_info[:3]),"
    "'bits':struct.calcsize('P')*8,"
    "'free_threaded':bool(sysconfig.get_config_var('Py_GIL_DISABLED'))}))"
)


class SetupError(Exception):
    pass


@dataclass(frozen=True)
class Runtime:
    version: tuple[int, int, int]
    bits: int
    free_threaded: bool = False

    @property
    def supported(self):
        return (3, 11) <= self.version[:2] < (3, 15) and self.bits == 64 and not self.free_threaded

    def describe(self):
        return f"Python {'.'.join(map(str, self.version))}, {self.bits} bits" + (", free-threaded" if self.free_threaded else "")


def probe(command: list[str]) -> Runtime | None:
    try:
        result = subprocess.run([*command, "-c", PROBE], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, text=True, timeout=30)
        if result.returncode:
            return None
        data = json.loads(result.stdout)
        return Runtime(tuple(data["version"]), data["bits"], data["free_threaded"])
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return None


def choose_python() -> tuple[list[str], Runtime]:
    launcher = shutil.which("py")
    if launcher:
        for version in PREFERRED_VERSIONS:
            command = [launcher, f"-{version}"]
            runtime = probe(command)
            if runtime and runtime.supported and runtime.version[:2] == tuple(map(int, version.split("."))):
                return command, runtime
    current = probe([sys.executable])
    if current and current.supported:
        return [sys.executable], current
    raise SetupError("Nenhum Python compatível de 64 bits foi encontrado. Instale Python 3.12 (64 bits) "
                     "de https://www.python.org/downloads/windows/ e execute novamente. "
                     "Python 3.11 a 3.14 são aceitos; Python 3.15 ainda não é suportado.")


def ensure_environment(root: Path) -> Path:
    folder = root / ".venv"
    executable = folder / "Scripts" / "python.exe"
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise SetupError(".venv deve ser uma pasta de ambiente virtual regular. O caminho existente foi preservado.")
    runtime = probe([str(executable)]) if executable.is_file() else None
    if runtime and runtime.supported:
        print(f"Usando {runtime.describe()} da .venv existente.")
        return executable
    # Locate the replacement first: never move the user's environment if no
    # supported interpreter is available to create a new one.
    command, selected = choose_python()
    backup = None
    if folder.exists():
        reason = runtime.describe() if runtime else "ambiente incompleto ou inválido"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = root / f".venv-backup-{stamp}-{uuid.uuid4().hex[:6]}"
        folder.rename(backup)
        print(f"Ambiente anterior ({reason}) preservado em {backup.name}.")
    print(f"Criando .venv com {selected.describe()}…")
    try:
        subprocess.run([*command, "-m", "venv", str(folder)], cwd=root, stdin=subprocess.DEVNULL, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        suffix = f" O ambiente anterior está em {backup}." if backup else ""
        raise SetupError(f"Não foi possível criar .venv: {exc}.{suffix}") from exc
    created = probe([str(executable)])
    if not created or not created.supported:
        raise SetupError("A nova .venv não passou na verificação de versão/arquitetura. "
                         + (f"O ambiente anterior está preservado em {backup}." if backup else "Verifique a instalação do Python."))
    return executable


def install(root: Path, extra: str = "") -> Path:
    executable = ensure_environment(root)
    spec = f".[{extra}]" if extra else "."
    # Editable local source is allowed. External dependencies must be wheels:
    # don't silently fall back to compiling PyYAML when a runtime has no wheel.
    subprocess.run([str(executable), "-m", "pip", "install", "--no-input", "--only-binary=:all:", "-e", spec],
                   cwd=root, check=True)
    return executable


def main() -> int:
    parser = argparse.ArgumentParser(description="Preparar o ambiente Windows do Ren'Py Revisor")
    extras = parser.add_mutually_exclusive_group()
    extras.add_argument("--build", action="store_true", help="Instalar também PyInstaller")
    extras.add_argument("--dev", action="store_true", help="Instalar também as dependências de testes")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        install(root, "build" if args.build else "dev" if args.dev else "")
    except (SetupError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Falha na preparação: {exc}", file=sys.stderr)
        return 1
    print("Ambiente pronto. Inicie com .venv\\Scripts\\python.exe -m renpy_revisor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
