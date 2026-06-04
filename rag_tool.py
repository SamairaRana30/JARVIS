"""
rag_tool.py — Local Document RAG (Retrieval-Augmented Generation).

Uses ChromaDB for vector storage and sentence-transformers for embeddings.
Everything runs locally — no cloud APIs.

Indexes:
  - notes/ (all markdown notes)
  - Any PDF you ask it to index
  - data/ JSON files for structured queries

Usage:
  "Jarvis, what do my notes say about CSS flexbox?"
  "Jarvis, explain this PDF" (path from clipboard or voice)
  "Jarvis, search my documents for auth flow"
  "Jarvis, index my notes" (manual trigger)
"""

import hashlib
import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()
CHROMA_DIR = BASE_DIR / "data" / "chroma_db"
COLLECTION_NAME = "jarvis_docs"

_client     = None
_collection = None
_lock       = threading.Lock()


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# ChromaDB client (lazy init)
# ---------------------------------------------------------------------------

def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection
    with _lock:
        if _collection is not None:
            return _collection
        try:
            import chromadb  # type: ignore
            from chromadb.utils import embedding_functions  # type: ignore
        except ImportError:
            raise RuntimeError(
                "chromadb not installed. Run: pip install chromadb sentence-transformers"
            )

        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))

        # Use sentence-transformers for local embeddings (no API key)
        try:
            print("Loading language model for document search (first run may take a minute)...")
            ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            print("Language model ready.")
        except Exception as e:
            logger.warning("sentence-transformers not available, using default embeddings: %s", e)
            ef = embedding_functions.DefaultEmbeddingFunction()

        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB collection ready: %d documents indexed.", _collection.count())
    return _collection


def _doc_id(source: str, chunk_idx: int) -> str:
    h = hashlib.md5(f"{source}:{chunk_idx}".encode()).hexdigest()[:8]
    return f"{Path(source).stem}_{chunk_idx}_{h}"


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks for better retrieval."""
    words  = text.split()
    chunks = []
    i      = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return [c for c in chunks if len(c.strip()) > 40]


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def index_file(path: str | Path, force: bool = False) -> int:
    """
    Index a single file (markdown or PDF) into ChromaDB.
    Returns the number of chunks added.
    """
    path = Path(path)
    if not path.exists():
        return 0

    col = _get_collection()

    # Extract text
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
            reader = PdfReader(str(path))
            text = "\n".join(p.extract_text() or "" for p in reader.pages).strip()
        except Exception as e:
            logger.warning("PDF read failed %s: %s", path, e)
            return 0
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Strip markdown frontmatter
        if text.startswith("---"):
            text = text.split("---", 2)[-1].strip()

    if not text or len(text) < 50:
        return 0

    # Check if already indexed (by checking a hash in metadata)
    file_hash = hashlib.md5(text.encode()).hexdigest()
    source    = str(path.relative_to(BASE_DIR))

    # Remove old chunks from this source if re-indexing
    if force:
        try:
            existing = col.get(where={"source": source})
            if existing["ids"]:
                col.delete(ids=existing["ids"])
        except Exception:
            pass

    chunks = _chunk_text(text)
    if not chunks:
        return 0

    ids       = [_doc_id(source, i) for i in range(len(chunks))]
    metadatas = [
        {"source": source, "file": path.name, "hash": file_hash,
         "chunk": i, "indexed": datetime.now().isoformat()}
        for i in range(len(chunks))
    ]

    try:
        col.upsert(ids=ids, documents=chunks, metadatas=metadatas)
        logger.debug("Indexed %d chunks from %s", len(chunks), path.name)
        return len(chunks)
    except Exception as e:
        logger.error("Indexing failed for %s: %s", path, e)
        return 0


def index_notes(speak_fn=None) -> str:
    """Index all notes in the notes/ directory."""
    notes_dir = BASE_DIR / "notes"
    if not notes_dir.exists():
        return "No notes directory found."

    if speak_fn:
        speak_fn("Indexing your notes. This may take a moment on first run.")

    files  = list(notes_dir.rglob("*.md"))
    total  = 0
    for f in files:
        total += index_file(f)

    msg = f"Indexed {len(files)} notes into {total} searchable chunks."
    logger.info(msg)
    if speak_fn:
        speak_fn(msg)
    return msg


def index_pdf(path: str, speak_fn=None) -> str:
    """Index a single PDF file."""
    n = index_file(path)
    msg = f"Indexed {n} chunks from {Path(path).name}." if n else f"Could not index {Path(path).name}."
    if speak_fn:
        speak_fn(msg)
    return msg


_META_PATH = BASE_DIR / "data" / "rag_index_meta.json"


def _load_meta() -> dict:
    try:
        return json.loads(_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"last_indexed": {}, "first_run": True}


def _save_meta(meta: dict) -> None:
    _META_PATH.parent.mkdir(parents=True, exist_ok=True)
    _META_PATH.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")


def index_all(speak_fn=None) -> str:
    """Full re-index of all documents."""
    return index_incremental(speak_fn=speak_fn, force=True)


def index_incremental(speak_fn=None, force: bool = False) -> str:
    """
    Incremental indexing -- only re-index files modified since last run.
    Tracks modification times in data/rag_index_meta.json.
    First run: indexes everything and speaks a loading message.
    """
    meta      = _load_meta()
    is_first  = meta.get("first_run", True) or force
    last_times = meta.get("last_indexed", {})

    if is_first and speak_fn:
        speak_fn("Building knowledge base for the first time. This takes a minute.")
    elif is_first:
        print("RAG: First-run full index starting...")

    # Collect all indexable sources
    sources: list[Path] = []
    for folder in ["notes", "data/journal", "logs/conversations"]:
        d = BASE_DIR / folder
        if d.exists():
            sources.extend(d.rglob("*.md"))
    for folder in ["docs", "documents"]:
        d = BASE_DIR / folder
        if d.exists():
            sources.extend(d.rglob("*.pdf"))

    files_indexed = 0
    chunks_total  = 0

    for path in sources:
        try:
            mtime = path.stat().st_mtime
            key   = str(path.relative_to(BASE_DIR))
            if not force and not is_first:
                last = float(last_times.get(key, 0))
                if mtime <= last:
                    continue   # unchanged — skip
            n = index_file(path, force=True)
            if n:
                files_indexed += 1
                chunks_total  += n
            last_times[key] = mtime
        except Exception as e:
            logger.warning("RAG index error %s: %s", path, e)

    meta["last_indexed"] = last_times
    meta["first_run"]    = False
    _save_meta(meta)

    if is_first:
        msg = f"Knowledge base ready. Indexed {files_indexed} documents, {chunks_total} chunks."
    elif files_indexed:
        msg = f"Knowledge base updated. {files_indexed} new/changed files indexed."
    else:
        msg = ""   # nothing changed — silent

    if msg:
        logger.info("RAG: %s", msg)
        if speak_fn:
            speak_fn(msg)
    return msg or f"Knowledge base current. {len(sources)} files tracked."


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def search(query: str, n_results: int = 5) -> list[dict]:
    """
    Semantic search over indexed documents.
    Returns list of {text, source, score}.
    """
    try:
        col = _get_collection()
        if col.count() == 0:
            return []
        results = col.query(
            query_texts=[query],
            n_results=min(n_results, col.count()),
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            hits.append({
                "text":   doc,
                "source": meta.get("source", "?"),
                "file":   meta.get("file", "?"),
                "score":  round(1 - dist, 3),   # cosine similarity
            })
        return hits
    except Exception as e:
        logger.error("RAG search error: %s", e)
        return []


def ask(question: str, llm_caller=None, n_context: int = 4) -> str:
    """
    Full RAG pipeline: retrieve relevant chunks → feed to LLM → answer.
    Falls back to pure LLM if no documents indexed.
    """
    hits = search(question, n_results=n_context)

    if not hits:
        # No documents indexed — try to answer from LLM directly
        if llm_caller:
            return llm_caller(question)
        return "No documents indexed yet. Say 'index my notes' to build the knowledge base."

    # Build context
    context_parts = []
    sources_seen  = set()
    for hit in hits:
        if hit["score"] < 0.2:   # too distant — skip
            continue
        context_parts.append(hit["text"])
        sources_seen.add(hit["file"])

    if not context_parts:
        if llm_caller:
            return llm_caller(question)
        return "I couldn't find relevant information in your documents."

    context = "\n\n---\n\n".join(context_parts[:n_context])
    sources = ", ".join(sorted(sources_seen))

    if llm_caller:
        prompt = (
            f"Answer the question using ONLY the context below. "
            f"If the answer isn't in the context, say so.\n\n"
            f"Context (from your documents: {sources}):\n{context}\n\n"
            f"Question: {question}\n\nAnswer:"
        )
        answer = llm_caller(prompt)
        return f"{answer}\n[Sources: {sources}]"

    # No LLM — return raw context
    return f"Found in {sources}:\n{context_parts[0][:400]}..."


def get_stats() -> str:
    """Return indexing stats."""
    try:
        col   = _get_collection()
        count = col.count()
        if count == 0:
            return "Knowledge base is empty. Say 'index my notes' to get started."
        # Count unique sources
        results = col.get(include=["metadatas"])
        sources = set(m.get("file","?") for m in results["metadatas"])
        return (
            f"Knowledge base: {count} chunks from {len(sources)} documents. "
            f"Files: {', '.join(sorted(sources)[:5])}."
        )
    except Exception as e:
        return f"Knowledge base unavailable: {e}"
