#!/usr/bin/env python3
"""
TrintzERP — Pre-deployment checks for Render.
Runs automatically before each deploy. Exit code 1 blocks the deploy.

Checks performed:
  1. Required environment variables are present
  2. SECRET_KEY is not a weak default
  3. Database is reachable
  4. All required tables exist; if not, init_database.sql is executed
"""
import os
import sys
import urllib.parse

REQUIRED_TABLES = [
    'users', 'products', 'inventory', 'suppliers',
    'purchase_orders', 'purchase_order_items', 'supplier_transactions',
    'sales_invoices', 'sales_invoice_items',
    'credit_customers', 'credit_transactions',
    'licenses', 'user_permissions', 'login_activity',
    'registration_otps', 'login_otps', 'trusted_devices', 'password_reset_otps',
]

WEAK_SECRETS = {'dev-secret-key', 'secret', 'changeme', 'password', ''}

def _ok(msg):   print(f"[PASS] {msg}", flush=True)
def _info(msg): print(f"[INFO] {msg}", flush=True)
def _warn(msg): print(f"[WARN] {msg}", flush=True)
def _fail(msg): print(f"[FAIL] {msg}", flush=True)


# ── 1. Environment variables ──────────────────────────────────────────────

def check_env_vars():
    failures = []

    # Must have SECRET_KEY
    if not os.environ.get('SECRET_KEY'):
        failures.append('SECRET_KEY is not set')

    # Must have DB access — either DATABASE_URL or individual vars
    has_url = bool(os.environ.get('DATABASE_URL'))
    individual_vars = ['DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']
    has_individual = all(os.environ.get(v) for v in individual_vars)

    if not has_url and not has_individual:
        failures.append(
            'No database credentials found. '
            'Set DATABASE_URL  OR  DB_HOST + DB_NAME + DB_USER + DB_PASSWORD'
        )

    for msg in failures:
        _fail(msg)

    if not failures:
        _ok('All required environment variables are present.')
    return not failures


# ── 2. Secret key strength ────────────────────────────────────────────────

def check_secret_key():
    key = os.environ.get('SECRET_KEY', '')
    if key in WEAK_SECRETS or len(key) < 32:
        _warn(
            'SECRET_KEY looks weak (< 32 chars or a known default). '
            'Generate a strong key: python -c "import secrets; print(secrets.token_hex(32))"'
        )
        return False
    _ok('SECRET_KEY is strong.')
    return True


# ── 3. DB connection params ────────────────────────────────────────────────

def get_db_params():
    url = os.environ.get('DATABASE_URL')
    if url:
        p = urllib.parse.urlparse(url)
        return dict(
            host=p.hostname,
            port=p.port or 5432,
            dbname=p.path.lstrip('/'),
            user=p.username,
            password=p.password,
            sslmode='require',
            connect_timeout=15,
        )
    return dict(
        host=os.environ['DB_HOST'],
        port=int(os.environ.get('DB_PORT', 5432)),
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
        sslmode='require',
        connect_timeout=15,
    )


# ── 4. DB check + optional init ───────────────────────────────────────────

def check_and_init_db(params):
    try:
        import psycopg2
    except ImportError:
        _fail('psycopg2 is not installed — cannot verify database.')
        return False

    _info(f"Connecting to {params['host']}:{params['port']}/{params['dbname']} ...")
    try:
        conn = psycopg2.connect(**params)
    except Exception as exc:
        _fail(f'Cannot connect to database: {exc}')
        return False

    _ok('Database connection successful.')
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""
        SELECT table_name
        FROM   information_schema.tables
        WHERE  table_schema = 'public'
          AND  table_type   = 'BASE TABLE'
    """)
    existing = {row[0] for row in cur.fetchall()}
    missing  = [t for t in REQUIRED_TABLES if t not in existing]

    if not missing:
        _ok(f'All {len(REQUIRED_TABLES)} required tables exist.')
        cur.close(); conn.close()
        return True

    _info(f'{len(missing)} table(s) missing: {", ".join(missing)}')
    _info('Running init_database.sql to initialise schema ...')

    sql_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'init_database.sql')
    if not os.path.isfile(sql_path):
        _fail(f'init_database.sql not found at {sql_path}')
        cur.close(); conn.close()
        return False

    with open(sql_path, 'r', encoding='utf-8') as f:
        sql = f.read()

    try:
        cur.execute(sql)
        _ok('init_database.sql executed successfully.')
    except Exception as exc:
        _fail(f'init_database.sql failed: {exc}')
        cur.close(); conn.close()
        return False

    # Re-verify
    cur.execute("""
        SELECT table_name
        FROM   information_schema.tables
        WHERE  table_schema = 'public'
          AND  table_type   = 'BASE TABLE'
    """)
    existing_after  = {row[0] for row in cur.fetchall()}
    still_missing   = [t for t in REQUIRED_TABLES if t not in existing_after]
    cur.close(); conn.close()

    if still_missing:
        _fail(f'Still missing after init: {", ".join(still_missing)}')
        return False

    _ok(f'All {len(REQUIRED_TABLES)} tables verified after initialisation.')
    return True


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    sep = '=' * 60
    print(sep, flush=True)
    print('TrintzERP — Pre-deployment checks', flush=True)
    print(sep, flush=True)

    results = {}

    results['env']    = check_env_vars()
    results['secret'] = check_secret_key()   # warning only — non-blocking

    if results['env']:
        try:
            params = get_db_params()
            results['db'] = check_and_init_db(params)
        except KeyError as exc:
            _fail(f'Missing DB env var: {exc}')
            results['db'] = False
    else:
        _info('Skipping DB check — environment variables missing.')
        results['db'] = False

    print(sep, flush=True)
    blocking_failures = [k for k in ('env', 'db') if not results.get(k)]

    if not blocking_failures:
        print('[PASS] All pre-deploy checks passed — proceeding with deployment.', flush=True)
        sys.exit(0)
    else:
        print(f'[ABORT] {len(blocking_failures)} check(s) failed: {", ".join(blocking_failures)}', flush=True)
        print('[ABORT] Deployment blocked.', flush=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
