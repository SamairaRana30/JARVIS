"""
screen_reader.py — Read text from the screen via OCR.
"Jarvis, read this" → screenshot → pytesseract OCR → speak.

Requires:
  pip install pytesseract Pillow
  Install Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
  Add to config.yaml:
    screen_reader:
      tesseract_path: "C:/Program Files/Tesseract-OCR/tesseract.exe"
      language: "eng"   # tesseract language code
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _configure_tesseract() -> None:
    try:
        import pytesseract  # type: ignore
        cfg      = _load_cfg()
        tess_cfg = cfg.get("screen_reader", {})
        tess_exe = tess_cfg.get(
            "tesseract_path",
            r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        )
        pytesseract.pytesseract.tesseract_cmd = tess_exe
    except ImportError:
        pass


def read_screen(region=None, llm_caller=None) -> str:
    """
    Take a screenshot (full screen or region), run OCR, return spoken text.
    region: (left, top, right, bottom) in pixels, or None for full screen.
    """
    try:
        import pytesseract   # type: ignore
        from PIL import ImageGrab  # type: ignore
    except ImportError:
        return (
            "Screen reader requires pytesseract and Pillow. "
            "Run: pip install pytesseract Pillow "
            "and install Tesseract from github.com/UB-Mannheim/tesseract"
        )

    _configure_tesseract()

    try:
        cfg  = _load_cfg()
        lang = cfg.get("screen_reader", {}).get("language", "eng")
        img  = ImageGrab.grab(bbox=region)
        text = pytesseract.image_to_string(img, lang=lang).strip()

        if not text:
            return "I couldn't find any readable text on the screen."

        # Clean up OCR noise
        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 2]
        clean = " ".join(lines)

        if llm_caller and len(clean) > 200:
            summary = llm_caller(
                f"Summarise or explain this text from the screen in simple terms:\n\n{clean[:1500]}"
            )
            return summary

        return clean[:600]   # speak up to 600 chars directly

    except Exception as e:
        logger.error("Screen reader error: %s", e)
        return f"Screen reader failed: {e}"


def read_clipboard_text(llm_caller=None) -> str:
    """Read clipboard and explain it — existing tool, but using LLM for better explanation."""
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=5
        )
        text = result.stdout.strip()
    except Exception as e:
        return f"Couldn't read clipboard: {e}"

    if not text:
        return "Clipboard is empty."

    if llm_caller:
        return llm_caller(
            f"Explain this in simple, clear terms — as if speaking to a student:\n\n{text[:2000]}"
        )
    return f"Clipboard contents: {text[:400]}"
