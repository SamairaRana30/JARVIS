"""ui/components/tasks_panel.py — Tasks + Goals with tab switcher."""

import json
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton,
    QTabWidget, QVBoxLayout, QWidget, QProgressBar,
    QDateTimeEdit, QDialog, QDialogButtonBox, QFormLayout
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _load_cfg():
    import yaml
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


PRIORITY_COLORS = {"high": "#F44336", "medium": "#FF9800", "low": "#4CAF50"}
PRIORITY_DOTS   = {"high": "🔴", "medium": "🟡", "low": "🟢"}


class AddTaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Task")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Task title")
        self.priority_box = QComboBox()
        self.priority_box.addItems(["medium", "high", "low"])
        self.deadline_edit = QLineEdit()
        self.deadline_edit.setPlaceholderText("e.g. 2025-06-10T23:59 (optional)")
        layout.addRow("Title:", self.title_edit)
        layout.addRow("Priority:", self.priority_box)
        layout.addRow("Deadline:", self.deadline_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)


class TaskItem(QFrame):
    def __init__(self, task: dict, on_done, on_delete):
        super().__init__()
        self.task = task
        self.setObjectName("card")
        self.setStyleSheet(
            "QFrame#card{background:#1A1A1A;border:1px solid #2A2A2A;"
            "border-radius:8px;margin:2px 0;padding:8px;}"
            "QFrame#card:hover{border-color:#3A3A3A;}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        # Priority dot
        p = task.get("priority", "medium")
        dot = QLabel(PRIORITY_DOTS.get(p, "🟡"))
        dot.setFixedWidth(24)
        layout.addWidget(dot)

        # Title + deadline
        info = QVBoxLayout()
        info.setSpacing(0)
        title_lbl = QLabel(task.get("title", ""))
        title_lbl.setFont(QFont("Segoe UI", 13))
        if task.get("done"):
            title_lbl.setStyleSheet("text-decoration:line-through;color:#444444;")
        info.addWidget(title_lbl)

        dl = task.get("deadline", "")
        if dl:
            try:
                dt = datetime.fromisoformat(dl)
                diff = dt - datetime.now()
                hours = diff.total_seconds() / 3600
                if hours < 0:
                    dl_str = "⚠️ Overdue"
                    color = "#F44336"
                elif hours < 2:
                    dl_str = f"Due in {int(diff.total_seconds() / 60)} min"
                    color = "#FF9800"
                elif hours < 24:
                    dl_str = f"Due in {int(hours)}h"
                    color = "#FF9800"
                else:
                    dl_str = dt.strftime("Due %d %b")
                    color = "#888888"
            except Exception:
                dl_str = dl[:10]
                color = "#888888"
            dl_lbl = QLabel(dl_str)
            dl_lbl.setStyleSheet(f"color:{color};font-size:11px;")
            info.addWidget(dl_lbl)

        layout.addLayout(info, 1)

        # Buttons
        done_btn = QPushButton("✓")
        done_btn.setFixedSize(32, 32)
        done_btn.setObjectName("success_btn")
        done_btn.clicked.connect(lambda: on_done(task["id"]))
        layout.addWidget(done_btn)

        del_btn = QPushButton("🗑")
        del_btn.setFixedSize(32, 32)
        del_btn.setObjectName("danger_btn")
        del_btn.clicked.connect(lambda: on_delete(task["id"]))
        layout.addWidget(del_btn)


class TasksPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._refresh()
        # Auto-refresh every 60s
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(60_000)
        # Signal-based refresh
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().tasks_updated.connect(self._refresh)
        except Exception:
            pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        # Title + add button
        header = QHBoxLayout()
        title = QLabel("✅  Tasks & Goals")
        title.setObjectName("panel_title")
        header.addWidget(title)
        header.addStretch()
        add_btn = QPushButton("＋ Add Task")
        add_btn.setObjectName("accent_btn")
        add_btn.clicked.connect(self._add_task)
        header.addWidget(add_btn)
        layout.addLayout(header)
        layout.addSpacing(12)

        # Tabs
        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        self._tasks_tab = QWidget()
        tt_lay = QVBoxLayout(self._tasks_tab)
        tt_lay.setContentsMargins(0, 8, 0, 0)

        # Filter row
        filter_row = QHBoxLayout()
        self._filter_box = QComboBox()
        self._filter_box.addItems(["All", "Today", "High priority", "Overdue"])
        self._filter_box.currentTextChanged.connect(self._refresh)
        filter_row.addWidget(QLabel("Filter:"))
        filter_row.addWidget(self._filter_box)
        filter_row.addStretch()
        tt_lay.addLayout(filter_row)

        self._task_list = QVBoxLayout()
        self._task_list.setSpacing(4)
        tt_lay.addLayout(self._task_list)
        tt_lay.addStretch()

        tabs.addTab(self._tasks_tab, "Tasks")

        # Goals tab
        self._goals_tab = QWidget()
        gl_lay = QVBoxLayout(self._goals_tab)
        gl_lay.setContentsMargins(0, 8, 0, 0)
        self._goals_list = QVBoxLayout()
        self._goals_list.setSpacing(8)
        gl_lay.addLayout(self._goals_list)
        gl_lay.addStretch()
        tabs.addTab(self._goals_tab, "Goals")

        layout.addWidget(tabs, 1)

    @pyqtSlot()
    def _refresh(self):
        self._refresh_tasks()
        self._refresh_goals()

    def _refresh_tasks(self):
        # Clear
        while self._task_list.count():
            item = self._task_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        try:
            cfg = _load_cfg()
            tasks_path = ROOT / cfg["paths"]["tasks"]
            tasks = json.loads(tasks_path.read_text())
        except Exception:
            return

        filt = self._filter_box.currentText()
        today = datetime.now().date().isoformat()
        now = datetime.now()

        pending = [t for t in tasks if not t.get("done")]
        pending.sort(key=lambda t: (
            {"high": 0, "medium": 1, "low": 2}.get(t.get("priority"), 1),
            t.get("deadline", "9999")
        ))

        if filt == "Today":
            pending = [t for t in pending if t.get("deadline", "")[:10] == today]
        elif filt == "High priority":
            pending = [t for t in pending if t.get("priority") == "high"]
        elif filt == "Overdue":
            pending = [t for t in pending if t.get("deadline") and
                       datetime.fromisoformat(t["deadline"]) < now]

        if not pending:
            lbl = QLabel("No tasks matching filter. 🎉")
            lbl.setObjectName("muted")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._task_list.addWidget(lbl)
            return

        for task in pending[:20]:
            item = TaskItem(task, self._mark_done, self._delete_task)
            self._task_list.addWidget(item)

    def _refresh_goals(self):
        while self._goals_list.count():
            item = self._goals_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        try:
            cfg = _load_cfg()
            goals_path = ROOT / cfg["paths"]["goals"]
            goals_data = json.loads(goals_path.read_text())
        except Exception:
            return

        for cat_key, cat_label in [("long_term", "LONG TERM"), ("short_term", "SHORT TERM")]:
            goals = goals_data.get(cat_key, [])
            if not goals:
                continue
            sec_lbl = QLabel(cat_label)
            sec_lbl.setObjectName("section_title")
            self._goals_list.addWidget(sec_lbl)
            for g in goals:
                card = QFrame()
                card.setObjectName("card")
                card.setStyleSheet(
                    "QFrame#card{background:#1A1A1A;border:1px solid #2A2A2A;"
                    "border-radius:8px;padding:12px;}"
                )
                cl = QVBoxLayout(card)
                cl.setSpacing(4)
                name_row = QHBoxLayout()
                name_row.addWidget(QLabel(g.get("goal", "")))
                name_row.addStretch()
                pct = g.get("progress", 0)
                pct_lbl = QLabel(f"{pct}%")
                pct_lbl.setObjectName("accent")
                name_row.addWidget(pct_lbl)
                cl.addLayout(name_row)
                bar = QProgressBar()
                bar.setMaximum(100)
                bar.setValue(pct)
                bar.setFixedHeight(6)
                cl.addWidget(bar)
                if g.get("deadline"):
                    dl_lbl = QLabel(f"Due: {g['deadline']}")
                    dl_lbl.setObjectName("muted")
                    cl.addWidget(dl_lbl)
                self._goals_list.addWidget(card)

    def _add_task(self):
        dlg = AddTaskDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        title    = dlg.title_edit.text().strip()
        priority = dlg.priority_box.currentText()
        deadline = dlg.deadline_edit.text().strip() or None
        if not title:
            return
        try:
            sys.path.insert(0, str(ROOT))
            import tools
            tools.add_task(title, deadline, priority=priority)
        except Exception as e:
            print(f"Add task error: {e}")
        self._refresh()

    def _mark_done(self, task_id: str):
        try:
            cfg = _load_cfg()
            tasks_path = ROOT / cfg["paths"]["tasks"]
            tasks = json.loads(tasks_path.read_text())
            for t in tasks:
                if t["id"] == task_id:
                    t["done"] = True
            tasks_path.write_text(json.dumps(tasks, indent=2))
        except Exception as e:
            print(f"Mark done error: {e}")
        self._refresh()

    def _delete_task(self, task_id: str):
        try:
            cfg = _load_cfg()
            tasks_path = ROOT / cfg["paths"]["tasks"]
            tasks = json.loads(tasks_path.read_text())
            tasks = [t for t in tasks if t["id"] != task_id]
            tasks_path.write_text(json.dumps(tasks, indent=2))
        except Exception as e:
            print(f"Delete task error: {e}")
        self._refresh()
