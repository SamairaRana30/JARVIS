"""
ui/components/hud_panel.py — Base HUD panel with corner brackets and glow border.
All content panels inherit from this.
"""

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPen, QFont
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QWidget, QLabel, QHBoxLayout

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))

CYAN    = QColor("#00D4FF")
DIM     = QColor("#002040")
SURFACE = QColor(0, 18, 32, 200)


class HudPanel(QFrame):
    """
    A panel with glowing cyan border and corner bracket decorations.
    Subclass this for all HUD content widgets.
    """

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self._title = title.upper()
        self._hover = False
        self._blink = False
        self.setObjectName("hud_panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Layout
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 14, 14, 10)
        self._layout.setSpacing(6)

        if title:
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 4)
            lbl = QLabel(f"◄ {title.upper()} ►")
            lbl.setObjectName("hud_title")
            lbl.setStyleSheet(
                "color:#00D4FF;font-family:'Orbitron','Arial Black',sans-serif;"
                "font-size:9px;letter-spacing:3px;font-weight:bold;"
            )
            header.addWidget(lbl)
            header.addStretch()
            self._layout.addLayout(header)

            # Separator line
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("color:rgba(0,212,255,0.2);")
            self._layout.addWidget(sep)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h   = self.width(), self.height()
        br_len = 14   # corner bracket arm length
        br_w   = 2    # bracket line width

        alpha   = 200 if self._hover else 100
        purple  = QColor(139, 43, 226, alpha)       # top-left: purple
        pink    = QColor(233, 30, 140, alpha)        # bottom-right: pink
        pen_p   = QPen(purple, br_w)
        pen_pk  = QPen(pink, br_w)

        # Top-left corner (purple)
        p.setPen(pen_p)
        p.drawLine(0, 0, br_len, 0)
        p.drawLine(0, 0, 0, br_len)

        # Top-right corner (purple)
        p.drawLine(w - br_len, 0, w - 1, 0)
        p.drawLine(w - 1, 0, w - 1, br_len)

        # Bottom-left corner (pink)
        p.setPen(pen_pk)
        p.drawLine(0, h - br_len, 0, h - 1)
        p.drawLine(0, h - 1, br_len, h - 1)

        # Bottom-right corner (pink)
        p.drawLine(w - br_len, h - 1, w - 1, h - 1)
        p.drawLine(w - 1, h - br_len, w - 1, h - 1)

        p.end()

    def content_layout(self) -> QVBoxLayout:
        return self._layout


class PulsingLabel(QLabel):
    """A QLabel that slowly pulses its opacity — used for status indicators."""

    def __init__(self, text: str = "", color: str = "#00D4FF", parent=None):
        super().__init__(text, parent)
        self._alpha = 255
        self._dir   = -4
        self._color = color
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._pulse)
        self._timer.start(40)
        self._apply()

    def _pulse(self):
        self._alpha = max(80, min(255, self._alpha + self._dir))
        if self._alpha <= 80 or self._alpha >= 255:
            self._dir *= -1
        self._apply()

    def _apply(self):
        r, g, b = int(self._color[1:3], 16), int(self._color[3:5], 16), int(self._color[5:7], 16)
        self.setStyleSheet(
            f"color: rgba({r},{g},{b},{self._alpha});"
            f"font-family:'Share Tech Mono',monospace;font-size:11px;"
        )

    def stop_pulsing(self):
        self._timer.stop()
        self._alpha = 255
        self._apply()
