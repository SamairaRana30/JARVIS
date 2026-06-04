"""
setup_models.py — First-launch model setup for Jarvis.
Called automatically at the top of jarvis.py before any thread starts.

Strategy:
  1. Try openWakeWord's built-in download utility (puts file in OWW's own
     resources/models/ directory, which is exactly where OWW looks).
  2. Fallback: download the .onnx file manually into OWW's resources/models/.
  3. Also copy the file to assets/models/ for reference / offline re-use.
"""

import logging
import os
import sys
import urllib.request
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.resolve()

_DEFAULT_URL  = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/hey_jarvis_v0.1.onnx"
_MODEL_NAME   = "hey_jarvis"          # name passed to Model(wakeword_models=[...])
_MODEL_FNAME  = "hey_jarvis_v0.1.onnx"  # filename OWW expects in its resources dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_cfg() -> dict:
    cfg_path = BASE_DIR / "config.yaml"
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def _get_oww_resources_dir() -> Path | None:
    """Return the openWakeWord resources/models directory, or None if OWW not installed."""
    try:
        import openwakeword  # type: ignore
        return Path(openwakeword.__file__).parent / "resources" / "models"
    except ImportError:
        return None


def _progress_hook(block_num: int, block_size: int, total_size: int) -> None:
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        bar = "#" * (pct // 5)
        sys.stdout.write(f"\r  [{bar:<20}] {pct:3d}%  ({downloaded // 1024} KB)")
        sys.stdout.flush()
        if pct == 100:
            sys.stdout.write("\n")
            sys.stdout.flush()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_oww_model_path() -> Path | None:
    """
    Return the path to the hey_jarvis model inside OWW's resources directory,
    or None if it doesn't exist yet.
    """
    d = _get_oww_resources_dir()
    if d is None:
        return None
    candidate = d / _MODEL_FNAME
    return candidate if candidate.exists() else None


def download_wake_word_model(
    model_url: str | None = None,
    model_path: str | None = None,   # kept for test injection / override
) -> str:
    """
    Ensure the hey_jarvis wake-word model is available inside OWW's
    resources/models/ directory (where OWW always looks).

    Steps:
      1. Return immediately if the model is already present.
      2. Try openwakeword.utils.download_models() — the official route.
      3. Fall back to a direct urllib download into OWW's resources dir.
      4. Also copy the file to assets/models/ for reference.

    Returns the path to the downloaded model file.
    Raises RuntimeError on unrecoverable failure.
    """
    cfg    = _load_cfg()
    ww_cfg = cfg.get("wake_word", {})
    url    = model_url or ww_cfg.get("model_url", _DEFAULT_URL)

    oww_dir = _get_oww_resources_dir()

    # ── If caller passed an explicit model_path (test mode) ──────────────────
    if model_path is not None:
        abs_path = Path(model_path) if os.path.isabs(model_path) else BASE_DIR / model_path
        if abs_path.exists():
            logger.debug("Wake word model already present: %s", abs_path)
            return str(abs_path)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        _download_url(url, abs_path)
        return str(abs_path)

    # ── Check OWW resources dir first ────────────────────────────────────────
    if oww_dir is not None:
        dest = oww_dir / _MODEL_FNAME
        if dest.exists():
            logger.debug("Wake word model already in OWW resources: %s", dest)
            return str(dest)

    # ── Attempt 1: OWW's built-in download utility ───────────────────────────
    try:
        from openwakeword.utils import download_models  # type: ignore
        print(f"Downloading wake word model via openWakeWord...")
        download_models([_MODEL_NAME])
        if oww_dir and (oww_dir / _MODEL_FNAME).exists():
            logger.info("Wake word model downloaded via OWW utility.")
            print(f"  Done — model in {oww_dir / _MODEL_FNAME}")
            _copy_to_assets(oww_dir / _MODEL_FNAME)
            return str(oww_dir / _MODEL_FNAME)
    except Exception as e:
        logger.debug("OWW download utility failed (%s), falling back to direct download.", e)

    # ── Attempt 2: direct download into OWW resources dir ────────────────────
    if oww_dir is not None:
        oww_dir.mkdir(parents=True, exist_ok=True)
        dest = oww_dir / _MODEL_FNAME
        print(f"Downloading wake word model from:\n  {url}")
        _download_url(url, dest)
        logger.info("Wake word model downloaded: %s", dest)
        _copy_to_assets(dest)
        return str(dest)

    # ── OWW not installed — download to assets/models/ as best effort ────────
    fallback = BASE_DIR / ww_cfg.get("model_path", "assets/models/hey_jarvis.onnx")
    if fallback.exists():
        return str(fallback)
    fallback.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading wake word model from:\n  {url}")
    _download_url(url, fallback)
    logger.info("Wake word model downloaded to fallback path: %s", fallback)
    return str(fallback)


def _download_url(url: str, dest: Path) -> None:
    """Download url to dest with progress bar. Cleans up on failure."""
    try:
        urllib.request.urlretrieve(url, dest, reporthook=_progress_hook)
    except Exception as e:
        if dest.exists():
            dest.unlink()
        raise RuntimeError(f"Failed to download wake word model: {e}") from e

    if dest.stat().st_size < 1024:
        dest.unlink()
        raise RuntimeError(
            "Downloaded wake word model is too small — possibly a bad URL or network error."
        )
    print(f"Wake word model saved to: {dest}")


def _copy_to_assets(src: Path) -> None:
    """Copy the model to assets/models/ for reference (best effort)."""
    try:
        import shutil
        assets_dest = BASE_DIR / "assets" / "models" / _MODEL_FNAME
        if not assets_dest.exists():
            assets_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, assets_dest)
    except Exception as e:
        logger.debug("Could not copy model to assets/: %s", e)


# ---------------------------------------------------------------------------
# Piper TTS auto-setup
# ---------------------------------------------------------------------------

PIPER_VERSION       = "2.0.0"
_PIPER_EXE          = BASE_DIR / "assets" / "piper" / "piper.exe"
_PIPER_VOICES_DIR   = BASE_DIR / "assets" / "piper" / "voices"
_PIPER_WINDOWS_URL  = f"https://github.com/rhasspy/piper/releases/download/{PIPER_VERSION}/piper_windows_amd64.zip"
_PIPER_MODEL_URL    = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "en/en_GB/alan/medium/en_GB-alan-medium.onnx"
)
_PIPER_CONFIG_URL   = _PIPER_MODEL_URL + ".json"


def setup_piper() -> None:
    """
    Download Piper binary and voice model if not already present.
    Graceful — logs a warning on failure, never raises.
    """
    if _PIPER_EXE.exists():
        logger.debug("Piper already installed: %s", _PIPER_EXE)
        return

    _PIPER_EXE.parent.mkdir(parents=True, exist_ok=True)
    _PIPER_VOICES_DIR.mkdir(parents=True, exist_ok=True)

    # Download binary zip
    zip_path = _PIPER_EXE.parent / "piper.zip"
    print(f"Downloading Piper TTS binary from:\n  {_PIPER_WINDOWS_URL}")
    try:
        urllib.request.urlretrieve(_PIPER_WINDOWS_URL, zip_path, reporthook=_progress_hook)
    except Exception as e:
        print(f"  WARNING: Could not download Piper: {e}")
        logger.warning("Piper download failed: %s", e)
        return

    import zipfile
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(_PIPER_EXE.parent)
        zip_path.unlink()
    except Exception as e:
        print(f"  WARNING: Could not extract Piper: {e}")
        return

    # Download voice model
    voice_path = _PIPER_VOICES_DIR / "en_GB-alan-medium.onnx"
    config_path = _PIPER_VOICES_DIR / "en_GB-alan-medium.onnx.json"
    for url, dest in [(_PIPER_MODEL_URL, voice_path), (_PIPER_CONFIG_URL, config_path)]:
        if not dest.exists():
            print(f"Downloading Piper voice: {dest.name}")
            try:
                urllib.request.urlretrieve(url, dest, reporthook=_progress_hook)
            except Exception as e:
                print(f"  WARNING: Could not download voice model: {e}")
                logger.warning("Piper voice download failed: %s", e)
                return

    print(f"Piper TTS ready.")
    logger.info("Piper TTS installed to %s", _PIPER_EXE)


# ---------------------------------------------------------------------------
# Audio chime generation
# ---------------------------------------------------------------------------

def generate_chime(path: Path, frequency: int = 880, duration: float = 0.3) -> None:
    """Generate a sine-wave chime with fade-out and save as WAV-in-MP3."""
    try:
        import math, struct, wave as _wave
        sr      = 44100
        samples = int(sr * duration)
        fade    = int(sr * 0.05)
        data    = []
        for i in range(samples):
            amp = math.sin(2 * math.pi * frequency * i / sr)
            if i > samples - fade:
                amp *= (samples - i) / fade
            data.append(int(amp * 32767))
        path.parent.mkdir(parents=True, exist_ok=True)
        wav = path.with_suffix(".wav")
        with _wave.open(str(wav), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack(f"<{len(data)}h", *data))
        wav.rename(path)   # rename .wav → .mp3 (pygame reads by content)
        logger.debug("Generated chime: %s (%dHz %.1fs)", path.name, frequency, duration)
    except Exception as e:
        logger.warning("Could not generate chime %s: %s", path, e)


def ensure_sound_files() -> None:
    """Generate missing chime files on first run."""
    sounds_dir = BASE_DIR / "assets" / "sounds"
    sounds_dir.mkdir(parents=True, exist_ok=True)

    chimes = {
        "wake.mp3":        (880, 0.20),   # high bright ping
        "done.mp3":        (660, 0.30),   # medium confirm
        "error.mp3":       (220, 0.40),   # low error tone
        "alarm.mp3":       (880, 1.00),   # longer alarm
        "pomodoro_end.mp3":(880, 1.35),   # 3-beep pattern approximated
    }
    for name, (freq, dur) in chimes.items():
        dest = sounds_dir / name
        if not dest.exists():
            generate_chime(dest, freq, dur)
            print(f"Generated sound: {name}")


# ---------------------------------------------------------------------------
# First-launch runner
# ---------------------------------------------------------------------------

def run_first_launch_setup() -> None:
    """
    Run all first-launch checks and downloads.
    Safe to call on every startup — skips anything already done.
    Never raises — Jarvis starts even if model download fails.
    """
    print("Jarvis: checking first-launch setup...")

    try:
        download_wake_word_model()
    except RuntimeError as e:
        logger.error("Wake word model setup failed: %s", e)
        print(f"  WARNING: {e}")
        print("  Jarvis will start without wake word detection.")
        oww_dir = _get_oww_resources_dir()
        print(f"    {oww_dir if oww_dir else 'assets/models/'}\n")

    # Ensure chime sound files exist
    ensure_sound_files()

    # Piper (best-effort — don't block startup if it fails)
    try:
        setup_piper()
    except Exception as e:
        logger.debug("Piper setup skipped: %s", e)

    print("Setup check complete.\n")
