# TrintzERP — Project Guide

Flask + PostgreSQL POS / ERP for agri-retail. Vanilla HTML/JS frontend (no build
step, no framework — plain `.html` pages + shared `.js` files served statically),
Python API under `/api`. Deployed on Render (Aiven-hosted Postgres).

## Run / test / deploy

```bash
# Dev server (port 5001)
python app.py

# Full test suite (needs a local pos_test_db — see tests/conftest.py)
# conftest overrides DB_* env vars to point at the TEST db, not your real one.
python -m pytest tests/ --ignore=tests/ui        # ui tests need `playwright`, usually skip
```

- **Test DB**: `pytest.ini` requires ≥70% coverage on `routes/`, `auth`, `db`.
  The suite applies `schema.sql` + `EXTRA_DDL` (in conftest) to `pos_test_db`.
  When you add a column to a live table, add its `ADD COLUMN IF NOT EXISTS`
  migration to `init_database.sql` **and** to conftest's `EXTRA_DDL`, or every
  test touching that table 500s.
- **Deploy**: `render.yaml` → `preDeployCommand: python predeploy.py`,
  `startCommand: gunicorn ... wsgi:application`. `predeploy.py` runs
  `init_database.sql` on every deploy (see "Migrations" below).

## Architecture

- `app.py` → `create_app()` registers ~30 blueprints, all under `/api`.
- `routes/` — one module (or package) per domain. `admin/`, `reports/`,
  `service/` are **packages** (were single files, split up); their blueprints
  are collected via `*_BLUEPRINTS` lists imported in `app.py`.
- `auth.py` — JWT (`generate_token`, `verify_token`) + decorators:
  `token_required`, `cashier_required`, `admin_required`, `permission_required(screen)`,
  `strict_permission_required(screen)`. `current_user` passed to routes **is the
  raw JWT payload** (`user_id`, `role`, `username`, `exp`). Deny-by-default:
  access needs an explicit `user_permissions` row unless the role is
  Admin/Manager/Super Admin (which bypass per-page checks).
- `db.py` — connection pool only (`get_db_connection` / `release_db_connection`).
  Domain logic never goes here.
- `ledger_utils.py` — shared idempotency guard for credit/supplier ledgers.
- Frontend: each page is a standalone `.html`; shared behavior in `auth-utils.js`
  (sidebar render, auth guard, logout), `sidebar-utils.js`, `component-utils.js`,
  `sales.js`, `chat-widget.js`. `styles.css` is the single design system.

## Ledger / accounting conventions (get these right — money is involved)

- **Customer credit** (`credit_customers` / `credit_transactions`): a credit
  **sale posts a `debit`** → balance goes NEGATIVE. Outstanding receivable =
  `-balance` when balance < 0. A payment is a `credit`.
- **Supplier** (`suppliers` / `supplier_transactions`): a credit **purchase
  posts a `credit`** → balance POSITIVE. Payable = `+balance`. A payment is a `debit`.
- A credit sale auto-posts its ledger debit in `routes/sales.py` (note
  `'Auto-posted from credit sale'`, keyed on `invoice_no`). Do NOT also post it
  from the frontend — that double-charged customers historically.
- Ledger writes use `ledger_utils.find_recent_duplicate()` (10s window) as an
  idempotency guard against double-submit. Backed by
  `idx_credit_txn_dup_guard` / `idx_supplier_txn_dup_guard` composite indexes.

## GST / invoice math (`routes/sales.py`)

- `rate_at_sale` is **GST-inclusive**. Taxable = amount / (1 + gst/100);
  GST = amount − taxable; SGST = CGST = GST/2.
- Per-item **rebate** is a flat ₹ off the line total (NOT a %). Column
  `sales_invoice_items.rebate_amount`. (`discount_percentage` is legacy per-item.)
- Whole-bill **Disc%** is applied PER LINE ITEM before insert (each line's
  taxable/GST scaled by `1 - disc/100`) so item rows reconcile with invoice
  totals for GSTR-1. Clamp `discount_percentage` to [0,100] once, up front, so
  the stored value matches what's actually applied.
- Returns refund from the stored `total_line_amount` (already net of every
  discount), prorated per unit — never recompute from rate/discount.

## Migrations & seed data

- `init_database.sql` is **idempotent** (`CREATE TABLE IF NOT EXISTS`,
  `ADD COLUMN IF NOT EXISTS`) and re-runs on **every** deploy via `predeploy.py`.
- The **seed block** (default admin/cashier accounts + sample data) lives between
  `-- === SEED-DATA-START ===` / `-- === SEED-DATA-END ===` markers.
  `predeploy.py` STRIPS this block when the DB already has users, so production
  never re-seeds demo accounts. If you add a real migration (not seed data), put
  it OUTSIDE those markers — inside, it silently never runs on existing DBs.
- `schema.sql` mirrors the same tables/seed (used by the in-app
  `POST /admin/service/run-schema` "repair schema" action, which also strips
  the seed block on existing DBs).
- After adding a column: update `schema.sql`, `init_database.sql` (both the
  CREATE and an `ADD COLUMN IF NOT EXISTS` in SAFE MIGRATIONS), and
  `tests/conftest.py` `EXTRA_DDL`.

## Frontend gotchas

- Code edits to `.py`/`.js`/`.html` need a **server restart / hard refresh** to
  take effect — a stale gunicorn process or cached JS is the usual reason "the
  fix didn't work" (this bit us repeatedly). Suspect caching before code.
- Sidebar branding is injected by `auth-utils.js` (`renderSidebarLinks`), not
  static in each page. Logout button uses shared id `#nav-logout-btn`.
- Record-creating forms must guard against double-submit (disable the button /
  in-flight flag) — several ledger duplicates traced to unguarded handlers.

## Production DB access (from a dev machine)

- The live DB is Aiven Postgres (host `pg-…aivencloud.com`, `defaultdb`). When a
  script "connects to local `trintz_qa_2`" unexpectedly, it's a **transient DNS
  failure** falling back to the `.env` — retry; verify with
  `SELECT inet_server_addr()` (prod is `159.65.x`).
- **Never mutate prod financial data without**: (1) confirming you're on prod,
  (2) a JSON backup of affected tables first, (3) a guarded transaction with
  post-change assertions that rolls back on mismatch. Prefer a read-only report
  for review over a bulk auto-delete — duplicate rows are often ambiguous manual
  entries, not clean bugs.

## Conventions

- Match surrounding style per file (mixed: some routes verbose, some terse).
- User-facing brand is **TrintzERP** (rebranded from TrintzPOS). `assets/favicon.png`
  = plain lotus (transparent); `assets/logo.png` = lotus + "Trintz Data Labs" lockup.
- Don't commit/push unless asked. Test DB creds and prod migrations are sensitive.
