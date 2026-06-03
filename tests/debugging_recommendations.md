# Debugging Recommendations — POS Test Suite

## Quick-Start Checklist

```
1. PostgreSQL running?        pg_isready -h localhost -p 5432
2. Test DB exists?            psql -U postgres -c "\l" | grep pos_test_db
3. Schema applied?            psql -U postgres -d pos_test_db -c "\dt"
4. App imports OK?            python -c "from app import create_app; print('OK')"
5. Playwright installed?      python -m playwright install chromium
6. Run fast tests first:      run_tests.bat fast
```

---

## Common Failures & Fixes

### 1. `connection refused` / `could not connect to server`
**Cause:** PostgreSQL not running or wrong host/port.  
**Fix:**
```powershell
# Start PostgreSQL (Windows service)
net start postgresql-x64-15
# OR on WSL/Linux
sudo service postgresql start

# Verify
pg_isready -h localhost -p 5432
```
Check `run_tests.bat` — `TEST_DB_HOST`, `TEST_DB_PORT` must match your install.

---

### 2. `column "full_name" does not exist`
**Cause:** Database was created before BUG-001 was fixed. Old schema missing columns.  
**Fix:** Re-run schema.sql against your test database:
```powershell
psql -U postgres -d pos_test_db -f schema.sql
```
Or manually apply the migration:
```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS mobile VARCHAR;
```

---

### 3. `relation "login_activity" does not exist`
**Cause:** Database predates BUG-002 fix. Tables never created.  
**Fix:** Re-run schema.sql (see above). The `CREATE TABLE IF NOT EXISTS` blocks are idempotent.

---

### 4. `fixture 'test_product' setup failed: AssertionError: 403`
**Cause:** `admin_token` fixture is using the wrong `user_id` or the `SECRET_KEY` in conftest doesn't match the app.  
**Diagnosis:**
```python
# Add to test to debug:
resp = client.get("/api/users/me", headers=admin_headers)
print(resp.status_code, resp.data)
```
**Fix:** Ensure `TEST_SECRET_KEY` in `conftest.py` matches `SECRET_KEY` in your `.env` / `app.py`.

---

### 5. `psycopg2.errors.UniqueViolation on invoice_number`
**Cause:** BUG-011 (race condition) or a previous failed test left invoice records in the DB.  
**Fix:**
```sql
-- Clean leftover test invoices
DELETE FROM sales_invoice_items WHERE invoice_id IN (
  SELECT invoice_id FROM sales_invoices WHERE customer_name LIKE '%Test%'
);
DELETE FROM sales_invoices WHERE customer_name LIKE '%Test%';
```
Or drop and recreate the test DB:
```powershell
psql -U postgres -c "DROP DATABASE pos_test_db"
psql -U postgres -c "CREATE DATABASE pos_test_db"
psql -U postgres -d pos_test_db -f schema.sql
```

---

### 6. `gzip / JSON decode error in parse_json()`
**Cause:** Response is not actually gzip-compressed but code tries to decompress it.  
**Diagnosis:**
```python
print(resp.headers.get("Content-Encoding"))
print(resp.status_code)
print(resp.data[:200])
```
**Fix:** `parse_json()` in conftest already checks `Content-Encoding == 'gzip'` before decompressing. If you see this error, the helper is being bypassed — always use `parse_json(resp)` not `resp.get_json()` directly.

---

### 7. `Playwright TimeoutError: waiting for selector [data-testid="..."]`
**Causes:**
- Flask app is not running
- Wrong port (default is 5001)
- HTML element doesn't have the `data-testid` attribute yet

**Fix:**
```powershell
# 1. Start the app
python app.py

# 2. Run UI tests in headed mode to see what's happening
pytest tests/ui/ -m ui --headed -s

# 3. Verify the attribute is in the HTML
# Open browser DevTools → inspect element → check data-testid
```

---

### 8. `AttributeError: module 'jwt' has no attribute 'decode'` / JWT version mismatch
**Cause:** Wrong PyJWT version. PyJWT v1.x API differs from v2.x.  
- v1: `jwt.encode()` returns `bytes`, `jwt.decode()` needs `algorithms` as optional
- v2: `jwt.encode()` returns `str`, `algorithms` is required in `decode()`

**Fix:** Pin to v2:
```
pip install "PyJWT>=2.8.0"
```
The conftest uses v2 API: `jwt.encode(payload, key, algorithm="HS256")` returns a `str`.

---

### 9. `psycopg2.errors.ForeignKeyViolation` in fixture teardown
**Cause:** Test created child records (e.g. sales invoices referencing a product) but teardown tries to delete the parent (product) first.  
**Fix:** Teardown order matters. Delete child records first:
```python
# In fixture teardown:
cur.execute("DELETE FROM sales_invoice_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE ...)")
cur.execute("DELETE FROM sales_invoices WHERE ...")
cur.execute("DELETE FROM inventory WHERE product_id = %s", (pid,))
cur.execute("DELETE FROM products WHERE product_id = %s", (pid,))
```

---

### 10. Tests passing locally but failing in CI
**Common causes:**
- CI runs against a clean DB → schema must be applied in CI setup step
- Timezone differences → invoice date assertions may fail if server is UTC but test expects local time
- Port conflicts → another service using 5001

**CI setup snippet (GitHub Actions):**
```yaml
- name: Setup test DB
  run: |
    psql -U postgres -c "CREATE DATABASE pos_test_db"
    psql -U postgres -d pos_test_db -f schema.sql

- name: Run tests
  env:
    TEST_DB_HOST: localhost
    TEST_DB_NAME: pos_test_db
    TEST_DB_USER: postgres
    TEST_DB_PASSWORD: postgres
  run: pytest tests/ -m "not slow and not ui" --tb=short
```

---

## Running Subsets of Tests

```powershell
# All except slow/UI (default)
run_tests.bat

# Only auth tests
pytest tests/api/test_auth.py -v

# Only DB integrity tests
pytest tests/database/ -v

# Only security tests
pytest tests/security/ -v

# UI tests (requires running app)
python app.py &
run_tests.bat ui

# With coverage
run_tests.bat coverage

# Parallel (4 workers)
pytest tests/ -m "not slow and not ui" -n 4

# Stop at first failure
pytest tests/ -x

# Show 10 slowest tests
pytest tests/ --durations=10
```

---

## Known Bugs That Will Cause Test Failures

| Test | Bug | Behaviour |
|------|-----|-----------|
| `test_search_excludes_inactive_products_bug007` | BUG-007 | Marked `xfail` — search returns inactive products |
| `test_grand_total_documents_bug006_double_gst` | BUG-006 | Marked `xfail` — grand_total double-counts GST |
| `test_super_admin_role_accepted` | BUG-004 | Fixed — should pass now |
| `test_login_records_user_agent` | BUG-005 | Fixed — should pass now |

Tests marked `xfail` with `strict=False` will show as `XFAIL` (expected failure) in the report — this is correct behaviour, not an error.

---

## Coverage Gaps

Areas **not yet covered** by existing tests:
- `PUT /api/inventory/<id>` (adjust stock endpoint)
- `GET /api/reports/*` (date range edge cases with partial data)
- File upload endpoints (`/api/data-upload`)
- Service module routes (`routes/service.py`)
- License validation routes
- `qry2db` direct SQL endpoint (security-critical — needs its own test file)
