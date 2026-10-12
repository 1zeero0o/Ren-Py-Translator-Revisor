import json
from pathlib import Path

import pytest
import yaml

from renpy_revisor.catalog import parse_template, quote, read_yaml, unquote
from renpy_revisor.demo import demo_project
from renpy_revisor.domain import Project, RevisorError, confined, validate_translation
from renpy_revisor.exporter import export_project, render_files


def test_native_ids_attributes_and_control_statements_survive_export():
    template = '''# game/chapter.rpy:20
translate seed chapter_explicit_id:
    # voice "audio/line.ogg"
    # e happy "Hello, [name]!" nointeract
    voice "audio/line.ogg"
    e happy "Hello, [name]!" nointeract

translate seed chapter_12345678:
    # "Alice" "Wait!" with dissolve
    "Alice" "Wait!" with dissolve

translate seed strings:
    old "Menu"
    new "Menu"
'''
    entries = parse_template("chapter.rpy", template, "seed")
    assert [e.source for e in entries] == ["Hello, [name]!", "Wait!", "Menu"]
    entries[0].update('Olá, [name]! "Tudo bem?"', reviewed=True)
    project = Project("unused", "pt_BR", entries=entries, templates={"chapter.rpy": template}, template_language="seed")
    exported = render_files(project)["revisor/native/chapter.rpy"].decode()
    assert "translate pt_BR chapter_explicit_id:" in exported
    assert 'voice "audio/line.ogg"' in exported
    assert 'e happy "Olá, [name]! \\"Tudo bem?\\"" nointeract' in exported
    assert '"Alice" "Wait!" with dissolve' in exported
    assert 'new "Menu"' in exported  # Untranslated strings fall back to the source.


@pytest.mark.parametrize("text", ['aspas " e \\ caminho', 'A  B   C', 'linha\nlinha', 'á [name] {b}ok{/b}', 'tab\tfim', '[[escaped]] {{literal}'])
def test_renpy_lexer_roundtrip(text):
    assert unquote(quote(text)) == text


def test_tokens_reject_missing_added_or_duplicated_tags():
    for target in ("Olá!", "Olá [name] [name] {b}ok{/b}", "Olá [name] {i}ok{/i}", "{/b}Olá [name] {b}ok"):
        with pytest.raises(RevisorError):
            validate_translation("Hello [name] {b}ok{/b}", target)
    validate_translation("Hello [items[0]!q] %s", "Olá [items[0]!q] %s")


def test_project_roundtrip_and_tampered_spans(tmp_path):
    project = demo_project()
    path = tmp_path / "project.rpt.json"
    project.save(path)
    loaded = Project.load(path)
    assert loaded.entries[0].status == "reviewed"
    assert loaded.templates == project.templates
    loaded.entries[0].start += 1
    with pytest.raises(RevisorError, match="corrompido"):
        render_files(loaded)


def test_yaml_text_values_lists_keys_types_and_export(tmp_path):
    source = tmp_path / "dialogue.yml"
    source.write_text('chapter:\n  title: Hello\n  lines: ["Goodbye", 12, true]\n', "utf-8")
    documents, entries, warnings = read_yaml({"data/dialogue.yml": source})
    assert not warnings
    assert [e.source for e in entries] == ["Hello", "Goodbye"]
    entries[0].update("Olá", reviewed=True)
    project = Project(str(tmp_path), "pt_BR", entries=entries, yaml_documents=documents)
    files = render_files(project)
    value = yaml.safe_load(files["data/dialogue.yml"])
    assert value == {"chapter": {"title": "Olá", "lines": ["Goodbye", 12, True]}}
    assert 'old "Hello"' in files["revisor/yaml_strings.rpy"].decode()
    assert 'new "Olá"' in files["revisor/yaml_strings.rpy"].decode()


def test_yaml_unsafe_tags_recursive_aliases_and_dates_reported(tmp_path):
    paths = {}
    for name, text in {"unsafe.yml": "x: !!python/object:os.system {}", "cycle.yml": "x: &a [*a]", "date.yml": "x: 2024-01-01"}.items():
        path = tmp_path / name
        path.write_text(text)
        paths[name] = path
    docs, entries, warnings = read_yaml(paths)
    assert docs == {} and entries == [] and len(warnings) == 3


def test_yaml_duplicate_translation_conflict():
    project = demo_project()
    from renpy_revisor.domain import Entry
    project.entries.extend([Entry("a", "Hello", "a.yml", 0, "yaml", "Olá"), Entry("b", "Hello", "b.yml", 0, "yaml", "Oi")])
    project.yaml_documents.update({"a.yml": "Hello", "b.yml": "Hello"})
    with pytest.raises(RevisorError, match="conflitantes"):
        render_files(project)


def test_repeatable_export_backup_and_preservation_of_unrelated_files(tmp_path):
    project = demo_project()
    source = Path(project.game_root) / "game" / "script.rpy"
    source.write_text("original", "utf-8")
    root, count, backup = export_project(project)
    assert count == 4 and backup is None
    extra = root / "player-notes.txt"
    extra.write_text("keep me")
    compiled = root / "revisor/native/script.rpyc"
    compiled.write_bytes(b"stale compiled file")
    project.entries[1].update("A estação estava quieta.")
    _, _, backup = export_project(project)
    assert backup and backup.is_file()
    assert not compiled.exists()
    assert extra.read_text() == "keep me"
    assert source.read_text() == "original"
    assert "A estação estava quieta." in (root / "revisor/native/script.rpy").read_text()


def test_external_edit_and_existing_translation_are_never_overwritten():
    project = demo_project()
    root, _, _ = export_project(project)
    target = root / "revisor/native/script.rpy"
    target.write_text("user edit")
    with pytest.raises(RevisorError, match="editado fora"):
        export_project(project)
    assert target.read_text() == "user edit"


def test_existing_duplicate_native_ids_block_export():
    project = demo_project()
    root = Path(project.game_root) / "game/tl/pt_BR"
    root.mkdir(parents=True)
    (root / "original.rpy").write_text(project.templates["script.rpy"].replace("revisor_template", "pt_BR"))
    with pytest.raises(RevisorError, match="conflitante"):
        export_project(project)
    assert not (root / "revisor").exists()


def test_unowned_target_and_traversal_block_export(tmp_path):
    project = demo_project()
    root = Path(project.game_root) / "game/tl/pt_BR/revisor/native"
    root.mkdir(parents=True)
    (root / "script.rpy").write_text("keep")
    with pytest.raises(RevisorError, match="sobrescreveria"):
        export_project(project)
    for name in ("../outside", "/absolute", "C:\\Windows\\file"):
        with pytest.raises(RevisorError):
            confined(tmp_path, name)


def test_disabled_language_activation_removes_only_owned_files():
    project = demo_project()
    root, _, _ = export_project(project)
    project.activate_language = False
    export_project(project)
    assert not (root / "revisor/00_language.rpy").exists()
    assert (root / "revisor/native/script.rpy").is_file()


def test_export_transaction_rolls_back_on_write_failure(monkeypatch):
    project = demo_project()
    root, _, _ = export_project(project)
    original = (root / "revisor/native/script.rpy").read_bytes()
    project.entries[1].update("Mudou")
    from renpy_revisor import exporter
    real_write = exporter.atomic_write
    calls = 0
    def failing(path, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        return real_write(path, data)
    monkeypatch.setattr(exporter, "atomic_write", failing)
    with pytest.raises(RevisorError, match="restauradas"):
        export_project(project)
    assert (root / "revisor/native/script.rpy").read_bytes() == original


def test_export_reports_incomplete_rollback_and_retains_backup(monkeypatch):
    project = demo_project()
    root, _, _ = export_project(project)
    from renpy_revisor import exporter
    def failing(path, data):
        raise OSError("disk full")
    monkeypatch.setattr(exporter, "atomic_write", failing)
    with pytest.raises(RevisorError, match="restauração incompleta.*Backup"):
        export_project(project)
    from renpy_revisor.domain import user_data_dir
    assert list((user_data_dir() / "backups").glob("*.zip"))
