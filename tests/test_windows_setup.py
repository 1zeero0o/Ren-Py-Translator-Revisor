import subprocess
import sys

import pytest

from scripts import setup_windows as setup


def old_environment(root):
    executable = root / ".venv/Scripts/python.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"old python")
    (root / ".venv/keep.txt").write_text("preserve this environment")
    return executable


def test_runtime_probe_executes_and_reads_real_interpreter():
    runtime = setup.probe([sys.executable])
    assert runtime.version == sys.version_info[:3]
    assert runtime.bits == 64


def test_selects_python_312_instead_of_default_315(monkeypatch):
    monkeypatch.setattr(setup.shutil, "which", lambda name: "py.exe")
    def probe(command):
        if "-3.12" in command:
            return setup.Runtime((3, 12, 10), 64)
        return setup.Runtime((3, 15, 0), 64)
    monkeypatch.setattr(setup, "probe", probe)
    command, runtime = setup.choose_python()
    assert command == ["py.exe", "-3.12"] and runtime.version[:2] == (3, 12)


def test_skips_32bit_and_free_threaded_runtimes(monkeypatch):
    monkeypatch.setattr(setup.shutil, "which", lambda name: "py.exe")
    versions = {"-3.12": setup.Runtime((3, 12, 0), 32), "-3.13": setup.Runtime((3, 13, 0), 64, True),
                "-3.14": setup.Runtime((3, 14, 0), 64)}
    monkeypatch.setattr(setup, "probe", lambda command: versions.get(command[-1]))
    assert setup.choose_python()[0] == ["py.exe", "-3.14"]


def test_reuses_compatible_existing_environment(tmp_path, monkeypatch):
    executable = old_environment(tmp_path)
    monkeypatch.setattr(setup, "probe", lambda command: setup.Runtime((3, 12, 0), 64))
    def unexpected():
        raise AssertionError("An installed compatible .venv should be reused")
    monkeypatch.setattr(setup, "choose_python", unexpected)
    assert setup.ensure_environment(tmp_path) == executable
    assert (tmp_path / ".venv/keep.txt").read_text() == "preserve this environment"
    assert not list(tmp_path.glob(".venv-backup-*"))


def test_replaces_315_environment_with_backup(tmp_path, monkeypatch):
    executable = old_environment(tmp_path)
    calls = []
    def probe(command):
        return setup.Runtime((3, 12, 0) if calls else (3, 15, 0), 64)
    monkeypatch.setattr(setup, "probe", probe)
    monkeypatch.setattr(setup, "choose_python", lambda: (["py.exe", "-3.12"], setup.Runtime((3, 12, 0), 64)))
    def create(command, **kwargs):
        calls.append(command)
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"new compatible python")
    monkeypatch.setattr(setup.subprocess, "run", create)
    assert setup.ensure_environment(tmp_path) == executable
    backup, = tmp_path.glob(".venv-backup-*")
    assert (backup / "Scripts/python.exe").read_bytes() == b"old python"
    assert (backup / "keep.txt").read_text() == "preserve this environment"
    assert calls == [["py.exe", "-3.12", "-m", "venv", str(tmp_path / ".venv")]]


def test_no_supported_python_preserves_existing_environment(tmp_path, monkeypatch):
    executable = old_environment(tmp_path)
    monkeypatch.setattr(setup.shutil, "which", lambda name: "py.exe")
    monkeypatch.setattr(setup, "probe", lambda command: setup.Runtime((3, 15, 0), 64))
    with pytest.raises(setup.SetupError, match="Instale Python 3.12"):
        setup.ensure_environment(tmp_path)
    assert executable.read_bytes() == b"old python"
    assert not list(tmp_path.glob(".venv-backup-*"))


def test_creation_failure_retains_old_environment(tmp_path, monkeypatch):
    old_environment(tmp_path)
    monkeypatch.setattr(setup, "probe", lambda command: setup.Runtime((3, 15, 0), 64))
    monkeypatch.setattr(setup, "choose_python", lambda: (["py.exe", "-3.12"], setup.Runtime((3, 12, 0), 64)))
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(setup.subprocess, "run", fail)
    with pytest.raises(setup.SetupError, match="ambiente anterior está"):
        setup.ensure_environment(tmp_path)
    backup, = tmp_path.glob(".venv-backup-*")
    assert (backup / "keep.txt").read_text() == "preserve this environment"


def test_install_requires_binary_external_dependencies(tmp_path, monkeypatch):
    executable = tmp_path / ".venv/Scripts/python.exe"
    monkeypatch.setattr(setup, "ensure_environment", lambda root: executable)
    commands = []
    monkeypatch.setattr(setup.subprocess, "run", lambda command, **kwargs: commands.append((command, kwargs)))
    assert setup.install(tmp_path, "build") == executable
    command, kwargs = commands[0]
    assert "--only-binary=:all:" in command and command[-2:] == ["-e", ".[build]"]
    assert kwargs["cwd"] == tmp_path and kwargs["check"] is True
