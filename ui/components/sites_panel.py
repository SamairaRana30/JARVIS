"""ui/components/sites_panel.py — Blocked + study sites manager."""

import json
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton,
    QSplitter, QVBoxLayout, QWidget
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _load_cfg():
    import yaml
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


class SitesPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._study_mode_active = False
        self._setup_ui()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=30_000).start()
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().sites_updated.connect(self._refresh)
        except Exception:
            pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("🌐  Sites")
        title.setObjectName("panel_title")
        header.addWidget(title)
        layout.addLayout(header)
        layout.addSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: blocked sites
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        sec1 = QLabel("🚫 BLOCKED SITES")
        sec1.setObjectName("section_title")
        ll.addWidget(sec1)
        self._blocked_list = QListWidget()
        ll.addWidget(self._blocked_list, 1)
        block_input_row = QHBoxLayout()
        self._block_input = QLineEdit()
        self._block_input.setPlaceholderText("site.com")
        self._block_input.returnPressed.connect(self._add_blocked)
        block_input_row.addWidget(self._block_input, 1)
        add_block_btn = QPushButton("＋")
        add_block_btn.setFixedWidth(36)
        add_block_btn.clicked.connect(self._add_blocked)
        block_input_row.addWidget(add_block_btn)
        ll.addLayout(block_input_row)

        rem_block_btn = QPushButton("Remove Selected")
        rem_block_btn.clicked.connect(self._remove_blocked)
        ll.addWidget(rem_block_btn)
        splitter.addWidget(left)

        # Right: study + quick links
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        sec2 = QLabel("📚 STUDY SITES")
        sec2.setObjectName("section_title")
        rl.addWidget(sec2)
        self._study_list = QListWidget()
        rl.addWidget(self._study_list, 1)
        study_input_row = QHBoxLayout()
        self._study_input = QLineEdit()
        self._study_input.setPlaceholderText("site.com")
        self._study_input.returnPressed.connect(self._add_study)
        study_input_row.addWidget(self._study_input, 1)
        add_study_btn = QPushButton("＋")
        add_study_btn.setFixedWidth(36)
        add_study_btn.clicked.connect(self._add_study)
        study_input_row.addWidget(add_study_btn)
        rl.addLayout(study_input_row)

        rem_study_btn = QPushButton("Remove Selected")
        rem_study_btn.clicked.connect(self._remove_study)
        rl.addWidget(rem_study_btn)
        splitter.addWidget(right)

        splitter.setSizes([350, 350])
        layout.addWidget(splitter, 1)

        # Study mode button
        self._study_mode_btn = QPushButton("🔴  Start Study Mode")
        self._study_mode_btn.setObjectName("accent_btn")
        self._study_mode_btn.setFixedHeight(44)
        self._study_mode_btn.clicked.connect(self._toggle_study_mode)
        layout.addSpacing(8)
        layout.addWidget(self._study_mode_btn)

        desc = QLabel("Blocks distracting sites · Opens study apps · Starts Pomodoro · Plays focus music")
        desc.setObjectName("muted")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

    def _read_sites(self):
        cfg = _load_cfg()
        return json.loads((ROOT / cfg["paths"]["sites"]).read_text())

    @pyqtSlot()
    def _refresh(self):
        try:
            sites = self._read_sites()
        except Exception:
            return
        self._blocked_list.clear()
        for s in sites.get("distracting", []):
            self._blocked_list.addItem(s)
        self._study_list.clear()
        for s in sites.get("study", []):
            self._study_list.addItem(s)

    def _add_blocked(self):
        site = self._block_input.text().strip()
        if not site: return
        self._block_input.clear()
        try:
            import tools; tools.sites_add(site, "distracting")
            self._refresh()
        except Exception as e:
            print(e)

    def _remove_blocked(self):
        item = self._blocked_list.currentItem()
        if not item: return
        try:
            import tools; tools.sites_remove(item.text(), "distracting")
            self._refresh()
        except Exception as e:
            print(e)

    def _add_study(self):
        site = self._study_input.text().strip()
        if not site: return
        self._study_input.clear()
        try:
            import tools; tools.sites_add(site, "study")
            self._refresh()
        except Exception as e:
            print(e)

    def _remove_study(self):
        item = self._study_list.currentItem()
        if not item: return
        try:
            import tools; tools.sites_remove(item.text(), "study")
            self._refresh()
        except Exception as e:
            print(e)

    def _toggle_study_mode(self):
        self._study_mode_active = not self._study_mode_active
        if self._study_mode_active:
            self._study_mode_btn.setText("🟢  End Study Mode")
            self._study_mode_btn.setStyleSheet(
                "background:#1A2A1A;border:1px solid #4CAF50;color:#4CAF50;"
                "border-radius:8px;font-weight:bold;"
            )
        else:
            self._study_mode_btn.setText("🔴  Start Study Mode")
            self._study_mode_btn.setStyleSheet("")
            self._study_mode_btn.setObjectName("accent_btn")
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().user_typed.emit(
                "end study mode" if not self._study_mode_active else "yes, confirm"
            )
        except Exception:
            pass
