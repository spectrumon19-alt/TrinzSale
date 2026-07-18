---
name: prod-db-safety
description: Use when reading or (especially) modifying the TrintzERP PRODUCTION database — the Aiven Postgres instance (defaultdb, host pg-…aivencloud.com). Covers confirming you're on prod vs local, backing up before writes, running mutations inside a guarded/asserted transaction, and cleaning up duplicate ledger rows safely. Trigger on any request to fix/clean/correct/delete data in production, reconcile balances, or run a migration against the live DB.
---

# Production DB safety (TrintzERP)

The live DB is **Aiven Postgres**: `defaultdb`, host `pg-…aivencloud.com`, user
`avnadmin`, server IP `159.65.x`. Local dev is `trintz_qa_2` on `localhost`.
DB connection is driven by `.env` via `db.get_db_connection()`.

**Never mutate production financial data (credit_transactions, supplier_transactions,
sales_invoices, balances) without doing ALL of the steps below, in order.**

## 0. Confirm the target FIRST — every time

Transient DNS failures make a prod-pointed script silently fall back to local.
Always verify inside the script, with a retry loop:

```python
import db, time
def get_prod():
    for _ in range(20):
        try:
            c = db.get_db_connection(); cur = c.cursor()
            cur.execute("SELECT inet_server_addr()::text"); h = cur.fetchone()[0]
            if h and h.startswith('159.65'):     # <-- prod signature
                return c, cur
            cur.close(); db.release_db_connection(c)
        except Exception:
            pass
        time.sleep(2)
    return None, None
conn, cur = get_prod()
assert conn, "COULD NOT REACH PROD — do not proceed"
```

If it connects to `localhost` / `trintz_qa_2`, it is NOT prod — stop, retry.

## 1. Back up affected tables to JSON before any write

```python
import json, datetime
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
for t in ['credit_transactions','credit_customers']:   # affected tables
    cur.execute(f"SELECT * FROM {t}")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    json.dump(rows, open(f'<scratchpad>/PRODBACKUP_{t}_{ts}.json','w'),
              default=str, indent=2)
```

## 2. Read-only report BEFORE deciding what to change

Duplicate/junk rows are frequently ambiguous **manual entries**, not clean bugs.
Produce a report the user can review; do NOT auto-delete on a heuristic. Example
duplicate signature: same account + type + amount + reference, seconds apart, or
two `debit` rows sharing one `invoice_no`. Show the rows and the proposed action;
get explicit sign-off on WHICH ids to touch.

## 3. Mutate inside one guarded transaction with assertions

Delete/update, then RECOMPUTE the affected balance from surviving rows and assert
it equals the expected value before commit — rollback on any mismatch.

```python
try:
    cur.execute("SELECT inet_server_addr()::text")
    assert cur.fetchone()[0].startswith('159.65'), "not prod"
    cur.execute("DELETE FROM credit_transactions WHERE transaction_id = ANY(%s)", (ids,))
    if cur.rowcount != len(ids): raise Exception(f"expected {len(ids)}, got {cur.rowcount}")
    # recompute balance from survivors, assert, then UPDATE the stored balance
    ...
    if recomputed != expected: raise Exception(f"{recomputed} != {expected}, rolling back")
    conn.commit()
except Exception as e:
    conn.rollback(); print("ROLLED BACK:", e)
```

## 4. Verify independently after commit

Re-read the rows/balances in a fresh query and confirm the change landed and no
duplicate groups remain.

## Ledger balance rules (for recompute)

- Customer: `debit` lowers balance, `credit` raises it. Receivable = `-balance`.
- Supplier: `credit` raises balance, `debit` lowers it. Payable = `+balance`.
- Balance = initial (the `previous_balance` of the earliest surviving txn)
  + Σ(+credit / −debit) over surviving rows in `created_at` order.

## Root-cause the source, not just the data

If you're cleaning duplicates, find and fix WHY they appeared (e.g. frontend
double-post, missing idempotency guard) — cleaning data without fixing the source
just refills the table. See `ledger_utils.find_recent_duplicate` and the
credit auto-post in `routes/sales.py`.
