"""ui/components/schedule_panel.py — Class schedule view."""

import json
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))

TYPE_COLORS = {
    "Lecture":  "#6C63FF",
    "Seminar":  "#4ECDC4",
    "Lab":      "#4CAF50",
    "Deadline": "#F44336",
}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class SchedulePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=60_000).start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("📅  Schedule")
        title.setObjectName("panel_title")
        header.addWidget(title)
        layout.addLayout(header)
        layout.addSpacing(12)

        # Today section
        today_sec = QLabel("TODAY")
        today_sec.setObjectName("section_title")
        layout.addWidget(today_sec)
        self._today_layout = QVBoxLayout()
        self._today_layout.setSpacing(6)
        layout.addLayout(self._today_layout)
        layout.addSpacing(16)

        # This week
        week_sec = QLabel("THIS WEEK")
        week_sec.setObjectName("section_title")
        layout.addWidget(week_sec)
        layout.addSpacing(6)

        self._week_widget = QWidget()
        wl = QHBoxLayout(self._week_widget)
        wl.setSpacing(4)
        self._day_cols: list[QVBoxLayout] = []
        today_idx = datetime.now().weekday()  # 0=Monday
        for i, day_name in enumerate(DAY_SHORT[:5]):
            col_w = QWidget()
            col_w.setFixedWidth(120)
            if i == today_idx:
                col_w.setStyleSheet(
                    "background:#1E1A3A;border:1px solid #6C63FF;border-radius:8px;"
                )
            else:
                col_w.setStyleSheet(
                    "background:#1A1A1A;border:1px solid #2A2A2A;border-radius:8px;"
                )
            col_lay = QVBoxLayout(col_w)
            col_lay.setContentsMargins(6, 6, 6, 6)
            col_lay.setSpacing(4)
            day_lbl = QLabel(day_name)
            day_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            day_lbl.setStyleSheet(
                f"color:{'#6C63FF' if i == today_idx else '#888888'};"
                "font-weight:bold;font-size:11px;"
            )
            col_lay.addWidget(day_lbl)
            self._day_cols.append(col_lay)
            wl.addWidget(col_w)
        wl.addStretch()

        layout.addWidget(self._week_widget)
        layout.addStretch()

    def _load_schedule(self):
        sched_path = ROOT / "data" / "schedule.json"
        if not sched_path.exists():
            return {"classes": []}
        return json.loads(sched_path.read_text())

    @pyqtSlot()
    def _refresh(self):
        # Clear today layout
        while self._today_layout.count():
            item = self._today_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        # Clear week columns
        for col in self._day_cols:
            while col.count() > 1:  # keep the day label
                item = col.takeAt(1)
                if item.widget(): item.widget().deleteLater()

        try:
            sched = self._load_schedule()
        except Exception:
            return

        now       = datetime.now()
        today_str = DAYS[now.weekday()]

        today_classes = []
        for cls in sched.get("classes", []):
            if today_str in cls.get("days", []):
                cls_time = datetime.strptime(cls["time"], "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
                diff_min = int((cls_time - now).total_seconds() / 60)
                today_classes.append((cls_time, diff_min, cls))

        today_classes.sort(key=lambda x: x[0])

        if not today_classes:
            lbl = QLabel("No classes today. 🎉")
            lbl.setObjectName("secondary")
            self._today_layout.addWidget(lbl)
        else:
            for cls_time, diff_min, cls in today_classes:
                card = QFrame()
                color = TYPE_COLORS.get(cls.get("type", ""), "#6C63FF")
                card.setStyleSheet(
                    f"QFrame{{background:#1A1A1A;border-left:4px solid {color};"
                    "border-radius:8px;padding:10px 12px;}}"
                )
                cl = QVBoxLayout(card)
                cl.setSpacing(2)

                name_row = QHBoxLayout()
                name_lbl = QLabel(cls["name"])
                name_lbl.setStyleSheet("font-weight:bold;font-size:13px;")
                name_row.addWidget(name_lbl)
                name_row.addStretch()
                time_lbl = QLabel(cls["time"])
                time_lbl.setObjectName("secondary")
                name_row.addWidget(time_lbl)
                cl.addLayout(name_row)

                detail_row = QHBoxLayout()
                detail_row.addWidget(QLabel(cls.get("room", "")))
                detail_row.addStretch()
                if diff_min > 0:
                    countdown_str = f"In {diff_min} min" if diff_min < 60 else f"In {diff_min // 60}h {diff_min % 60}m"
                    countdown = QLabel(f"⏰ {countdown_str}")
                    countdown.setStyleSheet(f"color:{color};font-size:11px;")
                    detail_row.addWidget(countdown)
                elif diff_min > -cls.get("duration_minutes", 90):
                    in_prog = QLabel("🟢 In progress")
                    in_prog.setStyleSheet("color:#4CAF50;font-size:11px;")
                    detail_row.addWidget(in_prog)
                cl.addLayout(detail_row)
                self._today_layout.addWidget(card)

        # Populate week columns
        for cls in sched.get("classes", []):
            for day_str in cls.get("days", []):
                if day_str in DAYS:
                    day_idx = DAYS.index(day_str)
                    if day_idx < len(self._day_cols):
                        color = TYPE_COLORS.get(cls.get("type", ""), "#6C63FF")
                        pill = QLabel(f"{cls['time']}\n{cls['name'][:10]}")
                        pill.setStyleSheet(
                            f"background:{color}22;border:1px solid {color};"
                            "border-radius:4px;padding:2px 4px;font-size:10px;"
                        )
                        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        self._day_cols[day_idx].addWidget(pill)
