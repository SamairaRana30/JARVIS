"""
ui/components/hud_panels.py -- All HUD content panels.
Tasks, Goals, Budget (left column), Weather, Schedule, Fridge, Wellbeing (right).
Uses ASCII-only labels to avoid encoding corruption.
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QProgressBar,
                              QVBoxLayout, QWidget)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from ui.components.hud_panel import HudPanel, PulsingLabel


def _load_cfg():
    import yaml
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def _data(rel_path: str):
    try:
        path = ROOT / rel_path
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _hbar(pct: int) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(min(pct, 100))
    bar.setFixedHeight(6)
    bar.setTextVisible(False)
    if pct > 100:
        style = "QProgressBar::chunk{background:#FF6B35;}"
    elif pct >= 80:
        style = "QProgressBar::chunk{background:#FF9800;}"
    else:
        style = "QProgressBar::chunk{background:#00D4FF;}"
    bar.setStyleSheet(
        "QProgressBar{background:#001220;border:1px solid rgba(0,212,255,0.15);"
        "border-radius:0;}" + style
    )
    return bar


# ---------------------------------------------------------------------------
# TASKS PANEL
# ---------------------------------------------------------------------------

class HudTasksPanel(HudPanel):
    PRIORITY_LABELS = {"high": "[!]", "medium": "[~]", "low": "[.]"}
    PRIORITY_COLORS = {"high": "#FF6B35", "medium": "#FFAA00", "low": "#00FF9F"}

    def __init__(self, parent=None):
        super().__init__("ACTIVE OBJECTIVES", parent)
        self._body = QVBoxLayout()
        self._body.setSpacing(6)
        self.content_layout().addLayout(self._body)
        self.content_layout().addStretch()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=30_000).start()
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().tasks_updated.connect(self._refresh)
        except Exception:
            pass

    @pyqtSlot()
    def _refresh(self):
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        try:
            cfg   = _load_cfg()
            tasks = _data(cfg["paths"]["tasks"])
            if not isinstance(tasks, list): tasks = []
            pending = [t for t in tasks if not t.get("done")]
            pending.sort(key=lambda t: (
                {"high": 0, "medium": 1, "low": 2}.get(t.get("priority", "medium"), 1),
                t.get("deadline", "9999")
            ))
        except Exception:
            pending = []

        if not pending:
            lbl = QLabel("ALL OBJECTIVES COMPLETE [OK]")
            lbl.setStyleSheet("color:#00FF9F;font-size:14px;letter-spacing:1px;")
            self._body.addWidget(lbl)
            return

        for task in pending[:5]:
            p     = task.get("priority", "medium")
            label = self.PRIORITY_LABELS.get(p, "[~]")
            color = self.PRIORITY_COLORS.get(p, "#FFAA00")
            row   = QHBoxLayout()
            tag   = QLabel(label)
            tag.setStyleSheet(f"color:{color};font-size:14px;font-weight:bold;")
            tag.setFixedWidth(30)
            row.addWidget(tag)
            name_col = QVBoxLayout()
            name_col.setSpacing(0)
            name = QLabel(task.get("title", "")[:26].upper())
            name.setStyleSheet("color:#00D4FF;font-size:13px;")
            name_col.addWidget(name)
            dl = task.get("deadline", "")
            if dl:
                try:
                    dt   = datetime.fromisoformat(dl)
                    diff = dt - datetime.now()
                    hrs  = diff.total_seconds() / 3600
                    if hrs < 0:
                        dl_str = "OVERDUE"
                    elif hrs < 24:
                        dl_str = f"DUE: {int(hrs)}H"
                    else:
                        dl_str = f"DUE: {dl[:10]}"
                    dl_color = "#FF6B35" if hrs < 4 else "#FFAA00" if hrs < 24 else "#004455"
                    dl_lbl = QLabel(dl_str)
                    dl_lbl.setStyleSheet(f"color:{dl_color};font-size:12px;")
                    name_col.addWidget(dl_lbl)
                except Exception:
                    pass
            row.addLayout(name_col, 1)
            w = QWidget()
            w.setLayout(row)
            self._body.addWidget(w)


# ---------------------------------------------------------------------------
# GOALS PANEL
# ---------------------------------------------------------------------------

class HudGoalsPanel(HudPanel):
    def __init__(self, parent=None):
        super().__init__("MISSION PROGRESS", parent)
        self._body = QVBoxLayout()
        self._body.setSpacing(8)
        self.content_layout().addLayout(self._body)
        self.content_layout().addStretch()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=60_000).start()

    @pyqtSlot()
    def _refresh(self):
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        try:
            cfg      = _load_cfg()
            progress = _data(cfg["paths"]["progress"])
            goals    = progress.get("goals", []) if isinstance(progress, dict) else []
            if not goals:
                g_data = _data(cfg["paths"]["goals"])
                if isinstance(g_data, dict):
                    goals = [
                        {"goal": g["goal"], "snapshots": [{"progress_percent": g.get("progress", 0)}]}
                        for g in g_data.get("long_term", []) + g_data.get("short_term", [])
                    ]
        except Exception:
            goals = []

        for g in goals[:4]:
            snaps = g.get("snapshots", [])
            pct   = snaps[-1]["progress_percent"] if snaps else 0
            delta = ""
            if len(snaps) >= 2:
                d = snaps[-1]["progress_percent"] - snaps[-2]["progress_percent"]
                if d > 0:
                    delta = f"  +{d}%"

            col = QVBoxLayout()
            col.setSpacing(2)
            row = QHBoxLayout()
            name = QLabel(g.get("goal", "")[:20].upper())
            name.setStyleSheet("color:#00D4FF;font-size:13px;letter-spacing:1px;")
            row.addWidget(name, 1)
            pct_lbl = QLabel(f"{pct}%{delta}")
            pct_lbl.setStyleSheet("color:#00FF9F;font-size:13px;")
            row.addWidget(pct_lbl)
            col.addLayout(row)
            col.addWidget(_hbar(pct))
            w = QWidget()
            w.setLayout(col)
            self._body.addWidget(w)


# ---------------------------------------------------------------------------
# BUDGET PANEL
# ---------------------------------------------------------------------------

class HudBudgetPanel(HudPanel):
    def __init__(self, parent=None):
        super().__init__("RESOURCE ALLOCATION", parent)
        self._body = QVBoxLayout()
        self._body.setSpacing(5)
        self.content_layout().addLayout(self._body)
        self.content_layout().addStretch()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=60_000).start()

    @pyqtSlot()
    def _refresh(self):
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        try:
            from budget_tool import get_monthly_data
            data   = get_monthly_data()
            budget = data["budget"]
            by_cat = data["by_category"]
            cur    = budget.get("currency", "EUR")
            limits = budget.get("limits", {})
            total  = data["total_spent"]
            income = float(budget.get("monthly_income", 0))
        except Exception:
            lbl = QLabel("BUDGET DATA UNAVAILABLE")
            lbl.setStyleSheet("color:#004455;font-size:12px;")
            self._body.addWidget(lbl)
            return

        for cat, limit in list(limits.items())[:6]:
            spent = by_cat.get(cat, 0.0)
            if limit <= 0 and spent == 0:
                continue
            pct   = int(spent / limit * 100) if limit else 0
            color = "#FF6B35" if pct > 100 else "#FFAA00" if pct >= 80 else "#00D4FF"
            warn  = " [!]" if pct > 100 else " [^]" if pct >= 80 else ""

            row = QHBoxLayout()
            name_lbl = QLabel(cat.upper()[:9])
            name_lbl.setFixedWidth(80)
            name_lbl.setStyleSheet(f"color:{color};font-size:12px;letter-spacing:1px;")
            row.addWidget(name_lbl)
            bar = _hbar(pct)
            bar.setFixedWidth(80)
            row.addWidget(bar)
            val_lbl = QLabel(f"{cur}{int(spent)}/{cur}{int(limit)}{warn}")
            val_lbl.setStyleSheet(f"color:{color};font-size:11px;")
            row.addWidget(val_lbl)
            w = QWidget()
            w.setLayout(row)
            self._body.addWidget(w)

        if income:
            sep = QLabel("-" * 28)
            sep.setStyleSheet("color:#002040;font-size:10px;")
            self._body.addWidget(sep)
            tot_row = QHBoxLayout()
            tot_lbl = QLabel(f"SPENT: {cur}{int(total)}")
            tot_lbl.setStyleSheet("color:#FFAA00;font-size:12px;")
            tot_row.addWidget(tot_lbl, 1)
            rem_lbl = QLabel(f"LEFT: {cur}{int(income - total)}")
            rem_lbl.setStyleSheet("color:#00FF9F;font-size:12px;")
            tot_row.addWidget(rem_lbl)
            w2 = QWidget()
            w2.setLayout(tot_row)
            self._body.addWidget(w2)


# ---------------------------------------------------------------------------
# WEATHER PANEL
# ---------------------------------------------------------------------------

class HudWeatherPanel(HudPanel):
    def __init__(self, parent=None):
        super().__init__("ATMOSPHERIC DATA", parent)
        self._body = QVBoxLayout()
        self._body.setSpacing(4)
        self.content_layout().addLayout(self._body)
        self.content_layout().addStretch()
        self._update()
        QTimer(self, timeout=self._update, interval=30 * 60 * 1000).start()

    def _update(self):
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        try:
            import yaml, requests, unicodedata, re as _re
            with open(ROOT / "config.yaml") as f:
                cfg = yaml.safe_load(f)
            city = cfg.get("weather", {}).get("default_location", "Berlin")
            resp = requests.get(f"https://wttr.in/{city}?format=j1",
                                timeout=6, headers={"User-Agent": "Jarvis/1.0"})
            d       = resp.json()
            current = d.get("current_condition", [{}])[0]
            temp_c  = current.get("temp_C", "?")
            desc    = current.get("weatherDesc", [{}])[0].get("value", "").upper()
            weather = d.get("weather", [])

            for text, style in [
                (city.upper(),           "color:#00D4FF;font-size:14px;letter-spacing:2px;"),
                (desc[:20],              "color:#008FAA;font-size:12px;"),
                (f"TEMP: {temp_c} C",    "color:#00D4FF;font-size:15px;font-weight:bold;"),
            ]:
                lbl = QLabel(text)
                lbl.setStyleSheet(style)
                self._body.addWidget(lbl)

            if weather:
                sep = QLabel("FORECAST:")
                sep.setStyleSheet("color:#004455;font-size:11px;letter-spacing:1px;margin-top:4px;")
                self._body.addWidget(sep)
                days = ["TODAY", "TOMORROW", "DAY 3"]
                for day_name, w in zip(days, weather[:3]):
                    max_c = w.get("maxtempC", "?")
                    min_c = w.get("mintempC", "?")
                    d_desc = w.get("hourly", [{}])[4].get(
                        "weatherDesc", [{}])[0].get("value", "")[:10].upper()
                    row = QLabel(f"{day_name[:3]} {d_desc} {max_c}/{min_c}C")
                    row.setStyleSheet("color:#008FAA;font-size:12px;")
                    self._body.addWidget(row)
        except Exception:
            lbl = QLabel("FEED UNAVAILABLE")
            lbl.setStyleSheet("color:#004455;font-size:12px;")
            self._body.addWidget(lbl)


# ---------------------------------------------------------------------------
# SCHEDULE PANEL
# ---------------------------------------------------------------------------

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class HudSchedulePanel(HudPanel):
    def __init__(self, parent=None):
        super().__init__("MISSION SCHEDULE", parent)
        self._body = QVBoxLayout()
        self._body.setSpacing(5)
        self.content_layout().addLayout(self._body)
        self.content_layout().addStretch()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=60_000).start()

    @pyqtSlot()
    def _refresh(self):
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        try:
            sched = _data("data/schedule.json")
            classes = sched.get("classes", []) if isinstance(sched, dict) else []
            now   = datetime.now()
            today = now.strftime("%A").lower()
            today_cls = []
            for cls in classes:
                if today in [d.lower() for d in cls.get("days", [])]:
                    cls_time = datetime.strptime(cls["time"], "%H:%M").replace(
                        year=now.year, month=now.month, day=now.day)
                    diff_min = int((cls_time - now).total_seconds() / 60)
                    today_cls.append((cls_time, diff_min, cls))
            today_cls.sort(key=lambda x: x[0])
        except Exception:
            today_cls = []

        if not today_cls:
            lbl = QLabel("NO MISSIONS SCHEDULED")
            lbl.setStyleSheet("color:#004455;font-size:13px;")
            self._body.addWidget(lbl)
            return

        for cls_time, diff_min, cls in today_cls[:4]:
            col = QVBoxLayout()
            col.setSpacing(1)
            if diff_min > 0:
                countdown = f"T-{diff_min}MIN" if diff_min < 60 else f"T-{diff_min // 60}H"
                color = "#FF6B35" if diff_min < 30 else "#FFAA00" if diff_min < 90 else "#004455"
            elif diff_min > -cls.get("duration_minutes", 90):
                countdown = "[LIVE]"
                color = "#00FF9F"
            else:
                countdown = "DONE"
                color = "#002040"

            name_lbl = QLabel(f"> {cls.get('name', '').upper()[:22]}")
            name_lbl.setStyleSheet(f"color:{color};font-size:13px;letter-spacing:1px;")
            col.addWidget(name_lbl)
            detail = QLabel(f"  {cls.get('time', '')} | {cls.get('room', '').upper()[:12]}  {countdown}")
            detail.setStyleSheet(f"color:{color};font-size:11px;")
            col.addWidget(detail)
            w = QWidget()
            w.setLayout(col)
            self._body.addWidget(w)


# ---------------------------------------------------------------------------
# FRIDGE / SUPPLY ALERTS PANEL
# ---------------------------------------------------------------------------

class HudFridgePanel(HudPanel):
    def __init__(self, parent=None):
        super().__init__("SUPPLY ALERTS", parent)
        self._body = QVBoxLayout()
        self._body.setSpacing(5)
        self.content_layout().addLayout(self._body)
        self.content_layout().addStretch()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=60_000).start()
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().fridge_updated.connect(self._refresh)
        except Exception:
            pass

    @pyqtSlot()
    def _refresh(self):
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        try:
            cfg    = _load_cfg()
            fridge = _data(cfg["paths"]["fridge"])
            items  = fridge.get("items", []) if isinstance(fridge, dict) else []
            cutoff = (date.today() + timedelta(days=3)).isoformat()
            expiring = sorted(
                [i for i in items if i.get("expires") and i["expires"] <= cutoff],
                key=lambda i: i["expires"]
            )
        except Exception:
            expiring = []

        if not expiring:
            lbl = QLabel("SUPPLIES NOMINAL [OK]")
            lbl.setStyleSheet("color:#00FF9F;font-size:13px;")
            self._body.addWidget(lbl)
        else:
            for item in expiring[:5]:
                try:
                    days = (date.fromisoformat(item["expires"]) - date.today()).days
                except Exception:
                    days = -1
                color = "#FF6B35" if days <= 1 else "#FFAA00"
                when  = "EXPIRED" if days < 0 else "TODAY" if days == 0 else f"T-{days}D"
                row = QHBoxLayout()
                warn = QLabel("[!]")
                warn.setStyleSheet(f"color:{color};font-size:13px;font-weight:bold;")
                warn.setFixedWidth(28)
                row.addWidget(warn)
                col = QVBoxLayout()
                col.setSpacing(0)
                n_lbl = QLabel(item["name"].upper()[:18])
                n_lbl.setStyleSheet(f"color:{color};font-size:13px;")
                col.addWidget(n_lbl)
                w_lbl = QLabel(f"EXPIRES: {when}")
                w_lbl.setStyleSheet(f"color:{color};font-size:11px;")
                col.addWidget(w_lbl)
                row.addLayout(col)
                w = QWidget()
                w.setLayout(row)
                self._body.addWidget(w)


# ---------------------------------------------------------------------------
# WELLBEING / AGENT STATUS PANEL
# ---------------------------------------------------------------------------

MOOD_MAP = {
    "good": "OPTIMAL", "great": "OPTIMAL", "amazing": "OPTIMAL",
    "okay": "NOMINAL", "bad": "DEGRADED", "tired": "LOW POWER",
    "stressed": "ELEVATED", "sick": "IMPAIRED", "": "UNKNOWN"
}

MOOD_COLORS = {
    "OPTIMAL":  "#00FF9F",
    "NOMINAL":  "#00D4FF",
    "DEGRADED": "#FF6B35",
    "LOW POWER":"#FFAA00",
    "ELEVATED": "#FF6B35",
    "IMPAIRED": "#FF6B35",
    "UNKNOWN":  "#004455",
}


class HudWellbeingPanel(HudPanel):
    def __init__(self, parent=None):
        super().__init__("AGENT STATUS", parent)
        self._body = QVBoxLayout()
        self._body.setSpacing(5)
        self.content_layout().addLayout(self._body)
        self.content_layout().addStretch()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=60_000).start()
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().wellbeing_updated.connect(self._refresh)
        except Exception:
            pass

    @pyqtSlot()
    def _refresh(self):
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        try:
            cfg   = _load_cfg()
            wb    = _data(cfg["paths"]["wellbeing"])
            today = date.today().isoformat()
            entry = next((e for e in (wb if isinstance(wb, list) else [])
                          if e.get("date") == today), {})
        except Exception:
            entry = {}

        mood     = entry.get("mood", "")
        energy   = entry.get("energy", "")
        sleep    = entry.get("sleep", "")
        hydration= float(entry.get("hydration_L", 0) or 0)
        exercise = entry.get("exercise", "")

        mood_status = MOOD_MAP.get(mood.lower(), "UNKNOWN")
        mood_color  = MOOD_COLORS.get(mood_status, "#004455")

        rows = [
            ("MOOD",     f"{mood_status}" if mood else "AWAITING DATA", mood_color),
            ("ENERGY",   energy.upper() if energy else "---", "#00D4FF"),
            ("SLEEP",    sleep.upper() if sleep else "---", "#008FAA"),
            ("WATER",    f"{hydration}L / 2L", "#00FF9F" if hydration >= 1.5 else "#FFAA00"),
            ("EXERCISE", "LOGGED [OK]" if exercise else "NOT LOGGED", "#00FF9F" if exercise else "#FF6B35"),
        ]
        for label, value, color in rows:
            row = QHBoxLayout()
            lbl_w = QLabel(f"{label}:")
            lbl_w.setFixedWidth(72)
            lbl_w.setStyleSheet("color:#004455;font-size:11px;letter-spacing:1px;")
            row.addWidget(lbl_w)
            val_w = QLabel(value)
            val_w.setStyleSheet(f"color:{color};font-size:12px;")
            row.addWidget(val_w, 1)
            w = QWidget()
            w.setLayout(row)
            self._body.addWidget(w)

        # Streak (ASCII only)
        try:
            wb_list = _data(cfg["paths"]["wellbeing"]) if isinstance(
                _data(cfg["paths"]["wellbeing"]), list) else []
            week_ago = (date.today() - timedelta(days=7)).isoformat()
            ex_days  = sum(1 for e in wb_list if e.get("date", "") >= week_ago
                           and e.get("exercise", ""))
            color = "#00FF9F" if ex_days >= 5 else "#FFAA00" if ex_days >= 3 else "#FF6B35"
            streak_lbl = QLabel(f"* STREAK: {ex_days}/7 DAYS")
            streak_lbl.setStyleSheet(f"color:{color};font-size:13px;margin-top:4px;")
            self._body.addWidget(streak_lbl)
        except Exception:
            pass
