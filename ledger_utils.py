"""
Shared idempotency guard for ledger tables (credit_transactions, supplier_transactions).

Both ledgers can receive a duplicate POST from a double-click, a client retry
after a timeout, or (for credit_transactions) an internal auto-post — this
guard rejects an identical transaction submitted within a short window instead
of inserting a second row and compounding the balance.
"""


def find_recent_duplicate(cur, table, id_col, id_value, transaction_type, amount,
                           ref_col, ref_value, note_value, window_seconds=10):
    """Look for an existing row in `table` matching (id_col, transaction_type,
    amount, ref_col, note) created within the last `window_seconds`.

    `ref_col` is the ledger-specific reference column (invoice_no for
    credit_transactions, purchase_order_number for supplier_transactions).
    Returns the matching row (as a dict, since callers use RealDictCursor) or
    None if no duplicate is found within the window.
    """
    cur.execute(f"""
        SELECT *
        FROM {table}
        WHERE {id_col} = %s
          AND transaction_type = %s
          AND amount = %s
          AND COALESCE({ref_col}, '') = COALESCE(%s, '')
          AND COALESCE(note, '')      = COALESCE(%s, '')
          AND created_at >= NOW() - INTERVAL '{int(window_seconds)} seconds'
        ORDER BY created_at DESC
        LIMIT 1
    """, (id_value, transaction_type, amount, ref_value, note_value))
    return cur.fetchone()
