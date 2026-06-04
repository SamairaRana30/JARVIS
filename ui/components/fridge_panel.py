"""ui/components/fridge_panel.py — Fridge items + grocery list."""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSplitter, QVBoxLayout, QWidget
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _load_cfg():
    import yaml
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def _expiry_color(expires_str: str | None) -> str:
    if not expires_str:
        return "#888888"
    try:
        exp = date.fromisoformat(expires_str)
        days = (exp - date.today()).days
        if days <= 0:  return "#F44336"
        if days <= 2:  return "#F44336"
        if days <= 4:  return "#FF9800"
        return "#4CAF50"
    except Exception:
        return "#888888"


def _expiry_dot(expires_str: str | None) -> str:
    color = _expiry_color(expires_str)
    if color == "#F44336": return "🔴"
    if color == "#FF9800": return "🟡"
    return "🟢" if expires_str else "⚪"


class FridgePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=60_000).start()
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().fridge_updated.connect(self._refresh)
        except Exception:
            pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("🧊  Fridge")
        title.setObjectName("panel_title")
        header.addWidget(title)
        header.addStretch()
        add_btn = QPushButton("＋ Add Item")
        add_btn.setObjectName("accent_btn")
        add_btn.clicked.connect(self._add_item)
        header.addWidget(add_btn)
        layout.addLayout(header)
        layout.addSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: fridge items
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        sec1 = QLabel("FRIDGE CONTENTS")
        sec1.setObjectName("section_title")
        ll.addWidget(sec1)
        self._items_layout = QVBoxLayout()
        self._items_layout.setSpacing(4)
        ll.addLayout(self._items_layout)
        ll.addStretch()
        splitter.addWidget(left)

        # Right: grocery list
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        sec2 = QLabel("GROCERY LIST")
        sec2.setObjectName("section_title")
        rl.addWidget(sec2)
        self._grocery_layout = QVBoxLayout()
        self._grocery_layout.setSpacing(4)
        rl.addLayout(self._grocery_layout)
        rl.addStretch()
        add_gro_row = QHBoxLayout()
        self._grocery_input = QLineEdit()
        self._grocery_input.setPlaceholderText("Add item...")
        self._grocery_input.returnPressed.connect(self._add_grocery)
        add_gro_row.addWidget(self._grocery_input, 1)
        add_g_btn = QPushButton("＋")
        add_g_btn.setFixedWidth(36)
        add_g_btn.clicked.connect(self._add_grocery)
        add_gro_row.addWidget(add_g_btn)
        rl.addLayout(add_gro_row)
        splitter.addWidget(right)

        splitter.setSizes([400, 300])
        layout.addWidget(splitter, 1)

        # Recipe suggestion
        recipe_frame = QFrame()
        recipe_frame.setObjectName("card")
        recipe_frame.setStyleSheet(
            "QFrame#card{background:#1A1A3A;border:1px solid #6C63FF;"
            "border-radius:8px;padding:12px;margin-top:8px;}"
        )
        rl2 = QVBoxLayout(recipe_frame)
        rl2.addWidget(QLabel("🍳  Recipe Suggestion"))
        self._recipe_lbl = QLabel("Loading...")
        self._recipe_lbl.setObjectName("secondary")
        self._recipe_lbl.setWordWrap(True)
        rl2.addWidget(self._recipe_lbl)
        layout.addWidget(recipe_frame)

    def _read_fridge(self):
        cfg = _load_cfg()
        p = ROOT / cfg["paths"]["fridge"]
        return json.loads(p.read_text())

    def _write_fridge(self, data):
        cfg = _load_cfg()
        p = ROOT / cfg["paths"]["fridge"]
        import shutil
        if p.exists():
            shutil.copy(p, p.with_suffix(".bak"))
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    @pyqtSlot()
    def _refresh(self):
        try:
            fridge = self._read_fridge()
        except Exception:
            return
        self._refresh_items(fridge.get("items", []))
        self._refresh_grocery(fridge.get("grocery_list", []))
        self._refresh_recipe(fridge)

    def _refresh_items(self, items):
        while self._items_layout.count():
            item = self._items_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        today = date.today()
        items_sorted = sorted(
            items,
            key=lambda i: i.get("expires", "9999") or "9999"
        )
        for item in items_sorted:
            row = QFrame()
            row.setStyleSheet(
                "QFrame{background:#1A1A1A;border:1px solid #2A2A2A;"
                "border-radius:6px;padding:6px 8px;}"
                "QFrame:hover{border-color:#3A3A3A;}"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 2, 4, 2)

            dot = QLabel(_expiry_dot(item.get("expires")))
            rl.addWidget(dot)

            name_col = QVBoxLayout()
            name_col.setSpacing(0)
            name_lbl = QLabel(item["name"])
            name_lbl.setFont(__import__("PyQt6.QtGui", fromlist=["QFont"]).QFont("Segoe UI", 12))
            name_col.addWidget(name_lbl)

            exp = item.get("expires")
            if exp:
                try:
                    days = (date.fromisoformat(exp) - today).days
                    if days < 0:
                        exp_str = "Expired!"
                    elif days == 0:
                        exp_str = "Expires today!"
                    elif days == 1:
                        exp_str = "Expires tomorrow"
                    else:
                        exp_str = f"Expires in {days} days"
                    exp_lbl = QLabel(exp_str)
                    exp_lbl.setStyleSheet(f"color:{_expiry_color(exp)};font-size:11px;")
                    name_col.addWidget(exp_lbl)
                except Exception:
                    pass

            rl.addLayout(name_col, 1)
            qty = item.get("quantity", "")
            if qty:
                rl.addWidget(QLabel(str(qty)))

            del_btn = QPushButton("🗑")
            del_btn.setFixedSize(28, 28)
            del_btn.clicked.connect(lambda _, n=item["name"]: self._remove_item(n))
            rl.addWidget(del_btn)
            self._items_layout.addWidget(row)

    def _refresh_grocery(self, grocery_list):
        while self._grocery_layout.count():
            item = self._grocery_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        for item in grocery_list:
            row = QHBoxLayout()
            lbl = QLabel(f"• {item}")
            row.addWidget(lbl, 1)
            del_btn = QPushButton("✕")
            del_btn.setFixedSize(24, 24)
            del_btn.setStyleSheet("color:#888888;background:transparent;border:none;")
            del_btn.clicked.connect(lambda _, i=item: self._remove_grocery(i))
            row.addWidget(del_btn)
            w = QWidget()
            w.setLayout(row)
            self._grocery_layout.addWidget(w)

    def _refresh_recipe(self, fridge):
        items = fridge.get("items", [])
        perishable = sorted(
            [i for i in items if i.get("expires")],
            key=lambda i: i["expires"]
        )
        if perishable:
            names = ", ".join(i["name"] for i in perishable[:3])
            self._recipe_lbl.setText(f"Try using: {names}")
        else:
            self._recipe_lbl.setText("Add items to get recipe suggestions.")

    def _add_item(self):
        from PyQt6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Fridge Item")
        dlg.setMinimumWidth(320)
        fl = QFormLayout(dlg)
        name_edit = QLineEdit()
        qty_edit  = QLineEdit()
        exp_edit  = QLineEdit()
        exp_edit.setPlaceholderText("YYYY-MM-DD or leave blank")
        fl.addRow("Item:", name_edit)
        fl.addRow("Quantity:", qty_edit)
        fl.addRow("Expires:", exp_edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = name_edit.text().strip()
        if not name:
            return
        try:
            import tools
            tools.fridge_add(name, qty_edit.text().strip() or "1", exp_edit.text().strip() or None)
            self._refresh()
        except Exception as e:
            print(f"Add item error: {e}")

    def _remove_item(self, name: str):
        try:
            import tools
            tools.fridge_remove(name)
            self._refresh()
        except Exception as e:
            print(f"Remove item error: {e}")

    def _add_grocery(self):
        item = self._grocery_input.text().strip()
        if not item:
            return
        self._grocery_input.clear()
        try:
            import tools
            tools.grocery_add(item)
            self._refresh()
        except Exception as e:
            print(f"Add grocery error: {e}")

    def _remove_grocery(self, item: str):
        try:
            import tools
            tools.grocery_remove_item(item)
            self._refresh()
        except Exception as e:
            print(f"Remove grocery error: {e}")
