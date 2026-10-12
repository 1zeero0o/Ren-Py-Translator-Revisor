"""Optional tests using the real uploaded SRT and a user-installed Ren'Py SDK."""
import os
import pickle
import shutil
import zlib
from pathlib import Path
from threading import Event

import pytest

from renpy_revisor.catalog import read_templates, read_yaml
from renpy_revisor.exporter import export_project
from renpy_revisor.extraction import native_command, prepare_project, prepare_srt, run_command, srt_operation

CAN_RUN_SRT = os.name == "nt" or bool(shutil.which("wine"))
LAUNCHER = os.environ.get("RENPY_TEST_LAUNCHER")


def write_rpa(path, members):
    key = 0x2468ABCD
    header_size = len(b"RPA-3.0 0000000000000000 00000000\n")
    offset = header_size
    payload = b""
    index = {}
    for name, data in members.items():
        index[name] = [(offset ^ key, len(data) ^ key)]
        payload += data
        offset += len(data)
    path.write_bytes(f"RPA-3.0 {offset:016x} {key:08x}\n".encode() + payload + zlib.compress(pickle.dumps(index, protocol=2)))


@pytest.mark.skipif(not CAN_RUN_SRT, reason="SRT requer Windows ou Wine; este teste não simula o executável")
def test_real_srt_extracts_rpa_and_yaml(tmp_path):
    archive = tmp_path / "scripts.rpa"
    write_rpa(archive, {"script.rpy": b'label start:\n    "Hello"\n', "data/lines.yml": b"text: Hello\n"})
    workspace = tmp_path / "tools"
    workspace.mkdir()
    srt = prepare_srt(workspace)
    output = tmp_path / "out"
    srt_operation(srt, archive, output, "-e", Event(), tmp_path / "extract.log")
    assert (output / "script.rpy").read_bytes() == b'label start:\n    "Hello"\n'
    assert (output / "data/lines.yml").read_bytes() == b"text: Hello\n"


@pytest.mark.skipif(not LAUNCHER or not CAN_RUN_SRT, reason="Defina RENPY_TEST_LAUNCHER e use Windows/Wine para o teste completo")
def test_native_compiled_archive_to_in_game_translation(tmp_path):
    launcher = Path(LAUNCHER).resolve()
    root = tmp_path / "Example Game"
    game = root / "game"
    game.mkdir(parents=True)
    script = game / "script.rpy"
    script.write_text('define e = Character("Eileen")\ndefault player_name = "Alex"\nlabel start:\n    e "Hello, [player_name]."\n    menu:\n        "Continue":\n            pass\n    return\n', "utf-8")
    def engine(args, log):
        return run_command(native_command(launcher, [str(root), *args, "--savedir", str(tmp_path / "saves")]), launcher.parent, tmp_path / log, Event())
    engine(["translate", "baseline"], "baseline.log")
    _, baseline = read_templates(game / "tl/baseline", "baseline")
    expected = next(e.block for e in baseline if e.source == "Hello, [player_name].")
    write_rpa(game / "archive.rpa", {"script.rpyc": script.with_suffix(".rpyc").read_bytes(), "data/lines.yml": b"text: Good morning\n"})
    script.unlink()
    script.with_suffix(".rpyc").unlink()
    shutil.rmtree(game / "tl")
    project, paths = prepare_project(root, "pt_BR", "auto", "pt", launcher, None, lambda *a: None, Event())
    dialogue = next(e for e in project.entries if e.source == "Hello, [player_name].")
    assert dialogue.block == expected
    dialogue.update("Olá, [player_name].", reviewed=True)
    next(e for e in project.entries if e.source == "Continue").update("Continuar", reviewed=True)
    docs, entries, warnings = read_yaml(paths)
    assert not warnings and len(entries) == 1
    entries[0].update("Bom dia", reviewed=True)
    project.yaml_documents = docs
    project.entries.extend(entries)
    export_project(project)
    # Assert the real engine loads the exported native dialogue, menu string and
    # localized YAML. This checks more than generated files or a process exit code.
    verifier = game / "zz_revisor_verify.rpy"
    verifier.write_text('init 999 python:\n'
                        f'    _verify = renpy.game.script.translator.language_translates[({expected!r}, "pt_BR")]\n'
                        '    _what = _verify.what if hasattr(_verify, "what") else _verify.block[-1].what\n'
                        '    assert _what == "Olá, [player_name]."\n'
                        '    assert renpy.translation.translate_string("Continue", "pt_BR") == "Continuar"\n'
                        '    renpy.game.preferences.language = "pt_BR"\n'
                        '    assert "Bom dia" in renpy.loader.load("data/lines.yml").read().decode("utf-8")\n'
                        '    import io\n'
                        '    with io.open(config.basedir + "/verified.txt", "w", encoding="utf-8") as _out:\n'
                        '        _out.write("dialogue + menu + yaml verified")\n', "utf-8")
    engine(["translate", "pt_BR", "--count"], "verify.log")
    assert (root / "verified.txt").read_text() == "dialogue + menu + yaml verified"
