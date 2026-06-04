"""
ui/components/category_bar.py -- Animated category button bar.

Fixed at bottom of HUD. Each button:
- Glowing icon + label
- Flashes when AI auto-activates its panel
- Pulses while panel is open
- Click to toggle panel
"""

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPainter, QPen
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel,
                              QPushButton, QScrollArea, QWidget)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))

PURPLE = "#8B2BE2"
PINK   = "#E91E8C"
TEAL   = "#00FFB3"
DIM    = "#2A1450"

CATEGORIES = [
    ("tasks",     "[!]",  "OBJECTIVES"),
    ("goals",     "[>>]", "MISSIONS"),
    ("schedule",  "[=]",  "SCHEDULE"),
    ("weather",   "[~]",  "ATMOS"),
    ("fridge",    "[*]",  "SUPPLY"),
    ("budget",    "[$]",  "BUDGET"),
    ("stylist",   "[v]",  "ATTIRE"),
    ("wellbeing", "[+]",  "STATUS"),
    ("notes",     "[?]",  "INTEL"),
    ("sites",     "[X]",  "NETWORK"),
    ("news",      "[>>]", "INTEL FEED"),
    ("chat",      "[:]",  "COMM"),
    ("settings",  "[S]",  "CONFIG"),
]


class CategoryButton(QPushButton):
    """Single glowing category button with flash animation."""

    def __init__(self, category: str, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.category = category
        self._icon    = icon
        self._label   = label
        self._active  = False
        self._flash_count = 0
        self._flash_state = False

        self.setFixedSize(80, 52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._do_flash)

    def _apply_style(self):
        if self._active:
            border = PURPLE
            bg     = "rgba(139,43,226,0.2)"
            color  = "#C77DFF"
        else:
            border = "rgba(42,20,80,0.6)"
            bg     = "rgba(13,11,30,0.4)"
            color  = "#3D1F6B"
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                border: 1px solid {border};
                color: {color};
                font-family: 'Share Tech Mono', monospace;
                font-size: 10px;
                letter-spacing: 1px;
                text-align: center;
                padding: 2px;
            }}
            QPushButton:hover {{
                border-color: {PURPLE};
                background: rgba(139,43,226,0.15);
                color: #C77DFF;
            }}
        """)
        self.setText(f"{self._icon}\n{self._label}")

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_style()

    def flash(self, times: int = 3) -> None:
        """Flash cyan to signal AI activated this panel."""
        self._flash_count = times * 2
        self._flash_state = False
        if not self._flash_timer.isActive():
            self._flash_timer.start(150)

    def _do_flash(self):
        self._flash_state = not self._flash_state
        self._flash_count -= 1
        if self._flash_count <= 0:
            self._flash_timer.stop()
            self._flash_state = False
            self._apply_style()
            return
        if self._flash_state:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(233,30,140,0.25);
                    border: 1px solid {PINK};
                    color: {PINK};
                    font-family: 'Share Tech Mono', monospace;
                    font-size: 10px;
                    letter-spacing: 1px;
                    text-align: center;
                    padding: 2px;
                }}
            """)
        else:
            self._apply_style()


class CategoryBar(QWidget):
    """
    Horizontal bar of category buttons.
    Emits panel_requested(category) when a button is clicked
    or when AI auto-opens a panel.
    """

    panel_requested = pyqtSignal(str, bool)  # (category, auto_opened)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("category_bar")
        self.setFixedHeight(60)
        self.setStyleSheet(
            "background:#050510;border-top:1px solid rgba(139,43,226,0.25);"
        )
        self._buttons: dict[str, CategoryButton] = {}
        self._active_panels: set[str] = set()
        self._setup_ui()

    def _setup_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        row = QHBoxLayout(inner)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(4)

        for cat, icon, label in CATEGORIES:
            btn = CategoryButton(cat, icon, label)
            btn.clicked.connect(lambda checked, c=cat: self._on_click(c))
            self._buttons[cat] = btn
            row.addWidget(btn)

        row.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _on_click(self, category: str) -> None:
        if category in self._active_panels:
            self._active_panels.discard(category)
            self._buttons[category].set_active(False)
            self.panel_requested.emit(category + ":close", False)
        else:
            self._active_panels.add(category)
            self._buttons[category].set_active(True)
            self.panel_requested.emit(category, False)

    def activate_panel(self, category: str, auto: bool = True) -> None:
        """Called when AI speech triggers a category."""
        if category not in self._buttons:
            return
        if auto:
            self._buttons[category].flash(3)
        self._active_panels.add(category)
        self._buttons[category].set_active(True)
        self.panel_requested.emit(category, auto)

    def deactivate_panel(self, category: str) -> None:
        self._active_panels.discard(category)
        if category in self._buttons:
            self._buttons[category].set_active(False)
