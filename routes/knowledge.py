"""
routes/knowledge.py — RAG Knowledge Base for TrintzERP

Endpoints (all under /api prefix via Blueprint):
  GET    /api/knowledge/documents              — list documents (admin)
  POST   /api/knowledge/documents              — upload + ingest doc (admin)
  DELETE /api/knowledge/documents/<id>         — delete doc + chunks (admin)
  PATCH  /api/knowledge/documents/<id>/toggle  — toggle is_active (admin)
  POST   /api/knowledge/documents/<id>/reindex — re-embed doc (admin)
  POST   /api/knowledge/chat                   — RAG chat (permission: ai-chat)
  GET    /api/knowledge/embed-status           — check embed support (admin)
  GET    /api/knowledge/stats                  — document/chunk counts (admin)
"""

import io
import json
import logging
import threading
from datetime import datetime

import requests
from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_db_connection, release_db_connection
from auth import admin_required, permission_required

logger = logging.getLogger(__name__)
knowledge_bp = Blueprint('knowledge', __name__)

# ── Embedding provider defaults ───────────────────────────────────────────────
_EMBED_DEFAULTS = {
    'openai':   {'model': 'text-embedding-3-small', 'dim': 1536},
    'ollama':   {'model': 'nomic-embed-text',        'dim': None},
    'gemini':   {'model': 'text-embedding-004',      'dim': 768},
    'together': {'model': 'togethercomputer/m2-bert-80M-8k-retrieval', 'dim': 768},
}

_UNSUPPORTED_PROVIDERS = {
    'anthropic': 'Anthropic Claude does not provide an embeddings API. Configure OpenAI, Ollama, Gemini, or Together AI as your active provider to use the Knowledge Base.',
    'groq':      'Groq does not provide an embeddings API. Configure OpenAI, Ollama, Gemini, or Together AI as your active provider to use the Knowledge Base.',
    'mistral':   'Mistral AI does not expose a standalone embeddings endpoint in this integration. Configure OpenAI, Ollama, Gemini, or Together AI.',
    'minimax':   'MiniMax does not provide a supported embeddings API. Configure OpenAI, Ollama, Gemini, or Together AI.',
    'mimo':      'Xiaomi MiMo does not provide a supported embeddings API. Configure OpenAI, Ollama, Gemini, or Together AI.',
}


# ── Schema migration (run once per process start) ─────────────────────────────
_SCHEMA_ENSURED = False

def _ensure_schema():
    """Create kb_documents and kb_chunks tables + embed_model column if absent."""
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Enable pgvector
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.warning("Could not create vector extension (may already exist or need superuser): %s", e)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS kb_documents (
                    id          SERIAL        PRIMARY KEY,
                    title       VARCHAR(255)  NOT NULL,
                    description TEXT          NOT NULL DEFAULT '',
                    source_type VARCHAR(20)   NOT NULL DEFAULT 'text',
                    file_name   VARCHAR(255),
                    char_count  INTEGER       NOT NULL DEFAULT 0,
                    chunk_count INTEGER       NOT NULL DEFAULT 0,
                    status      VARCHAR(20)   NOT NULL DEFAULT 'ready',
                    error_msg   TEXT,
                    is_active   BOOLEAN       NOT NULL DEFAULT TRUE,
                    created_by  INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
                    created_at  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS kb_chunks (
                    id          SERIAL  PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    content     TEXT    NOT NULL,
                    embedding   vector,
                    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_kb_chunks_document
                ON kb_chunks(document_id)
            """)

            # Full-text search column — fallback when embeddings are unavailable
            try:
                cur.execute("""
                    ALTER TABLE kb_chunks
                    ADD COLUMN IF NOT EXISTS content_tsv tsvector
                    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_kb_chunks_fts
                    ON kb_chunks USING gin(content_tsv)
                """)
                conn.commit()
            except Exception:
                conn.rollback()

            # Migration: add embed_model to ai_settings if not present
            cur.execute("""
                ALTER TABLE ai_settings
                ADD COLUMN IF NOT EXISTS embed_model VARCHAR(150) DEFAULT ''
            """)

            conn.commit()
        _SCHEMA_ENSURED = True
    except Exception as e:
        conn.rollback()
        logger.error("Knowledge schema ensure failed: %s", e)
    finally:
        release_db_connection(conn)


# ── Config helpers ────────────────────────────────────────────────────────────

def _get_embed_config() -> dict:
    """
    Load the active AI config from DB.
    Always returns a config dict. Sets 'embed_supported': True/False so callers
    can decide whether to attempt embedding or fall back to full-text search.
    Never raises for unsupported providers — they just get embed_supported=False.
    """
    _ensure_schema()
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM ai_settings WHERE is_active = TRUE LIMIT 1")
            row = cur.fetchone()
    finally:
        release_db_connection(conn)

    if not row:
        raise RuntimeError(
            "No active AI provider is configured. Go to Admin → AI Settings to set up and activate a provider."
        )

    config = dict(row)
    provider = config.get('provider', '')

    if provider in _UNSUPPORTED_PROVIDERS or provider not in _EMBED_DEFAULTS:
        config['embed_supported'] = False
        config['embed_reason'] = (
            _UNSUPPORTED_PROVIDERS.get(provider)
            or f"Provider '{provider}' does not support embeddings. "
               "Using full-text search instead. "
               "Switch to OpenAI, Ollama, Gemini, or Together AI for semantic search."
        )
        return config

    # Set default embed_model if not explicitly configured
    embed_model = (config.get('embed_model') or '').strip()
    config['embed_model']      = embed_model or _EMBED_DEFAULTS[provider]['model']
    config['embed_supported']  = True
    config['embed_reason']     = ''
    return config


# ── Embedding call ─────────────────────────────────────────────────────────────

def _embed(text: str, config: dict) -> list:
    """
    Call the provider embedding API and return a list of floats.
    """
    provider  = config.get('provider', '')
    api_key   = config.get('api_key', '')
    base_url  = (config.get('api_base_url') or '').rstrip('/')
    model     = config.get('embed_model', '')

    if provider == 'openai':
        base = base_url or 'https://api.openai.com/v1'
        r = requests.post(
            f'{base}/embeddings',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': model, 'input': text},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()['data'][0]['embedding']

    elif provider == 'ollama':
        base = base_url or 'http://localhost:11434'
        hdrs = {'Content-Type': 'application/json'}
        if api_key:
            hdrs['Authorization'] = f'Bearer {api_key}'
        # /api/embed is the current endpoint (Ollama 0.1.26+)
        # /api/embeddings is the legacy endpoint — try new first, fall back
        try:
            r = requests.post(
                f'{base}/api/embed',
                headers=hdrs,
                json={'model': model, 'input': text},
                timeout=60,
            )
            if r.status_code != 404:
                r.raise_for_status()
                return r.json()['embeddings'][0]
        except Exception:
            pass
        r = requests.post(
            f'{base}/api/embeddings',
            headers=hdrs,
            json={'model': model, 'prompt': text},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()['embedding']

    elif provider == 'gemini':
        r = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={api_key}',
            json={
                'model': f'models/{model}',
                'content': {'parts': [{'text': text}]},
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()['embedding']['values']

    elif provider == 'together':
        r = requests.post(
            'https://api.together.xyz/v1/embeddings',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': model, 'input': text},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()['data'][0]['embedding']

    else:
        raise RuntimeError(
            f"Provider '{provider}' does not support embeddings. "
            "Use openai, ollama, gemini, or together."
        )


# ── Text utilities ─────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_words: int = 300, overlap: int = 50) -> list:
    """
    Split text into word-boundary chunks with overlap.
    Returns a list of non-empty string chunks.
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    step = max(1, chunk_words - overlap)
    start = 0
    while start < len(words):
        end = min(start + chunk_words, len(words))
        chunk = ' '.join(words[start:end])
        if chunk.strip():
            chunks.append(chunk.strip())
        if end >= len(words):
            break
        start += step
    return chunks


def _extract_text(content_bytes: bytes, mime_type: str) -> str:
    """
    Extract plain text from bytes.
    For PDF: tries PyMuPDF (fitz) first, then pdfplumber.
    For other types: UTF-8 decode.
    Raises RuntimeError with pip install hint if no PDF library available.
    """
    is_pdf = (
        mime_type in ('application/pdf', 'application/x-pdf')
        or mime_type.startswith('application/pdf')
    )

    if is_pdf:
        # Try PyMuPDF first (faster)
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=content_bytes, filetype='pdf')
            pages = []
            for page in doc:
                pages.append(page.get_text())
            doc.close()
            return '\n'.join(pages)
        except ImportError:
            pass
        except Exception as e:
            logger.warning("PyMuPDF failed, trying pdfplumber: %s", e)

        # Fall back to pdfplumber
        try:
            import pdfplumber
            pages = []
            with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        pages.append(t)
            return '\n'.join(pages)
        except ImportError:
            pass
        except Exception as e:
            logger.warning("pdfplumber failed: %s", e)
            raise RuntimeError(f"PDF extraction failed: {e}. Try installing PyMuPDF: pip install PyMuPDF")

        raise RuntimeError(
            "No PDF library is installed. Install one to enable PDF uploads:\n"
            "  pip install PyMuPDF\n"
            "or\n"
            "  pip install pdfplumber"
        )

    # Plain text / unknown: UTF-8 decode
    try:
        return content_bytes.decode('utf-8')
    except UnicodeDecodeError:
        return content_bytes.decode('latin-1', errors='replace')


# ── Background ingest ──────────────────────────────────────────────────────────

def _ingest_document(doc_id: int, text: str, config: dict):
    """
    Chunk text → (optionally) embed each chunk → store in kb_chunks.
    If provider does not support embeddings, stores text-only chunks and
    relies on PostgreSQL full-text search (content_tsv) at query time.
    Runs in a background thread.
    """
    try:
        chunks = _chunk_text(text)
        if not chunks:
            _set_doc_error(doc_id, "Document produced no text chunks after processing.")
            return

        embed_supported = config.get('embed_supported', True)
        results = []   # list of (idx, chunk, vec_str | None)

        if embed_supported:
            for idx, chunk in enumerate(chunks):
                try:
                    vec = _embed(chunk, config)
                    vec_str = '[' + ','.join(str(f) for f in vec) + ']'
                    results.append((idx, chunk, vec_str))
                except Exception as e:
                    logger.warning(
                        "Embedding chunk %d for doc %d failed (%s) — storing text-only.",
                        idx, doc_id, e
                    )
                    results.append((idx, chunk, None))
        else:
            # Provider does not support embeddings — store text only
            logger.info(
                "Doc %d: provider has no embedding support, storing text-only chunks "
                "(full-text search will be used at query time).", doc_id
            )
            results = [(idx, chunk, None) for idx, chunk in enumerate(chunks)]

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM kb_chunks WHERE document_id = %s", (doc_id,))

                for idx, chunk, vec_str in results:
                    if vec_str is not None:
                        cur.execute(
                            """
                            INSERT INTO kb_chunks (document_id, chunk_index, content, embedding)
                            VALUES (%s, %s, %s, %s::vector)
                            """,
                            (doc_id, idx, chunk, vec_str),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO kb_chunks (document_id, chunk_index, content)
                            VALUES (%s, %s, %s)
                            """,
                            (doc_id, idx, chunk),
                        )

                embedded_count = sum(1 for _, _, v in results if v is not None)
                cur.execute(
                    """
                    UPDATE kb_documents
                    SET status      = 'ready',
                        chunk_count = %s,
                        char_count  = %s,
                        error_msg   = %s,
                        updated_at  = %s
                    WHERE id = %s
                    """,
                    (
                        len(results),
                        len(text),
                        None if embedded_count == len(results)
                        else f'Text-only mode: {embedded_count}/{len(results)} chunks embedded. '
                             f'Using full-text search. Switch to OpenAI/Ollama/Gemini for semantic search.',
                        datetime.utcnow(),
                        doc_id,
                    ),
                )
                conn.commit()
        finally:
            release_db_connection(conn)

        logger.info("Document %d ingested: %d chunks (%d embedded, %d text-only).",
                    doc_id, len(results), embedded_count, len(results) - embedded_count)

    except Exception as e:
        logger.exception("Ingest error for doc %d: %s", doc_id, e)
        _set_doc_error(doc_id, str(e))


def _set_doc_error(doc_id: int, msg: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_documents
                SET status = 'error', error_msg = %s, updated_at = %s
                WHERE id = %s
                """,
                (msg[:2000], datetime.utcnow(), doc_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("Could not set doc error state for doc %d: %s", doc_id, e)
    finally:
        release_db_connection(conn)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@knowledge_bp.route('/knowledge/documents', methods=['GET'])
@admin_required
def list_documents(current_user):
    """List all knowledge base documents."""
    _ensure_schema()
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT d.id, d.title, d.description, d.source_type, d.file_name,
                       d.char_count, d.chunk_count, d.status, d.error_msg,
                       d.is_active, d.created_at, d.updated_at,
                       u.username AS created_by_username
                FROM kb_documents d
                LEFT JOIN users u ON u.user_id = d.created_by
                ORDER BY d.created_at DESC
            """)
            rows = cur.fetchall()
        docs = []
        for r in rows:
            d = dict(r)
            d['created_at'] = d['created_at'].isoformat() if d.get('created_at') else None
            d['updated_at'] = d['updated_at'].isoformat() if d.get('updated_at') else None
            docs.append(d)
        return jsonify({'documents': docs})
    finally:
        release_db_connection(conn)


@knowledge_bp.route('/knowledge/documents', methods=['POST'])
@admin_required
def upload_document(current_user):
    """
    Upload a plain-text or PDF document.
    Immediately creates a DB record with status='processing',
    then spawns a background thread to chunk+embed it.
    Returns {id, status: 'processing'} immediately.
    """
    _ensure_schema()

    title       = (request.form.get('title') or '').strip()
    description = (request.form.get('description') or '').strip()

    if not title:
        return jsonify({'error': 'Title is required.'}), 400

    # Determine source: uploaded file or plain text body
    file_obj  = request.files.get('file')
    text_body = (request.form.get('content') or '').strip()

    if file_obj and file_obj.filename:
        _ALLOWED_MIME = {
            'application/pdf', 'text/plain', 'text/csv',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        }
        _MAX_BYTES = 20 * 1024 * 1024  # 20 MB

        content_bytes = file_obj.read()
        if len(content_bytes) > _MAX_BYTES:
            return jsonify({'error': 'File too large. Maximum size is 20 MB.'}), 413

        mime_type = file_obj.content_type or 'application/octet-stream'
        file_name = file_obj.filename

        # Validate by extension as well as MIME
        ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else ''
        if mime_type not in _ALLOWED_MIME and ext not in ('pdf', 'txt', 'csv', 'doc', 'docx'):
            return jsonify({'error': f'File type not allowed: {mime_type}. '
                                      'Upload PDF, TXT, CSV, or Word documents.'}), 415

        source_type = 'pdf' if 'pdf' in mime_type.lower() or ext == 'pdf' else 'file'
    elif text_body:
        content_bytes = text_body.encode('utf-8')
        mime_type     = 'text/plain'
        file_name     = None
        source_type   = 'text'
    else:
        return jsonify({'error': 'Provide either a file upload or text content.'}), 400

    # Load config — never blocks on unsupported providers (falls back to FTS)
    try:
        config = _get_embed_config()
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503   # only fires if NO provider configured at all

    # Extract text
    try:
        raw_text = _extract_text(content_bytes, mime_type)
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 400

    if not raw_text.strip():
        return jsonify({'error': 'The document appears to be empty or could not be parsed.'}), 400

    created_by = current_user.get('user_id')

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO kb_documents
                    (title, description, source_type, file_name, status, created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'processing', %s, %s, %s)
                RETURNING id
                """,
                (title, description, source_type, file_name, created_by,
                 datetime.utcnow(), datetime.utcnow()),
            )
            doc_id = cur.fetchone()['id']
            conn.commit()
    finally:
        release_db_connection(conn)

    # Kick off background ingest
    t = threading.Thread(
        target=_ingest_document,
        args=(doc_id, raw_text, config),
        daemon=True,
    )
    t.start()

    return jsonify({'id': doc_id, 'status': 'processing'}), 202


@knowledge_bp.route('/knowledge/documents/<int:doc_id>', methods=['DELETE'])
@admin_required
def delete_document(current_user, doc_id):
    """Delete a document and all its chunks (CASCADE)."""
    _ensure_schema()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM kb_documents WHERE id = %s RETURNING id", (doc_id,))
            deleted = cur.fetchone()
            conn.commit()
        if not deleted:
            return jsonify({'error': 'Document not found.'}), 404
        return jsonify({'message': 'Document deleted.'})
    finally:
        release_db_connection(conn)


@knowledge_bp.route('/knowledge/documents/<int:doc_id>/toggle', methods=['PATCH'])
@admin_required
def toggle_document(current_user, doc_id):
    """Toggle is_active on a document."""
    _ensure_schema()
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT is_active FROM kb_documents WHERE id = %s", (doc_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'Document not found.'}), 404
            new_val = not row['is_active']
            cur.execute(
                "UPDATE kb_documents SET is_active = %s, updated_at = %s WHERE id = %s",
                (new_val, datetime.utcnow(), doc_id),
            )
            conn.commit()
        return jsonify({'id': doc_id, 'is_active': new_val})
    finally:
        release_db_connection(conn)


@knowledge_bp.route('/knowledge/documents/<int:doc_id>/reindex', methods=['POST'])
@admin_required
def reindex_document(current_user, doc_id):
    """Re-embed an existing document (re-runs ingest on existing text from chunks)."""
    _ensure_schema()

    try:
        config = _get_embed_config()
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Fetch existing chunks to reconstruct text
            cur.execute(
                "SELECT content FROM kb_chunks WHERE document_id = %s ORDER BY chunk_index",
                (doc_id,),
            )
            chunk_rows = cur.fetchall()

            cur.execute("SELECT id, title FROM kb_documents WHERE id = %s", (doc_id,))
            doc = cur.fetchone()
            if not doc:
                return jsonify({'error': 'Document not found.'}), 404

            if not chunk_rows:
                return jsonify({'error': 'Document has no stored chunks to reindex.'}), 400

            # Mark as processing
            cur.execute(
                "UPDATE kb_documents SET status = 'processing', updated_at = %s WHERE id = %s",
                (datetime.utcnow(), doc_id),
            )
            conn.commit()
    finally:
        release_db_connection(conn)

    # Reconstruct text from chunks (with a space separator)
    raw_text = ' '.join(r['content'] for r in chunk_rows)

    t = threading.Thread(
        target=_ingest_document,
        args=(doc_id, raw_text, config),
        daemon=True,
    )
    t.start()

    return jsonify({'id': doc_id, 'status': 'processing'}), 202


@knowledge_bp.route('/knowledge/chat', methods=['POST'])
@permission_required('ai-chat')
def knowledge_chat(current_user):
    """
    RAG chat endpoint.
    1. Embed question
    2. Cosine similarity search against active kb_chunks
    3. Build context from top-k chunks
    4. Call LLM with context-only instruction
    5. Return {answer, sources}
    """
    _ensure_schema()

    body     = request.get_json(force=True, silent=True) or {}
    question = (body.get('question') or '').strip()
    top_k    = min(int(body.get('top_k', 3)), 8)

    if not question:
        return jsonify({'error': 'Question is required.'}), 400
    if len(question) > 2000:
        return jsonify({'error': 'Question too long (max 2000 characters).'}), 400

    try:
        config = _get_embed_config()
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503

    embed_supported = config.get('embed_supported', True)

    # 1. Try to embed the question (skip if provider has no embedding support)
    q_vec_str    = None
    search_mode  = 'vector'
    search_note  = ''

    if embed_supported:
        try:
            q_vec     = _embed(question, config)
            q_vec_str = '[' + ','.join(str(f) for f in q_vec) + ']'
        except Exception as e:
            logger.warning("Question embedding failed (%s) — falling back to full-text search.", e)
            q_vec_str   = None
            search_mode = 'fts'
            search_note = 'Semantic search unavailable — using keyword search.'
    else:
        search_mode = 'fts'
        search_note = config.get('embed_reason', 'Using keyword search (full-text).')

    # 2. Search: vector similarity OR PostgreSQL full-text search
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            # Check if any chunks actually have embeddings (for mixed docs)
            if q_vec_str:
                cur.execute(
                    "SELECT 1 FROM kb_chunks c "
                    "JOIN kb_documents d ON d.id = c.document_id "
                    "WHERE d.is_active AND d.status='ready' AND c.embedding IS NOT NULL LIMIT 1"
                )
                has_vectors = cur.fetchone() is not None
                if not has_vectors:
                    search_mode = 'fts'
                    search_note = 'Documents are indexed in text-only mode. Using keyword search.'
                    q_vec_str   = None

            if search_mode == 'vector' and q_vec_str:
                cur.execute(
                    """
                    SELECT c.document_id, c.chunk_index, c.content,
                           d.title AS doc_title,
                           1 - (c.embedding <=> %s::vector) AS similarity
                    FROM   kb_chunks c
                    JOIN   kb_documents d ON d.id = c.document_id
                    WHERE  d.is_active = TRUE AND d.status = 'ready'
                      AND  c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT  %s
                    """,
                    (q_vec_str, q_vec_str, top_k),
                )
            else:
                # Full-text search fallback — works for every LLM
                cur.execute(
                    """
                    SELECT c.document_id, c.chunk_index, c.content,
                           d.title AS doc_title,
                           ts_rank(c.content_tsv,
                                   plainto_tsquery('english', %s))::float AS similarity
                    FROM   kb_chunks c
                    JOIN   kb_documents d ON d.id = c.document_id
                    WHERE  d.is_active = TRUE AND d.status = 'ready'
                      AND  c.content_tsv @@ plainto_tsquery('english', %s)
                    ORDER BY similarity DESC
                    LIMIT  %s
                    """,
                    (question, question, top_k),
                )
                # If no FTS hits, fall back to recent chunks (broad retrieval)
                if cur.rowcount == 0:
                    cur.execute(
                        """
                        SELECT c.document_id, c.chunk_index, c.content,
                               d.title AS doc_title, 0.0::float AS similarity
                        FROM   kb_chunks c
                        JOIN   kb_documents d ON d.id = c.document_id
                        WHERE  d.is_active = TRUE AND d.status = 'ready'
                        ORDER BY c.document_id, c.chunk_index
                        LIMIT  %s
                        """,
                        (top_k,),
                    )

            results = cur.fetchall()

    except Exception as e:
        logger.error("Knowledge search failed: %s", e)
        return jsonify({'error': f'Search failed: {e}'}), 500
    finally:
        release_db_connection(conn)

    if not results:
        return jsonify({
            'answer': (
                'I could not find any relevant information in the knowledge base to answer your question. '
                'Please ensure documents have been uploaded and indexed.'
            ),
            'sources': [],
            'search_mode': search_mode,
        })

    # 3. Build context — trim each chunk to 200 words to reduce LLM input tokens
    context_parts = []
    for i, row in enumerate(results, 1):
        words   = row['content'].split()
        excerpt = ' '.join(words[:200])
        context_parts.append(f"[Source {i}: {row['doc_title']}]\n{excerpt}")
    context_str = '\n\n---\n\n'.join(context_parts)

    system_prompt = (
        "You are a helpful knowledge base assistant for a Point-of-Sale business system. "
        "Answer the user's question using ONLY the information provided in the context below. "
        "If the context does not contain enough information to answer, say so clearly. "
        "Be concise, accurate, and helpful. Do not make up information not found in the context.\n\n"
        "CONTEXT:\n" + context_str
    )

    # 4. Call LLM — reuse config already fetched above (no extra DB roundtrip)
    try:
        from routes.ai_settings import call_provider
        answer = call_provider(config, system_prompt, question, max_tokens=600,
                               feature='chat', user_id=current_user.get('user_id'),
                               username=current_user.get('username', ''))
    except Exception as e:
        logger.error("LLM call failed in knowledge chat: %s", e)
        return jsonify({'error': f'LLM call failed: {e}'}), 500

    # 5. Build sources list
    sources = []
    seen_docs = {}
    for row in results:
        doc_id   = row['document_id']
        sim      = float(row['similarity']) if row['similarity'] is not None else 0.0
        preview  = row['content'][:200].replace('\n', ' ').strip()
        if doc_id not in seen_docs or seen_docs[doc_id]['similarity'] < sim:
            seen_docs[doc_id] = {
                'doc_id':     doc_id,
                'title':      row['doc_title'],
                'similarity': round(sim, 4),
                'preview':    preview,
            }

    # Sort by similarity descending, unique per document
    sources = sorted(seen_docs.values(), key=lambda x: x['similarity'], reverse=True)

    return jsonify({
        'answer':      answer,
        'sources':     sources,
        'search_mode': search_mode,   # 'vector' or 'fts'
        'search_note': search_note,   # shown in UI when FTS is used
    })


@knowledge_bp.route('/knowledge/embed-status', methods=['GET'])
@admin_required
def embed_status(current_user):
    """Check whether the active AI provider supports embeddings."""
    _ensure_schema()
    try:
        config          = _get_embed_config()
        provider        = config.get('provider', '')
        embed_supported = config.get('embed_supported', True)
        return jsonify({
            'supported':    embed_supported,
            'fallback':     not embed_supported,   # True = FTS fallback active
            'provider':     provider,
            'embed_model':  config.get('embed_model', ''),
            'display_name': config.get('display_name', provider),
            'note':         config.get('embed_reason', ''),
        })
    except RuntimeError as e:
        return jsonify({'supported': False, 'fallback': False, 'error': str(e)})
    except Exception as e:
        return jsonify({'supported': False, 'error': str(e)})


@knowledge_bp.route('/knowledge/stats', methods=['GET'])
@admin_required
def knowledge_stats(current_user):
    """Return aggregate stats: total docs, active docs, total chunks, total chars."""
    _ensure_schema()
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(*)                              AS total_docs,
                    COUNT(*) FILTER (WHERE is_active)     AS active_docs,
                    COALESCE(SUM(chunk_count), 0)         AS total_chunks,
                    COALESCE(SUM(char_count),  0)         AS total_chars
                FROM kb_documents
            """)
            row = cur.fetchone()
        return jsonify({
            'total_docs':   int(row['total_docs']),
            'active_docs':  int(row['active_docs']),
            'total_chunks': int(row['total_chunks']),
            'total_chars':  int(row['total_chars']),
        })
    finally:
        release_db_connection(conn)


@knowledge_bp.route('/knowledge/documents/<int:doc_id>/status', methods=['GET'])
@admin_required
def document_status(current_user, doc_id):
    """Poll a single document's status (used by frontend during ingest)."""
    _ensure_schema()
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, status, chunk_count, char_count, error_msg FROM kb_documents WHERE id = %s",
                (doc_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({'error': 'Not found.'}), 404
        return jsonify(dict(row))
    finally:
        release_db_connection(conn)
