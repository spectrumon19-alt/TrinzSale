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

    if missing:
        _info(f'{len(missing)} table(s) missing: {", ".join(missing)}')
    else:
        _ok(f'All {len(REQUIRED_TABLES)} required tables exist.')

    # ALWAYS run init_database.sql on every deploy — not just when a table is
    # missing. The script's schema/migration statements are fully idempotent
    # (CREATE TABLE IF NOT EXISTS + ALTER TABLE ... ADD COLUMN IF NOT EXISTS),
    # so re-running them is safe and is the mechanism that applies additive
    # schema migrations (e.g. new columns like sales_invoice_items.rebate_amount)
    # to an EXISTING production database. Previously this only ran when a whole
    # table was missing, so column-level migrations never reached prod and
    # caused runtime 500s (UndefinedColumn).
    _info('Running init_database.sql to apply schema + idempotent migrations ...')

    sql_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'init_database.sql')
    if not os.path.isfile(sql_path):
        _fail(f'init_database.sql not found at {sql_path}')
        cur.close(); conn.close()
        return False

    with open(sql_path, 'r', encoding='utf-8') as f:
        sql = f.read()

    # On an EXISTING database (has users already), strip the DEFAULT SEED DATA
    # block (default admin/cashier accounts + sample products/suppliers) between
    # the SEED-DATA-START/END markers. That block must only ever run once, on a
    # genuinely fresh install — re-running it against production would silently
    # (re)create a known-password 'cashier'/'cashier123' account on every deploy.
    # On a truly fresh DB the users table doesn't exist yet — that query raises
    # UndefinedTable (harmless with autocommit=True; no transaction to poison),
    # which just means "fresh install", so treat it as has_existing_data=False.
    try:
        cur.execute("SELECT EXISTS (SELECT 1 FROM users LIMIT 1)")
        has_existing_data = cur.fetchone()[0]
    except Exception:
        has_existing_data = False
    if has_existing_data:
        start_marker = '-- === SEED-DATA-START ==='
        end_marker    = '-- === SEED-DATA-END ==='
        start = sql.find(start_marker)
        end   = sql.find(end_marker)
        if start != -1 and end != -1:
            sql = sql[:start] + sql[end + len(end_marker):]
            _info('Existing database detected — skipped default seed data '
                  '(admin/cashier demo accounts, sample products/suppliers).')
        else:
            # Fail safe: refuse to run the full script (with seed data intact)
            # against a database we know already has real data, rather than
            # silently recreating the known-password admin/cashier accounts.
            # This should only happen if init_database.sql's marker comments
            # are ever edited without checking this file — treat it as a bug
            # to fix, not something to run through.
            _fail('SEED-DATA markers not found in init_database.sql, but this '
                  'database already has users. Refusing to run the script — '
                  'it would re-seed default admin/cashier accounts into an '
                  'existing database. Check the SEED-DATA-START/END markers '
                  'in init_database.sql are intact.')
            cur.close(); conn.close()
            return False

    try:
        cur.execute(sql)
        _ok('init_database.sql executed successfully (schema + migrations applied).')
    except Exception as exc:
        _fail(f'init_database.sql failed: {exc}')
        cur.close(); conn.close()
        return False

    # Re-verify all required tables exist after running the script
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

    _ok(f'All {len(REQUIRED_TABLES)} tables verified.')
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
