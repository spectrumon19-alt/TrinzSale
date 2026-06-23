"""Shared helpers for the service blueprint package (extracted from the
former monolithic routes/service.py). No routes here — pure functions/constants
used by more than one service submodule."""
from flask import request
from db import get_db_connection, release_db_connection
from psycopg2.extras import RealDictCursor
import re

# Optional import for system monitoring
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# ── Query-to-DB safety: audit log + destructive-query classification ──────────
_DESTRUCTIVE_RE = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|'
    r'REPLACE|COPY|MERGE|VACUUM|REINDEX|CLUSTER|CALL|DO)\b',
    re.IGNORECASE
)


def _is_select_only(sql: str) -> bool:
    """True if the statement is a pure read (SELECT/WITH…SELECT/EXPLAIN/SHOW/TABLE)
    with no destructive keyword anywhere in it."""
    s = sql.strip()
    if _DESTRUCTIVE_RE.search(s):
        return False
    return bool(re.match(r'(?is)^\s*(SELECT|WITH|EXPLAIN|SHOW|TABLE|VALUES)\b', s))


def _ensure_sql_audit_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sql_query_audit (
                id          SERIAL PRIMARY KEY,
                run_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                user_id     INTEGER,
                username    VARCHAR(100),
                query_text  TEXT NOT NULL,
                is_select   BOOLEAN NOT NULL DEFAULT TRUE,
                success     BOOLEAN NOT NULL DEFAULT FALSE,
                row_count   INTEGER,
                error_msg   TEXT,
                ip_address  VARCHAR(64)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sql_audit_run_at "
                    "ON sql_query_audit(run_at DESC)")
    conn.commit()


def _audit_sql(payload, query, is_select, success, row_count=None, error_msg=None):
    """Best-effort audit record. Never raises into the caller."""
    conn = None
    try:
        conn = get_db_connection()
        _ensure_sql_audit_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sql_query_audit
                    (user_id, username, query_text, is_select, success,
                     row_count, error_msg, ip_address)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                (payload or {}).get('user_id'),
                (payload or {}).get('username'),
                (query or '')[:20000],
                is_select, success, row_count,
                (error_msg or None) and str(error_msg)[:2000],
                request.remote_addr,
            ))
        conn.commit()
    except Exception:
        import traceback; traceback.print_exc()
    finally:
        if conn:
            release_db_connection(conn)



_RESTORE_TABLE_ORDER = [
    'users', 'products', 'inventory', 'suppliers',
    'purchase_orders', 'purchase_order_items',
    'sales_invoices', 'sales_invoice_items',
    'sales_returns', 'sales_return_items',
    'supplier_transactions', 'credit_customers', 'credit_transactions',
    'licenses', 'login_activity', 'user_permissions',
    'store_settings',
    # backup_logs and backup_settings are intentionally excluded:
    # backup_logs is operational history (not business data) and must survive
    # a restore so the UI history list stays intact.
    # backup_settings holds auto-backup config that should not be wiped.
]


def _rewrite_legacy_columns(stmt):
    """
    Rewrite INSERT statements from older backup versions to match the current schema.
    Each fix is narrowly scoped to its table to avoid corrupting other statements.
    """
    # products: duplicate "pack_size" column (legacy 'pack' col renamed but pack_size already existed)
    if 'INSERT INTO "products"' in stmt and '"pack_size", "pack_size"' in stmt:
        stmt = stmt.replace('"pack_size", "pack_size"', '"pack_size"', 1)
        # The old 'pack' value was always NULL and sat right after the name string
        stmt = re.sub(r"(VALUES\s*\(\d+,\s*'(?:[^']|'')*'),\s*NULL,\s*", r'\1, ', stmt)

    # user_permissions: old schema had "permission_id" (now "id") and an extra "created_at" column
    if 'INSERT INTO "user_permissions"' in stmt:
        if '"permission_id"' in stmt:
            stmt = stmt.replace('"permission_id"', '"id"')
        # Remove "created_at" from column list and its trailing value from VALUES
        # Pattern: col list ends with ..., "created_at") VALUES (..., 'timestamp')
        stmt = re.sub(
            r',\s*"created_at"(\s*\)\s*VALUES\s*\([^)]+),\s*\'[\d\-: .]+\'(\s*\))',
            r'\1\2',
            stmt
        )

    return stmt


def _apply_restore_sql(conn, sql_content):
    """
    Apply a backup SQL dump to the database. Returns (ok_count, err_count).

    Strategy:
      1. Discover all tables the backup writes to.
      2. TRUNCATE them (CASCADE) to start clean — removes seed rows and old data.
      3. Attempt to disable FK enforcement for the session so inserts succeed
         regardless of order and orphaned audit-log rows (deleted users referenced
         in login_activity) don't cause failures.  Falls back gracefully if the
         DB user lacks the required privilege (Render / Aiven managed DBs).
      4. Apply every INSERT, accumulating ok/err counts.
      5. Re-enable FK enforcement and commit.
    """
    import logging as _log
    logger = _log.getLogger(__name__)

    cur = conn.cursor()
    ok = err = 0
    fk_disabled = False

    try:
        # ── 1. Discover tables ────────────────────────────────────────────────
        all_inserted = set(
            m.group(1) for m in re.finditer(
                r'INSERT\s+INTO\s+"?([a-zA-Z_]\w*)"?', sql_content, re.IGNORECASE)
        )
        ordered   = [t for t in _RESTORE_TABLE_ORDER if t in all_inserted]
        unordered = [t for t in all_inserted if t not in _RESTORE_TABLE_ORDER]
        tables_to_clear = ordered + unordered

        # ── 2. TRUNCATE ───────────────────────────────────────────────────────
        if tables_to_clear:
            quoted = ', '.join(f'"{t}"' for t in tables_to_clear)
            try:
                cur.execute(f'TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE')
                conn.commit()
            except Exception as e:
                conn.rollback()
                cur = conn.cursor()
                logger.warning('TRUNCATE failed (%s), falling back to DELETE', e)
                # Fallback: delete in reverse FK order
                for t in reversed(ordered + unordered):
                    try:
                        cur.execute(f'DELETE FROM "{t}"')
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        cur = conn.cursor()

        # ── 3. Disable FK enforcement (best-effort — needs superuser) ─────────
        try:
            cur.execute("SET session_replication_role = replica")
            conn.commit()
            fk_disabled = True
        except Exception:
            conn.rollback()
            cur = conn.cursor()
            logger.info('session_replication_role unavailable; FK order must be correct')

        # ── 4. Apply statements ───────────────────────────────────────────────
        for stmt in _split_sql_statements(sql_content):
            stmt = stmt.strip()
            if not stmt:
                continue
            upper = stmt.upper()
            # Skip comments, SET commands, and the backup's own DELETE lines
            # (tables were already cleared in step 2)
            if stmt.startswith('--') or upper.startswith('SET ') or upper.startswith('DELETE FROM'):
                continue
            stmt = _rewrite_legacy_columns(stmt)
            # Skip backup_logs / backup_settings inserts — those tables are
            # intentionally preserved across restores (operational, not business data).
            if re.match(r'INSERT\s+INTO\s+"?(backup_logs|backup_settings)"?',
                        stmt, re.IGNORECASE):
                continue
            try:
                cur.execute(stmt)
                ok += 1
            except Exception as e:
                err += 1
                conn.rollback()
                cur = conn.cursor()
                if fk_disabled:
                    try:
                        cur.execute("SET session_replication_role = replica")
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        cur = conn.cursor()
                        fk_disabled = False
                logger.debug('Restore skipped statement (%s): %.120s', e, stmt)

        # ── 5. Commit and restore FK enforcement ─────────────────────────────
        conn.commit()

    finally:
        # Always restore FK enforcement before returning connection to pool
        if fk_disabled:
            try:
                cur.execute("SET session_replication_role = DEFAULT")
                conn.commit()
            except Exception:
                conn.rollback()
        cur.close()

    return ok, err




def _split_sql_statements(sql_text):
    """
    Split a SQL script into individual statements, correctly handling BOTH:
      - single-quoted string literals (so a ';' or a '$' inside a value, e.g. a
        pbkdf2 hash '$pbkdf2$...' or a user-agent 'Mozilla/5.0 (...; x64)',
        does not split the statement or get mistaken for a dollar-quote tag), and
      - dollar-quoted blocks (DO $$ ... $$ / $kb$ ... $kb$) that contain ';'.
    Returns a list of non-empty statement strings.
    """
    statements = []
    current = []
    dollar_tag = None   # the dollar-quote tag we're inside (e.g. '$$'), or None
    in_str = False      # inside a single-quoted '...' string literal

    i = 0
    n = len(sql_text)
    while i < n:
        ch = sql_text[i]

        # ── Single-quoted string literals take precedence ──────────────────
        if in_str:
            if ch == "'":
                # Escaped '' stays inside the string
                if i + 1 < n and sql_text[i + 1] == "'":
                    current.append("''")
                    i += 2
                    continue
                in_str = False
            current.append(ch)
            i += 1
            continue

        # Only when NOT in a single-quoted string:
        if ch == "'" and dollar_tag is None:
            in_str = True
            current.append(ch)
            i += 1
            continue

        # Detect start/end of a dollar-quoted block ($tag$ ... $tag$)
        if ch == '$':
            m = re.match(r'\$([A-Za-z_][A-Za-z0-9_]*)?\$', sql_text[i:])
            if m:
                tag = m.group(0)
                if dollar_tag is None:
                    dollar_tag = tag
                    current.append(tag)
                    i += len(tag)
                    continue
                elif sql_text[i:i + len(dollar_tag)] == dollar_tag:
                    current.append(dollar_tag)
                    i += len(dollar_tag)
                    dollar_tag = None
                    continue

        current.append(ch)

        if ch == ';' and dollar_tag is None:
            stmt = ''.join(current).strip()
            stmt_stripped = re.sub(r'--[^\n]*', '', stmt).strip()
            if stmt_stripped and stmt_stripped != ';':
                statements.append(stmt)
            current = []

        i += 1

    # Catch any final statement without trailing semicolon
    remainder = ''.join(current).strip()
    remainder_clean = re.sub(r'--[^\n]*', '', remainder).strip()
    if remainder_clean:
        statements.append(remainder)

    return statements
