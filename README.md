JARVIS — Local AI Personal Assistant

A privacy-first, fully local AI assistant for Windows: wake-word voice control, a local LLM for reasoning, a desktop HUD dashboard, and 40+ built-in tools covering calendar, budget, study, and daily life — no cloud AI subscription, no data leaving the machine by default.

Overview
Wake word: always-listening detection via openWakeWord (custom "Jarvis" ONNX model), with echo suppression while Jarvis is speaking and a cooldown window to prevent false retriggers
Speech-to-text: faster-whisper, voice-activity gated so silence never reaches the model, cached fully offline after first download
Reasoning: a locally-hosted LLM via Ollama (Llama 3), with automatic crash detection, process restart, and retry
Speech output: edge-tts, with fully offline Piper TTS as a fallback
Interface: a PyQt6 "HUD" desktop dashboard plus a system tray app
Language: bilingual English/German — auto-detects the spoken language from Whisper and switches the assistant's voice and responses mid-conversation
Architecture
Component	Responsibility
jarvis.py	Core loop — wires together session state, STT, intent routing, the LLM, TTS, transcripts, and memory
intent_router.py	Fast-path pattern matching for common commands, so simple requests skip the LLM entirely
tools.py + tool modules	40+ discrete tools: calendar, budget, closet/outfit stylist, email, focus tracking, flashcards, journaling, meetings, news, notifications, Notion, Spotify, study/Pomodoro tracking, WhatsApp, Wikipedia, and more
memory/	Long-term fact extraction, session summaries, and goal tracking, backed by a local RAG index (ChromaDB + sentence-transformers)
proactive_engine.py / scheduler.py	Time-based check-ins and briefings (morning/evening, weekly review)
plugin_loader.py / plugins/	Plugin system for adding new tools without touching core logic
whatsapp_bridge/	Node.js bridge for WhatsApp messaging integration
ui/	PyQt6 HUD dashboard
Notable engineering details
Robust voice pipeline: filters STT noise (single-word fillers like "um"/"yeah"), suppresses the assistant's own voice from re-triggering the wake word, and enforces a cooldown between activations
LLM context management: when conversation history approaches the model's context window, older turns are automatically summarized by a second LLM call and replaced with that summary, keeping recent turns verbatim instead of silently truncating
Self-healing LLM connection: detects when the local Ollama process has died, attempts an automatic restart, and retries the failed request once before falling back gracefully
Bilingual by design: language is detected per-utterance from Whisper's output; both the assistant's spoken responses and fast-path tool replies switch language automatically mid-session
Tested: a 12-file pytest suite covering budget, closet, alarms, notes, Pomodoro, memory, and end-to-end integration flows
Privacy-conscious by construction: the committed config.yaml ships with every credential field (Notion token, Google app password, Spotify keys) left blank as a template — nothing is hardcoded — and .gitignore excludes personal data (journal, memory, conversation logs) and WhatsApp auth sessions from version control
Tech stack

Python · Ollama (Llama 3) · faster-whisper · openWakeWord · edge-tts / Piper TTS · PyQt6 · ChromaDB · sentence-transformers · pytest · Notion API · CalDAV (Google Calendar) · WhatsApp Web bridge (Node.js)

Status

v0.1.0 — built for daily personal use, actively evolving.
