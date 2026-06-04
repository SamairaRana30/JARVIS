"""ui/components/settings_panel.py — Visual config editor, no YAML editing needed."""

import json
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
    QScrollArea, QSlider, QVBoxLayout, QWidget
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _load_cfg():
    import yaml
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def _save_cfg_key(key: str, value) -> None:
    """Update a single top-level key in config.yaml and re-save."""
    import re
    cfg_path = ROOT / "config.yaml"
    text = cfg_path.read_text(encoding="utf-8")
    pattern = rf'^({re.escape(key)}:\s*)["\']?[^#\n]*["\']?'
    if isinstance(value, str):
        replacement = rf'\g<1>"{value}"'
    else:
        replacement = rf'\g<1>{value}'
    new_text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
    if new_text != text:
        cfg_path.write_text(new_text, encoding="utf-8")


class SettingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("⚙️  Settings")
        title.setObjectName("panel_title")
        layout.addWidget(title)
        layout.addSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(12)
        form.setContentsMargins(0, 0, 16, 0)

        cfg = _load_cfg()

        # ── VOICE ─────────────────────────────────────────────────────────
        self._add_section(form, "VOICE")

        self._voice_edit = QLineEdit(cfg.get("voice", "en-GB-RyanNeural"))
        form.addRow("TTS Voice:", self._voice_edit)

        rate_val = self._parse_pct(cfg.get("speaking_rate", "+0%"))
        self._rate_slider = self._make_slider(-50, 50, rate_val)
        self._rate_lbl = QLabel(f"{rate_val:+d}%")
        rate_row = self._slider_row(self._rate_slider, self._rate_lbl)
        self._rate_slider.valueChanged.connect(lambda v: self._rate_lbl.setText(f"{v:+d}%"))
        form.addRow("Speed:", rate_row)

        vol_val = self._parse_pct(cfg.get("speaking_volume", "+0%"))
        self._vol_slider = self._make_slider(-50, 50, vol_val)
        self._vol_lbl = QLabel(f"{vol_val:+d}%")
        vol_row = self._slider_row(self._vol_slider, self._vol_lbl)
        self._vol_slider.valueChanged.connect(lambda v: self._vol_lbl.setText(f"{v:+d}%"))
        form.addRow("Volume:", vol_row)

        # ── WAKE WORD ─────────────────────────────────────────────────────
        self._add_section(form, "WAKE WORD")

        sens_val = int(float(cfg.get("wake_word", {}).get("sensitivity",
                              cfg.get("wake_word_sensitivity", 0.75))) * 100)
        self._sens_slider = self._make_slider(10, 100, sens_val)
        self._sens_lbl = QLabel(f"{sens_val / 100:.2f}")
        sens_row = self._slider_row(self._sens_slider, self._sens_lbl)
        self._sens_slider.valueChanged.connect(lambda v: self._sens_lbl.setText(f"{v / 100:.2f}"))
        form.addRow("Sensitivity:", sens_row)

        self._mic_edit = QLineEdit(str(cfg.get("mic_device_index", "1")))
        form.addRow("Mic device index:", self._mic_edit)

        # ── PROFILE ───────────────────────────────────────────────────────
        self._add_section(form, "PROFILE")
        self._profile_box = QComboBox()
        self._profile_box.addItems(["study", "work", "chill"])
        self._profile_box.setCurrentText(cfg.get("profile", "study"))
        form.addRow("Default profile:", self._profile_box)

        # ── WHISPER ───────────────────────────────────────────────────────
        self._add_section(form, "WHISPER")
        self._whisper_size = QComboBox()
        self._whisper_size.addItems(["tiny", "base", "small", "medium", "large"])
        self._whisper_size.setCurrentText(cfg.get("whisper", {}).get("model_size", "base"))
        form.addRow("Model size:", self._whisper_size)

        self._whisper_device = QComboBox()
        self._whisper_device.addItems(["cpu", "cuda"])
        self._whisper_device.setCurrentText(cfg.get("whisper", {}).get("device", "cpu"))
        form.addRow("Device:", self._whisper_device)

        # ── BRIEFING ──────────────────────────────────────────────────────
        self._add_section(form, "BRIEFING")
        br = cfg.get("briefing", {})
        self._morning_time = QLineEdit(br.get("morning_time", "08:00"))
        self._evening_time = QLineEdit(br.get("evening_time", "20:00"))
        self._startup_delay = QLineEdit(str(br.get("startup_delay_seconds", 60)))
        form.addRow("Morning briefing:", self._morning_time)
        form.addRow("Evening check-in:", self._evening_time)
        form.addRow("Startup delay (s):", self._startup_delay)

        # ── TIMEZONE ─────────────────────────────────────────────────────
        self._add_section(form, "TIMEZONE")
        self._tz_edit = QLineEdit(cfg.get("timezone", "Europe/Berlin"))
        form.addRow("Timezone:", self._tz_edit)

        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        # Save / Reset buttons
        btn_row = QHBoxLayout()
        save_btn = QPushButton("💾  Save Settings")
        save_btn.setObjectName("accent_btn")
        save_btn.clicked.connect(self._save)
        reset_btn = QPushButton("↺  Reset")
        reset_btn.clicked.connect(self._reset)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(reset_btn)
        layout.addLayout(btn_row)

    def _add_section(self, form, label):
        sec = QLabel(label)
        sec.setObjectName("section_title")
        form.addRow(sec)

    def _make_slider(self, min_val, max_val, value):
        s = QSlider(Qt.Orientation.Horizontal)
        s.setMinimum(min_val)
        s.setMaximum(max_val)
        s.setValue(value)
        return s

    def _slider_row(self, slider, label):
        w = QWidget()
        rl = QHBoxLayout(w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(slider, 1)
        label.setFixedWidth(52)
        rl.addWidget(label)
        return w

    def _parse_pct(self, s: str) -> int:
        import re
        m = re.match(r"([+-]?\d+)%", str(s).strip())
        return int(m.group(1)) if m else 0

    def _save(self):
        try:
            _save_cfg_key("voice", self._voice_edit.text().strip())
            _save_cfg_key("speaking_rate", f"{self._rate_slider.value():+d}%")
            _save_cfg_key("speaking_volume", f"{self._vol_slider.value():+d}%")
            _save_cfg_key("profile", self._profile_box.currentText())
            _save_cfg_key("timezone", self._tz_edit.text().strip())
            _save_cfg_key("mic_device_index", self._mic_edit.text().strip())
            # Reload tts and jarvis settings
            try:
                import tts as _tts
                _tts._RATE   = f"{self._rate_slider.value():+d}%"
                _tts._VOL_DB = f"{self._vol_slider.value():+d}%"
                _tts._VOICE  = self._voice_edit.text().strip()
            except Exception:
                pass
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Settings", "Settings saved and applied.")
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not save: {e}")

    def _reset(self):
        self._rate_slider.setValue(0)
        self._vol_slider.setValue(0)
        self._profile_box.setCurrentText("study")
