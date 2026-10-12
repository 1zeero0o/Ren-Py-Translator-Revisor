from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QTableView, QVBoxLayout, QWidget,
)

from .catalog import read_yaml
from .domain import Cancelled, Entry, Project, RevisorError, validate_language
from .exporter import export_project
from .extraction import find_launcher, prepare_project
from .google import GoogleTranslator, translate_batch

STATUS = {"pending": "Pendente", "translated": "Traduzida", "machine": "Automática", "reviewed": "Revisada"}
COLORS = {"pending": "#8596b3", "translated": "#b8a2f6", "machine": "#f4bd6e", "reviewed": "#64d6b3"}
LANGUAGES = [("Português (Brasil)", "pt_BR", "pt"), ("Português (Portugal)", "pt_PT", "pt-PT"),
             ("English", "english", "en"), ("Español", "spanish", "es"), ("Français", "french", "fr"),
             ("Deutsch", "german", "de"), ("Italiano", "italian", "it"), ("日本語", "japanese", "ja"),
             ("한국어", "korean", "ko"), ("中文 (简体)", "schinese", "zh-CN"), ("Русский", "russian", "ru")]

STYLE = """
QWidget { background: #111722; color: #e4eaf4; font-family: 'Segoe UI', 'DejaVu Sans'; font-size: 13px; }
QMainWindow, QDialog { background: #111722; }
QLabel#Brand { font-size: 24px; font-weight: 700; color: #f5f8fc; }
QLabel#Muted { color: #91a0b8; }
QLabel#Section { color: #70dfc0; font-size: 11px; font-weight: 700; }
QLabel#GameTitle { font-size: 17px; font-weight: 600; }
QLabel#Count { font-size: 27px; font-weight: 600; }
QFrame#Card { background: #1a2331; border: 1px solid #2a3547; border-radius: 9px; }
QFrame#Card QLabel, QFrame#Card QCheckBox { background: transparent; }
QPushButton { background: #263247; border: 1px solid #3a485d; border-radius: 6px; padding: 9px 15px; font-weight: 600; }
QPushButton:hover { background: #33435d; border-color: #7187a5; }
QPushButton:disabled { color: #56667b; border-color: #263143; background: #1b2533; }
QPushButton#Primary { background: #57d1af; color: #09281f; border: none; }
QPushButton#Primary:hover { background: #77e5c5; }
QPushButton#Primary:disabled { background: #21483f; color: #679e8f; }
QPushButton#Quiet { background: transparent; border: 1px solid #344158; }
QLineEdit, QComboBox { background: #1a2433; border: 1px solid #35445d; border-radius: 6px; padding: 8px; selection-background-color: #315e67; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #57d1af; }
QComboBox QAbstractItemView { background: #202c3d; selection-background-color: #315e67; }
QTableView { background: #141d2a; alternate-background-color: #192332; border: 1px solid #2a384d; border-radius: 5px; gridline-color: #29364a; selection-background-color: #244d50; selection-color: #ffffff; }
QHeaderView::section { background: #212e41; color: #a8b9d0; border: none; padding: 10px; font-weight: 600; }
QPlainTextEdit { background: #172130; border: 1px solid #35445d; border-radius: 7px; padding: 10px; selection-background-color: #315e67; }
QProgressBar { border: none; border-radius: 4px; background: #263348; height: 7px; text-align: center; }
QProgressBar::chunk { background: #57d1af; border-radius: 4px; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { background: #182331; border: 1px solid #657b96; border-radius: 3px; }
QCheckBox::indicator:checked { background: #57d1af; border: 1px solid #91e8d0; border-radius: 3px; }
QTableView::indicator:unchecked { background: #182331; border: 1px solid #657b96; border-radius: 3px; width: 14px; height: 14px; }
QTableView::indicator:checked { background: #57d1af; border: 1px solid #91e8d0; border-radius: 3px; width: 14px; height: 14px; }
QSplitter::handle { background: #29374a; }
QStatusBar { background: #172131; color: #b6c3d6; }
QToolTip { background: #263348; color: #e4eaf4; border: 1px solid #52657f; }
"""


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback, style=None):
    widget = QPushButton(text)
    if style:
        widget.setObjectName(style)
    widget.clicked.connect(callback)
    return widget


class TaskThread(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, str)
    translation = Signal(str, str, str)

    def __init__(self, work, parent):
        super().__init__(parent)
        self.work = work
        self.cancel = Event()

    def run(self):
        try:
            self.result.emit(self.work(self))
        except Cancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)


class EntryModel(QAbstractTableModel):
    selectionChanged = Signal()
    limitReached = Signal()
    HEADERS = ["Marcar", "Original", "Tradução", "Estado", "Arquivo / contexto"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.checked = set()

    def replace(self, entries):
        self.beginResetModel()
        self.entries = entries
        self.checked.clear()
        self.endResetModel()
        self.selectionChanged.emit()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self.entries[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.CheckStateRole and c == 0:
            return Qt.CheckState.Checked if e.id in self.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            return ["", e.source.replace("\n", " ↵ "), e.target.replace("\n", " ↵ "),
                    "Erro" if e.error else STATUS[e.status], f"{e.file}:{e.line}" if e.line else e.file][c]
        if role == Qt.ItemDataRole.ToolTipRole:
            return e.error or (e.source if c == 1 else e.target if c == 2 else f"{e.file}\n{e.block or 'YAML: ' + str(e.yaml_path)}")
        if role == Qt.ItemDataRole.ForegroundRole and c == 3:
            return QColor("#f28a8a" if e.error else COLORS[e.status])
        if role == Qt.ItemDataRole.TextAlignmentRole and c in (0, 3):
            return Qt.AlignmentFlag.AlignCenter

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return flags | Qt.ItemFlag.ItemIsUserCheckable if index.column() == 0 else flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != 0:
            return False
        e = self.entries[index.row()]
        if value == Qt.CheckState.Checked.value or value == Qt.CheckState.Checked:
            if e.id not in self.checked and len(self.checked) >= 50:
                self.limitReached.emit()
                return False
            self.checked.add(e.id)
        else:
            self.checked.discard(e.id)
        self.dataChanged.emit(index, index, [role])
        self.selectionChanged.emit()
        return True

    def changed(self, row):
        self.dataChanged.emit(self.index(row, 0), self.index(row, 4))


class EntryFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ""
        self.status = ""
        self.file = ""
        self.setDynamicSortFilter(True)

    def filterAcceptsRow(self, row, parent):
        e = self.sourceModel().entries[row]
        return (not self.status or e.status == self.status) and (not self.file or e.file == self.file) and (
            not self.query or self.query in (e.source + " " + e.target + " " + e.file).casefold())

    def refresh(self):
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)


class OpenGameDialog(QDialog):
    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preparar jogo Ren'Py")
        self.setMinimumWidth(610)
        self.root = root
        layout = QVBoxLayout(self)
        layout.addWidget(label("Novo projeto de tradução", "GameTitle"))
        layout.addWidget(label(str(root), "Muted", True))
        form = QFormLayout()
        self.language = QComboBox()
        for title, code, google in LANGUAGES:
            self.language.addItem(title, (code, google))
        self.code = QLineEdit("pt_BR")
        self.google = QLineEdit("pt")
        self.source = QComboBox()
        self.source.addItem("Detectar automaticamente", "auto")
        for title, code, google in LANGUAGES:
            self.source.addItem(title, google)
        self.language.currentIndexChanged.connect(self.change_language)
        form.addRow("Traduzir para", self.language)
        form.addRow("Identificador no Ren'Py", self.code)
        form.addRow("Código no Google", self.google)
        form.addRow("Idioma de origem", self.source)
        self.launcher = QLineEdit(str(find_launcher(root) or ""))
        self.launcher.setPlaceholderText("Executável do jogo ou renpy.exe / renpy.sh de um SDK compatível")
        form.addRow("Motor Ren'Py", self.path_picker(self.launcher, "Executável (*.exe *.sh);;Todos os arquivos (*)"))
        self.srt = QLineEdit()
        self.srt.setPlaceholderText("Usar o SRT enviado, incluído no programa")
        form.addRow("SRT (opcional)", self.path_picker(self.srt, "SRT (srt.exe)"))
        layout.addLayout(form)
        self.activate = QCheckBox("Ativar este idioma ao iniciar o jogo")
        self.activate.setChecked(True)
        layout.addWidget(self.activate)
        layout.addWidget(label("A extração ocorre em uma cópia de game. Os scripts originais são preservados.\n"
                               "Reserve espaço para a cópia e o conteúdo extraído. Use um motor da mesma versão do jogo.", "Muted", True))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Extrair e preparar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def path_picker(self, edit, pattern):
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit)

        def pick():
            path, _ = QFileDialog.getOpenFileName(self, "Selecionar ferramenta", str(self.root), pattern)
            if path:
                edit.setText(path)

        row.addWidget(button("…", pick, "Quiet"))
        return widget

    def change_language(self):
        code, google = self.language.currentData()
        self.code.setText(code)
        self.google.setText(google)

    def accept(self):
        try:
            validate_language(self.code.text().strip())
            if not self.google.text().strip():
                raise RevisorError("Informe o código do idioma no Google.")
            if not Path(self.launcher.text()).is_file():
                raise RevisorError("Selecione o executável do jogo ou um SDK Ren'Py compatível.")
        except RevisorError as exc:
            QMessageBox.warning(self, "Verifique as opções", str(exc))
            return
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ren'Py Translator & Revisor")
        self.resize(1380, 900)
        self.setMinimumSize(1000, 680)
        self.project: Project | None = None
        self.project_path: Path | None = None
        self.current: Entry | None = None
        self.thread = None
        self.busy = False
        self.loading_editor = False
        self.draft_dirty = False
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.timeout.connect(self.save_local)
        self.build_ui()
        self.build_menu()
        self.update_summary()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(24, 20, 24, 12)
        outer.setSpacing(15)
        top = QHBoxLayout()
        branding = QVBoxLayout()
        branding.addWidget(label("REN'PY   /   TRANSLATOR & REVISOR", "Section"))
        branding.addWidget(label("Cada história, no seu idioma.", "Brand"))
        top.addLayout(branding)
        top.addStretch()
        self.open_button = button("Abrir pasta do jogo", self.open_game, "Primary")
        self.project_button = button("Abrir projeto", self.open_project)
        self.save_button = button("Salvar no jogo", self.save_game)
        top.addWidget(self.open_button)
        top.addWidget(self.project_button)
        top.addWidget(self.save_button)
        outer.addLayout(top)
        card = QFrame()
        card.setObjectName("Card")
        info = QHBoxLayout(card)
        info.setContentsMargins(16, 13, 16, 13)
        game_info = QVBoxLayout()
        self.game_title = label("Nenhum jogo aberto", "GameTitle")
        self.game_path = label("Selecione a pasta onde está o executável do jogo.", "Muted")
        self.game_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        game_info.addWidget(self.game_title)
        game_info.addWidget(self.game_path)
        info.addLayout(game_info, 1)
        for name in ("Total de strings", "Revisadas", "Marcadas / 50"):
            box = QVBoxLayout()
            count = label("0", "Count")
            box.addWidget(count)
            box.addWidget(label(name, "Muted"))
            info.addLayout(box)
            if name == "Total de strings": self.total_label = count
            elif name == "Revisadas": self.reviewed_label = count
            else: self.checked_label = count
        outer.addWidget(card)
        self.workflow = label("01  ABRIR JOGO      →      02  EXTRAIR E GERAR      →      03  TRADUZIR E REVISAR      →      04  SALVAR EM game/tl", "Muted")
        outer.addWidget(self.workflow)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar no original, na tradução ou no arquivo…")
        self.search.setClearButtonEnabled(True)
        self.state_filter = QComboBox()
        self.state_filter.addItem("Todos os estados", "")
        for key, title in STATUS.items(): self.state_filter.addItem(title, key)
        self.file_filter = QComboBox()
        self.file_filter.setMaximumWidth(280)
        self.file_filter.addItem("Todos os arquivos", "")
        tools.addWidget(self.search, 1)
        tools.addWidget(self.file_filter)
        tools.addWidget(self.state_filter)
        self.select_button = button("Marcar até 50", self.select_visible, "Quiet")
        self.clear_button = button("Limpar marcas", self.clear_checks, "Quiet")
        self.google_button = button("Traduzir marcadas · Google", self.google_batch)
        tools.addWidget(self.select_button)
        tools.addWidget(self.clear_button)
        tools.addWidget(self.google_button)
        outer.addLayout(tools)
        self.model = EntryModel(self)
        self.proxy = EntryFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(39)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 65)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(3, 105)
        self.table.setColumnWidth(4, 240)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        editor = QWidget()
        edit_layout = QVBoxLayout(editor)
        edit_layout.setContentsMargins(0, 5, 0, 0)
        editor_top = QHBoxLayout()
        self.context = label("Selecione uma string para editar e revisar", "Muted")
        editor_top.addWidget(self.context, 1)
        self.visible_label = label("0 visíveis", "Muted")
        editor_top.addWidget(self.visible_label)
        edit_layout.addLayout(editor_top)
        panes = QHBoxLayout()
        source = QVBoxLayout()
        source.addWidget(label("ORIGINAL", "Section"))
        self.original = QPlainTextEdit()
        self.original.setReadOnly(True)
        self.original.setPlaceholderText("O texto original aparecerá aqui.")
        source.addWidget(self.original)
        target = QVBoxLayout()
        target.addWidget(label("TRADUÇÃO", "Section"))
        self.translation = QPlainTextEdit()
        self.translation.setPlaceholderText("Digite sua tradução ou edite a sugestão do Google…")
        target.addWidget(self.translation)
        panes.addLayout(source)
        panes.addLayout(target)
        edit_layout.addLayout(panes)
        edit_actions = QHBoxLayout()
        edit_actions.addWidget(label("Preserve [variáveis], {tags} e quebras de linha.", "Muted"), 1)
        self.copy_button = button("Copiar original", self.copy_original, "Quiet")
        self.apply_button = button("Aplicar tradução", self.apply_current)
        self.review_button = button("Revisar e próxima  →", self.review_next, "Primary")
        edit_actions.addWidget(self.copy_button)
        edit_actions.addWidget(self.apply_button)
        edit_actions.addWidget(self.review_button)
        edit_layout.addLayout(edit_actions)
        split.addWidget(editor)
        split.setSizes([420, 225])
        outer.addWidget(split, 1)
        footer = QHBoxLayout()
        self.operation = label("Pronto para abrir um jogo. Extração e revisão ficam salvas em um projeto local.", "Muted")
        self.operation.setWordWrap(True)
        footer.addWidget(self.operation, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(200)
        self.progress.hide()
        self.cancel_button = button("Cancelar", self.cancel_task, "Quiet")
        self.cancel_button.hide()
        self.logs_button = button("Área de trabalho", self.open_workspace, "Quiet")
        footer.addWidget(self.progress)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.logs_button)
        outer.addLayout(footer)
        self.table.selectionModel().currentRowChanged.connect(self.change_current)
        self.model.selectionChanged.connect(self.update_summary)
        self.model.limitReached.connect(lambda: self.statusBar().showMessage("O limite é de 50 strings marcadas por lote.", 5000))
        self.search.textChanged.connect(self.filter_changed)
        self.file_filter.currentIndexChanged.connect(self.filter_changed)
        self.state_filter.currentIndexChanged.connect(self.filter_changed)
        self.translation.textChanged.connect(self.editor_changed)

    def build_menu(self):
        file = self.menuBar().addMenu("Arquivo")
        self.actions = []
        for title, callback, shortcut in (("Abrir pasta do jogo…", self.open_game, "Ctrl+O"),
                                          ("Abrir projeto…", self.open_project, "Ctrl+Shift+O"),
                                          ("Salvar projeto como…", self.save_project_as, "Ctrl+Shift+S"),
                                          ("Salvar no jogo", self.save_game, "Ctrl+S")):
            action = QAction(title, self)
            action.triggered.connect(callback)
            action.setShortcut(QKeySequence(shortcut))
            file.addAction(action)
            self.actions.append(action)
        help_menu = self.menuBar().addMenu("Ajuda")
        help_menu.addAction("Como usar", self.show_help)
        settings_menu = self.menuBar().addMenu("Projeto")
        action = QAction("Idiomas e exportação…", self)
        action.triggered.connect(self.project_settings)
        settings_menu.addAction(action)
        self.actions.append(action)

    def project_settings(self):
        if not self.project or self.busy or not self.flush_draft(): return
        dialog = QDialog(self)
        dialog.setWindowTitle("Idiomas e exportação")
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        code = QLineEdit(self.project.language)
        source = QLineEdit(self.project.google_source)
        target = QLineEdit(self.project.google_target)
        activate = QCheckBox("Ativar este idioma ao iniciar o jogo")
        activate.setChecked(self.project.activate_language)
        form.addRow("Identificador Ren'Py", code)
        form.addRow("Origem no Google (auto, en…)", source)
        form.addRow("Destino no Google (pt, es…)", target)
        layout.addLayout(form)
        layout.addWidget(activate)
        layout.addWidget(label("Alterar o identificador salva em outra pasta de idioma. As traduções anteriores permanecem no jogo.", "Muted", True))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                validate_language(code.text().strip())
                if not source.text().strip() or not target.text().strip():
                    raise RevisorError("Preencha os códigos de idioma do Google.")
            except RevisorError as exc:
                self.task_failed(str(exc))
                return
            self.project.language = code.text().strip()
            self.project.google_source = source.text().strip()
            self.project.google_target = target.text().strip()
            self.project.activate_language = activate.isChecked()
            self.game_title.setText(f"{Path(self.project.game_root).name}   /   {self.project.language}")
            self.save_local()

    def show_help(self):
        QMessageBox.information(self, "Como usar", "1. Abra a pasta base do jogo e escolha o idioma.\n"
                                "2. Aguarde a extração/decompilação e escolha se deseja incluir YAML.\n"
                                "3. Marque até 50 strings para enviar ao Google ou traduza manualmente.\n"
                                "4. Edite no painel inferior e clique em Revisar e próxima.\n"
                                "5. Salve no jogo para gerar game/tl/<idioma>/.\n\n"
                                "Projetos são salvos automaticamente. Ctrl+Shift+S exporta um projeto portátil.\n"
                                "YAML localizado funciona com renpy.file/open_file após a ativação do idioma; jogos que leem via open() ou durante init podem precisar de integração específica.")

    def set_busy(self, busy):
        self.busy = busy
        for widget in (self.open_button, self.project_button, self.save_button, self.select_button, self.clear_button,
                       self.google_button, self.table, self.translation, self.copy_button, self.apply_button, self.review_button):
            widget.setEnabled(not busy)
        for action in self.actions: action.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.update_summary()

    def run_task(self, work, done, translation=False, cancellable=True):
        self.set_busy(True)
        self.progress.setRange(0, 0)
        thread = TaskThread(work, self)
        self.thread = thread
        thread.progress.connect(self.task_progress)
        thread.result.connect(done)
        thread.failed.connect(self.task_failed)
        if translation: thread.translation.connect(self.machine_result)
        thread.finished.connect(lambda: self.task_finished(thread))
        self.cancel_button.setEnabled(cancellable)
        thread.start()

    def task_finished(self, thread):
        if self.thread is thread:
            self.thread = None
            self.set_busy(False)
            self.save_local()
        thread.deleteLater()

    def task_failed(self, message):
        self.operation.setText(message.splitlines()[0][:240])
        QMessageBox.warning(self, "Não foi possível concluir", message)

    def task_progress(self, value, total, text):
        self.progress.setRange(0, total)
        self.progress.setValue(value)
        self.operation.setText(text)

    def cancel_task(self):
        if self.thread:
            self.thread.cancel.set()
            self.cancel_button.setEnabled(False)
            self.operation.setText("Cancelando… aguardando a operação atual terminar.")

    def open_game(self):
        if self.busy or not self.flush_draft(): return
        name = QFileDialog.getExistingDirectory(self, "Selecione a pasta base do jogo (onde está o .exe)")
        if not name: return
        root = Path(name)
        if not (root / "game").is_dir():
            QMessageBox.warning(self, "Pasta inválida", "Selecione a pasta que contém game e o executável do jogo.")
            return
        dialog = OpenGameDialog(root, self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        language = dialog.code.text().strip()
        google_source, google_target = dialog.source.currentData(), dialog.google.text().strip()
        launcher = Path(dialog.launcher.text())
        srt = Path(dialog.srt.text()) if dialog.srt.text() else None
        activate = dialog.activate.isChecked()

        def work(task):
            return prepare_project(root, language, google_source, google_target, launcher, srt, task.progress.emit, task.cancel)

        def done(result):
            project, paths = result
            project.activate_language = activate
            if paths:
                answer = QMessageBox.question(self, "Incluir arquivos YAML?", f"Foram encontrados {len(paths)} arquivo(s) .yml/.yaml.\n"
                                             "Deseja incluir seus valores textuais na tradução?\n\n"
                                             "Também serão salvas cópias localizadas em game/tl/<idioma>/. Chaves e estrutura serão preservadas. "
                                             "Strings de configuração também podem aparecer; revise antes de traduzir.",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if answer == QMessageBox.StandardButton.Yes:
                    docs, entries, warnings = read_yaml(paths)
                    project.yaml_documents = docs
                    project.entries.extend(entries)
                    project.warnings.extend(warnings)
            self.install_project(project, Path(project.workspace) / "project.rpt.json")
            if project.warnings: QMessageBox.warning(self, "Importação com avisos", "\n".join(project.warnings))
        self.run_task(work, done)

    def install_project(self, project, path):
        self.autosave.stop()
        self.project, self.project_path = project, path
        self.current = None
        self.draft_dirty = False
        self.model.replace(project.entries)
        self.by_id = {e.id: i for i, e in enumerate(project.entries)}
        self.file_filter.blockSignals(True)
        self.file_filter.clear()
        self.file_filter.addItem("Todos os arquivos", "")
        for name in sorted({e.file for e in project.entries}): self.file_filter.addItem(name, name)
        self.file_filter.blockSignals(False)
        self.search.clear()
        self.state_filter.setCurrentIndex(0)
        self.filter_changed()
        self.game_title.setText(f"{Path(project.game_root).name}   /   {project.language}")
        self.game_path.setText(project.game_root)
        self.game_path.setToolTip(project.game_root)
        self.operation.setText(f"{len(project.entries)} strings importadas. Selecione uma linha para começar a revisão.")
        self.save_local()
        if self.proxy.rowCount(): self.table.setCurrentIndex(self.proxy.index(0, 1))
        else: self.clear_editor()
        self.update_summary()

    def open_project(self):
        if self.busy or not self.flush_draft(): return
        name, _ = QFileDialog.getOpenFileName(self, "Abrir projeto de revisão", "", "Projeto (*.rpt.json);;JSON (*.json)")
        if not name: return
        try:
            project = Project.load(Path(name))
            if not (Path(project.game_root) / "game").is_dir():
                root = QFileDialog.getExistingDirectory(self, "O jogo mudou de pasta. Selecione a nova pasta base")
                if not root: return
                if not (Path(root) / "game").is_dir(): raise RevisorError("A pasta selecionada não contém game.")
                project.game_root = root
            self.install_project(project, Path(name))
        except (OSError, RevisorError) as exc:
            self.task_failed(str(exc))

    def save_local(self):
        if self.project and self.project_path:
            try:
                self.project.save(self.project_path)
            except OSError as exc:
                self.statusBar().showMessage(f"Falha no salvamento local: {exc}")

    def save_project_as(self):
        if self.busy or not self.project or not self.flush_draft(): return
        name, _ = QFileDialog.getSaveFileName(self, "Salvar projeto portátil", f"{Path(self.project.game_root).name}.rpt.json", "Projeto (*.rpt.json)")
        if name:
            self.project_path = Path(name if name.endswith(".rpt.json") else name + ".rpt.json")
            self.save_local()
            self.statusBar().showMessage(f"Projeto salvo em {self.project_path}", 5000)

    def save_game(self):
        if self.busy or not self.project or not self.flush_draft(): return
        pending = sum(not e.target for e in self.project.entries)
        machine = sum(e.status == "machine" for e in self.project.entries)
        answer = QMessageBox.question(self, "Salvar tradução no jogo", f"Destino: {Path(self.project.game_root) / 'game' / 'tl' / self.project.language}\n\n"
                                     f"{pending} string(s) sem tradução usarão o original.\n{machine} sugestão(ões) automática(s) ainda não foram revisadas.\n"
                                     f"Ativar idioma ao iniciar: {'sim' if self.project.activate_language else 'não'}.\n\nSalvar agora?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes: return

        def done(result):
            folder, count, backup = result
            self.operation.setText(f"{count} arquivo(s) salvos em {folder}. Reinicie o jogo para carregar a tradução.")
            QMessageBox.information(self, "Tradução salva", f"{count} arquivo(s) salvos em:\n{folder}\n\n"
                                    + (f"Backup da versão anterior:\n{backup}\n\n" if backup else "")
                                    + ("Reinicie o jogo. O idioma será ativado ao iniciar." if self.project.activate_language else
                                       f"Selecione o idioma {self.project.language} no jogo (Language({self.project.language!r})).")
                                    + ("\n\nYAML: o jogo deve ler os arquivos pelo loader do Ren'Py após ativar o idioma; leitores próprios podem exigir adaptação." if self.project.yaml_documents else ""))
        self.operation.setText("Salvando a tradução no jogo…")
        self.run_task(lambda task: export_project(self.project), done, cancellable=False)

    def update_summary(self):
        entries = self.model.entries
        self.total_label.setText(str(len(entries)))
        self.reviewed_label.setText(str(sum(e.status == "reviewed" for e in entries)))
        self.checked_label.setText(str(len(self.model.checked)))
        self.visible_label.setText(f"{self.proxy.rowCount()} visíveis")
        active = self.project is not None and not self.busy
        self.save_button.setEnabled(active)
        self.select_button.setEnabled(active)
        self.clear_button.setEnabled(active)
        self.google_button.setEnabled(active and bool(self.model.checked))
        for w in (self.apply_button, self.review_button, self.copy_button, self.translation): w.setEnabled(active and self.current is not None)
        self.logs_button.setEnabled(self.project is not None)

    def filter_changed(self):
        self.proxy.query = self.search.text().casefold()
        self.proxy.status = self.state_filter.currentData() or ""
        self.proxy.file = self.file_filter.currentData() or ""
        self.proxy.refresh()
        self.update_summary()

    def clear_checks(self):
        self.model.checked.clear()
        if self.model.entries:
            self.model.dataChanged.emit(self.model.index(0, 0), self.model.index(len(self.model.entries) - 1, 0))
        self.update_summary()

    def select_visible(self):
        for row in range(self.proxy.rowCount()):
            index = self.proxy.mapToSource(self.proxy.index(row, 0))
            e = self.model.entries[index.row()]
            if not e.target and e.id not in self.model.checked and len(self.model.checked) < 50:
                self.model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)

    def clear_editor(self):
        self.loading_editor = True
        self.original.clear()
        self.translation.clear()
        self.context.setText("Selecione uma string para editar e revisar")
        self.loading_editor = False

    def change_current(self, index, previous):
        if self.loading_editor: return
        if not self.flush_draft():
            self.loading_editor = True
            self.table.setCurrentIndex(previous)
            self.loading_editor = False
            return
        if not index.isValid():
            self.current = None
            self.clear_editor()
            self.update_summary()
            return
        e = self.model.entries[self.proxy.mapToSource(index).row()]
        self.current = e
        self.loading_editor = True
        self.original.setPlainText(e.source)
        self.translation.setPlainText(e.target)
        self.context.setText(f"{e.file}" + (f" : {e.line}" if e.line else f"   /   YAML {e.yaml_path}") + f"   ·   {STATUS[e.status]}")
        self.context.setToolTip(e.block)
        self.loading_editor = False
        self.draft_dirty = False
        self.update_summary()

    def editor_changed(self):
        if not self.loading_editor and self.current:
            self.draft_dirty = True

    def flush_draft(self):
        if self.current and self.draft_dirty:
            return self.apply_current()
        return True

    def apply_current(self, reviewed=False):
        if not self.current: return True
        entry = self.current
        try:
            entry.update(self.translation.toPlainText(), reviewed=reviewed)
        except RevisorError as exc:
            QMessageBox.warning(self, "Verifique os marcadores", str(exc))
            return False
        self.draft_dirty = False
        self.model.changed(self.by_id[entry.id])
        if self.current is entry:
            self.context.setText(f"{entry.file}" + (f" : {entry.line}" if entry.line else f"   /   YAML {entry.yaml_path}") + f"   ·   {STATUS[entry.status]}")
        self.autosave.start(300)
        self.update_summary()
        self.statusBar().showMessage("Revisão aplicada." if reviewed else "Tradução aplicada ao projeto.", 3000)
        return True

    def review_next(self):
        if not self.current: return
        if not self.translation.toPlainText():
            QMessageBox.warning(self, "Tradução vazia", "Digite a tradução ou copie o original para revisar esta string.")
            return
        old_row = self.table.currentIndex().row()
        if self.apply_current(reviewed=True) and self.proxy.rowCount():
            # A pending/machine filter may remove the current row after review.
            row = old_row if self.proxy.status and self.proxy.status != "reviewed" else old_row + 1
            self.table.setCurrentIndex(self.proxy.index(min(row, self.proxy.rowCount() - 1), 1))

    def copy_original(self):
        if self.current: self.translation.setPlainText(self.current.source)

    def google_batch(self):
        if self.busy or not self.project or not self.flush_draft(): return
        entries = [e for e in self.project.entries if e.id in self.model.checked]
        if not 1 <= len(entries) <= 50: return
        message = f"Enviar {len(entries)} string(s) ao Google Tradutor, uma por vez?\n\n"
        message += "As strings marcadas serão enviadas ao serviço do Google pela internet. As sugestões ficarão como Automáticas até você revisá-las."
        if any(e.target for e in entries): message += "\n\nA tradução atual das strings marcadas será substituída."
        if QMessageBox.question(self, "Tradução automática", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        source, target = self.project.google_source, self.project.google_target

        def work(task):
            return translate_batch(entries, GoogleTranslator(source, target), task.translation.emit, task.progress.emit, task.cancel)

        def done(count):
            self.operation.setText(f"{count} string(s) traduzidas. Revise as sugestões antes de salvar no jogo.")
        self.run_task(work, done, translation=True)

    def machine_result(self, entry_id, target, error):
        row = self.by_id[entry_id]
        e = self.model.entries[row]
        if error:
            e.error = error
        else:
            e.update(target, machine=True)
            self.model.checked.discard(entry_id)
        self.model.changed(row)
        if self.current is e:
            self.loading_editor = True
            self.translation.setPlainText(e.target)
            self.loading_editor = False
            self.draft_dirty = False
        self.update_summary()
        self.autosave.start(300)

    def open_workspace(self):
        if self.project:
            folder = Path(self.project.workspace) if self.project.workspace and Path(self.project.workspace).is_dir() else self.project_path.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, event):
        if self.busy:
            self.statusBar().showMessage("Aguarde a operação terminar ou clique em Cancelar antes de fechar.", 6000)
            event.ignore()
            return
        if not self.flush_draft():
            event.ignore()
            return
        self.autosave.stop()
        self.save_local()
        event.accept()
