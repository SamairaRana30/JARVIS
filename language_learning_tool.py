"""
language_learning_tool.py -- Language learning for Jarvis.
Vocabulary tracking, translation, quiz, STT corrections.
Fully local via LLM -- no external translation API needed.
"""

import json
import logging
import random
from datetime import date
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()
VOCAB_PATH = BASE_DIR / "data" / "vocabulary.json"


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml") as f:
        return yaml.safe_load(f)


def _load_vocab() -> dict:
    try:
        return json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"known_words": [], "corrections": []}


def _save_vocab(data: dict) -> None:
    VOCAB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

def translate(text: str, to_lang: str = "de", llm_caller=None) -> str:
    """Translate a word/phrase and save to vocabulary."""
    lang_names = {"de": "German", "en": "English", "fr": "French",
                  "es": "Spanish", "it": "Italian"}
    lang_name = lang_names.get(to_lang.lower(), to_lang)

    if not llm_caller:
        return f"Translation unavailable without LLM. Set up Ollama first."

    result = llm_caller(
        f"Translate '{text}' to {lang_name}. "
        f"If it's a noun, include the article (der/die/das for German). "
        f"Reply with ONLY the translation, nothing else."
    ).strip()

    # Save to vocabulary
    vocab = _load_vocab()
    words = vocab.get("known_words", [])
    entry = {
        "original":     text,
        "translation":  result,
        "language":     to_lang,
        "added":        date.today().isoformat(),
        "times_tested": 0,
        "times_correct": 0,
    }
    # Avoid duplicates
    existing = [w for w in words if w.get("original", "").lower() == text.lower()
                and w.get("language") == to_lang]
    if not existing:
        words.append(entry)
        vocab["known_words"] = words
        _save_vocab(vocab)

    return f"'{text}' in {lang_name} is: {result}"


# ---------------------------------------------------------------------------
# Vocabulary quiz
# ---------------------------------------------------------------------------

def quiz_vocabulary(n: int = 10, language: str = "de",
                    speak_fn=None, listen_fn=None, llm_caller=None) -> str:
    """Quiz the user on saved vocabulary words."""
    vocab = _load_vocab()
    words = [w for w in vocab.get("known_words", [])
             if w.get("language") == language]

    if not words:
        return f"No {language} vocabulary saved yet. Try 'German for deadline' to add words."

    # Prioritise low-accuracy words
    words.sort(key=lambda w: (
        w.get("times_correct", 0) / max(w.get("times_tested", 1), 1)
    ))
    quiz_words = words[:n]
    random.shuffle(quiz_words)

    if not speak_fn or not listen_fn:
        # Non-interactive mode — just list words
        lines = [f"Your {language} vocabulary ({len(words)} words):"]
        for w in words[:10]:
            lines.append(f"  {w['original']} = {w['translation']}")
        return "\n".join(lines)

    score = 0
    for word in quiz_words:
        # Alternate direction
        if random.random() > 0.5:
            question = f"What is the {language} for '{word['original']}'?"
            correct  = word["translation"]
        else:
            question = f"What does '{word['translation']}' mean?"
            correct  = word["original"]

        speak_fn(question)
        answer = listen_fn(timeout=10.0) if listen_fn else ""

        # Grade with LLM
        verdict = "incorrect"
        if answer and llm_caller:
            v = llm_caller(
                f"Is '{answer}' a correct answer for: {question}\n"
                f"Correct answer: {correct}\n"
                f"Reply with only 'correct' or 'incorrect'."
            ).lower().strip()
            verdict = "correct" if "correct" in v and "incorrect" not in v else "incorrect"

        # Update stats
        word["times_tested"] = word.get("times_tested", 0) + 1
        if verdict == "correct":
            score += 1
            word["times_correct"] = word.get("times_correct", 0) + 1
            speak_fn(f"Correct!")
        else:
            speak_fn(f"Not quite. The answer is: {correct}")

    _save_vocab(vocab)
    pct = int(score / len(quiz_words) * 100) if quiz_words else 0
    return (
        f"Quiz complete. {score}/{len(quiz_words)} — {pct}%. "
        + ("Excellent!" if pct >= 80 else "Keep practising!")
    )


# ---------------------------------------------------------------------------
# Daily word
# ---------------------------------------------------------------------------

def daily_word(language: str = "de") -> str:
    """Return a random word from vocabulary for daily practice."""
    vocab = _load_vocab()
    words = [w for w in vocab.get("known_words", [])
             if w.get("language") == language]
    if not words:
        return ""
    word = random.choice(words)
    lang_names = {"de": "German", "en": "English"}
    lang = lang_names.get(language, language)
    return f"Your {lang} word of the day: {word['translation']} -- {word['original']}."


# ---------------------------------------------------------------------------
# Grammar explanation
# ---------------------------------------------------------------------------

def explain_grammar(question: str, llm_caller=None) -> str:
    """Explain a grammar rule simply via LLM."""
    if not llm_caller:
        return "Grammar explanation needs LLM (Ollama)."
    return llm_caller(
        f"Explain this grammar rule simply for a beginner: {question}. "
        f"Use short sentences and give 1-2 examples."
    )


# ---------------------------------------------------------------------------
# STT Corrections
# ---------------------------------------------------------------------------

def apply_corrections(text: str) -> str:
    """Apply user-defined STT corrections to transcribed text."""
    vocab = _load_vocab()
    for correction in vocab.get("corrections", []):
        heard   = correction.get("heard", "")
        correct = correction.get("correct", "")
        if heard and correct:
            text = text.replace(heard, correct)
            text = text.replace(heard.title(), correct)
    return text


def add_correction(heard: str, correct: str) -> str:
    """Add a new STT correction."""
    vocab = _load_vocab()
    corrections = vocab.get("corrections", [])
    # Remove existing
    corrections = [c for c in corrections if c.get("heard", "").lower() != heard.lower()]
    corrections.append({"heard": heard.lower(), "correct": correct})
    vocab["corrections"] = corrections
    _save_vocab(vocab)
    return f"Got it -- I'll auto-correct '{heard}' to '{correct}' in future."


def get_vocab_stats() -> str:
    """Return vocabulary statistics."""
    vocab = _load_vocab()
    words = vocab.get("known_words", [])
    if not words:
        return "No vocabulary saved yet."
    by_lang: dict[str, int] = {}
    for w in words:
        lang = w.get("language", "?")
        by_lang[lang] = by_lang.get(lang, 0) + 1
    lang_str = ", ".join(f"{v} {k}" for k, v in by_lang.items())
    return f"Vocabulary: {len(words)} words total -- {lang_str}."
