import psycopg2
import os
import sys
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor
from psycopg2 import pool

# Load environment variables from .env file (override=True to force reload)
load_dotenv(override=True)

# Get database connection parameters with fallback for Render
def _reload_db_config():
    """Reload database configuration from environment variables."""
    global DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT
    DB_HOST = os.environ.get('DB_HOST')
    DB_NAME = os.environ.get('DB_NAME')
    DB_USER = os.environ.get('DB_USER')
    DB_PASSWORD = os.environ.get('DB_PASSWORD')
    DB_PORT = os.environ.get('DB_PORT')
    
    # If critical env vars are missing, check for Render's DATABASE_URL
    if not DB_HOST or not DB_NAME or not DB_USER or not DB_PASSWORD:
        database_url = os.environ.get('DATABASE_URL')
        if database_url:
            import urllib.parse
            parsed = urllib.parse.urlparse(database_url)
            DB_HOST = parsed.hostname
            DB_PORT = str(parsed.port) if parsed.port else '5432'
            DB_NAME = parsed.path.lstrip('/')
            DB_USER = parsed.username
            DB_PASSWORD = parsed.password
            print(f"[DB] Using DATABASE_URL fallback. Host: {DB_HOST}, DB: {DB_NAME}", file=sys.stderr)
    
    print(f"[DB] Config loaded - HOST: {DB_HOST}, NAME: {DB_NAME}, USER: {'SET' if DB_USER else 'MISSING'}, PORT: {DB_PORT or 'MISSING'}", file=sys.stderr)

# Initialize config
DB_HOST = None
DB_NAME = None
DB_USER = None
DB_PASSWORD = None
DB_PORT = None
_reload_db_config()

# Connection pool - initialized lazily on first use
_connection_pool = None

def reset_connection_pool():
    """Close existing pool and reset config so new .env values are picked up."""
    global _connection_pool
    if _connection_pool:
        try:
            _connection_pool.closeall()
        except Exception:
            pass
        _connection_pool = None
    # Reload config from environment (which now has updated .env values)
    load_dotenv(override=True)
    _reload_db_config()
    print(f"[DB] Connection pool reset. New host: {DB_HOST}", file=sys.stderr)

def _get_pool():
    """Get or create the connection pool (lazy initialization)."""
    global _connection_pool
    if _connection_pool is None:
        # Reload config in case .env was updated
        _reload_db_config()
        # Fail fast with clear error if DB_HOST is missing
        if not DB_HOST:
            raise RuntimeError(
                "DB_HOST is not set. Please set DB_HOST, DB_NAME, DB_USER, DB_PASSWORD environment variables, "
                "or provide a DATABASE_URL."
            )
        try:
            # Use SSL when connecting to a remote host (Render/Aiven/Supabase).
            # Local/dev connections (localhost / 127.0.0.1) skip SSL.
            _is_remote = DB_HOST not in ('localhost', '127.0.0.1', None)
            _ssl_args  = {'sslmode': 'require'} if _is_remote else {}
            _connection_pool = pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=10,
                host=DB_HOST,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                port=DB_PORT or '5432',
                **_ssl_args
            )
        except Exception as e:
            print(f"Connection pool creation failed: {e}", file=sys.stderr)
            raise
    return _connection_pool

def get_db_connection():
    """Get a connection from the pool (much faster than creating new connections)."""
    try:
        pool = _get_pool()
        conn = pool.getconn()
        return conn
    except Exception as e:
        print(f"Database connection failed: {e}", file=sys.stderr)
        print(f"DB_HOST: {DB_HOST}", file=sys.stderr)
        print(f"DB_NAME: {DB_NAME}", file=sys.stderr)
        print(f"DB_USER: {DB_USER}", file=sys.stderr)
        print(f"DB_PORT: {DB_PORT}", file=sys.stderr)
        raise

def release_db_connection(conn):
    """Return a connection back to the pool. Always call this instead of conn.close().

    Roll back any open transaction first so the connection is returned clean: a
    pooled connection that still holds an open transaction would carry a stale
    MVCC snapshot (or an aborted-transaction state) into the next request,
    causing stale reads or "current transaction is aborted" errors.
    """
    global _connection_pool
    if conn and _connection_pool:
        try:
            if not getattr(conn, 'autocommit', False):
                conn.rollback()
        except Exception:
            pass
        try:
            _connection_pool.putconn(conn)
        except Exception:
            pass  # Connection may already be closed

def close_all_connections():
    """Close all connections in the pool. Call on app shutdown."""
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None

def init_db():
    """Initialize database - verify connection and run schema only if needed."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Quick check: does the users table exist?
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'users'
            )
        """)
        table_exists = cur.fetchone()[0]
        
        if table_exists:
            # Tables already exist - skip schema execution (fast startup)
            print("Database tables already exist, skipping schema initialization.")
            cur.close()
            release_db_connection(conn)
            return
        
        # Tables don't exist - run full schema
        print("Database tables not found, running schema initialization...")
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        with open(schema_path, 'r') as f:
            schema = f.read()
            statements = schema.split(';')
            for statement in statements:
                if statement.strip():
                    try:
                        cur.execute(statement)
                        conn.commit()
                        cur = conn.cursor()
                    except Exception as e:
                        print(f"Error executing statement: {e}")
                        conn.rollback()
                        cur = conn.cursor()
        
        print("Database schema created successfully!")
        cur.close()
    except Exception as e:
        print(f"Database initialization error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            release_db_connection(conn)