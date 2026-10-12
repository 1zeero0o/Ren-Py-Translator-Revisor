from pathlib import Path

from PySide6.QtCore import Qt

from renpy_revisor.demo import demo_project
from renpy_revisor.domain import Entry, Project
from renpy_revisor.ui import MainWindow


def test_desktop_edit_review_search_save_and_reopen(app, tmp_path):
    window = MainWindow()
    project = demo_project()
    path = tmp_path / "review.rpt.json"
    window.install_project(project, path)
    window.show()
    app.processEvents()
    window.table.setCurrentIndex(window.proxy.index(2, 1))
    window.translation.setPlainText("Ainda resta {i}uma{/i} história para contar.")
    window.review_next()
    window.save_local()
    assert project.entries[2].status == "reviewed"
    assert project.entries[2].target == "Ainda resta {i}uma{/i} história para contar."
    window.search.setText("história")
    assert window.proxy.rowCount() == 1
    loaded = Project.load(path)
    assert loaded.entries[2].status == "reviewed"
    window.close()


def test_selection_cap_remains_global_across_filters(app, tmp_path):
    window = MainWindow()
    project = Project(str(tmp_path), "pt_BR", entries=[Entry(str(i), f"Line {i}", "a" if i < 50 else "b", i, "yaml") for i in range(60)])
    window.install_project(project, tmp_path / "project.rpt.json")
    window.select_visible()
    assert len(window.model.checked) == 50
    window.file_filter.setCurrentIndex(window.file_filter.findData("b"))
    assert window.proxy.rowCount() == 10
    index = window.proxy.mapToSource(window.proxy.index(0, 0))
    assert not window.model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert len(window.model.checked) == 50
    window.clear_checks()
    assert not window.model.checked
    window.select_visible()
    assert len(window.model.checked) == 10
    window.close()


def test_filter_review_advances_without_losing_text(app, tmp_path):
    window = MainWindow()
    project = demo_project()
    window.install_project(project, tmp_path / "project.rpt.json")
    window.state_filter.setCurrentIndex(window.state_filter.findData("pending"))
    window.table.setCurrentIndex(window.proxy.index(0, 1))
    original_entry = window.current
    window.translation.setPlainText("Ainda resta {i}uma{/i} história para contar.")
    window.review_next()
    assert original_entry.status == "reviewed"
    assert original_entry.target == "Ainda resta {i}uma{/i} história para contar."
    assert window.current is not original_entry
    window.close()
