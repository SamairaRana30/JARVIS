"""ui/components/sidebar.py — Collapsible left navigation."""

import qtawesome as qta
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QPushButton, QScrollArea, QSizePolicy,
    QSpacerItem, QVBoxLayout, QWidget
)

NAV_ITEMS = [
    ("home",     "fa6s.house",        "Home"),
    ("chat",     "fa6s.comment",      "Chat"),
    ("tasks",    "fa6s.check",        "Tasks"),
    ("notes",    "fa6s.note-sticky",  "Notes"),
    ("fridge",   "fa6s.ice-cream",    "Fridge"),
    ("wellbeing","fa6s.heart",        "Health"),
    ("stylist",  "fa6s.shirt",        "Stylist"),
    ("budget",   "fa6s.wallet",       "Budget"),
    ("sites",    "fa6s.globe",        "Sites"),
    ("schedule", "fa6s.calendar",     "Schedule"),
    ("settings", "fa6s.gear",         "Settings"),
]

ACCENT   = "#6C63FF"
SIDEBAR_W = 200
ICON_W    = 60


class SidebarButton(QPushButton):
    def __init__(self, key: str, icon_name: str, label: str, collapsed: bool = False):
        super().__init__()
        self.key = key
        self._icon_name = icon_name
        self._label = label
        self._collapsed = collapsed
        self.setObjectName("nav_btn")
        self.setCheckable(True)
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._render()

    def _render(self):
        try:
            icon = qta.icon(self._icon_name, color="#888888")
            self.setIcon(icon)
        except Exception:
            pass
        self.setText("" if self._collapsed else f"  {self._label}")

    def set_active(self, active: bool):
        self.setChecked(active)
        color = ACCENT if active else "#888888"
        try:
            icon = qta.icon(self._icon_name, color=color)
            self.setIcon(icon)
        except Exception:
            pass
        if active:
            self.setStyleSheet(
                "QPushButton#nav_btn {"
                f"background:#1E1A3A; color:{ACCENT}; "
                "border-left:3px solid " + ACCENT + "; border-radius:8px; "
                "padding:10px 16px; text-align:left;}"
            )
        else:
            self.setStyleSheet("")

    def collapse(self, collapsed: bool):
        self._collapsed = collapsed
        self.setText("" if collapsed else f"  {self._label}")
        self.setFixedWidth(ICON_W if collapsed else SIDEBAR_W)


class SidebarWidget(QWidget):
    """Collapsible left navigation sidebar."""

    page_changed = pyqtSignal(str)   # emits nav key when clicked

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._collapsed = False
        self._active_key = "home"
        self._buttons: dict[str, SidebarButton] = {}
        self._setup_ui()
        self.setFixedWidth(SIDEBAR_W)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(2)

        # Collapse toggle
        self._toggle_btn = QPushButton("◀")
        self._toggle_btn.setFixedHeight(32)
        self._toggle_btn.setObjectName("nav_btn")
        self._toggle_btn.clicked.connect(self._toggle_collapse)
        layout.addWidget(self._toggle_btn)
        layout.addSpacing(8)

        # Nav buttons
        for key, icon_name, label in NAV_ITEMS:
            btn = SidebarButton(key, icon_name, label)
            btn.clicked.connect(lambda checked, k=key: self._select(k))
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum,
                                         QSizePolicy.Policy.Expanding))

        self._select("home")

    def _select(self, key: str):
        self._active_key = key
        for k, btn in self._buttons.items():
            btn.set_active(k == key)
        self.page_changed.emit(key)

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        w = ICON_W if self._collapsed else SIDEBAR_W
        self.setFixedWidth(w)
        self._toggle_btn.setText("▶" if self._collapsed else "◀")
        for btn in self._buttons.values():
            btn.collapse(self._collapsed)

    def select(self, key: str):
        """Programmatically select a panel."""
        self._select(key)
