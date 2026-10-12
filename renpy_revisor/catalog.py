"""Read engine-generated translation templates, never invent dialogue IDs."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .domain import Entry, RevisorError, safe_relative, stable_id

LITERAL = re.compile(r'''r?(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)''')
HEADER = re.compile(r"^translate\s+([A-Za-z_]\w*)\s+([\w.]+)\s*:\s*(?:#.*)?$")
NON_SAY = {"voice", "play", "stop", "show", "hide", "scene", "window", "pause", "call", "jump", "pass", "return", "image", "camera", "old", "new", "translate", "python", "nvl"}


def unquote(literal: str) -> str:
    raw = literal.startswith("r")
    if raw:
        return literal[2:-1]
    text = re.sub(r"[ \n]+", " ", literal[1:-1])

    def dequote(m):
        c = m.group(1)
        if c in ("{", "[", "%"):
            return c * 2
        if c == "n":
            return "\n"
        if c.startswith("u"):
            return chr(int(c[1:], 16))
        return c

    return re.sub(r"\\(u[0-9a-fA-F]{1,4}|.)", dequote, text)


def quote(text: str) -> str:
    # Escape repeated spaces using Ren'Py's lexer rules, not Python/JSON rules.
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    text = re.sub(r"(?<= ) ", r"\\ ", text)
    for c in ("\t", "\r", "\x00"):
        text = text.replace(c, "\\u%04x" % ord(c))
    return '"' + text + '"'


def say_literal(line: str):
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "$")) or stripped.split()[0] in NON_SAY:
        return None
    # Ignore literals within a character expression's function arguments.
    top = []
    pos = 0
    depth = 0
    for match in LITERAL.finditer(line):
        for c in line[pos:match.start()]:
            if c in "([":
                depth += 1
            elif c in ")]":
                depth -= 1
        if depth == 0:
            top.append(match)
        pos = match.end()
    if not top:
        return None
    # A literal speaker name may precede the spoken text.
    first = top[0]
    if not line[:first.start()].strip() and len(top) > 1:
        return top[1]
    return first


def parse_template(name: str, text: str, language: str) -> list[Entry]:
    safe_relative(name)
    entries = []
    block = ""
    offset = 0
    source_line = 0
    source_file = name
    originals: list[str] = []
    old = None
    sequence = 0
    for line in text.splitlines(keepends=True):
        clean = line.strip()
        if m := HEADER.match(line.rstrip()):
            if m[1] != language:
                block = ""
            else:
                block = m[2]
            originals = []
            old = None
            sequence = 0
        elif line.startswith("# ") and (m := re.match(r"# (.+):(\d+)\s*$", line)):
            source_file, source_line = m[1], int(m[2])
        elif block == "strings":
            if clean.startswith("# ") and (m := re.match(r"# (.+):(\d+)\s*$", clean)):
                source_file, source_line = m[1], int(m[2])
            elif clean.startswith("old ") and (m := LITERAL.search(line)):
                old = unquote(m[0])
            elif clean.startswith("new ") and (m := LITERAL.search(line)) and old is not None:
                target = unquote(m[0])
                entries.append(Entry(stable_id("string", old), old, source_file, source_line, "string",
                                     target if target != old else "", "translated" if target and target != old else "pending",
                                     name, offset + m.start(), offset + m.end(), block))
                old = None
        elif block:
            if clean.startswith("# "):
                if m := say_literal(clean[2:]):
                    originals.append(unquote(m[0]))
            elif clean and (m := say_literal(line)):
                if sequence >= len(originals):
                    raise RevisorError(f"Bloco de tradução não reconhecido: {name} / {block}")
                source = originals[sequence]
                target = unquote(m[0])
                entries.append(Entry(stable_id(name, block, sequence), source, source_file, source_line, "dialogue",
                                     target if target != source else "", "translated" if target and target != source else "pending",
                                     name, offset + m.start(), offset + m.end(), block))
                sequence += 1
        offset += len(line)
    return entries


def read_templates(folder: Path, language: str):
    templates = {}
    entries = []
    seen = set()
    for path in sorted(folder.rglob("*.rpy")):
        name = path.relative_to(folder).as_posix()
        text = path.read_text("utf-8-sig")
        templates[name] = text
        for e in parse_template(name, text, language):
            if e.id in seen:
                raise RevisorError(f"String duplicada nos templates: {e.source[:80]}")
            entries.append(e)
            seen.add(e.id)
    if not entries:
        raise RevisorError("O Ren'Py não gerou strings traduzíveis. Consulte o log; verifique a versão do motor e os scripts extraídos.")
    return templates, entries


def read_yaml(paths: dict[str, Path]):
    documents = {}
    entries = []
    warnings = []

    def visit(value, path, filename, active):
        if isinstance(value, str) and value.strip():
            entries.append(Entry(stable_id("yaml", filename, path), value, filename, 0, "yaml", yaml_path=path))
        elif isinstance(value, (dict, list)):
            if id(value) in active:
                raise RevisorError(f"YAML com referência recursiva não suportado: {filename}")
            active = active | {id(value)}
            items = value.items() if isinstance(value, dict) else enumerate(value)
            for key, item in items:
                if isinstance(value, dict) and not isinstance(key, str):
                    raise RevisorError(f"YAML com chave não textual não suportado: {filename}")
                visit(item, path + [key], filename, active)

    for name, path in sorted(paths.items()):
        safe_relative(name)
        try:
            # The JSON project format deliberately accepts only JSON-compatible YAML.
            value = yaml.safe_load(path.read_text("utf-8-sig"))
            import json
            json.dumps(value, allow_nan=False)
            visit(value, [], name, set())
            documents[name] = value
        except (yaml.YAMLError, ValueError, TypeError, UnicodeError, RevisorError) as exc:
            entries = [e for e in entries if e.file != name]
            warnings.append(f"YAML ignorado ({name}): {exc}")
    return documents, entries, warnings
