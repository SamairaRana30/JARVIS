"""
ui/signals.py — PyQt6 signals bridge between Jarvis voice engine and dashboard.

Voice engine (jarvis.py, tools.py etc.) runs in background threads.
PyQt6 UI must only be updated from the main thread.
This module provides a singleton QObject whose signals carry data
safely across the thread boundary via Qt's queued connection mechanism.
"""

from PyQt6.QtCore import QObject, pyqtSignal


class JarvisSignals(QObject):
    # ── Voice state ───────────────────────────────────────────────────────────
    status_changed   = pyqtSignal(str)    # "Listening" / "Processing" / "Speaking" / "Paused" / "Sleeping"
    jarvis_speaking  = pyqtSignal(str)    # text Jarvis is about to say
    user_spoke       = pyqtSignal(str)    # transcribed user text
    jarvis_listening = pyqtSignal()

    # ── Data file changed (triggers panel refresh) ───────────────────────────
    tasks_updated    = pyqtSignal()
    fridge_updated   = pyqtSignal()
    notes_updated    = pyqtSignal()
    goals_updated    = pyqtSignal()
    wellbeing_updated= pyqtSignal()
    sites_updated    = pyqtSignal()
    reminders_updated= pyqtSignal()

    # ── UI → Voice engine ─────────────────────────────────────────────────────
    user_typed       = pyqtSignal(str)    # user typed a message in chat panel
    profile_changed  = pyqtSignal(str)   # user switched profile in UI

    # ── System ────────────────────────────────────────────────────────────────
    error_occurred   = pyqtSignal(str)
    wake_confidence  = pyqtSignal(float) # 0.0–1.0 wake word confidence

    _instance = None

    @classmethod
    def instance(cls) -> "JarvisSignals":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# Convenience alias
signals = JarvisSignals.instance
