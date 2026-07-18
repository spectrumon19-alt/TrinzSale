---
name: add-migration
description: Use when adding, renaming, or changing a database column/table/index in TrintzERP so the change actually reaches production and doesn't break the test suite. Covers the three files that must stay in sync (schema.sql, init_database.sql, tests/conftest.py), where the migration must live so it runs on existing prod DBs, and the deploy mechanism. Trigger whenever a feature needs a new column/table/index or a schema change.
---

# Add a schema migration (TrintzERP)

The deploy runs `init_database.sql` on **every** deploy via `predeploy.py`. There
is no Alembic — migrations are idempotent SQL. A schema change is only "done"
when it reaches production AND the test DB. Miss a file and you get a runtime
`UndefinedColumn` 500 in prod, or a red test suite.

## The three files to update (all of them)

1. **`init_database.sql`** — the file that runs on deploy.
   - Add the column to the table's `CREATE TABLE IF NOT EXISTS` (for fresh installs).
   - AND add an idempotent migration in the **SAFE MIGRATIONS** section (for
     existing DBs): `ALTER TABLE <t> ADD COLUMN IF NOT EXISTS <col> <type> DEFAULT <d>;`
   - **Placement matters**: real migrations must be OUTSIDE the
     `-- === SEED-DATA-START ===` / `-- === SEED-DATA-END ===` markers.
     `predeploy.py` strips everything between those markers on an existing DB, so
     anything inside silently never runs in production.

2. **`schema.sql`** — mirror of the same tables (used by the in-app
   `POST /admin/service/run-schema` repair action). Add the column to the
   matching `CREATE TABLE` here too. Its seed block is also marker-guarded.

3. **`tests/conftest.py`** — the test DB is built from `schema.sql` + the
   `EXTRA_DDL` string. If `schema.sql`'s `CREATE TABLE IF NOT EXISTS` can't add
   the column to a pre-existing test DB, add an
   `ALTER TABLE <t> ADD COLUMN IF NOT EXISTS ...` line to `EXTRA_DDL` — otherwise
   every test that inserts into that table 500s.

## Indexes

Add `CREATE INDEX IF NOT EXISTS ...` to BOTH `schema.sql` and `init_database.sql`.
If the index backs a hot query (e.g. an idempotency-guard SELECT), use a composite
index matching the predicate column order, and verify with `EXPLAIN` (force with
`SET enable_seqscan=off` if the local table is too small for the planner to pick it).

## Verify

- Parse: `python -c "import ast; ast.parse(open('routes/<f>.py').read())"` for any
  code changes.
- Idempotency: run `init_database.sql` twice against a populated local DB and
  confirm row counts don't change (no reseed) and no errors:
  ```python
  # BEFORE row counts == AFTER row counts for users/products/suppliers
  cur.execute(open('init_database.sql').read())
  ```
- Fresh-install path still seeds: run against an empty DB and confirm the
  `admin`/`cashier` default users appear.
- Run the suite: `python -m pytest tests/ --ignore=tests/ui`.

## Common column examples in this codebase

- `sales_invoice_items.rebate_amount DECIMAL(10,2) DEFAULT 0.00` — per-item flat ₹ rebate.
- Composite dup-guard indexes on `credit_transactions` / `supplier_transactions`
  over `(id, transaction_type, amount, created_at)`.
