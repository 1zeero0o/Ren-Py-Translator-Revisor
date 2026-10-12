from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from threading import Event

from .catalog import read_templates
from .domain import Cancelled, Project, RevisorError, user_data_dir, validate_language


def find_launcher(root: Path) -> Path | None:
    suffix = ".exe" if os.name == "nt" else ".sh"
    choices = sorted(p for p in root.glob(f"*{suffix}") if not p.name.endswith("-32" + suffix) and p.name.lower() not in ("srt.exe", "uninstall.exe"))
    return choices[0] if len(choices) == 1 else None


def bundled_zip() -> Path:
    return Path(__file__).resolve().parent / "resources" / "srtp_v1.1.zip"


def prepare_srt(workspace: Path, supplied: Path | None = None) -> Path:
    folder = workspace / "srt"
    folder.mkdir(exist_ok=True)
    if supplied:
        if supplied.suffix.lower() != ".exe" or not supplied.is_file():
            raise RevisorError("Selecione o srt.exe da ferramenta SRT.")
        dll = supplied.parent / "libzstd.dll"
        if not dll.is_file():
            raise RevisorError("libzstd.dll precisa estar ao lado do srt.exe.")
        shutil.copy2(supplied, folder / "srt.exe")
        shutil.copy2(dll, folder / "libzstd.dll")
    else:
        archive = bundled_zip()
        if not archive.is_file():
            raise RevisorError("SRT não encontrado. Selecione srt.exe nas opções de abertura.")
        if hashlib.sha256(archive.read_bytes()).hexdigest() != "165c11fb6e1819eb35694eaebe5045b525ace6fbbbf4460a279ceb1c3631e165":
            raise RevisorError("O pacote SRT incluído foi alterado. Restaure o ZIP original ou selecione srt.exe manualmente.")
        with zipfile.ZipFile(archive) as z:
            # Explicit members only; never execute the attached install.bat.
            for name in ("srt.exe", "libzstd.dll", "readme.txt"):
                (folder / name).write_bytes(z.read(name))
    return folder / "srt.exe"


def native_command(executable: Path, args: list[str]) -> list[str]:
    if os.name != "nt" and executable.suffix.lower() == ".exe":
        wine = shutil.which("wine")
        if not wine:
            raise RevisorError("O SRT enviado é para Windows. Use este programa no Windows ou instale Wine para extrair/decompilar no Linux.")
        args = ["Z:" + a.replace("/", "\\") if a.startswith("/") else a for a in args]
        return [wine, str(executable), *args]
    if executable.suffix == ".sh" and not os.access(executable, os.X_OK):
        return ["/bin/sh", str(executable), *args]
    return [str(executable), *args]


def run_command(command, cwd: Path, log: Path, cancel: Event, timeout=600):
    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy", "RENPY_DISABLE_SOUND": "1", "WINEDEBUG": "-all"})
    kwargs = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NO_WINDOW}
    start = time.monotonic()

    def stop(process):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()

    with log.open("wb") as output:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, **kwargs)
        except OSError as exc:
            raise RevisorError(f"Não foi possível executar a ferramenta: {exc}") from exc
        while process.poll() is None:
            if cancel.wait(0.15):
                stop(process)
                raise Cancelled("Preparação cancelada; os arquivos originais foram preservados.")
            if time.monotonic() - start > timeout:
                stop(process)
                raise RevisorError(f"A ferramenta excedeu {timeout}s. Consulte {log}.")
    text = log.read_text("utf-8", errors="replace")
    if process.returncode != 0:
        raise RevisorError(f"A ferramenta terminou com código {process.returncode}. Log: {log}\n{text[-2500:]}")
    return text


def srt_operation(srt: Path, source: Path, destination: Path, operation: str, cancel: Event, log: Path):
    destination.mkdir(parents=True, exist_ok=True)
    prior = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in srt.parent.glob("errorlog_*.txt")}
    args = [str(source), operation, str(destination)]
    if operation == "-d":
        args.append("-b")  # Already extracted archives; never process their packed scripts twice.
    text = run_command(native_command(srt, args), srt.parent, log, cancel)
    errors = [p for p in srt.parent.glob("errorlog_*.txt") if p not in prior or prior[p] != (p.stat().st_mtime_ns, p.read_bytes())]
    if errors:
        raise RevisorError(f"O SRT registrou falhas. Log: {errors[-1]}\n{errors[-1].read_text('utf-8', errors='replace')[-2500:]}")
    if not re.search(r"Done\.\s*\d+", text):
        raise RevisorError(f"O SRT não confirmou a operação. Consulte {log}.")
    if operation == "-e" and not any(p.is_file() for p in destination.rglob("*")):
        raise RevisorError(f"Nenhum arquivo extraído de {source.name}. O arquivo pode estar protegido ou não ser suportado pelo SRT.")
    # SRT is a separate binary. Reject links/escape paths before using its output.
    for p in destination.rglob("*"):
        if p.is_symlink() or not p.resolve().is_relative_to(destination.resolve()):
            raise RevisorError(f"Caminho extraído inválido: {p}")


def copy_game(source: Path, destination: Path, cancel: Event):
    destination.mkdir(parents=True)
    for path in source.rglob("*"):
        if cancel.is_set():
            raise Cancelled("Preparação cancelada.")
        relative = path.relative_to(source)
        if relative.parts[0] in ("saves", "cache"):
            continue
        if path.is_symlink():
            raise RevisorError(f"A pasta game contém um link simbólico: {relative}. Use uma cópia regular do jogo.")
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


# Source installation occurs during init, after the original compiled AST is loaded.
# This lets Ren'Py emit original dialogue IDs AND scan decompiled _() calls, without
# recompiling a decompiled script and silently changing the translation identifiers.
SOURCE_HELPER = '''init 999 python:
    import io as _rr_io
    import json as _rr_json
    import os as _rr_os
    import shutil as _rr_shutil
    with _rr_io.open(_rr_os.path.join(config.basedir, "revisor_sources.json"), "r", encoding="utf-8") as _rr_f:
        _rr_candidates = _rr_json.load(_rr_f)
    _rr_selected = {}
    for _rr_name, _rr_choices in _rr_candidates.items():
        for _rr_choice in _rr_choices:
            try:
                with renpy.loader.load(_rr_choice["logical"], tl=False) as _rr_f:
                    _rr_loaded = _rr_f.read()
                with _rr_io.open(_rr_choice["original"], "rb") as _rr_f:
                    _rr_expected = _rr_f.read()
                if _rr_loaded != _rr_expected:
                    continue
                _rr_selected[_rr_name] = _rr_choice["source"]
                if _rr_name.endswith((".rpy", ".rpym")):
                    _rr_dest = _rr_os.path.join(config.gamedir, _rr_name)
                    if not _rr_os.path.exists(_rr_dest):
                        _rr_parent = _rr_os.path.dirname(_rr_dest)
                        if not _rr_os.path.isdir(_rr_parent):
                            _rr_os.makedirs(_rr_parent)
                        _rr_shutil.copyfile(_rr_choice["source"], _rr_dest)
                        config.translate_files.append(_rr_dest)
                break
            except Exception:
                continue
    with _rr_io.open(_rr_os.path.join(config.basedir, "revisor_selected.json"), "w", encoding="utf-8") as _rr_f:
        _rr_f.write(_rr_json.dumps(_rr_selected, ensure_ascii=True))
'''


def prepare_project(root: Path, language: str, google_source: str, google_target: str,
                    launcher: Path | None, srt_path: Path | None, on_progress, cancel: Event) -> tuple[Project, dict[str, Path]]:
    root = root.resolve()
    validate_language(language)
    if not (root / "game").is_dir():
        raise RevisorError("Selecione a pasta base do jogo, que contém a subpasta game e o executável.")
    launcher = (launcher or find_launcher(root))
    if not launcher or not launcher.is_file():
        raise RevisorError("Selecione o executável do jogo ou o launcher de um SDK Ren'Py compatível nas opções de abertura.")
    workspace = user_data_dir() / "projects" / uuid.uuid4().hex
    workspace.mkdir(parents=True)
    stage = workspace / "staging"
    stage.mkdir()
    on_progress(0, 5, "Copiando game para a área de trabalho…")
    copy_game(root / "game", stage / "game", cancel)
    groups = [(stage / "game", Path("."), workspace / "decompiled" / "loose")]
    archives = sorted((stage / "game").rglob("*.rpa"))
    needs_srt = bool(archives or list((stage / "game").rglob("*.rpyc")) or list((stage / "game").rglob("*.rpymc")))
    srt = prepare_srt(workspace, srt_path) if needs_srt else None
    on_progress(1, 5, f"Extraindo {len(archives)} arquivo(s) RPA…")
    for index, archive in enumerate(archives):
        if cancel.is_set():
            raise Cancelled("Extração cancelada.")
        destination = workspace / "extracted" / f"{index:04d}_{archive.stem}"
        srt_operation(srt, archive, destination, "-e", cancel, workspace / "logs" / f"extract-{index}.log")
        # RPA member names are relative to game/, even when the physical archive
        # sits in a subdirectory selected through config.archives.
        groups.append((destination, Path("."), workspace / "decompiled" / f"archive-{index:04d}"))
        on_progress(1, 5, f"RPA {index + 1}/{len(archives)}: {archive.name}")
    on_progress(2, 5, "Decompilando scripts com o SRT…")
    candidates = {}
    for index, (source, prefix, decompiled) in enumerate(groups):
        scripts = [p for p in source.rglob("*") if p.suffix.lower() in (".rpyc", ".rpymc") and "tl" not in p.relative_to(source).parts]
        missing = [p for p in scripts if not p.with_suffix(p.suffix[:-1]).is_file()]
        if missing:
            srt_operation(srt, source, decompiled, "-d", cancel, workspace / "logs" / f"decompile-{index}.log")
            for compiled in missing:
                output = decompiled / compiled.relative_to(source).with_suffix(compiled.suffix[:-1])
                if not output.is_file() or not output.stat().st_size:
                    raise RevisorError(f"SRT não decompilou {compiled.name}. Consulte os logs em {workspace / 'logs'}.")
        for compiled in scripts:
            plain = compiled.with_suffix(compiled.suffix[:-1])
            if not plain.is_file():
                plain = decompiled / compiled.relative_to(source).with_suffix(compiled.suffix[:-1])
            logical = (prefix / compiled.relative_to(source)).as_posix()
            name = str(Path(logical).with_suffix(compiled.suffix[:-1])).replace("\\", "/")
            candidates.setdefault(name, []).append({"source": str(plain), "original": str(compiled), "logical": logical})
        for plain in source.rglob("*"):
            if plain.suffix.lower() not in (".rpy", ".rpym", ".yml", ".yaml") or "tl" in plain.relative_to(source).parts:
                continue
            logical = (prefix / plain.relative_to(source)).as_posix()
            candidates.setdefault(logical, []).append({"source": str(plain), "original": str(plain), "logical": logical})
    on_progress(3, 5, "Gerando os templates nativos do Ren'Py…")
    template_language = "revisor_" + uuid.uuid4().hex[:12]
    helper = stage / "game" / ("zz_" + template_language + ".rpy")
    helper.write_text(SOURCE_HELPER, "utf-8")
    (stage / "revisor_sources.json").write_text(json.dumps(candidates, ensure_ascii=True), "utf-8")
    args = [str(stage), "translate", template_language, "--savedir", str(workspace / "saves")]
    # Compiled nodes contain elided filenames such as game/script.rpy. With the
    # source absent until init, Ren'Py resolves them against the working directory.
    # Run from staging so the native translator and installed source share a key.
    run_command(native_command(launcher.resolve(), args), stage, workspace / "logs" / "renpy-translate.log", cancel)
    selected_path = stage / "revisor_selected.json"
    if not selected_path.is_file():
        raise RevisorError(f"O motor não executou a geração nativa. Verifique o launcher e o log em {workspace / 'logs'}.")
    selected = json.loads(selected_path.read_text("utf-8"))
    # A missing source is not silently treated as a successful partial import.
    missing = [name for name in candidates if name.endswith((".rpy", ".rpym")) and name not in selected]
    if missing:
        raise RevisorError("O motor não reconheceu estes scripts extraídos: " + ", ".join(missing[:8]) + ". Consulte o log; o jogo pode usar um carregador personalizado.")
    templates, entries = read_templates(stage / "game" / "tl" / template_language, template_language)
    for e in entries:
        e.file = e.file.replace(str(stage / "game") + os.sep, "").replace("\\", "/")
    on_progress(4, 5, "Organizando as strings e arquivos YAML…")
    yaml_paths = {name: Path(value) for name, value in selected.items() if Path(name).suffix.lower() in (".yml", ".yaml")}
    # Remove helpers from the retained staging area; they are never exported.
    helper.unlink(missing_ok=True)
    helper.with_suffix(".rpyc").unlink(missing_ok=True)
    project = Project(str(root), language, google_source, google_target, entries, templates,
                      template_language=template_language, workspace=str(workspace))
    project.save(workspace / "project.rpt.json")
    on_progress(5, 5, "Jogo preparado para revisão.")
    return project, yaml_paths
