"""
flashcard_tool.py — Study flashcards generated from your notes.
"Jarvis, quiz me on my CSS notes" → Jarvis asks questions, waits for answers.

Session state is kept in RAM only.
"""

import logging
import random
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()

# Active quiz session state
_quiz_deck:    list[dict] = []    # [{"question": ..., "answer": ...}]
_quiz_index:   int        = 0
_quiz_score:   int        = 0
_quiz_total:   int        = 0
_quiz_active:  bool       = False
_awaiting_answer: bool    = False


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _extract_qa_from_text(text: str, llm_caller) -> list[dict]:
    """Ask LLM to extract Q&A pairs from a block of text."""
    raw = llm_caller(
        "Extract 5 study flashcard question-and-answer pairs from the text below. "
        "Format each as:\nQ: [question]\nA: [answer]\n\n"
        f"Text:\n{text[:2000]}"
    )
    pairs = []
    lines = raw.splitlines()
    q = a = None
    for line in lines:
        line = line.strip()
        if line.startswith("Q:"):
            q = line[2:].strip()
        elif line.startswith("A:") and q:
            a = line[2:].strip()
            if q and a:
                pairs.append({"question": q, "answer": a})
            q = a = None
    return pairs


def start_quiz(topic: str, llm_caller) -> str:
    """
    Find notes matching topic, extract Q&A pairs, start a quiz session.
    """
    global _quiz_deck, _quiz_index, _quiz_score, _quiz_total, _quiz_active, _awaiting_answer

    try:
        import json
        cfg   = _load_cfg()
        paths = cfg.get("paths", {})
        idx_path = BASE_DIR / paths.get("notes_index", "data/notes_index.json")
        index = json.loads(idx_path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"Couldn't load notes: {e}"

    q = topic.lower()
    matches = [
        n for n in index
        if q in n.get("title", "").lower()
        or q in n.get("preview", "").lower()
        or q in n.get("topic", "").lower()
        or any(q in tag.lower() for tag in n.get("tags", []))
    ]

    if not matches:
        return f"No notes found about '{topic}'. Take some notes first."

    # Read content of matched notes
    combined = []
    for note in matches[:3]:
        try:
            path = BASE_DIR / note["path"]
            text = path.read_text(encoding="utf-8")
            if text.startswith("---"):
                text = text.split("---", 2)[-1].strip()
            combined.append(text)
        except Exception:
            combined.append(note.get("preview", ""))

    full_text = "\n\n".join(combined)
    if not full_text.strip():
        return f"Your notes about '{topic}' appear to be empty."

    pairs = _extract_qa_from_text(full_text, llm_caller)
    if not pairs:
        return f"Couldn't generate flashcards from your {topic} notes. Try taking more detailed notes."

    random.shuffle(pairs)
    _quiz_deck     = pairs
    _quiz_index    = 0
    _quiz_score    = 0
    _quiz_total    = len(pairs)
    _quiz_active   = True
    _awaiting_answer = True

    logger.info("Flashcard quiz started: %d cards for topic '%s'.", _quiz_total, topic)
    return (
        f"Starting a {_quiz_total}-card quiz on {topic}. "
        f"I'll ask you a question — just say your answer. "
        f"Question 1: {_quiz_deck[0]['question']}"
    )


def submit_answer(user_answer: str, llm_caller) -> str:
    """
    Grade the user's answer to the current flashcard.
    Uses LLM for flexible grading.
    """
    global _quiz_index, _quiz_score, _awaiting_answer

    if not _quiz_active or not _awaiting_answer:
        return "No active quiz. Say 'quiz me on [topic]' to start one."

    card   = _quiz_deck[_quiz_index]
    correct_answer = card["answer"]

    # LLM-based flexible grading
    verdict = llm_caller(
        f"Is this answer correct? Reply with only 'correct' or 'incorrect'.\n"
        f"Question: {card['question']}\n"
        f"Correct answer: {correct_answer}\n"
        f"User's answer: {user_answer}"
    ).lower().strip()

    if "correct" in verdict and "incorrect" not in verdict:
        _quiz_score += 1
        feedback = f"Correct! {correct_answer}."
    else:
        feedback = f"Not quite. The answer is: {correct_answer}."

    _quiz_index += 1
    _awaiting_answer = False

    if _quiz_index >= _quiz_total:
        return end_quiz() + " " + feedback

    # Next question
    _awaiting_answer = True
    next_q = _quiz_deck[_quiz_index]["question"]
    return (
        f"{feedback} "
        f"Question {_quiz_index + 1} of {_quiz_total}: {next_q}"
    )


def end_quiz() -> str:
    global _quiz_active, _awaiting_answer, _quiz_deck, _quiz_index, _quiz_score, _quiz_total
    if not _quiz_active:
        return "No quiz is running."
    score = _quiz_score
    total = _quiz_total
    _quiz_active = _awaiting_answer = False
    _quiz_deck = []
    _quiz_index = _quiz_score = _quiz_total = 0
    pct = int(score / total * 100) if total else 0
    verdict = "Excellent!" if pct >= 80 else ("Good effort!" if pct >= 50 else "Keep studying!")
    return f"Quiz complete. You got {score} out of {total} — {pct}%. {verdict}"


def quiz_status() -> str:
    if not _quiz_active:
        return "No quiz running. Say 'quiz me on [topic]' to start."
    return (
        f"Quiz in progress: question {_quiz_index + 1} of {_quiz_total}. "
        f"Score so far: {_quiz_score}."
    )


def is_quiz_awaiting_answer() -> bool:
    return _quiz_active and _awaiting_answer
