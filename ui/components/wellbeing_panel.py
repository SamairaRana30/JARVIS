"""ui/components/wellbeing_panel.py — Mood, habits, streaks, charts."""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QProgressBar,
    QVBoxLayout, QWidget
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _load_cfg():
    import yaml
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


MOOD_EMOJIS = {"good": "😊", "great": "😊", "amazing": "🤩",
               "okay": "😐", "bad": "😟", "tired": "😴",
               "stressed": "😰", "sick": "🤒", "": "—"}


class WellbeingPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=60_000).start()
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().wellbeing_updated.connect(self._refresh)
        except Exception:
            pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("❤️  Wellbeing")
        title.setObjectName("panel_title")
        layout.addWidget(title)
        layout.addSpacing(12)

        # Today card
        today_card = QFrame()
        today_card.setStyleSheet(
            "QFrame{background:#1A1A1A;border:1px solid #2A2A2A;border-radius:12px;padding:16px;}"
        )
        tc_lay = QHBoxLayout(today_card)

        # Left: today stats
        today_stats = QVBoxLayout()
        today_stats.setSpacing(6)
        sec = QLabel("TODAY")
        sec.setObjectName("section_title")
        today_stats.addWidget(sec)
        self._mood_lbl    = QLabel("Mood: —")
        self._energy_lbl  = QLabel("Energy: —")
        self._sleep_lbl   = QLabel("Sleep: —")
        self._water_lbl   = QLabel("Water: —")
        self._exercise_lbl= QLabel("Exercise: —")
        for lbl in [self._mood_lbl, self._energy_lbl, self._sleep_lbl,
                    self._water_lbl, self._exercise_lbl]:
            lbl.setFont(__import__("PyQt6.QtGui", fromlist=["QFont"]).QFont("Segoe UI", 13))
            today_stats.addWidget(lbl)
        tc_lay.addLayout(today_stats)

        # Right: quick log buttons
        log_col = QVBoxLayout()
        log_col.setSpacing(6)
        sec2 = QLabel("QUICK LOG")
        sec2.setObjectName("section_title")
        log_col.addWidget(sec2)

        self._mood_box = QComboBox()
        self._mood_box.addItems(["good", "great", "okay", "tired", "stressed", "bad", "sick"])
        log_col.addWidget(self._mood_box)

        log_mood_btn = QPushButton("Log Mood")
        log_mood_btn.clicked.connect(self._log_mood)
        log_col.addWidget(log_mood_btn)

        self._exercise_input = QLineEdit()
        self._exercise_input.setPlaceholderText("30 min walk")
        log_col.addWidget(self._exercise_input)

        log_ex_btn = QPushButton("Log Exercise")
        log_ex_btn.clicked.connect(self._log_exercise)
        log_col.addWidget(log_ex_btn)

        self._water_input = QLineEdit()
        self._water_input.setPlaceholderText("Litres (e.g. 1.5)")
        log_col.addWidget(self._water_input)

        log_w_btn = QPushButton("Log Water")
        log_w_btn.clicked.connect(self._log_water)
        log_col.addWidget(log_w_btn)

        tc_lay.addLayout(log_col)
        layout.addWidget(today_card)
        layout.addSpacing(12)

        # Streak section
        sec3 = QLabel("HABIT STREAKS")
        sec3.setObjectName("section_title")
        layout.addWidget(sec3)
        layout.addSpacing(4)

        self._streaks_layout = QVBoxLayout()
        self._streaks_layout.setSpacing(8)
        layout.addLayout(self._streaks_layout)
        layout.addStretch()

    @pyqtSlot()
    def _refresh(self):
        try:
            cfg = _load_cfg()
            wb_path = ROOT / cfg["paths"]["wellbeing"]
            wb = json.loads(wb_path.read_text())
        except Exception:
            return

        today_str = date.today().isoformat()
        today_entry = next((e for e in wb if e.get("date") == today_str), {})

        mood     = today_entry.get("mood", "")
        energy   = today_entry.get("energy", "")
        sleep    = today_entry.get("sleep", "")
        hydration= today_entry.get("hydration_L", 0)
        exercise = today_entry.get("exercise", "")

        self._mood_lbl.setText(f"Mood: {MOOD_EMOJIS.get(mood, '—')} {mood or '—'}")
        self._energy_lbl.setText(f"Energy: {energy or '—'}")
        self._sleep_lbl.setText(f"Sleep: {sleep or '—'}")
        self._water_lbl.setText(f"Water: {hydration}L" if hydration else "Water: —")
        self._exercise_lbl.setText(f"Exercise: {'✅ ' + exercise if exercise else '—'}")

        # Streaks
        while self._streaks_layout.count():
            item = self._streaks_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        week_ago = (date.today() - timedelta(days=7)).isoformat()
        recent   = [e for e in wb if e.get("date", "") >= week_ago]

        streaks = [
            ("💧 Water",    sum(1 for e in recent if float(e.get("hydration_L", 0)) >= 1.5)),
            ("🏃 Exercise", sum(1 for e in recent if e.get("exercise", "").strip())),
            ("😴 Sleep 7h+",sum(1 for e in recent if "7" in str(e.get("sleep", "")))),
        ]
        for label, count in streaks:
            row = QFrame()
            rl = QVBoxLayout(row)
            rl.setSpacing(2)
            name_row = QHBoxLayout()
            name_row.addWidget(QLabel(label))
            name_row.addStretch()
            streak_lbl = QLabel(f"🔥 {count}/7 days")
            streak_lbl.setObjectName("accent" if count >= 5 else "secondary")
            name_row.addWidget(streak_lbl)
            rl.addLayout(name_row)
            bar = QProgressBar()
            bar.setMaximum(7)
            bar.setValue(count)
            bar.setFixedHeight(6)
            rl.addWidget(bar)
            self._streaks_layout.addWidget(row)

    def _log_mood(self):
        mood = self._mood_box.currentText()
        try:
            import sys; sys.path.insert(0, str(ROOT))
            import tools
            from pathlib import Path
            from datetime import date
            cfg = _load_cfg()
            wb_path = ROOT / cfg["paths"]["wellbeing"]
            wb = json.loads(wb_path.read_text())
            today = date.today().isoformat()
            for e in wb:
                if e.get("date") == today:
                    e["mood"] = mood
                    wb_path.write_text(json.dumps(wb, indent=2))
                    self._refresh()
                    return
            wb.append({"date": today, "mood": mood, "energy": "", "sleep": "",
                       "exercise": "", "hydration_L": 0, "notes": "", "source": "ui"})
            wb_path.write_text(json.dumps(wb, indent=2))
            self._refresh()
        except Exception as e:
            print(f"Log mood error: {e}")

    def _log_exercise(self):
        activity = self._exercise_input.text().strip() or "exercised"
        self._exercise_input.clear()
        try:
            import tools
            tools.log_exercise(activity)
            self._refresh()
        except Exception as e:
            print(f"Log exercise error: {e}")

    def _log_water(self):
        try:
            amount = float(self._water_input.text().strip())
            self._water_input.clear()
            import tools
            tools.log_hydration(amount)
            self._refresh()
        except Exception as e:
            print(f"Log water error: {e}")
