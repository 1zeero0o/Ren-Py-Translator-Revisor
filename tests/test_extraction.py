import io
import json
import sys
import textwrap
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from renpy_revisor.domain import Cancelled, RevisorError
from renpy_revisor.extraction import SOURCE_HELPER, copy_game, prepare_project, prepare_srt, run_command, srt_operation


def test_bundled_srt_unpack_does_not_execute_install_bat(tmp_path):
    srt = prepare_srt(tmp_path)
    assert srt.read_bytes().startswith(b"MZ")
    assert (srt.parent / "libzstd.dll").is_file()
    assert not (srt.parent / "install.bat").exists()


def test_runner_captures_failures_and_cancellation(tmp_path):
    log = tmp_path / "run.log"
    with pytest.raises(RevisorError, match="código 3"):
        run_command([sys.executable, "-c", "print('failed');raise SystemExit(3)"], tmp_path, log, Event())
    assert "failed" in log.read_text()
    cancel = Event()
    cancel.set()
    with pytest.raises(Cancelled):
        run_command([sys.executable, "-c", "import time;time.sleep(30)"], tmp_path, log, cancel)


def test_srt_combined_extract_decompile_flags_are_never_used(tmp_path, monkeypatch):
    from renpy_revisor import extraction
    srt = tmp_path / "srt.exe"
    srt.write_bytes(b"MZ")
    calls = []
    monkeypatch.setattr(extraction, "native_command", lambda exe, args: args)
    def run(cmd, cwd, log, cancel):
        calls.append(cmd)
        output = Path(cmd[2])
        (output / "result.rpyc").write_text("compiled")
        return "Done. 1"
    monkeypatch.setattr(extraction, "run_command", run)
    srt_operation(srt, tmp_path / "archive.rpa", tmp_path / "out", "-e", Event(), tmp_path / "log")
    srt_operation(srt, tmp_path / "out", tmp_path / "plain", "-d", Event(), tmp_path / "log")
    assert calls[0][1] == "-e" and "-d" not in calls[0]
    assert calls[1][1] == "-d" and "-e" not in calls[1] and "-b" in calls[1]


def test_source_helper_uses_engine_archive_precedence_without_parsing_decompiled_scripts(tmp_path):
    stage = tmp_path / "staging"
    game = stage / "game"
    game.mkdir(parents=True)
    good = tmp_path / "good.rpy"
    good.write_text('label start:\n    "Hello"\n')
    bad = tmp_path / "bad.rpy"
    bad.write_text('label start:\n    "WRONG"\n')
    original = tmp_path / "good.rpyc"
    original.write_bytes(b"original compiled AST")
    wrong = tmp_path / "bad.rpyc"
    wrong.write_bytes(b"outdated archive")
    options = {"script.rpy": [{"source": str(bad), "original": str(wrong), "logical": "script.rpyc"},
                               {"source": str(good), "original": str(original), "logical": "script.rpyc"}]}
    (stage / "revisor_sources.json").write_text(json.dumps(options))
    config = SimpleNamespace(basedir=str(stage), gamedir=str(game), translate_files=[])
    loader = SimpleNamespace(load=lambda *a, **k: io.BytesIO(b"original compiled AST"))
    assert not (game / "script.rpy").exists()
    # Execute only our helper's Python block with an engine loader stub. No .rpy
    # is parsed here; template generation subsequently uses the already loaded AST.
    exec(textwrap.dedent(SOURCE_HELPER.split("\n", 1)[1]), {"config": config, "renpy": SimpleNamespace(loader=loader)})
    assert (game / "script.rpy").read_text() == good.read_text()
    assert config.translate_files == [str(game / "script.rpy")]
    assert json.loads((stage / "revisor_selected.json").read_text()) == {"script.rpy": str(good)}


def test_loose_source_game_pipeline_preserves_original_files(tmp_path, monkeypatch):
    from renpy_revisor import extraction
    root = tmp_path / "My Game"
    game = root / "game"
    game.mkdir(parents=True)
    (game / "script.rpy").write_text('label start:\n    "Hello"\n', "utf-8")
    (game / "lines.yml").write_text("text: Hello\n", "utf-8")
    launcher = root / "Game.sh"
    launcher.write_text("placeholder")
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    def fake_engine(command, cwd, log, cancel):
        command_index = command.index("translate")
        stage, lang = command[command_index - 1], command[command_index + 1]
        stage = Path(stage)
        assert cwd == stage
        folder = stage / "game/tl" / lang
        folder.mkdir(parents=True)
        (folder / "script.rpy").write_text(f'# game/script.rpy:2\ntranslate {lang} start_hello:\n    # "Hello"\n    "Hello"\n')
        (stage / "revisor_selected.json").write_text(json.dumps({"script.rpy": str(stage / "game/script.rpy"), "lines.yml": str(stage / "game/lines.yml")}))
        return ""
    monkeypatch.setattr(extraction, "run_command", fake_engine)
    project, yaml_paths = prepare_project(root, "pt_BR", "auto", "pt", launcher, None, lambda *a: None, Event())
    assert project.entries[0].source == "Hello" and "lines.yml" in yaml_paths
    after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert before == after


def test_nested_rpa_member_paths_are_relative_to_game_not_archive_parent(tmp_path, monkeypatch):
    from renpy_revisor import extraction
    root = tmp_path / "Nested Game"
    (root / "game/data").mkdir(parents=True)
    (root / "game/data/scripts.rpa").write_bytes(b"archive fixture")
    launcher = root / "Game.sh"
    launcher.write_text("placeholder")
    monkeypatch.setattr(extraction, "prepare_srt", lambda *a: tmp_path / "srt.exe")
    def fake_srt(exe, source, destination, operation, cancel, log):
        destination.mkdir(parents=True)
        if operation == "-e":
            (destination / "chapter.rpyc").write_bytes(b"compiled")
        else:
            (destination / "chapter.rpy").write_text('label chapter:\n    "Hello"\n')
    monkeypatch.setattr(extraction, "srt_operation", fake_srt)
    def fake_engine(command, cwd, log, cancel):
        stage = cwd
        manifest = json.loads((stage / "revisor_sources.json").read_text())
        assert list(manifest) == ["chapter.rpy"]
        assert manifest["chapter.rpy"][0]["logical"] == "chapter.rpyc"
        lang = command[command.index("translate") + 1]
        folder = stage / "game/tl" / lang
        folder.mkdir(parents=True)
        (folder / "chapter.rpy").write_text(f'translate {lang} chapter_hello:\n    # "Hello"\n    "Hello"\n')
        (stage / "revisor_selected.json").write_text(json.dumps({"chapter.rpy": manifest["chapter.rpy"][0]["source"]}))
        return ""
    monkeypatch.setattr(extraction, "run_command", fake_engine)
    project, _ = prepare_project(root, "pt_BR", "auto", "pt", launcher, None, lambda *a: None, Event())
    assert project.entries[0].block == "chapter_hello"
