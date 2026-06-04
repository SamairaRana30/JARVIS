"""ui/components/notes_panel.py — Notes browser with folder tree and preview."""

import json
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSplitter, QTextEdit, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _load_cfg():
    import yaml
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


class NotesPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path: Path | None = None
        self._setup_ui()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=30_000).start()
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().notes_updated.connect(self._refresh)
        except Exception:
            pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("📝  Notes")
        title.setObjectName("panel_title")
        header.addWidget(title)
        header.addStretch()
        new_btn = QPushButton("＋ New Note")
        new_btn.setObjectName("accent_btn")
        new_btn.clicked.connect(self._new_note)
        header.addWidget(new_btn)
        layout.addLayout(header)
        layout.addSpacing(8)

        # Search bar
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search notes...")
        self._search.textChanged.connect(self._filter_tree)
        layout.addWidget(self._search)
        layout.addSpacing(8)

        # Splitter: tree left, preview right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Folder tree
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemClicked.connect(self._on_item_clicked)
        splitter.addWidget(self._tree)

        # Preview pane
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)

        self._preview_title = QLabel("Select a note to preview")
        self._preview_title.setObjectName("panel_title")
        self._preview_title.setFont(QFont("Segoe UI", 14))
        rl.addWidget(self._preview_title)

        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setStyleSheet(
            "background:#1A1A1A;border:1px solid #2A2A2A;border-radius:8px;padding:12px;"
        )
        rl.addWidget(self._preview, 1)

        btn_row = QHBoxLayout()
        edit_btn = QPushButton("✏️  Edit in VS Code")
        edit_btn.clicked.connect(self._open_in_editor)
        btn_row.addWidget(edit_btn)
        btn_row.addStretch()
        rl.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setSizes([220, 580])
        layout.addWidget(splitter, 1)

    @pyqtSlot()
    def _refresh(self):
        self._tree.clear()
        try:
            cfg        = _load_cfg()
            index_path = ROOT / cfg["paths"]["notes_index"]
            index      = json.loads(index_path.read_text())
        except Exception:
            return

        folders: dict[str, list] = {}
        for note in index:
            folder = note.get("folder", "quick")
            folders.setdefault(folder, []).append(note)

        FOLDER_ICONS = {
            "quick": "📌", "study": "📚", "projects": "💼",
            "ideas": "💡", "meetings": "🤝", "personal": "🔒"
        }
        for folder, notes in sorted(folders.items()):
            icon = FOLDER_ICONS.get(folder, "📁")
            parent = QTreeWidgetItem(self._tree, [f"{icon} {folder.title()} ({len(notes)})"])
            parent.setData(0, Qt.ItemDataRole.UserRole, None)
            for note in sorted(notes, key=lambda n: n.get("created", ""), reverse=True):
                child = QTreeWidgetItem(parent, [f"  {note['title'][:45]}"])
                child.setData(0, Qt.ItemDataRole.UserRole, note)
                child.setToolTip(0, note.get("preview", ""))
            parent.setExpanded(True)

    def _filter_tree(self, query: str):
        q = query.lower()
        for i in range(self._tree.topLevelItemCount()):
            parent = self._tree.topLevelItem(i)
            visible_children = 0
            for j in range(parent.childCount()):
                child = parent.child(j)
                note = child.data(0, Qt.ItemDataRole.UserRole)
                match = (not q or q in child.text(0).lower() or
                         (note and q in note.get("preview", "").lower()))
                child.setHidden(not match)
                if match:
                    visible_children += 1
            parent.setHidden(visible_children == 0 and bool(q))

    def _on_item_clicked(self, item, col):
        note = item.data(0, Qt.ItemDataRole.UserRole)
        if not note:
            return
        self._current_path = ROOT / note["path"]
        self._preview_title.setText(note.get("title", "Note"))
        try:
            text = self._current_path.read_text(encoding="utf-8")
            if text.startswith("---"):
                text = text.split("---", 2)[-1].strip()
            self._preview.setPlainText(text[:2000])
        except Exception:
            self._preview.setPlainText("Could not load note content.")

    def _new_note(self):
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "New Note", "Note text:")
        if ok and text:
            try:
                import tools
                tools.save_note(text, folder="quick")
                self._refresh()
            except Exception as e:
                print(f"New note error: {e}")

    def _open_in_editor(self):
        if not self._current_path:
            return
        try:
            import subprocess
            import tools
            exe = tools._resolve_app_map("vscode") or "notepad"
            subprocess.Popen([exe, str(self._current_path)])
        except Exception as e:
            print(f"Open editor error: {e}")
