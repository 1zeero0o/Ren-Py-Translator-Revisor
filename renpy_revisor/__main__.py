import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .domain import Project
from .ui import MainWindow, STYLE


def main():
    parser = argparse.ArgumentParser(description="Ren'Py Translator & Revisor")
    parser.add_argument("project", nargs="?", help="Projeto .rpt.json para abrir")
    parser.add_argument("--demo", action="store_true", help="Abrir um projeto demonstrativo sem precisar de um jogo")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("RenPyRevisor")
    app.setOrganizationName("RenPyRevisor")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    if args.demo:
        from .demo import demo_project
        project = demo_project()
        window.install_project(project, Path(project.workspace) / "demo.rpt.json")
        window.setWindowTitle("Ren'Py Translator & Revisor — Demonstração")
    elif args.project:
        window.install_project(Project.load(Path(args.project)), Path(args.project))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
