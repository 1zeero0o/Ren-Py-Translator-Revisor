from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath


class RevisorError(Exception):
    """An actionable error safe to show in the interface."""


class Cancelled(RevisorError):
    pass


def safe_relative(name: str) -> Path:
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or not p.parts or any(x in ("..", ".") or ":" in x for x in p.parts):
        raise RevisorError(f"Caminho inválido: {name}")
    return Path(*p.parts)


def confined(root: Path, name: str) -> Path:
    path = root / safe_relative(name)
    if not path.resolve().is_relative_to(root.resolve()):
        raise RevisorError(f"O caminho sai da pasta de destino: {name}")
    return path


def validate_language(language: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", language) or language in ("None", "strings", "python"):
        raise RevisorError("O idioma Ren'Py deve ser um identificador, como pt_BR, spanish ou french.")
    return language


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".revisor-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def stable_id(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:24]


# Ren'Py text tags/interpolation, Python-style formatting and literal escapes.
TOKEN = re.compile(
    r"\{\{|\{[^{}\n]+\}|\[\[|\[(?:[^\[\]\n]|\[[^\]\n]*\])+\]|"
    r"%%|%(?:\([^)]+\))?[-+#0 ]*\d*(?:\.\d+)?[srdifouxXeEgGc]|\n"
)


def protected_tokens(text: str) -> list[str]:
    return TOKEN.findall(text)


def validate_translation(source: str, target: str) -> None:
    if target and Counter(protected_tokens(source)) != Counter(protected_tokens(target)):
        raise RevisorError("Preserve as variáveis, tags, quebras de linha e marcadores do original.")
    if target:
        source_tags = [t for t in protected_tokens(source) if t.startswith("{") and t != "{{"]
        target_tags = [t for t in protected_tokens(target) if t.startswith("{") and t != "{{"]
        if source_tags != target_tags:
            raise RevisorError("Preserve a ordem das tags para manter sua abertura e fechamento corretos.")
    if "\x00" in target or "\r" in target:
        raise RevisorError("O texto contém caracteres de controle inválidos.")


@dataclass
class Entry:
    id: str
    source: str
    file: str
    line: int
    kind: str  # dialogue, string, yaml
    target: str = ""
    status: str = "pending"
    template: str = ""
    start: int = 0
    end: int = 0
    block: str = ""
    yaml_path: list = field(default_factory=list)
    error: str = ""

    def update(self, target: str, reviewed: bool = False, machine: bool = False) -> None:
        validate_translation(self.source, target)
        self.target = target
        self.status = "reviewed" if reviewed and target else "machine" if machine else "translated" if target else "pending"
        self.error = ""


@dataclass
class Project:
    game_root: str
    language: str
    google_source: str = "auto"
    google_target: str = "pt"
    entries: list[Entry] = field(default_factory=list)
    templates: dict[str, str] = field(default_factory=dict)
    yaml_documents: dict = field(default_factory=dict)
    template_language: str = "revisor_template"
    workspace: str = ""
    activate_language: bool = True
    warnings: list[str] = field(default_factory=list)

    def save(self, path: Path) -> None:
        atomic_write(path, json.dumps({"format": "renpy-revisor", "version": 1, **asdict(self)}, ensure_ascii=False, indent=2).encode("utf-8"))

    @classmethod
    def load(cls, path: Path) -> Project:
        try:
            data = json.loads(path.read_text("utf-8"))
            if data.pop("format") != "renpy-revisor" or data.pop("version") != 1:
                raise ValueError("Formato de projeto não suportado")
            entries = [Entry(**e) for e in data.pop("entries")]
            p = cls(entries=entries, **data)
            validate_language(p.language)
            validate_language(p.template_language)
            if len({e.id for e in entries}) != len(entries):
                raise ValueError("IDs de strings duplicados")
            for name in list(p.templates) + list(p.yaml_documents):
                safe_relative(name)
            for e in entries:
                validate_translation(e.source, e.target)
                if e.status not in ("pending", "translated", "machine", "reviewed"):
                    raise ValueError("Estado de revisão inválido")
                if e.kind in ("dialogue", "string"):
                    text = p.templates[e.template]
                    if not 0 <= e.start < e.end <= len(text):
                        raise ValueError("Posição da string inválida")
                elif e.kind != "yaml" or e.file not in p.yaml_documents:
                    raise ValueError("Origem da string inválida")
            return p
        except (ValueError, TypeError, KeyError) as exc:
            raise RevisorError(f"Projeto inválido: {exc}") from exc


def user_data_dir() -> Path:
    if override := os.environ.get("REVISOR_DATA_DIR"):
        root = Path(override)
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RenPyRevisor"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "renpy-revisor"
    root.mkdir(parents=True, exist_ok=True)
    return root
